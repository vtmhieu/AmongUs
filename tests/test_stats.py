"""The statistical tests, on data with known answers and on the degenerate cases a pilot produces."""

import json

import numpy as np
import pandas as pd
import pytest
from scipy import stats as sps

from govlab import stats


def games_table(n_per_cell=40, seed=0, win=None, wrongful=None, kill_rate=None, hazard=None):
    """A synthetic games table with planted effects per (threshold, protocol) cell."""
    rng = np.random.default_rng(seed)
    cells = [("plurality", "freeform"), ("plurality", "justification"), ("majority", "freeform"), ("majority", "justification")]
    win = win or dict.fromkeys(cells, 0.5)
    wrongful = wrongful or dict.fromkeys(cells, 0.4)
    kill_rate = kill_rate or dict.fromkeys(cells, 0.15)
    hazard = hazard or dict.fromkeys(cells, 0.3)
    rows = []
    for threshold, protocol in cells:
        cell = (threshold, protocol)
        for i in range(n_per_cell):
            exposure = int(rng.integers(6, 16))
            meetings = int(rng.integers(0, 4))
            caught = [m for m in range(1, meetings + 1) if rng.random() < hazard[cell]]
            rows.append(
                {
                    "game_id": f"{threshold}-{protocol}-{i}",
                    "condition": f"{threshold}/{protocol}",
                    "threshold": threshold,
                    "protocol": protocol,
                    "ballot": "public",
                    "crew_win": int(rng.random() < win[cell]),
                    "wrongful_any": int(rng.random() < wrongful[cell]),
                    "wrongful_count": 0,
                    "kills": int(rng.poisson(kill_rate[cell] * exposure)),
                    "exposure": exposure,
                    "insider_ejected": int(bool(caught)),
                    "time": caught[0] if caught else meetings,
                    "event": int(bool(caught)),
                    "meetings": meetings,
                    "timesteps": exposure + meetings,
                    "reason": "tasks",
                }
            )
    return pd.DataFrame(rows)


NO_MEETINGS = pd.DataFrame(columns=["condition", "rule_changed_outcome"])


class TestBuildingBlocks:
    def test_wilson_interval(self):
        p = stats.proportion(10, 20)
        assert (p["p"], round(p["low"], 3), round(p["high"], 3)) == (0.5, 0.299, 0.701)
        assert stats.proportion(0, 0)["p"] is None

    def test_wilson_interval_stays_inside_zero_and_one(self):
        zero, all_ = stats.proportion(0, 5), stats.proportion(5, 5)
        assert zero["low"] == 0 and 0 < zero["high"] < 1
        assert 0 < all_["low"] < 1 and all_["high"] == 1

    def test_two_proportions(self):
        c = stats.compare_proportions(15, 20, 5, 20)
        assert c["risk_difference"] == pytest.approx(0.5)
        assert c["rd_low"] < 0.5 < c["rd_high"] and c["rd_low"] > 0
        assert c["odds_ratio"] == pytest.approx(9.0)
        assert c["p_fisher"] == pytest.approx(sps.fisher_exact([[15, 5], [5, 15]])[1])
        assert c["p_z"] < 0.01

    def test_two_identical_proportions(self):
        c = stats.compare_proportions(10, 20, 10, 20)
        assert c["risk_difference"] == 0 and c["p_fisher"] == pytest.approx(1.0)
        assert stats.compare_proportions(0, 10, 0, 10)["p_z"] is None  # no variation: no z test

    def test_cliffs_delta(self):
        assert stats.cliffs_delta([3, 3, 3], [1, 1, 1]) == 1.0
        assert stats.cliffs_delta([1, 1], [3, 3]) == -1.0
        assert stats.cliffs_delta([1, 2, 3], [1, 2, 3]) == 0.0
        assert stats.cliffs_delta([], [1]) is None

    def test_mann_whitney(self):
        c = stats.compare_counts([2, 3, 3, 2, 3, 3], [0, 1, 0, 1, 1, 0])
        assert c["cliffs_delta"] == 1.0 and c["p"] < 0.01
        same = stats.compare_counts([1, 1, 1], [1, 1, 1])
        assert same["p"] is None and same["reason"] == "all values identical"

    def test_holm(self):
        assert stats.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
        assert stats.holm([0.01, None, 0.04]) == [pytest.approx(0.02), None, pytest.approx(0.04)]
        assert stats.holm([]) == []

    def test_power_matches_the_research_plan(self):
        # "40 games per level ... detects about 29 percentage points; at 30 games [60 per level] about 25"
        assert stats.minimum_detectable_difference(40) == pytest.approx(0.29, abs=0.02)
        assert stats.minimum_detectable_difference(60) == pytest.approx(0.25, abs=0.02)


