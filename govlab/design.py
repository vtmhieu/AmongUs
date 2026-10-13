"""The experiment design: which conditions, how many games, in what order.

A design is a full factorial over the governance levels it lists. The default is the
2x2 of the research plan (vote threshold x discussion protocol); adding a level to a
factor, or a second ballot type, extends it without code changes.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import asdict, dataclass, field
from statistics import NormalDist

import numpy as np

from amongagents.agent.llm import LLMConfig
from amongagents.envs.configs.game_config import STUDY_GAME, validate_game_config
from amongagents.envs.governance import (
    BALLOTS,
    FREEFORM,
    JUSTIFICATION,
    MAJORITY,
    PLURALITY,
    PROTOCOLS,
    PUBLIC,
    THRESHOLDS,
    Governance,
)

LABELS = {
    "plurality": "Plurality",
    "majority": "Majority",
    "supermajority": "Supermajority",
    "freeform": "Free-form",
    "justification": "Justification",
    "public": "Public ballot",
    "secret": "Secret ballot",
}

# Pre-specified exclusion criterion: a game is invalid, and is played again, if more
# than this share of its turns had to be replaced by a neutral action because the
# model's reply could not be read. A game that aborts on an API error is also invalid.
MAX_FALLBACK_RATE = 0.05


@dataclass(frozen=True)
class ExperimentSpec:
    name: str = "experiment"
    thresholds: tuple[str, ...] = (PLURALITY, MAJORITY)
    protocols: tuple[str, ...] = (FREEFORM, JUSTIFICATION)
    ballots: tuple[str, ...] = (PUBLIC,)
    disclose_rules: bool = True
    games_per_condition: int = 20
    seed: int = 2202
    # Replicate r uses the same seed in every condition, so all conditions start from
    # the same roles, colours and tasks (a blocked design). Off: every game has its own.
    matched_seeds: bool = True
    game: dict = field(default_factory=lambda: dict(STUDY_GAME))
    llm: LLMConfig = field(default_factory=LLMConfig)
    concurrency: int = 4  # games in flight at once
    max_attempts: int = 3  # times a slot is played before it is given up as failed
    max_fallback_rate: float = MAX_FALLBACK_RATE
    budget_usd: float | None = None  # stop starting new games once spend reaches this

    def __post_init__(self):
        for levels, allowed, what in (
            (self.thresholds, THRESHOLDS, "thresholds"),
            (self.protocols, PROTOCOLS, "protocols"),
            (self.ballots, BALLOTS, "ballots"),
        ):
            if not levels:
                raise ValueError(f"{what} needs at least one level")
            if len(set(levels)) != len(levels):
                raise ValueError(f"{what} lists a level twice")
            unknown = [level for level in levels if level not in allowed]
            if unknown:
                raise ValueError(f"unknown {what}: {unknown}; choose from {allowed}")
        if not 1 <= self.games_per_condition <= 500:
            raise ValueError("games_per_condition must be between 1 and 500")
        if not 1 <= self.concurrency <= 32:
            raise ValueError("concurrency must be between 1 and 32")
        if not 1 <= self.max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        if not 0 <= self.max_fallback_rate <= 1:
            raise ValueError("max_fallback_rate must be between 0 and 1")
        if self.budget_usd is not None and self.budget_usd <= 0:
            raise ValueError("budget_usd must be positive")
        object.__setattr__(self, "game", validate_game_config(self.game))
        object.__setattr__(self, "name", self.name.strip() or "experiment")

    def conditions(self) -> list[Governance]:
        return [
            Governance(threshold=t, protocol=p, ballot=b, disclose_rules=self.disclose_rules)
            for t, p, b in itertools.product(self.thresholds, self.protocols, self.ballots)
        ]

    @property
    def n_games(self) -> int:
        return len(self.conditions()) * self.games_per_condition

    def schedule(self) -> list[dict]:
        """The games to play, in order.

        Conditions are interleaved: each block holds one game of every condition in a
        shuffled order. Drift in the hosted model over a long run then falls on all
        conditions alike instead of on whichever was run last.
        """
        conditions = self.conditions()
        order = np.random.default_rng(self.seed)
        slots = []
        for block in range(self.games_per_condition):
            for index in order.permutation(len(conditions)):
                governance = conditions[int(index)]
                if self.matched_seeds:
                    seed = self.seed + block
                else:
                    seed = self.seed + block * len(conditions) + int(index)
                slots.append(
                    {
                        "slot": len(slots),
                        "block": block,
                        "condition": governance.condition,
                        "governance": governance.to_dict(),
                        "seed": seed,
                    }
                )
        return slots

    def to_dict(self) -> dict:
        data = asdict(self)
        for key in ("thresholds", "protocols", "ballots"):
            data[key] = list(data[key])
        return data

    @classmethod
    def from_dict(cls, data: dict) -> ExperimentSpec:
        known = set(cls.__dataclass_fields__)
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"unknown experiment settings: {sorted(unknown)}")
        values = dict(data)
        for key in ("thresholds", "protocols", "ballots"):
            if key in values:
                values[key] = tuple(values[key])
        if isinstance(values.get("llm"), dict):
            values["llm"] = LLMConfig.from_dict(values["llm"])
        return cls(**values)


def estimate(spec: ExperimentSpec, calls_per_game: float = 75, seconds_per_call: float = 3.0) -> dict:
    """A rough cost and duration for a design, before any game has been played.

    Every number here is an estimate, not a measurement. The system prompt is about
    2,200 characters, taken as 700 tokens; the user prompt is taken as 1,000 tokens once
    a model's own memory and the other players' speeches are in it, and a reply as 350.
    Scripted mock games average about 60 calls; 75 allows for models playing longer
    games. The pilot report prints the measured values that replace all of these.
    """
    from amongagents.agent.llm import PRICING

    system_tokens, user_tokens, output_tokens = 700, 1000, 350
    price = PRICING.get(spec.llm.model)
    cost_per_game = None
    if spec.llm.provider == "mock":
        cost_per_game, seconds_per_call = 0.0, spec.llm.mock_latency
    elif price:
        per = [p / 1_000_000 for p in price]
        # the system prompt is a cache read on all but each agent's first call
        cost_per_game = calls_per_game * (
            system_tokens * per[2] + user_tokens * per[0] + output_tokens * per[1]
        ) + spec.game["num_players"] * system_tokens * (per[3] - per[2])
    minutes = spec.n_games * calls_per_game * seconds_per_call / 60 / spec.concurrency
    return {
        "games": spec.n_games,
        "conditions": len(spec.conditions()),
        "cost_per_game_usd": cost_per_game,
        "cost_usd": None if cost_per_game is None else cost_per_game * spec.n_games,
        "minutes": minutes,
        "calls_per_game": calls_per_game,
    }


def minimum_detectable_difference(n_per_group: int, baseline: float = 0.5, power: float = 0.8, alpha: float = 0.05) -> float | None:
    """Smallest difference in proportions a two-group comparison detects at the given power."""
    if n_per_group < 2:
        return None
    z_alpha, z_power = NormalDist().inv_cdf(1 - alpha / 2), NormalDist().inv_cdf(power)
    for step in range(1, 1000):
        delta = step / 1000
        p1 = min(baseline + delta, 0.999)
        pooled = (baseline + p1) / 2
        needed = (
            z_alpha * math.sqrt(2 * pooled * (1 - pooled))
            + z_power * math.sqrt(baseline * (1 - baseline) + p1 * (1 - p1))
        ) ** 2 / (p1 - baseline) ** 2
        if needed <= n_per_group:
            return delta
    return None
