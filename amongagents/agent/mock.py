"""Scripted offline players.

MockLLM stands in for a model: it reads the prompt an agent would send, applies a few
hand-written heuristics, and answers in the same output format. Nothing about it is
meant to resemble how a language model plays. It exists so that the full pipeline
(prompting, parsing, re-prompts, protocol checks, logging, analysis, the web UI) can
be exercised deterministically, for free, without an API key.

Results from mock games are not findings: every reaction these players have to the
rules, such as accusing less readily in a round that demands evidence, is hand-written.
"""

from __future__ import annotations

import asyncio
import json
import re

import numpy as np

from amongagents.agent.llm import LLMConfig, LLMResponse, Usage

MOCK_MODEL = "mock-scripted"

_NAME = r"Player \d+: \w+"
_ME = re.compile(rf"You are ({_NAME})\.")
_ACTION_LINE = re.compile(r"^\d+\. (.+)$", re.MULTILINE)
_HERE = re.compile(r"^Players in .+?: (.*)$", re.MULTILINE)
_SAW_KILL = re.compile(rf"({_NAME}) KILL ({_NAME})")
_ACCUSED = re.compile(rf"({_NAME}) SPEAK: .*?accuse:? ({_NAME})", re.IGNORECASE | re.DOTALL)
_VOTED = re.compile(rf"({_NAME}) VOTE ({_NAME})")
_LEFT = re.compile(rf"({_NAME}) MOVE from ([\w ]+?) to ([\w ]+)$", re.MULTILINE)
_PATH = re.compile(r"^\d+\. .+\(.+\) *$\nPath: (.+)$", re.MULTILINE)
_MEMORY = re.compile(r"\n\nMemory: (.*?)\n\nPhase:", re.DOTALL)


def _section(prompt: str, start: str, end: str) -> str:
    """The text between two headings of the prompt."""
    begin = prompt.find(start)
    if begin < 0:
        return ""
    stop = prompt.find(end, begin)
    return prompt[begin + len(start) : stop if stop >= 0 else len(prompt)]


class MockLLM:
    def __init__(self, config: LLMConfig):
        self.config = config

    async def complete(self, system: str, user: str, *, seed: int | None = None) -> LLMResponse:
        if self.config.mock_latency > 0:
            await asyncio.sleep(self.config.mock_latency)
        rng = np.random.default_rng(seed)
        if rng.random() < self.config.mock_malformed_rate:
            text = "I am not sure what to do here."
        else:
            text = _play(system, user, rng)
        return LLMResponse(
            text=text,
            model=MOCK_MODEL,
            stop_reason="end_turn",
            usage=Usage(
                calls=1,
                input_tokens=(len(system) + len(user)) // 4,
                output_tokens=len(text) // 4,
            ),
            latency_s=self.config.mock_latency,
        )

    async def close(self) -> None:
        return None