class TestSurvival:
    def test_kaplan_meier_on_a_worked_example(self):
        # times 1,1,2,3 with the third censored: S(1) = 2/4, S(2) unchanged, S(3) = 0
        curve = stats.kaplan_meier([1, 1, 2, 3], [1, 1, 0, 1])
        assert [(p["t"], p["s"]) for p in curve] == [(0.0, 1.0), (1.0, 0.5), (3.0, 0.0)]
        assert [p["at_risk"] for p in curve] == [4, 4, 1]

    def test_kaplan_meier_with_no_events_is_flat(self):
        assert stats.kaplan_meier([0, 2, 3], [0, 0, 0]) == [{"t": 0.0, "s": 1.0, "at_risk": 3}]

    def test_logrank_agrees_with_scipy(self):
        rng = np.random.default_rng(3)
        time = np.concatenate([rng.integers(1, 4, 40), rng.integers(1, 6, 40)]).astype(float)
        event = (rng.random(80) < 0.7).astype(int)
        group = np.array(["a"] * 40 + ["b"] * 40)
        ours = stats.logrank(time, event, group)
        theirs = sps.logrank(
            sps.CensoredData(uncensored=time[:40][event[:40] == 1], right=time[:40][event[:40] == 0]),
            sps.CensoredData(uncensored=time[40:][event[40:] == 1], right=time[40:][event[40:] == 0]),
        )
        assert ours["p"] == pytest.approx(theirs.pvalue, rel=1e-6)
        assert ours["chi2"] == pytest.approx(theirs.statistic**2, rel=1e-6)

    def test_logrank_degenerate_cases(self):
        assert stats.logrank([1, 2], [0, 0], ["a", "b"])["reason"] == "the insider was never ejected"
        assert stats.logrank([1, 2], [1, 1], ["a", "a"])["reason"] == "one group"

    def test_cox_recovers_a_planted_hazard_ratio(self):
        cells = {("plurality", "freeform"): 0.5, ("plurality", "justification"): 0.5, ("majority", "freeform"): 0.2, ("majority", "justification"): 0.2}
        games = games_table(300, hazard=cells)
        fit = stats.cox(games, stats.design_factors(games), interaction=False)
        term = next(t for t in fit["terms"] if t["term"] == "threshold: majority")
        assert fit["ok"] and term["hazard_ratio"] < 0.7 and term["hazard_ratio_high"] < 1


