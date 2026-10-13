"""The pre-specified comparisons (research plan, section 2.4 and Table 2).

Every function takes plain arrays or the games table and returns plain dicts, so the
same results feed the written report, the figures and the web UI.

Conventions
-----------
- Reference levels are the upstream rules: plurality, free-form, public ballot. Every
  effect is "this level compared with the reference".
- Main effects come from the additive model (outcome ~ threshold + protocol), the
  interaction from the model that adds the product terms. With treatment coding, the
  lower-order terms of an interaction model are simple effects at the reference level
  of the other factor, which is not what RQ1 and RQ2 ask.
- Tests are two-sided at alpha = 0.05. Confirmatory p-values are Holm-corrected as one
  family. Effect sizes and 95% intervals are reported for everything and are what
  should be interpreted; the study is powered for large effects only.
- A model that cannot be estimated (no variation in the outcome, perfect separation,
  no events) is reported as such with the reason, and the exact test stands in for it.
"""

from __future__ import annotations

import itertools
import math
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats as sps
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import confint_proportions_2indep, proportion_confint
from statsmodels.tools.sm_exceptions import (
    ConvergenceWarning,
    HessianInversionWarning,
    PerfectSeparationError,
    PerfectSeparationWarning,
)

from amongagents.envs.governance import BALLOTS, PROTOCOLS, THRESHOLDS
from govlab.design import minimum_detectable_difference  # noqa: F401  (part of this module's interface)

ALPHA = 0.05
FACTORS = {"threshold": THRESHOLDS, "protocol": PROTOCOLS, "ballot": BALLOTS}

# The confirmatory family: (id, question, outcome, factor, kind of model).
# Fixed here, in code, before any main-experiment game is played.
CONFIRMATORY = [
    ("RQ1a", "Vote threshold -> good-team win", "crew_win", "threshold", "binary"),
    ("RQ1b", "Vote threshold -> damage absorbed", "kills", "threshold", "count"),
    ("H1", "Vote threshold -> wrongful removal", "wrongful_any", "threshold", "binary"),
    ("RQ2", "Discussion protocol -> wrongful removal", "wrongful_any", "protocol", "binary"),
]


def _f(x) -> float | None:
    """A float that survives JSON: NaN and infinities become None."""
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


# --- single-sample and two-sample building blocks ---------------------------------


def proportion(successes: int, n: int) -> dict:
    """A proportion with its Wilson 95% interval."""
    if n == 0:
        return {"k": 0, "n": 0, "p": None, "low": None, "high": None}
    low, high = proportion_confint(successes, n, alpha=ALPHA, method="wilson")
    return {"k": int(successes), "n": int(n), "p": successes / n, "low": _f(low), "high": _f(high)}


def compare_proportions(k1: int, n1: int, k0: int, n0: int) -> dict:
    """Group 1 against group 0 (the reference): risk difference, odds ratio, exact and z tests."""
    if n1 == 0 or n0 == 0:
        return {"ok": False, "reason": "an empty group"}
    low, high = confint_proportions_2indep(
        k1, n1, k0, n0, method="newcomb", compare="diff", alpha=ALPHA
    )
    odds_ratio, p_fisher = sps.fisher_exact([[k1, n1 - k1], [k0, n0 - k0]])
    pooled = (k1 + k0) / (n1 + n0)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n0))
    z = (k1 / n1 - k0 / n0) / se if se > 0 else None
    return {
        "ok": True,
        "p1": k1 / n1,
        "p0": k0 / n0,
        "n1": int(n1),
        "n0": int(n0),
        "risk_difference": k1 / n1 - k0 / n0,
        "rd_low": _f(low),
        "rd_high": _f(high),
        "odds_ratio": _f(odds_ratio),
        "p_fisher": _f(p_fisher),
        "z": _f(z),
        "p_z": _f(2 * sps.norm.sf(abs(z))) if z is not None else None,
    }