def _play(system: str, user: str, rng: np.random.Generator) -> str:
    me = _ME.search(system).group(1)
    impostor = "You are an Impostor" in system
    actions = _ACTION_LINE.findall(_section(user, "Available actions:\n", "\n\nMemory:"))
    observations = _section(user, "Observation history:\n", "Action history:")

    # what this player has noted so far travels in its own [Condensed Memory]
    memory = {"suspect": None, "accused": {}}
    stored = _MEMORY.search(user)
    if stored:
        try:
            memory.update(json.loads(stored.group(1)))
        except json.JSONDecodeError:
            pass
    killer = next((k for k, _ in _SAW_KILL.findall(observations) if k != me), None)
    if killer:
        memory["suspect"] = killer
    for speaker, accused in _ACCUSED.findall(observations):
        if speaker != me:
            memory["accused"][accused] = memory["accused"].get(accused, 0) + 1
    votes_seen = [target for _, target in _VOTED.findall(observations)]

    def pick(prefix: str) -> list[str]:
        return [a for a in actions if a.startswith(prefix)]

    def choose(options: list[str]) -> str:
        return options[int(rng.integers(len(options)))]

    def most_accused(exclude: str) -> str | None:
        tally = dict(memory["accused"])
        for target in votes_seen:
            tally[target] = tally.get(target, 0) + 1
        tally.pop(exclude, None)
        return max(tally, key=tally.get) if tally else None

    thought = "Keep going."
    if pick("VOTE") or pick("SKIP VOTE"):
        candidates = [a.removeprefix("VOTE ") for a in pick("VOTE")]
        target = memory["suspect"] if memory["suspect"] in candidates else None
        if target is None:
            popular = most_accused(exclude=me)
            if popular in candidates and rng.random() < (0.85 if impostor else 0.65):
                target = popular
            elif impostor or rng.random() < 0.4:
                target = choose(candidates)
        action = f"VOTE {target}" if target else "SKIP VOTE"
        thought = f"Voting for {target}." if target else "Not enough to go on, I abstain."
    elif pick("SPEAK"):
        living = [n for n in re.findall(_NAME, _HERE.search(user).group(1)) if n != me]
        justify = "ACCUSE: <" in user  # the justification protocol is in force this round
        accused = memory["suspect"] if memory["suspect"] in living else None
        if accused:
            evidence = f"I saw {accused} kill a crewmate with my own eyes."
            line = f"I accuse {accused}. {evidence}"
        else:
            popular = most_accused(exclude=me)
            roll = rng.random()
            if popular in living and roll < 0.35:
                accused = popular
                evidence = f"Others have pointed at {accused} and their story does not add up."
            elif living and roll < (0.85 if impostor else 0.3 if justify else 0.6):
                accused = choose(living)
                evidence = f"{accused} kept following me around and was not doing any tasks."
            else:
                evidence = "I was working on my tasks and saw nothing unusual."
            line = f"I accuse {accused}. {evidence}" if accused else evidence
        if justify:
            line += f"\nACCUSE: {accused or 'NONE'}\nEVIDENCE: {evidence}"
        action = f"SPEAK: {line}"
        thought = "Say what I know."
    elif impostor:
        others_here = len(re.findall(_NAME, _HERE.search(user).group(1))) - 1
        kills = pick("KILL")
        p_kill = {1: 0.95, 2: 0.3}.get(others_here, 0.03)
        # follow the last player seen leaving this room
        here = _section(user, "Current Location: ", "\n")
        trail = [f"MOVE from {a} to {b}" for _, a, b in _LEFT.findall(observations) if a == here]
        if kills and rng.random() < p_kill:
            action, thought = choose(kills), "Few witnesses. Strike now."
        elif trail and trail[-1] in actions and rng.random() < 0.7:
            action, thought = trail[-1], "Follow them."
        elif pick("COMPLETE FAKE TASK") and rng.random() < 0.3:
            action, thought = choose(pick("COMPLETE FAKE TASK")), "Blend in."
        elif pick("VENT") and rng.random() < 0.15:
            action, thought = choose(pick("VENT")), "Relocate unseen."
        else:
            action, thought = choose(pick("MOVE")), "Look for someone alone."
    else:
        path = _PATH.search(_section(user, "Your Assigned Tasks:\n", "Available actions:"))
        hops = path.group(1).split("->") if path else []
        if pick("REPORT DEAD BODY") and rng.random() < 0.9:
            action, thought = pick("REPORT DEAD BODY")[0], "A body. Report it."
        elif pick("CALL MEETING") and (memory["suspect"] or rng.random() < 0.03):
            action, thought = pick("CALL MEETING")[0], "The crew needs to talk."
        elif rng.random() < 0.25:
            action, thought = choose(pick("MOVE")), "Have a look around first."
        elif pick("COMPLETE TASK"):
            action, thought = pick("COMPLETE TASK")[0], "Do my task."
        elif len(hops) > 1 and f"MOVE from {hops[0]} to {hops[1]}" in actions:
            action, thought = f"MOVE from {hops[0]} to {hops[1]}", "Head to my next task."
        else:
            action, thought = choose(pick("MOVE")), "Look around."

    return (
        f"[Condensed Memory]\n{json.dumps(memory)}\n"
        f"[Thinking Process]\n{thought}\n"
        f"[Action] {action}"
    )
