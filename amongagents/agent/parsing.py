"""Turning a model's reply into one of the actions a player may take.

The upstream sandbox fell through to the last action in the list when nothing matched,
which during a vote meant a ballot for whoever happened to be listed last. Here a reply
either names an available action or it does not; what happens then is the caller's
decision (re-prompt, then a neutral turn).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from amongagents.envs.action import Action, Kill, Speak, Vote, Wait

_MEMORY_TAG = re.compile(r"\[\s*Condensed Memory\s*\]", re.IGNORECASE)
_THOUGHT_TAG = re.compile(r"\[\s*Thinking Process\s*\]", re.IGNORECASE)
_ACTION_TAG = re.compile(r"\[\s*Action\s*\]", re.IGNORECASE)
_SPEAK = re.compile(r"\bSPEAK\b\W{0,3}", re.IGNORECASE)
_BARE_INDEX = re.compile(r"^\W*(\d{1,2})\W*$")
_PLAYER_NUMBER = re.compile(r"player\s*(\d+)", re.IGNORECASE)
_SKIP = re.compile(r"\b(skip|abstain)\b", re.IGNORECASE)


@dataclass
class Reply:
    memory: str | None  # text under [Condensed Memory], if the section is present
    thought: str | None  # text under [Thinking Process], if the section is present
    action_text: str  # everything after the last [Action] tag, or the whole reply


def split_reply(text: str) -> Reply:
    """Split a reply written in the [Condensed Memory] / [Thinking Process] / [Action] format."""
    action_tags = list(_ACTION_TAG.finditer(text))
    if not action_tags:
        return Reply(memory=None, thought=None, action_text=text.strip())
    head = text[: action_tags[-1].start()]
    action_text = text[action_tags[-1].end() :].strip()

    memory_tag = _MEMORY_TAG.search(head)
    thought_tag = _THOUGHT_TAG.search(head)
    memory = thought = None
    if memory_tag and thought_tag and memory_tag.start() < thought_tag.start():
        memory = head[memory_tag.end() : thought_tag.start()]
        thought = head[thought_tag.end() :]
    elif thought_tag:
        thought = head[thought_tag.end() :]
    elif memory_tag:
        memory = head[memory_tag.end() :]
    clean = lambda s: s.strip(" \n\t*:") if s is not None else None  # noqa: E731
    return Reply(memory=clean(memory), thought=clean(thought), action_text=action_text)


def _normalise(text: str) -> str:
    """Lower-case and drop punctuation, so "Vote Player 3 - green." matches "VOTE Player 3: green"."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def match_action(action_text: str, available: Sequence[Action]) -> Action | None:
    """Return the available action named in action_text, or None.

    Matching is forgiving about case, punctuation and markdown, but never guesses:
    a reply that names no available action matches nothing.
    """
    if not available or not action_text.strip():
        return None
    haystack = f" {_normalise(action_text)} "

    # 1. An available action copied from the list. If several appear, the reply's
    #    first one is the choice (later ones are usually commentary); a longer match
    #    beats a shorter one starting at the same place.
    found = []
    for action in available:
        if isinstance(action, Speak):
            continue
        needle = f" {_normalise(repr(action))} "
        position = haystack.find(needle)
        if position >= 0:
            found.append((position, -len(needle), action))
    if found:
        return min(found, key=lambda item: item[:2])[2]

    # 2. SPEAK carries free text: everything after the keyword is the message.
    speak = next((a for a in available if isinstance(a, Speak)), None)
    if speak is not None:
        keyword = _SPEAK.search(action_text)
        if keyword is None:
            return None
        message = action_text[keyword.end() :].strip().strip('"“”').strip()
        speak.provide_message(message or "...")
        return speak

    # 3. A ballot or a kill that names its target by player number only.
    verb = action_text.strip().split(None, 1)[0].upper().strip("*:") if action_text.strip() else ""
    for kind, keyword in ((Vote, "VOTE"), (Kill, "KILL")):
        targets = [a for a in available if isinstance(a, kind) and a.other_player is not None]
        number = _PLAYER_NUMBER.search(action_text)
        if targets and number and verb == keyword:
            prefix = f"Player {int(number.group(1))}:"
            match = [a for a in targets if a.other_player.name.startswith(prefix)]
            if len(match) == 1:
                return match[0]
    skip = next((a for a in available if isinstance(a, Vote) and a.other_player is None), None)
    if skip is not None and _SKIP.search(action_text) and not _PLAYER_NUMBER.search(action_text):
        return skip

    # 4. The action's number in the list, and nothing else.
    index = _BARE_INDEX.match(action_text)
    if index and 1 <= int(index.group(1)) <= len(available):
        return available[int(index.group(1)) - 1]
    return None


def neutral_action(available: Sequence[Action], location: str) -> Action:
    """The turn a player takes when no action could be read from the model's reply.

    A voter abstains, a speaker stays silent, and in the task phase the player stands
    still. None of these can eject, accuse or kill anyone.
    """
    skip = next((a for a in available if isinstance(a, Vote) and a.other_player is None), None)
    if skip is not None:
        return skip
    speak = next((a for a in available if isinstance(a, Speak)), None)
    if speak is not None:
        speak.provide_message("...")
        return speak
    return Wait(location)