def cliffs_delta(x, y) -> float | None:
    """P(x > y) - P(x < y): how often a value from x exceeds one from y."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if len(x) == 0 or len(y) == 0:
        return None
    greater = (x[:, None] > y[None, :]).sum()
    less = (x[:, None] < y[None, :]).sum()
    return float((greater - less) / (len(x) * len(y)))


def compare_counts(x, y) -> dict:
    """Group x against group y (the reference): Mann-Whitney U with Cliff's delta."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if len(x) == 0 or len(y) == 0:
        return {"ok": False, "reason": "an empty group"}
    result = {
        "ok": True,
        "n1": len(x),
        "n0": len(y),
        "mean1": _f(x.mean()),
        "mean0": _f(y.mean()),
        "median1": _f(np.median(x)),
        "median0": _f(np.median(y)),
        "cliffs_delta": cliffs_delta(x, y),
    }
    if len(set(x) | set(y)) < 2:
        return {**result, "u": None, "p": None, "reason": "all values identical"}
    u, p = sps.mannwhitneyu(x, y, alternative="two-sided")
    return {**result, "u": _f(u), "p": _f(p)}


# --- design matrices ----------------------------------------------------------------


def design_factors(games: pd.DataFrame) -> dict[str, list[str]]:
    """The manipulated factors of a run and their levels, reference level first."""
    factors = {}
    for factor, order in FACTORS.items():
        present = [level for level in order if level in set(games[factor])]
        if len(present) > 1:
            factors[factor] = present
    return factors


def design_matrix(
    games: pd.DataFrame, factors: dict[str, list[str]], interaction: bool
) -> pd.DataFrame:
    """Treatment-coded regressors, with product terms for every pair of factors if asked."""
    columns = {"intercept": np.ones(len(games))}
    by_factor: dict[str, list[str]] = {}
    for factor, levels in factors.items():
        for level in levels[1:]:
            name = f"{factor}: {level}"
            columns[name] = (games[factor] == level).to_numpy(dtype=float)
            by_factor.setdefault(factor, []).append(name)
    if interaction:
        for f1, f2 in itertools.combinations(by_factor, 2):
            for a, b in itertools.product(by_factor[f1], by_factor[f2]):
                columns[f"{a} x {b}"] = columns[a] * columns[b]
    return pd.DataFrame(columns, index=games.index)


def _terms(fit, names: list[str], exponentiate: str) -> list[dict]:
    """Coefficient table. exponentiate names what exp(coef) is: an odds, rate or hazard ratio."""
    interval = np.asarray(fit.conf_int(alpha=ALPHA))
    rows = []
    for i, name in enumerate(names):
        coef, low, high = float(fit.params[i]), float(interval[i][0]), float(interval[i][1])
        rows.append(
            {
                "term": name,
                "coef": _f(coef),
                "se": _f(fit.bse[i]),
                "p": _f(fit.pvalues[i]),
                "low": _f(low),
                "high": _f(high),
                exponentiate: _f(math.exp(coef)) if abs(coef) < 50 else None,
                f"{exponentiate}_low": _f(math.exp(low)) if abs(low) < 50 else None,
                f"{exponentiate}_high": _f(math.exp(high)) if abs(high) < 50 else None,
            }
        )
    return rows


def _usable(fit, n_params: int) -> bool:
    values = np.concatenate([np.asarray(fit.params)[:n_params], np.asarray(fit.bse)[:n_params]])
    return bool(
        np.all(np.isfinite(values)) and np.all(np.abs(np.asarray(fit.params)[:n_params]) < 15)
    )


_FIT_PROBLEMS = (
    PerfectSeparationWarning,
    ConvergenceWarning,
    HessianInversionWarning,
    RuntimeWarning,
)


# --- regression models ----------------------------------------------------------------


def logistic(games: pd.DataFrame, outcome: str, factors: dict, interaction: bool) -> dict:
    """Logistic regression of a binary outcome on the design factors."""
    y = games[outcome].to_numpy(dtype=float)
    x = design_matrix(games, factors, interaction)
    info = {"model": "logistic", "outcome": outcome, "interaction": interaction, "n": len(y)}
    if len(set(y)) < 2:
        return {**info, "ok": False, "reason": f"{outcome} is the same in every game"}
    if len(y) <= x.shape[1]:
        return {**info, "ok": False, "reason": "fewer games than parameters"}
    try:
        with warnings.catch_warnings():
            for problem in _FIT_PROBLEMS:
                warnings.simplefilter("error", problem)
            fit = sm.Logit(y, x.to_numpy()).fit(disp=0, maxiter=200)
    except (PerfectSeparationError, PerfectSeparationWarning):
        return {
            **info,
            "ok": False,
            "reason": f"perfect separation: {outcome} is all 0 or all 1 in some condition",
        }
    except _FIT_PROBLEMS as e:
        return {**info, "ok": False, "reason": f"did not converge ({type(e).__name__})"}
    except np.linalg.LinAlgError:
        return {**info, "ok": False, "reason": "singular design: a condition has no games"}
    if not _usable(fit, x.shape[1]):
        return {**info, "ok": False, "reason": "estimates diverged (quasi-separation)"}
    return {**info, "ok": True, "terms": _terms(fit, list(x.columns), "odds_ratio")}


