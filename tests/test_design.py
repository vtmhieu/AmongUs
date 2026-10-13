"""The experiment design and its schedule."""

from collections import Counter

import pytest

from amongagents.agent.llm import LLMConfig
from govlab.design import ExperimentSpec, estimate


def test_the_default_design_is_the_2x2_of_the_research_plan():
    spec = ExperimentSpec()
    assert [g.condition for g in spec.conditions()] == [
        "plurality/freeform",
        "plurality/justification",
        "majority/freeform",
        "majority/justification",
    ]
    assert spec.games_per_condition == 20 and spec.n_games == 80
    assert (spec.game["num_players"], spec.game["num_impostors"]) == (5, 1)
    assert spec.llm.model == "claude-haiku-5-5"


def test_levels_multiply_into_a_full_factorial():
    spec = ExperimentSpec(
        thresholds=("plurality", "majority", "supermajority"), ballots=("public", "secret")
    )
    assert len(spec.conditions()) == 3 * 2 * 2
    assert len({g.condition for g in spec.conditions()}) == 12


def test_every_block_holds_each_condition_once_in_a_shuffled_order():
    spec = ExperimentSpec(games_per_condition=12)
    schedule = spec.schedule()
    assert [s["slot"] for s in schedule] == list(range(48))
    orders = set()
    for block in range(12):
        in_block = [s for s in schedule if s["block"] == block]
        assert Counter(s["condition"] for s in in_block) == Counter(
            g.condition for g in spec.conditions()
        )
        orders.add(tuple(s["condition"] for s in in_block))
    assert len(orders) > 1  # interleaved, not the same order every time


def test_no_condition_is_systematically_played_first():
    schedule = ExperimentSpec(games_per_condition=40).schedule()
    first = Counter(schedule[i]["condition"] for i in range(0, len(schedule), 4))
    assert len(first) == 4 and max(first.values()) < 20


def test_matched_seeds_give_every_condition_of_a_block_the_same_seed():
    schedule = ExperimentSpec(games_per_condition=5, seed=100).schedule()
    for block in range(5):
        assert {s["seed"] for s in schedule if s["block"] == block} == {100 + block}


def test_independent_seeds_are_all_different():
    schedule = ExperimentSpec(games_per_condition=5, matched_seeds=False).schedule()
    assert len({s["seed"] for s in schedule}) == len(schedule)


def test_the_schedule_is_a_function_of_the_seed():
    assert ExperimentSpec(seed=7).schedule() == ExperimentSpec(seed=7).schedule()
    assert ExperimentSpec(seed=7).schedule() != ExperimentSpec(seed=8).schedule()


def test_round_trip_through_json_types():
    spec = ExperimentSpec(
        name="pilot",
        thresholds=("majority",),
        games_per_condition=5,
        budget_usd=2.5,
        llm=LLMConfig(effort="low", thinking="adaptive"),
    )
    assert ExperimentSpec.from_dict(spec.to_dict()) == spec


@pytest.mark.parametrize(
    "bad",
    [
        {"thresholds": ()},
        {"thresholds": ("plurality", "plurality")},
        {"protocols": ("debate",)},
        {"games_per_condition": 0},
        {"concurrency": 0},
        {"budget_usd": 0},
        {"game": {"num_players": 5}},
    ],
)
def test_invalid_designs_are_rejected(bad):
    with pytest.raises(ValueError):
        ExperimentSpec(**bad)


def test_unknown_settings_are_rejected_rather_than_ignored():
    with pytest.raises(ValueError, match="unknown"):
        ExperimentSpec.from_dict({"games_per_conditon": 20})


def test_the_estimate_scales_with_the_design():
    small, large = (
        estimate(ExperimentSpec(games_per_condition=5)),
        estimate(ExperimentSpec(games_per_condition=20)),
    )
    assert large["games"] == 4 * small["games"]
    assert large["cost_usd"] == pytest.approx(4 * small["cost_usd"])
    assert 0 < large["cost_usd"] < 10  # Haiku 5.5: the full study costs a few dollars
    assert estimate(ExperimentSpec(llm=LLMConfig(provider="mock")))["cost_usd"] == 0
