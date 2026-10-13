"""Governance: the rules of the collective decision.

These are the study's independent variables. Everything here is pure (no game
state, no I/O) so the tally logic can be unit-tested on synthetic ballots and
re-run on recorded ballots under a rule other than the one a game was played with.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

SKIP = "SKIP"

# Vote threshold: how many votes remove a player.
PLURALITY = "plurality"
MAJORITY = "majority"
SUPERMAJORITY = "supermajority"
THRESHOLDS = (PLURALITY, MAJORITY, SUPERMAJORITY)

# Discussion protocol: what a statement must contain before the vote.
FREEFORM = "freeform"
JUSTIFICATION = "justification"
PROTOCOLS = (FREEFORM, JUSTIFICATION)

# Ballot: whether voters see each other's votes while voting.
PUBLIC = "public"
SECRET = "secret"
BALLOTS = (PUBLIC, SECRET)


@dataclass(frozen=True)
class Governance:
    """One governance condition.

    The defaults reproduce the upstream sandbox: plurality, free-form discussion,
    votes cast one at a time in the open.
    """

    threshold: str = PLURALITY
    protocol: str = FREEFORM
    ballot: str = PUBLIC
    # Whether players are told the voting rule. Off reproduces a "tally-only"
    # manipulation in which the rule changes without the voters knowing.
    disclose_rules: bool = True

    def __post_init__(self):
        if self.threshold not in THRESHOLDS:
            raise ValueError(f"threshold must be one of {THRESHOLDS}, got {self.threshold!r}")
        if self.protocol not in PROTOCOLS:
            raise ValueError(f"protocol must be one of {PROTOCOLS}, got {self.protocol!r}")
        if self.ballot not in BALLOTS:
            raise ValueError(f"ballot must be one of {BALLOTS}, got {self.ballot!r}")

    @property
    def condition(self) -> str:
        """Stable identifier of the condition, e.g. ``majority/justification``."""
        key = f"{self.threshold}/{self.protocol}"
        return key if self.ballot == PUBLIC else f"{key}/{self.ballot}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping) -> Governance:
        return cls(**{k: data[k] for k in ("threshold", "protocol", "ballot", "disclose_rules") if k in data})


@dataclass(frozen=True)
class Tally:
    rule: str
    counts: dict[str, int]  # option -> votes; SKIP is an option like any other
    n_voters: int  # living players entitled to vote
    required: int | None  # votes a player needs under this rule; None for plurality
    ejected: str | None


def votes_required(rule: str, n_voters: int) -> int | None:
    """Votes a single player must receive to be ejected, or None if the rule is relative."""
    if rule == MAJORITY:
        return n_voters // 2 + 1
    if rule == SUPERMAJORITY:
        return math.ceil(2 * n_voters / 3)
    if rule == PLURALITY:
        return None
    raise ValueError(f"unknown threshold {rule!r}")


def tally(ballots: Mapping[str, str], n_voters: int, rule: str) -> Tally:
    """Decide a vote.

    ballots maps each voter to the player they voted for, or to SKIP. A living
    player with no ballot is counted as SKIP, so the denominator is always the
    living electorate rather than the ballots that happened to be cast.

    - plurality: the single most-voted option wins; a tie, or SKIP on top, ejects no one.
    - majority: a player needs more than half of the living voters.
    - supermajority: a player needs at least two thirds of the living voters.
    """
    if len(ballots) > n_voters:
        raise ValueError(f"{len(ballots)} ballots cast by an electorate of {n_voters}")
    counts: dict[str, int] = {}
    for target in ballots.values():
        counts[target] = counts.get(target, 0) + 1
    abstained = n_voters - len(ballots)
    if abstained:
        counts[SKIP] = counts.get(SKIP, 0) + abstained

    required = votes_required(rule, n_voters)
    candidates = {option: n for option, n in counts.items() if option != SKIP}
    ejected = None
    if candidates:
        top = max(counts.values())
        leaders = [option for option, n in counts.items() if n == top]
        if required is None:
            if len(leaders) == 1 and leaders[0] != SKIP:
                ejected = leaders[0]
        else:
            # at most one player can clear a threshold above half the electorate
            ejected = next((option for option, n in candidates.items() if n >= required), None)
    return Tally(rule=rule, counts=counts, n_voters=n_voters, required=required, ejected=ejected)


def counterfactuals(ballots: Mapping[str, str], n_voters: int) -> dict[str, str | None]:
    """Who each threshold rule would eject on the same ballots.

    Recorded with every tally as the manipulation check: the share of meetings in
    which the rule actually changed the decision.
    """
    return {rule: tally(ballots, n_voters, rule).ejected for rule in THRESHOLDS}


# --- Justification protocol -------------------------------------------------

# Tolerant of markdown around the keywords and of both lines being run together.
_ACCUSE = re.compile(
    r"\bACCUSE\b\W{0,3}:(.*?)(?=\bEVIDENCE\b\W{0,3}:|\n|$)", re.IGNORECASE | re.DOTALL
)
_EVIDENCE = re.compile(r"\bEVIDENCE\b\W{0,3}:", re.IGNORECASE)
_NOBODY = re.compile(r"^\W*(none|nobody|no one|no-one|n/a|abstain)\b", re.IGNORECASE)
_PLAYER_NUMBER = re.compile(r"player\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Justification:
    accused: str | None  # a player's full name, or None for an explicit abstention
    evidence: str


def resolve_player(text: str, players: Sequence[str]) -> str | None:
    """Map free text such as "Player 3" or "green" onto one of the given player names."""
    match = _PLAYER_NUMBER.search(text)
    if match:
        prefix = f"Player {int(match.group(1))}:"
        return next((name for name in players if name.startswith(prefix)), None)
    lowered = text.lower()
    by_colour = [name for name in players if re.search(rf"\b{re.escape(name.split(': ')[-1])}\b", lowered)]
    return by_colour[0] if len(by_colour) == 1 else None


def parse_justification(message: str, players: Sequence[str]) -> Justification | None:
    """Parse the ACCUSE/EVIDENCE lines of a statement.

    Returns None when the statement does not satisfy the protocol: a line is
    missing, the evidence is empty or a placeholder, or the accusation names
    nobody in ``players``.
    """
    # a statement must end with the two lines, so the last occurrence of each counts
    accusations = _ACCUSE.findall(message)
    evidence_tags = list(_EVIDENCE.finditer(message))
    if not accusations or not evidence_tags:
        return None
    evidence_text = message[evidence_tags[-1].end() :].strip(" \n\t*_`\"")
    if not evidence_text or evidence_text.startswith("<"):
        return None
    target = accusations[-1].strip(" \n\t*_`\"")
    if _NOBODY.match(target):
        return Justification(accused=None, evidence=evidence_text)
    accused = resolve_player(target, players)
    if accused is None:
        return None
    return Justification(accused=accused, evidence=evidence_text)