class TestRegressions:
    def test_logistic_recovers_a_planted_main_effect(self):
        win = {("plurality", "freeform"): 0.3, ("plurality", "justification"): 0.3, ("majority", "freeform"): 0.7, ("majority", "justification"): 0.7}
        games = games_table(200, win=win)
        fit = stats.logistic(games, "crew_win", stats.design_factors(games), interaction=False)
        terms = {t["term"]: t for t in fit["terms"]}
        true_or = (0.7 / 0.3) / (0.3 / 0.7)
        assert terms["threshold: majority"]["odds_ratio_low"] < true_or < terms["threshold: majority"]["odds_ratio_high"]
        assert terms["threshold: majority"]["p"] < 0.001
        assert abs(terms["protocol: justification"]["coef"]) < 0.5  # nothing was planted here

    def test_the_interaction_model_has_the_product_term(self):
        games = games_table(60)
        fit = stats.logistic(games, "crew_win", stats.design_factors(games), interaction=True)
        assert [t["term"] for t in fit["terms"]] == [
            "intercept", "threshold: majority", "protocol: justification", "threshold: majority x protocol: justification",
        ]

    def test_logistic_reports_perfect_separation_instead_of_nonsense(self):
        win = {("plurality", "freeform"): 0.0, ("plurality", "justification"): 0.0, ("majority", "freeform"): 1.0, ("majority", "justification"): 1.0}
        fit = stats.logistic(games_table(10, win=win), "crew_win", {"threshold": ["plurality", "majority"], "protocol": ["freeform", "justification"]}, False)
        assert fit["ok"] is False and "separation" in fit["reason"]

    def test_logistic_without_variation(self):
        games = games_table(10)
        games["crew_win"] = 1
        fit = stats.logistic(games, "crew_win", stats.design_factors(games), False)
        assert fit["ok"] is False and "same in every game" in fit["reason"]

    def test_count_model_recovers_a_planted_rate_ratio(self):
        rate = {("plurality", "freeform"): 0.1, ("plurality", "justification"): 0.1, ("majority", "freeform"): 0.2, ("majority", "justification"): 0.2}
        games = games_table(250, kill_rate=rate)
        fit = stats.count_model(games, "kills", stats.design_factors(games), interaction=False)
        term = next(t for t in fit["terms"] if t["term"] == "threshold: majority")
        assert fit["ok"] and term["rate_ratio_low"] < 2.0 < term["rate_ratio_high"]
        assert term["rate_ratio_low"] > 1

    def test_count_model_uses_poisson_when_counts_are_not_overdispersed(self):
        games = games_table(30)
        games["kills"] = np.tile([1, 2], len(games) // 2)  # far less spread than a Poisson
        fit = stats.count_model(games, "kills", stats.design_factors(games), False)
        assert fit["ok"] and fit["model"].startswith("Poisson") and "note" in fit

    def test_count_model_with_no_damage_at_all(self):
        games = games_table(10)
        games["kills"] = 0
        assert stats.count_model(games, "kills", stats.design_factors(games), False)["ok"] is False


class TestAnalyse:
    def test_the_confirmatory_family_is_the_four_planned_tests(self):
        result = stats.analyse(games_table(30), NO_MEETINGS)
        assert [(t["id"], t["outcome"], t["contrast"]) for t in result["confirmatory"]] == [
            ("RQ1a", "crew_win", "majority vs plurality"),
            ("RQ1b", "kills", "majority vs plurality"),
            ("H1", "wrongful_any", "majority vs plurality"),
            ("RQ2", "wrongful_any", "justification vs freeform"),
        ]
        for t in result["confirmatory"]:
            assert t["p_holm"] >= t["p"]
        assert result["conditions"] == ["plurality/freeform", "plurality/justification", "majority/freeform", "majority/justification"]
        json.dumps(result)  # everything the UI is sent must be JSON

    def test_h1_and_h2_are_supported_when_their_effects_are_planted(self):
        cells = [("plurality", "freeform"), ("plurality", "justification"), ("majority", "freeform"), ("majority", "justification")]
        wrongful = dict(zip(cells, [0.7, 0.4, 0.3, 0.1]))  # lower under majority, lower with justification
        rate = dict(zip(cells, [0.08, 0.08, 0.2, 0.2]))  # more damage under majority
        result = stats.analyse(games_table(150, wrongful=wrongful, kill_rate=rate), NO_MEETINGS)
        verdicts = {h["id"]: h["verdict"] for h in result["hypotheses"]}
        assert verdicts["H1"] == "supported" and verdicts["H2"] == "supported"
        assert all(t["significant"] for t in result["confirmatory"] if t["id"] != "RQ1a")

    def test_h1_is_contradicted_when_majority_simply_wins_more(self):
        cells = [("plurality", "freeform"), ("plurality", "justification"), ("majority", "freeform"), ("majority", "justification")]
        result = stats.analyse(games_table(150, win=dict(zip(cells, [0.2, 0.2, 0.8, 0.8]))), NO_MEETINGS)
        assert {h["id"]: h["verdict"] for h in result["hypotheses"]}["H1"] == "contradicted"

    def test_no_effect_is_inconclusive_not_a_finding(self):
        games = games_table(20)
        for column, pattern in (("crew_win", [0, 1]), ("wrongful_any", [1, 0, 0, 1]), ("kills", [1, 2, 2, 1])):
            games[column] = np.tile(pattern, len(games) // len(pattern))  # the same in every condition
        games["exposure"] = 10
        result = stats.analyse(games, NO_MEETINGS)
        assert {h["verdict"] for h in result["hypotheses"]} == {"inconclusive"}
        assert not any(t["significant"] for t in result["confirmatory"])

    def test_a_verdict_must_survive_the_holm_correction(self):
        """An interval that excludes no effect is not enough once four tests are in the family."""
        cells = [("plurality", "freeform"), ("plurality", "justification"), ("majority", "freeform"), ("majority", "justification")]
        result = stats.analyse(games_table(40, seed=1, wrongful=dict(zip(cells, [0.55, 0.3, 0.55, 0.3]))), NO_MEETINGS)
        rq2 = next(t for t in result["confirmatory"] if t["id"] == "RQ2")
        h2 = next(h for h in result["hypotheses"] if h["id"] == "H2")
        assert rq2["effect"]["high"] < 1  # the unadjusted interval excludes no effect
        assert h2["verdict"] == ("supported" if rq2["significant"] else "inconclusive")

    def test_a_pilot_sized_run_with_separation_falls_back_to_exact_tests(self):
        cells = [("plurality", "freeform"), ("plurality", "justification"), ("majority", "freeform"), ("majority", "justification")]
        games = games_table(5, wrongful=dict(zip(cells, [1.0, 1.0, 0.0, 0.0])))
        result = stats.analyse(games, NO_MEETINGS)
        h1 = next(t for t in result["confirmatory"] if t["id"] == "H1")
        assert h1["test"] == "Fisher's exact test" and h1["fallback_reason"]
        assert h1["effect"]["measure"] == "risk_difference" and h1["effect"]["value"] == -1.0
        json.dumps(result)

    def test_one_condition_gives_descriptives_only(self):
        games = games_table(10)
        result = stats.analyse(games[games["condition"] == "plurality/freeform"], NO_MEETINGS)
        assert result["ok"] and result["confirmatory"] == [] and result["hypotheses"] == []
        assert len(result["cells"]) == 1 and "note" in result

    def test_a_single_factor_design_tests_only_that_factor(self):
        games = games_table(30)
        result = stats.analyse(games[games["protocol"] == "freeform"], NO_MEETINGS)
        assert [t["id"] for t in result["confirmatory"]] == ["RQ1a", "RQ1b", "H1"]
        assert result["models"]["crew_win"]["interaction"] is None

    def test_no_games(self):
        assert stats.analyse(pd.DataFrame(), NO_MEETINGS)["ok"] is False
