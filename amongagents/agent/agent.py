from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from amongagents.agent.llm import LLM, Usage
from amongagents.agent.parsing import match_action, neutral_action, split_reply
from amongagents.agent.prompts import (
    CREWMATE_EXAMPLE,
    CREWMATE_PROMPT,
    IMPOSTOR_EXAMPLE,
    IMPOSTOR_PROMPT,
    INVALID_ACTION_REPROMPT,
)
from amongagents.envs.action import Action
from amongagents.envs.events import Emit, discard


def build_system_prompt(player, impostor_names: list[str]) -> str:
    if player.identity == "Crewmate":
        return CREWMATE_PROMPT.format(name=player.name) + CREWMATE_EXAMPLE
    return (
        IMPOSTOR_PROMPT.format(name=player.name)
        + IMPOSTOR_EXAMPLE
        + f"List of impostors: {impostor_names}"
    )


@dataclass
class Decision:
    """What an agent did on one turn, and what it took to get there."""

    action: Action
    thought: str = ""  # the reply's [Thinking Process]
    memory: str = ""  # the reply's [Condensed Memory]
    fallback: bool = False  # no action could be read; the turn became a neutral one
    reprompts: int = 0  # extra model calls needed before the reply was usable
    refused: bool = False  # the model declined to answer (stop_reason "refusal")
    usage: Usage = field(default_factory=Usage)
    latency_s: float = 0.0


class LLMAgent:
    """A player driven by a language model.

    Between turns the agent carries only what it wrote itself: its last
    [Condensed Memory] and [Thinking Process], which are fed back in the next prompt.
    """

    def __init__(
        self,
        player,
        llm: LLM,
        impostor_names: list[str],
        game_id: str = "game",
        seed: int = 0,
        llm_log: Emit = discard,
    ):
        self.player = player
        self.llm = llm
        self.model = llm.config.model
        self.system_prompt = build_system_prompt(player, impostor_names)
        self.summarization = "No thought process has been made."
        self.processed_memory = "No memory has been processed."
        self.game_id = game_id
        self.llm_log = llm_log
        self.usage = Usage()
        self.decisions = 0
        self.fallbacks = 0
        self.reprompts = 0
        self.refusals = 0
        # draws a seed per call so scripted (mock) players are reproducible
        self._rng = np.random.default_rng(seed)
        self.llm_log(
            {
                "type": "agent",
                "game_id": game_id,
                "player": player.name,
                "identity": player.identity,
                "model": self.model,
                "system_prompt": self.system_prompt,
            }
        )

    async def choose_action(self, timestep: int, phase: str, note: str | None = None) -> Decision:
        """Ask the model for this turn's action.

        phase is "Task phase" or "Meeting phase". note, if given, is appended to the
        prompt; the game uses it to re-prompt for a statement that broke the protocol.
        A reply that names no available action is re-prompted once, then replaced by a
        neutral turn (see parsing.neutral_action).
        """
        available = self.player.get_available_actions()
        prompt = (
            f"Summarization: {self.summarization}\n\n{self.player.all_info_prompt()}\n\n"
            f"Memory: {self.processed_memory}\n\nPhase: {phase}. Return your output."
        )
        if note:
            prompt += f"\n\n{note}"

        decision = Decision(action=None)
        action = None
        for attempt in range(2):
            if attempt:
                prompt += f"\n\n{INVALID_ACTION_REPROMPT}"
                decision.reprompts += 1
            response = await self.llm.complete(
                self.system_prompt, prompt, seed=int(self._rng.integers(2**31))
            )
            decision.usage.add(response.usage)
            decision.latency_s += response.latency_s
            decision.refused = response.refused
            reply = split_reply(response.text)
            action = None if response.refused else match_action(reply.action_text, available)
            self.llm_log(
                {
                    "type": "llm_call",
                    "game_id": self.game_id,
                    "timestep": timestep,
                    "phase": phase,
                    "player": self.player.name,
                    "identity": self.player.identity,
                    "attempt": attempt,
                    "prompt": prompt,
                    "response": response.text,
                    "matched_action": repr(action) if action is not None else None,
                    "stop_reason": response.stop_reason,
                    "model": response.model,
                    "request_id": response.request_id,
                    "latency_s": response.latency_s,
                    "usage": response.usage.to_dict(),
                }
            )
            if action is not None:
                break

        # keep whatever the model wrote for itself, even on a turn it fumbled
        if reply.memory:
            self.processed_memory = reply.memory
        if reply.thought:
            self.summarization = reply.thought
        if action is None:
            action = neutral_action(available, self.player.location)
            decision.fallback = True

        decision.action = action
        decision.thought = reply.thought or ""
        decision.memory = reply.memory or ""
        decision.latency_s = round(decision.latency_s, 3)
        self.usage.add(decision.usage)
        self.decisions += 1
        self.fallbacks += decision.fallback
        self.reprompts += decision.reprompts
        self.refusals += decision.refused
        return decision