def count_model(games: pd.DataFrame, outcome: str, factors: dict, interaction: bool) -> dict:
    """Negative binomial regression of a count on the design factors, offset by log exposure.

    Kill counts in a five-player game range over 0-3 and are usually not overdispersed,
    in which case the negative binomial's dispersion goes to zero and it cannot be
    estimated. Poisson regression with robust standard errors is then used instead, and
    the result says so.
    """
    y = games[outcome].to_numpy(dtype=float)
    x = design_matrix(games, factors, interaction)
    offset = np.log(np.clip(games["exposure"].to_numpy(dtype=float), 1, None))
    info = {
        "model": "negative binomial",
        "outcome": outcome,
        "interaction": interaction,
        "n": len(y),
    }
    if y.sum() == 0:
        return {**info, "ok": False, "reason": f"{outcome} is zero in every game"}
    if len(y) <= x.shape[1]:
        return {**info, "ok": False, "reason": "fewer games than parameters"}
    names = list(x.columns)
    try:
        with warnings.catch_warnings():
            for problem in _FIT_PROBLEMS:
                warnings.simplefilter("error", problem)
            fit = sm.NegativeBinomial(y, x.to_numpy(), offset=offset).fit(disp=0, maxiter=500)
        alpha = float(fit.params[-1])
        if fit.mle_retvals.get("converged", True) and alpha > 1e-4 and _usable(fit, len(names)):
            return {
                **info,
                "ok": True,
                "dispersion": alpha,
                "terms": _terms(fit, names, "rate_ratio"),
            }
    except Exception:  # noqa: BLE001 - any failure of the NB fit leads to the Poisson fallback
        pass
    info["model"] = "Poisson (robust SE)"
    info["note"] = (
        "negative binomial could not be estimated (no overdispersion); Poisson with robust standard errors used"
    )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = sm.GLM(y, x.to_numpy(), family=sm.families.Poisson(), offset=offset).fit(
                cov_type="HC0"
            )
    except Exception as e:  # noqa: BLE001
        return {**info, "ok": False, "reason": f"could not be estimated ({type(e).__name__})"}
    if not _usable(fit, len(names)):
        return {
            **info,
            "ok": False,
            "reason": "estimates diverged: a condition has no damage at all",
        }
    return {**info, "ok": True, "dispersion": None, "terms": _terms(fit, names, "rate_ratio")}


# --- detection time -------------------------------------------------------------------


def kaplan_meier(time, event) -> list[dict]:
    """The Kaplan-Meier estimate of P(insider not yet ejected after meeting t)."""
    time, event = np.asarray(time, dtype=float), np.asarray(event, dtype=int)
    curve = [{"t": 0.0, "s": 1.0, "at_risk": int(len(time))}]
    survival = 1.0
    for t in sorted(set(time[event == 1])):
        at_risk = int((time >= t).sum())
        ejected = int(((time == t) & (event == 1)).sum())
        survival *= 1 - ejected / at_risk
        curve.append({"t": float(t), "s": survival, "at_risk": at_risk})
    return curve


def logrank(time, event, group) -> dict:
    """Log-rank test that detection curves are the same in every group."""
    time, event, group = (
        np.asarray(time, dtype=float),
        np.asarray(event, dtype=int),
        np.asarray(group),
    )
    groups = sorted(set(group))
    if len(groups) < 2:
        return {"ok": False, "reason": "one group"}
    if event.sum() == 0:
        return {"ok": False, "reason": "the insider was never ejected"}
    observed = np.zeros(len(groups))
    expected = np.zeros(len(groups))
    variance = np.zeros((len(groups), len(groups)))
    for t in sorted(set(time[event == 1])):
        at_risk = time >= t
        n = at_risk.sum()
        d = ((time == t) & (event == 1)).sum()
        n_g = np.array([(at_risk & (group == g)).sum() for g in groups], dtype=float)
        d_g = np.array(
            [((time == t) & (event == 1) & (group == g)).sum() for g in groups], dtype=float
        )
        observed += d_g
        expected += d * n_g / n
        if n > 1:
            factor = d * (n - d) / (n - 1)
            variance += factor * (np.diag(n_g / n) - np.outer(n_g, n_g) / n**2)
    diff = (observed - expected)[:-1]
    cov = variance[:-1, :-1]
    if np.linalg.matrix_rank(cov) < len(diff):
        return {"ok": False, "reason": "too few ejections to compare the groups"}
    chi2 = float(diff @ np.linalg.solve(cov, diff))
    return {
        "ok": True,
        "chi2": chi2,
        "df": len(groups) - 1,
        "p": _f(sps.chi2.sf(chi2, len(groups) - 1)),
        "groups": [str(g) for g in groups],
        "observed": [float(o) for o in observed],
        "expected": [float(e) for e in expected],
    }


