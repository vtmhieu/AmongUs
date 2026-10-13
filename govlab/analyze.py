"""One call from archived logs to every table, test and figure of a run.

    results = analyse_run(RunStore("runs/<run_id>"))

writes tables/*.csv, analysis/results.json, analysis/report.md and analysis/figures/*,
and returns the same results the web UI shows. Nothing here calls a model: it can be
re-run on archived logs at any time, which is what makes the analysis reproducible
even though the games themselves are not.
"""

from __future__ import annotations

import math

import pandas as pd

from govlab import charts, figures, stats
from govlab.metrics import DAMAGE_WEIGHTS, build_tables
from govlab.store import RunStore, write_json

# Pilot gates. The first two are the research plan's model-selection criteria; the
# third is added here because the design has nothing to measure in a game that never
# holds a meeting.
MIN_PARSE_RATE = 0.95
BASELINE_WIN_RANGE = (0.15, 0.85)
MIN_GAMES_WITH_MEETING = 0.5


def quality(store: RunStore, games: pd.DataFrame, meetings: pd.DataFrame) -> dict:
    """Data-quality numbers and the pilot's go/no-go gates."""
    attempts = store.summaries()
    final = store.final_games()
    decisions = sum(a.get("decisions", 0) for a in attempts)
    fallbacks = sum(a.get("fallbacks", 0) for a in attempts)
    invalid = [a for a in attempts if not a.get("valid")]
    reasons: dict[str, int] = {}
    for a in invalid:
        reasons[a.get("invalid_reason") or "unknown"] = reasons.get(a.get("invalid_reason") or "unknown", 0) + 1

    out = {
        "attempts": len(attempts),
        "valid_games": len(games),
        "invalid_attempts": len(invalid),
        "invalid_reasons": reasons,
        "failed_slots": sum(1 for s in final.values() if not s.get("valid")),
        "decisions": decisions,
        "parse_rate": 1 - fallbacks / decisions if decisions else None,
        "reprompts": sum(a.get("reprompts", 0) for a in attempts),
        "refusals": sum(a.get("refusals", 0) for a in attempts),
        "cost_usd": sum(a.get("cost_usd") or 0 for a in attempts),
        "gates": [],
    }
    if len(games) == 0:
        return out

    usage = games[["input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"]].sum()
    prompt_tokens = usage["input_tokens"] + usage["cache_read_tokens"] + usage["cache_write_tokens"]
    calls = games["calls"].sum()
    cost_per_game = games["cost_usd"].mean() if games["cost_usd"].notna().all() else None
    out.update(
        cost_per_game_usd=_num(cost_per_game),
        seconds_per_game=_num(games["duration_s"].mean()),
        calls_per_game=_num(games["calls"].mean()),
        prompt_tokens_per_call=_num(prompt_tokens / calls) if calls else None,
        output_tokens_per_call=_num(usage["output_tokens"] / calls) if calls else None,
        cache_hit_share=_num(usage["cache_read_tokens"] / prompt_tokens) if prompt_tokens else None,
        meetings_per_game=_num(games["meetings"].mean()),
        games_with_meeting=_num((games["meetings"] > 0).mean()),
        rule_changed_outcome=stats.proportion(int(meetings["rule_changed_outcome"].sum()) if len(meetings) else 0, len(meetings)),
    )
    justified = games[games["protocol"] == "justification"]
    if len(justified) and justified["final_statements"].sum():
        out["justification_compliance"] = _num(justified["justified_statements"].sum() / justified["final_statements"].sum())

    # what the remaining design would cost at the measured rate
    n_conditions = games["condition"].nunique()
    out["projection"] = {
        str(n): {
            "games": n * n_conditions,
            "cost_usd": _num(cost_per_game * n * n_conditions) if cost_per_game is not None else None,
            "minutes": _num(games["duration_s"].mean() * n * n_conditions / 60 / store.spec.concurrency),
            "detectable_difference": stats.minimum_detectable_difference(n * n_conditions // 2),
        }
        for n in (15, 20, 30)
    }

    # the baseline is the upstream rule set if the design has it, else its first condition
    reference = games[(games["threshold"] == "plurality") & (games["protocol"] == "freeform") & (games["ballot"] == "public")]
    if len(reference) == 0:
        reference = games[games["condition"] == stats._condition_order(games)[0]]
    win = reference["crew_win"].mean()
    low, high = BASELINE_WIN_RANGE
    out["gates"] = [
        {
            "id": "parse",
            "label": "Coherent play",
            "detail": f"{out['parse_rate']:.1%} of turns were read as a valid move (need at least {MIN_PARSE_RATE:.0%})",
            "pass": out["parse_rate"] >= MIN_PARSE_RATE,
        },
        {
            "id": "baseline",
            "label": "Baseline win rate",
            "detail": f"the crew wins {win:.0%} of {len(reference)} baseline games (need {low:.0%}-{high:.0%}); "
            "adjust tasks per player or the time limit if not",
            "pass": bool(low <= win <= high),
        },
        {
            "id": "meetings",
            "label": "Governance is exercised",
            "detail": f"{out['games_with_meeting']:.0%} of games held at least one meeting "
            f"(want at least {MIN_GAMES_WITH_MEETING:.0%}); {out['meetings_per_game']:.2f} meetings per game",
            "pass": bool(out["games_with_meeting"] >= MIN_GAMES_WITH_MEETING),
        },
    ]
    return out


def _num(x) -> float | None:
    if x is None:
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def analyse_run(store: RunStore, write: bool = True, draw: bool = True) -> dict:
    tables = build_tables(store, write=write)
    games, meetings, actions = tables["games"], tables["meetings"], tables["actions"]
    results = stats.analyse(games, meetings)
    results["run"] = store.overview()
    results["quality"] = quality(store, games, meetings)
    results["charts"] = charts.chart_data(games, actions)
    results["damage_weights"] = DAMAGE_WEIGHTS
    results["is_mock"] = store.spec.llm.provider == "mock"
    results["max_fallback_rate"] = store.spec.max_fallback_rate
    if write:
        out = store.path / "analysis"
        out.mkdir(exist_ok=True)
        results["figures"] = figures.draw_all(results["charts"], out / "figures") if draw else {}
        write_json(out / "results.json", results)
        (out / "report.md").write_text(report(results), encoding="utf-8")
    return results


# --- the written report -----------------------------------------------------------------


def _pct(x) -> str:
    return "–" if x is None else f"{x:.0%}"


def _p(x) -> str:
    return "–" if x is None else "<0.001" if x < 0.001 else f"{x:.3f}"


def _ci(p: dict) -> str:
    return "–" if p["p"] is None else f"{p['p']:.0%} [{p['low']:.0%}, {p['high']:.0%}]"


def _effect(effect: dict) -> str:
    if effect["value"] is None:
        return "–"
    name = {"odds_ratio": "OR", "rate_ratio": "RR", "risk_difference": "RD", "cliffs_delta": "δ"}[effect["measure"]]
    if effect["low"] is None:
        return f"{name} {effect['value']:.2f}"
    return f"{name} {effect['value']:.2f} [{effect['low']:.2f}, {effect['high']:.2f}]"


def _model_lines(title: str, model: dict | None, ratio: str) -> list[str]:
    if model is None:
        return []
    lines = [f"**{title}** — {model['model']}, n = {model['n']}"]
    if not model["ok"]:
        return lines + [f"Not estimated: {model['reason']}.", ""]
    if model.get("note"):
        lines.append(f"Note: {model['note']}.")
    lines += ["", f"| Term | {ratio} | 95% CI | p |", "|---|---|---|---|"]
    for t in model["terms"]:
        if t["term"] == "intercept":
            continue
        key = {"OR": "odds_ratio", "RR": "rate_ratio", "HR": "hazard_ratio"}[ratio]
        value = "–" if t[key] is None else f"{t[key]:.2f}"
        ci = "–" if t[f"{key}_low"] is None or t[f"{key}_high"] is None else f"[{t[f'{key}_low']:.2f}, {t[f'{key}_high']:.2f}]"
        lines.append(f"| {t['term']} | {value} | {ci} | {_p(t['p'])} |")
    return lines + [""]


def report(results: dict) -> str:
    run, q = results["run"], results["quality"]
    lines = [f"# {run['name']}", ""]
    if results.get("is_mock"):
        lines += [
            "> **Offline mock run.** These games were played by scripted players, not by a model.",
            "> The numbers below exercise the pipeline and are not findings.",
            "",
        ]
    lines += [
        f"Run `{run['run_id']}` · model `{run['model']}` · {q['valid_games']} valid games of {run['total']} scheduled "
        f"· {q['invalid_attempts']} invalid attempts regenerated · ${q['cost_usd']:.2f} spent.",
        "",
    ]
    if not results.get("ok"):
        return "\n".join(lines + [results.get("reason", "No results."), ""])

    lines += ["## Checks before interpreting", ""]
    for gate in q["gates"]:
        lines.append(f"- {'PASS' if gate['pass'] else 'FAIL'} — **{gate['label']}**: {gate['detail']}.")
    changed = q["rule_changed_outcome"]
    lines += [
        f"- Manipulation check: in {changed['k']} of {changed['n']} meetings the vote threshold changed who was ejected"
        + (f" ({changed['p']:.0%})." if changed["p"] is not None else "."),
    ]
    if "justification_compliance" in q:
        lines.append(f"- Protocol compliance: {q['justification_compliance']:.0%} of final-round statements under the justification protocol were valid.")
    lines += [
        f"- Per game: {q['calls_per_game']:.0f} model calls, {q['seconds_per_game']:.0f} s, "
        + ("cost not priced" if q["cost_per_game_usd"] is None else f"${q['cost_per_game_usd']:.3f}")
        + f"; {_pct(q['cache_hit_share'])} of prompt tokens read from cache.",
        "",
        "## Conditions",
        "",
        "| Condition | n | Crew win | Wrongful removal | Insider ejected | Kills (mean) | Meetings (mean) |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in results["cells"]:
        lines.append(
            f"| {c['condition']} | {c['n']} | {_ci(c['crew_win'])} | {_ci(c['wrongful_any'])} | "
            f"{_ci(c['insider_ejected'])} | {c['kills_mean']:.2f} | {c['meetings_mean']:.2f} |"
        )
    lines += ["", "Proportions are shown with 95% Wilson intervals.", ""]

    if results["confirmatory"]:
        lines += [
            "## Confirmatory tests",
            "",
            "Two-sided, alpha = 0.05, Holm-corrected as one family. Interpret the effect sizes and intervals, not the p-values alone.",
            "",
            "| | Question | Contrast | Effect | Test | p | p (Holm) |",
            "|---|---|---|---|---|---|---|",
        ]
        for t in results["confirmatory"]:
            lines.append(
                f"| {t['id']} | {t['question']} | {t['contrast']} | {_effect(t['effect'])} | {t['test']} | {_p(t['p'])} | {_p(t['p_holm'])} |"
            )
        lines += ["", "OR odds ratio, RR rate ratio, RD risk difference, δ Cliff's delta; brackets are 95% intervals.", ""]
        fallbacks = [t for t in results["confirmatory"] if t["fallback_reason"]]
        for t in fallbacks:
            lines.append(f"- {t['id']} ({t['contrast']}): the regression was not estimated ({t['fallback_reason']}); the exact test is reported instead.")
        if fallbacks:
            lines.append("")

    if results["hypotheses"]:
        lines += ["## Hypotheses", ""]
        for h in results["hypotheses"]:
            lines.append(f"- **{h['id']} — {h['verdict']}.** {h['statement']} *{h['why'].capitalize()}.*")
        lines += ["", "Verdicts apply the plan's decision rules mechanically. The study is powered for large effects only, so *inconclusive* is not evidence of no effect.", ""]

    lines += ["## Models", ""]
    for outcome, title, ratio in (("crew_win", "Good-team win", "OR"), ("wrongful_any", "Wrongful removal", "OR"), ("kills", "Damage (kills, offset log exposure)", "RR")):
        entry = results["models"].get(outcome) or {}
        lines += _model_lines(f"{title}, main effects", entry.get("main"), ratio)
        lines += _model_lines(f"{title}, with interaction", entry.get("interaction"), ratio)
    detection = results["detection"]
    lines += _model_lines("Detection time, main effects", detection["cox"]["main"], "HR")
    lines += _model_lines("Detection time, with interaction", detection["cox"]["interaction"], "HR")
    for factor, test in detection["logrank"].items():
        if test["ok"]:
            lines.append(f"- Log-rank test across {factor}: chi2({test['df']}) = {test['chi2']:.2f}, p = {_p(test['p'])}.")
        else:
            lines.append(f"- Log-rank test across {factor}: not computed ({test['reason']}).")
    lines += ["", "Detection time is meetings until the insider is first ejected; games in which that never happens are right-censored, not dropped.", ""]

    if results.get("figures"):
        lines += ["## Figures", ""]
        for name, files in results["figures"].items():
            lines.append(f"![{name}](figures/{files[0]})")
            lines.append("")
    lines += [
        "## Definitions",
        "",
        "- **Damage** is the insider's successful destructive actions. Kill is the only destructive action in this sandbox, so damage equals kills per game.",
        "- **Wrongful removal**: at least one good agent was ejected in the game.",
        "- **Exposure**: task-phase timesteps the insider was alive, the offset of the count model.",
        "- A game is excluded and replayed if it aborts on an API error or if more than "
        f"{results['max_fallback_rate']:.0%} of its turns could not be read as a move.",
        "",
    ]
    return "\n".join(lines)
