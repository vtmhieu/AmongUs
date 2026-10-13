"""Command line.

    govlab serve                      the web UI: configure, watch, read results
    govlab check                      one tiny request to confirm the API key works
    govlab run --games 20             the 2x2 experiment, headless
    govlab run --pilot                five games per condition
    govlab run --mock --games 5       the same pipeline with scripted offline players
    govlab resume runs/<run_id>       finish a run that was stopped or interrupted
    govlab analyze runs/<run_id>      tables, tests, figures and report from the logs
    govlab list                       the runs on disk

The human checks of the research plan:

    govlab sample runs/<run_id>       transcripts of wrongful ejections + a coding sheet
    govlab kappa a.csv b.csv          Cohen's kappa between the two authors' coding sheets
    govlab annotate runs/<run_id>     an empty hand-annotation sheet for ten games
    govlab validate runs/<run_id> annotations.csv
                                      agreement between hand annotations and the metrics
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from amongagents.agent.llm import (
    DEFAULT_MODEL,
    EFFORTS,
    THINKING_MODES,
    LLMConfig,
    check_connection,
)
from amongagents.envs.configs.game_config import GAME_PRESETS
from amongagents.envs.governance import BALLOTS, PROTOCOLS, THRESHOLDS
from govlab.design import ExperimentSpec, estimate
from govlab.runner import Runner
from govlab.store import REPO_ROOT, RunStore, list_runs


def _spec(args) -> ExperimentSpec:
    game = dict(GAME_PRESETS[args.preset])
    for item in args.set or []:
        key, _, value = item.partition("=")
        if key not in game:
            raise SystemExit(f"--set {key}: not a game setting. Choose from {sorted(game)}")
        game[key] = int(value)
    return ExperimentSpec(
        name=args.name or ("pilot" if args.pilot else "experiment"),
        thresholds=tuple(args.thresholds),
        protocols=tuple(args.protocols),
        ballots=tuple(args.ballots),
        disclose_rules=not args.no_disclose,
        games_per_condition=5 if args.pilot and args.games is None else (args.games or 20),
        seed=args.seed,
        matched_seeds=not args.independent_seeds,
        game=game,
        llm=LLMConfig(
            provider="mock" if args.mock else "anthropic",
            model=args.model,
            effort=args.effort,
            thinking=args.thinking,
            max_tokens=args.max_tokens,
        ),
        concurrency=args.concurrency,
        max_attempts=args.max_attempts,
        budget_usd=args.budget,
    )


def _progress(total: int):
    done = {"n": 0}

    def publish(message: dict) -> None:
        if message["kind"] != "game" or message["game"]["status"] in ("running", "cancelled"):
            return
        game = message["game"]
        done["n"] += 1
        if game["status"] == "valid":
            outcome = f"{game['winner']} ({game['reason']})  kills={game['kills']}  meetings={game['meetings']}"
        else:
            outcome = f"INVALID: {game['invalid_reason']}" + (
                f" - {game['error']}" if game.get("error") else ""
            )
        cost = "" if game.get("cost_usd") is None else f"  ${game['cost_usd']:.3f}"
        print(
            f"[{done['n']:>3}] {game['game_id']}  {game['condition']:<26} {outcome}{cost}",
            flush=True,
        )

    return publish


def _run(store: RunStore, analyse: bool) -> int:
    print(
        f"run {store.run_id}: {len(store.pending_slots())} games to play, {store.spec.concurrency} at a time"
    )
    overview = asyncio.run(Runner(store, publish=_progress(len(store.schedule))).run())
    state = overview["status"]
    print(
        f"\n{state['state']}: {overview['valid']}/{overview['total']} valid games, ${overview['cost_usd']:.2f}"
    )
    if state["error"]:
        print(f"  {state['error']}")
    if analyse and overview["valid"]:
        from govlab.analyze import analyse_run

        analyse_run(store)
        print(f"report: {store.path / 'analysis' / 'report.md'}")
    return 0 if state["state"] == "completed" else 1


def cmd_run(args) -> int:
    spec = _spec(args)
    guess = estimate(spec)
    cost = "unpriced model" if guess["cost_usd"] is None else f"about ${guess['cost_usd']:.2f}"
    print(
        f"{guess['conditions']} conditions x {spec.games_per_condition} games = {guess['games']} games, {cost} (estimate)"
    )
    return _run(RunStore.create(spec, args.runs), analyse=not args.no_analysis)


def cmd_resume(args) -> int:
    return _run(RunStore(args.run), analyse=True)


def cmd_analyze(args) -> int:
    from govlab.analyze import analyse_run

    store = RunStore(args.run)
    results = analyse_run(store)
    if not results.get("ok"):
        print(results.get("reason", "nothing to analyse"))
        return 1
    print((store.path / "analysis" / "report.md").read_text(encoding="utf-8"))
    return 0


def cmd_list(args) -> int:
    for store in list_runs(args.runs):
        o = store.overview()
        print(
            f"{o['run_id']:<44} {o['status']['state']:<10} {o['valid']:>3}/{o['total']:<3} valid  ${o['cost_usd']:.2f}  {o['model']}"
        )
    return 0


def cmd_sample(args) -> int:
    from govlab.qual import export_sample

    out = export_sample(RunStore(args.run), n=args.n, seed=args.seed)
    print(
        f"transcripts: {out / 'meetings.md'}\ncoding sheet: {out / 'coding_sheet.csv'} (one copy per author)"
    )
    return 0


def cmd_kappa(args) -> int:
    from govlab.qual import kappa_from_sheets

    result = kappa_from_sheets(args.sheet_a, args.sheet_b, column=args.column)
    kappa = (
        "undefined (both coders used one code throughout)"
        if result["kappa"] is None
        else f"{result['kappa']:.3f}"
    )
    print(
        f"{result['items']} items, raw agreement {result['agreement']:.0%}, Cohen's kappa {kappa}"
    )
    if result["disagreements"]:
        print("disagreements on items: " + ", ".join(result["disagreements"]))
    return 0


def cmd_annotate(args) -> int:
    from govlab.qual import annotation_template

    print(f"fill in by hand: {annotation_template(RunStore(args.run), n=args.n, seed=args.seed)}")
    return 0


def cmd_validate(args) -> int:
    from govlab.qual import agreement

    result = agreement(RunStore(args.run), args.annotations)
    if not result["fields"]:
        print("no annotated fields found")
        return 1
    print(
        f"{result['agreed']}/{result['fields']} fields agree over {result['games']} games: {result['rate']:.1%} (gate G2 needs 95%)"
    )
    for m in result["mismatches"]:
        print(
            f"  {m['game_id']} {m['field']}: annotated {m['annotated']!r}, computed {m['computed']!r}"
        )
    return 0 if result["rate"] >= 0.95 else 1


def cmd_check(args) -> int:
    result = asyncio.run(check_connection(LLMConfig(model=args.model)))
    if result["ok"]:
        print(f"ok: {result['model']} replied {result['reply']!r} in {result['latency_s']:.1f}s")
        return 0
    print(f"failed: {result['error']}")
    return 1


def cmd_serve(args) -> int:
    import uvicorn

    print(f"Governance Lab: http://{args.host}:{args.port}")
    uvicorn.run("govlab.server:app", host=args.host, port=args.port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(
        prog="govlab", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="play an experiment")
    run.add_argument("--name")
    run.add_argument("--games", type=int, help="games per condition (default 20)")
    run.add_argument("--pilot", action="store_true", help="five games per condition, named 'pilot'")
    run.add_argument(
        "--thresholds", nargs="+", default=["plurality", "majority"], choices=THRESHOLDS
    )
    run.add_argument(
        "--protocols", nargs="+", default=["freeform", "justification"], choices=PROTOCOLS
    )
    run.add_argument("--ballots", nargs="+", default=["public"], choices=BALLOTS)
    run.add_argument(
        "--no-disclose", action="store_true", help="do not tell the players the voting rule"
    )
    run.add_argument("--seed", type=int, default=2202)
    run.add_argument(
        "--independent-seeds", action="store_true", help="a different seed for every game"
    )
    run.add_argument("--preset", default="study", choices=sorted(GAME_PRESETS))
    run.add_argument(
        "--set",
        action="append",
        metavar="KEY=VALUE",
        help="override a game setting, e.g. max_timesteps=40",
    )
    run.add_argument(
        "--mock", action="store_true", help="scripted offline players instead of a model"
    )
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--effort", default="medium", choices=EFFORTS)
    run.add_argument("--thinking", default="disabled", choices=THINKING_MODES)
    run.add_argument("--max-tokens", type=int, default=4096)
    run.add_argument("--concurrency", type=int, default=4, help="games in flight at once")
    run.add_argument("--max-attempts", type=int, default=3)
    run.add_argument(
        "--budget", type=float, help="stop starting games once this many USD are spent"
    )
    run.add_argument("--no-analysis", action="store_true")
    run.add_argument("--runs", type=Path, help="where runs are stored (default ./runs)")
    run.set_defaults(func=cmd_run)

    resume = sub.add_parser("resume", help="finish a stopped run")
    resume.add_argument("run", type=Path)
    resume.set_defaults(func=cmd_resume)

    analyze = sub.add_parser("analyze", help="tables, tests, figures and report from a run's logs")
    analyze.add_argument("run", type=Path)
    analyze.set_defaults(func=cmd_analyze)

    listing = sub.add_parser("list", help="runs on disk")
    listing.add_argument("--runs", type=Path)
    listing.set_defaults(func=cmd_list)

    sample = sub.add_parser(
        "sample", help="export wrongful-ejection meetings for qualitative coding"
    )
    sample.add_argument("run", type=Path)
    sample.add_argument("--n", type=int, default=20)
    sample.add_argument("--seed", type=int, default=0)
    sample.set_defaults(func=cmd_sample)

    kappa = sub.add_parser("kappa", help="Cohen's kappa between two coding sheets")
    kappa.add_argument("sheet_a", type=Path)
    kappa.add_argument("sheet_b", type=Path)
    kappa.add_argument("--column", default="code")
    kappa.set_defaults(func=cmd_kappa)

    annotate = sub.add_parser("annotate", help="an empty hand-annotation sheet")
    annotate.add_argument("run", type=Path)
    annotate.add_argument("--n", type=int, default=10)
    annotate.add_argument("--seed", type=int, default=0)
    annotate.set_defaults(func=cmd_annotate)

    validate = sub.add_parser("validate", help="compare hand annotations with the computed metrics")
    validate.add_argument("run", type=Path)
    validate.add_argument("annotations", type=Path)
    validate.set_defaults(func=cmd_validate)

    check = sub.add_parser("check", help="confirm the API key and model work")
    check.add_argument("--model", default=DEFAULT_MODEL)
    check.set_defaults(func=cmd_check)

    serve = sub.add_parser("serve", help="the web UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