def cox(games: pd.DataFrame, factors: dict, interaction: bool) -> dict:
    """Cox proportional hazards model of meetings until the insider is first ejected."""
    used = games[games["time"] > 0]  # a game with no meeting was never at risk of an ejection
    info = {
        "model": "Cox proportional hazards",
        "outcome": "detection",
        "interaction": interaction,
        "n": len(used),
    }
    if used["event"].sum() == 0:
        return {**info, "ok": False, "reason": "the insider was never ejected"}
    x = design_matrix(used, factors, interaction).drop(columns="intercept")
    if len(used) <= x.shape[1] or x.shape[1] == 0:
        return {**info, "ok": False, "reason": "too few games with a meeting"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = sm.PHReg(
                used["time"].to_numpy(dtype=float),
                x.to_numpy(),
                status=used["event"].to_numpy(),
                ties="efron",
            ).fit()
    except Exception as e:  # noqa: BLE001
        return {**info, "ok": False, "reason": f"could not be estimated ({type(e).__name__})"}
    if not _usable(fit, x.shape[1]):
        return {
            **info,
            "ok": False,
            "reason": "estimates diverged: too few ejections to separate the conditions (see the log-rank test and the curves)",
        }
    return {
        **info,
        "ok": True,
        "events": int(used["event"].sum()),
        "terms": _terms(fit, list(x.columns), "hazard_ratio"),
    }


# --- putting it together ---------------------------------------------------------------


def holm(p_values: list[float | None]) -> list[float | None]:
    """Holm-adjusted p-values; entries that are None stay None and do not count as tests."""
    present = [(i, p) for i, p in enumerate(p_values) if p is not None]
    adjusted: list[float | None] = [None] * len(p_values)
    if present:
        corrected = multipletests([p for _, p in present], alpha=ALPHA, method="holm")[1]
        for (i, _), p in zip(present, corrected):
            adjusted[i] = float(p)
    return adjusted


def _term(model: dict, name: str) -> dict | None:
    if not model.get("ok"):
        return None
    return next((t for t in model["terms"] if t["term"] == name), None)


def condition_summary(games: pd.DataFrame, meetings: pd.DataFrame) -> list[dict]:
    """Descriptive statistics per condition, in design order."""
    order = {c: i for i, c in enumerate(_condition_order(games))}
    rows = []
    for condition, cell in sorted(games.groupby("condition"), key=lambda kv: order[kv[0]]):
        held = meetings[meetings["condition"] == condition] if len(meetings) else meetings
        first = cell.iloc[0]
        rows.append(
            {
                "condition": condition,
                "threshold": first["threshold"],
                "protocol": first["protocol"],
                "ballot": first["ballot"],
                "n": len(cell),
                "crew_win": proportion(int(cell["crew_win"].sum()), len(cell)),
                "wrongful_any": proportion(int(cell["wrongful_any"].sum()), len(cell)),
                "insider_ejected": proportion(int(cell["insider_ejected"].sum()), len(cell)),
                "kills_mean": _f(cell["kills"].mean()),
                "kills_sd": _f(cell["kills"].std(ddof=1)) if len(cell) > 1 else None,
                "kills_distribution": {
                    int(k): int(n) for k, n in cell["kills"].value_counts().sort_index().items()
                },
                "kills_per_exposure": _f(cell["kills"].sum() / max(cell["exposure"].sum(), 1)),
                "wrongful_mean": _f(cell["wrongful_count"].mean()),
                "meetings_mean": _f(cell["meetings"].mean()),
                "games_with_meeting": proportion(int((cell["meetings"] > 0).sum()), len(cell)),
                "timesteps_mean": _f(cell["timesteps"].mean()),
                "reasons": {str(k): int(v) for k, v in cell["reason"].value_counts().items()},
                "meetings": len(held),
                "rule_changed_outcome": proportion(
                    int(held["rule_changed_outcome"].sum()) if len(held) else 0, len(held)
                ),
            }
        )
    return rows


def _condition_order(games: pd.DataFrame) -> list[str]:
    def key(condition: str):
        cell = games[games["condition"] == condition].iloc[0]
        return tuple(FACTORS[f].index(cell[f]) for f in FACTORS)

    return sorted(games["condition"].unique(), key=key)


def main_effect(
    games: pd.DataFrame, factor: str, level: str, reference: str, outcome: str, kind: str
) -> dict:
    """One level against the reference, pooled over the other factors."""
    a = games[games[factor] == level][outcome]
    b = games[games[factor] == reference][outcome]
    if kind == "binary":
        return compare_proportions(int(a.sum()), len(a), int(b.sum()), len(b))
    return compare_counts(a, b)


def analyse(games: pd.DataFrame, meetings: pd.DataFrame) -> dict:
    """Run every pre-specified comparison on the valid games of a run."""
    if len(games) == 0:
        return {"n_games": 0, "ok": False, "reason": "no valid games yet"}
    factors = design_factors(games)
    conditions = _condition_order(games)
    result = {
        "ok": True,
        "n_games": len(games),
        "conditions": conditions,
        "factors": factors,
        "cells": condition_summary(games, meetings),
        "models": {},
        "pooled": {},
        "detection": {},
        "confirmatory": [],
    }
    if not factors:
        result["note"] = "one condition only: descriptive statistics, no comparisons"
    multi = len(factors) > 1

    # regressions: additive for main effects, with products for the interaction (H3)
    for outcome, fit in (
        ("crew_win", logistic),
        ("wrongful_any", logistic),
        ("kills", count_model),
    ):
        entry = {"main": fit(games, outcome, factors, False) if factors else None}
        entry["interaction"] = fit(games, outcome, factors, True) if multi else None
        result["models"][outcome] = entry

    # pooled two-group comparisons for every non-reference level of every factor
    for factor, levels in factors.items():
        for level in levels[1:]:
            key = f"{factor}: {level}"
            result["pooled"][key] = {
                "factor": factor,
                "level": level,
                "reference": levels[0],
                "crew_win": main_effect(games, factor, level, levels[0], "crew_win", "binary"),
                "wrongful_any": main_effect(
                    games, factor, level, levels[0], "wrongful_any", "binary"
                ),
                "kills": main_effect(games, factor, level, levels[0], "kills", "count"),
            }

    # detection time (RQ3)
    result["detection"] = {
        "curves": {
            c: kaplan_meier(
                games[games["condition"] == c]["time"], games[games["condition"] == c]["event"]
            )
            for c in conditions
        },
        "max_time": int(games["time"].max()),
        "logrank": {f: logrank(games["time"], games["event"], games[f]) for f in factors},
        "logrank_conditions": logrank(games["time"], games["event"], games["condition"])
        if len(conditions) > 1
        else None,
        "cox": {
            "main": cox(games, factors, False) if factors else None,
            "interaction": cox(games, factors, True) if multi else None,
        },
    }

    # the confirmatory family, Holm-corrected together
    family = []
    for test_id, question, outcome, factor, kind in CONFIRMATORY:
        if factor not in factors:
            continue
        for level in factors[factor][1:]:
            name = f"{factor}: {level}"
            model = result["models"][outcome]["main"]
            term = _term(model, name)
            pooled = result["pooled"][name][outcome]
            if term is not None:
                ratio = "odds_ratio" if kind == "binary" else "rate_ratio"
                source, p = model["model"], term["p"]
                effect = {
                    "measure": ratio,
                    "value": term[ratio],
                    "low": term[f"{ratio}_low"],
                    "high": term[f"{ratio}_high"],
                }
            else:
                source = "Fisher's exact test" if kind == "binary" else "Mann-Whitney U"
                p = pooled.get("p_fisher") if kind == "binary" else pooled.get("p")
                if kind == "binary":
                    effect = {
                        "measure": "risk_difference",
                        "value": pooled.get("risk_difference"),
                        "low": pooled.get("rd_low"),
                        "high": pooled.get("rd_high"),
                    }
                else:
                    effect = {
                        "measure": "cliffs_delta",
                        "value": pooled.get("cliffs_delta"),
                        "low": None,
                        "high": None,
                    }
            family.append(
                {
                    "id": test_id,
                    "question": question,
                    "outcome": outcome,
                    "contrast": f"{level} vs {factors[factor][0]}",
                    "test": source,
                    "fallback_reason": None if term is not None else (model or {}).get("reason"),
                    "effect": effect,
                    "pooled": pooled,
                    "p": p,
                }
            )
    for entry, adjusted in zip(family, holm([e["p"] for e in family])):
        entry["p_holm"] = adjusted
        entry["significant"] = adjusted is not None and adjusted < ALPHA
    result["confirmatory"] = family
    result["hypotheses"] = hypotheses(result)
    return result


def hypotheses(result: dict) -> list[dict]:
    """The research plan's decision rules, applied mechanically.

    A verdict is a reading aid, not a finding. "Inconclusive" is the expected verdict
    for effects smaller than the study is powered to detect. H3 is exploratory and
    outside the corrected family, so its verdict rests on its interval alone.
    """
    by_id = {(e["id"], e["contrast"]): e for e in result["confirmatory"]}
    verdicts = []

    def direction(test: dict) -> int:
        """-1 / +1 if the effect is clearly below / above "no effect", else 0.

        Clearly means both that the 95% interval excludes no effect and that the test
        survives the Holm correction, so verdicts respect the family-wise error rate.
        """
        effect = test["effect"]
        if effect["low"] is None or effect["high"] is None or not test["significant"]:
            return 0
        null = 1.0 if effect["measure"].endswith("ratio") else 0.0
        return -1 if effect["high"] < null else 1 if effect["low"] > null else 0

    contrast = "majority vs plurality"
    if all((i, contrast) in by_id for i in ("RQ1a", "RQ1b", "H1")):
        w, d, r = (direction(by_id[(i, contrast)]) for i in ("RQ1a", "RQ1b", "H1"))
        if r < 0 and d > 0 and w == 0:
            verdict, why = (
                "supported",
                "fewer wrongful removals and more damage under majority, with no clear effect on the win rate",
            )
        elif w > 0:
            verdict, why = "contradicted", "the win rate rises with the threshold"
        else:
            parts = [
                "wrongful removal " + {-1: "lower", 0: "not clearly different", 1: "higher"}[r],
                "damage " + {-1: "lower", 0: "not clearly different", 1: "higher"}[d],
                "win rate " + {-1: "lower", 0: "not clearly different", 1: "higher"}[w],
            ]
            verdict, why = "inconclusive", "under majority: " + ", ".join(parts)
        verdicts.append(
            {
                "id": "H1",
                "statement": "An absolute majority reduces wrongful removal but increases damage absorbed, so its effect on the win rate is non-monotone.",
                "verdict": verdict,
                "why": why,
            }
        )

    contrast = "justification vs freeform"
    if ("RQ2", contrast) in by_id:
        sign = direction(by_id[("RQ2", contrast)])
        verdict = {-1: "supported", 0: "inconclusive", 1: "contradicted"}[sign]
        why = {
            -1: "wrongful removal is lower with mandatory justification, interval excluding no effect",
            0: "the effect of justification on wrongful removal is not clearly different from none",
            1: "wrongful removal is higher with mandatory justification",
        }[sign]
        verdicts.append(
            {
                "id": "H2",
                "statement": "Requiring a justification lowers the wrongful-removal rate.",
                "verdict": verdict,
                "why": why,
            }
        )

    interaction = (result["models"].get("wrongful_any") or {}).get("interaction")
    if interaction is not None:
        term = _term(interaction, "threshold: majority x protocol: justification")
        if term is None:
            verdicts.append(
                {
                    "id": "H3",
                    "statement": "The benefit of justification is larger under plurality.",
                    "verdict": "not testable",
                    "why": interaction.get("reason", "the interaction model has no such term"),
                }
            )
        else:
            # With plurality and free-form as reference, a larger benefit under plurality
            # is a positive product term: justification lowers the odds less under majority.
            sign = -1 if term["high"] < 0 else 1 if term["low"] > 0 else 0
            verdict = {1: "supported", 0: "inconclusive", -1: "contradicted"}[sign]
            why = {
                1: "justification reduces wrongful removal more under plurality than under majority",
                0: "the interval for the interaction includes zero",
                -1: "justification reduces wrongful removal more under majority than under plurality",
            }[sign]
            verdicts.append(
                {
                    "id": "H3",
                    "statement": "The factors interact: the benefit of justification is larger under plurality (exploratory).",
                    "verdict": verdict,
                    "why": why,
                }
            )
    return verdicts
