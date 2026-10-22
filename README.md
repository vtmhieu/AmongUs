# Do voting rules reduce the damage from malicious AI agents?

A controlled experiment for II2202 (KTH, autumn 2026) by Rong Jin and Hieu Vu.

Five LLM agents share a task. One of them is an undisclosed insider working against it.
We vary the rules by which the team may vote a member out, and measure how much damage
the insider does and how often an innocent agent is removed. The agents are treated as
black boxes: nothing here looks inside a model.

The environment is the *Among Us* sandbox of Golechha and Garriga-Alonso
([paper](https://arxiv.org/abs/2504.04072), [code](https://github.com/7vik/AmongUs)),
which builds on [AmongAgents](https://github.com/cyzus/among-agents). This repository is a
fork trimmed down to the game engine, with the governance rules, the measurements, the
experiment runner, the analysis and a web UI added on top.

## Quick start

Requires Python 3.10 or newer.

```bash
uv venv && uv pip install -e ".[dev]"     # or: python -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env                      # then put your Anthropic API key in .env
.venv/bin/govlab check                    # one tiny request: confirms the key and the model
.venv/bin/govlab serve                    # http://127.0.0.1:8765
```

No key yet? Everything except the model calls works without one. Choose **Offline mock**
in the UI, or pass `--mock` on the command line, to run the whole pipeline with scripted
players. Mock results exercise the tooling; they are not findings.

## The web UI

`govlab serve` opens one page with three views.

- **Design.** Tick the governance levels to compare (every combination becomes a
  condition), set the game, the model and the number of games. The page shows the
  conditions, an estimate of cost, time and the smallest detectable effect, and the exact
  text each level adds to what the players are told.
- **Watch.** The run's progress by condition, and any one game on a map of the ship with
  its transcript: who moved where, the kills, each meeting's statements and ballots, and
  the tally against its threshold, including what the other voting rules would have
  decided on the same ballots. Live while a game is being played, or replayed afterwards.
- **Results.** The pilot's go/no-go checks, the five planned figures, the planned
  comparisons with effect sizes and corrected p-values, and downloads of every table.

## The experiment

| | |
|---|---|
| Design | 2×2 between games: vote threshold × discussion protocol |
| Vote threshold | **plurality** (most votes; a tie ejects no one) vs **majority** (more than half of the living players) |
| Discussion protocol | **free-form** vs **justification** (the final statement must name an accused, or none, and one piece of evidence) |
| Held fixed | 5 agents, 1 insider, model and its settings, map, tasks, discussion rounds, time limit, all other prompt text |
| Model | Claude Haiku 5.5 (`claude-haiku-5-5`) through the Anthropic API |
| Outcomes | good-team win · damage absorbed (insider kills) · wrongful removal · meetings until the insider is ejected |
| Sample | 20 games per condition planned (floor 15, target 30), conditions interleaved |

Two more levels are implemented and can be added to a design, but are not part of the
planned 2×2: a **supermajority** threshold (two thirds) and a **secret ballot**.

The procedure, in the order of the research plan:

```bash
govlab run --pilot                        # T4: five games per condition
govlab analyze runs/<pilot>               #     read "Checks before interpreting": all three should pass
git tag prereg-v1                         # T5: freeze the analysis before any main-experiment game
govlab run --games 20 --name main         # T6: the experiment (estimated: about $2, about an hour)
govlab analyze runs/<main>                # T7: tables, tests, five figures, report.md
govlab sample runs/<main>                 #     20 wrongful ejections to code by hand; then `govlab kappa`
```

For the main run, the material for both hand checks (gate G2 and the coding) is already
exported, with instructions, in [docs/human-checks/](docs/human-checks/README.md).

`govlab --help` lists every command; `govlab run --help` every setting. A run that is
stopped or interrupted is continued with `govlab resume runs/<run_id>`.

Before relying on any of this, read [docs/design-notes.md](docs/design-notes.md). It lists
where the implementation departs from the research plan and from the upstream sandbox,
and what is still yours to decide.

## What a run produces

```
runs/<run_id>/
  manifest.json            the design, the schedule, the commit and library versions
  games/<game_id>/
    events.jsonl           structured events: what the analysis reads
    llm.jsonl              every prompt and raw reply: the primary record
    summary.json           result, validity, tokens, cost
  tables/                  games.csv, meetings.csv, actions.csv
  analysis/                results.json, report.md, figures/F1…F5 (png and pdf)
```

Model sampling cannot be reproduced token for token, so the logs are the record: every
number in the analysis is recomputed from `events.jsonl` and can be rebuilt at any time.
`runs/` is not tracked by git; archive finished runs deliberately. The formats are
described in [docs/log-schema.md](docs/log-schema.md).

## Layout

```
amongagents/               the game (from the upstream sandbox)
  envs/governance.py       the voting rules and the tally: pure functions
  envs/game.py             the game loop, meetings, votes, event log
  agent/                   prompts, the Claude client, reply parsing, the offline mock
govlab/                    the study
  design.py                conditions, schedule, seeds, exclusion criterion
  runner.py                plays a schedule: retries, regeneration, budget, resume
  metrics.py               the dependent variables, from the event log
  stats.py                 the pre-specified tests and the hypotheses' decision rules
  charts.py figures.py     figures F1–F5
  analyze.py               logs → tables, tests, figures, report, pilot checks
  qual.py                  wrongful-ejection sample, Cohen's kappa, annotation agreement
  server.py web/           the web UI
tests/                     none of them calls a model or needs a key
```

## Development

```bash
.venv/bin/python -m pytest          # about 20 seconds
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The tests exercise the Claude code path offline: the SDK is pointed at an in-process
transport, so the request it would send and its handling of real response bodies are
checked without a key or a network call.

## Credits and licence

Game logic from [AmongUs](https://github.com/7vik/AmongUs) by Satvik Golechha and Adrià
Garriga-Alonso, itself based on [AmongAgents](https://github.com/cyzus/among-agents) by
Chi, Mao and Tang. The white-box parts of that project (activation probes, sparse
autoencoders, deception ELO, human trials) are out of scope here and were removed; they
remain available upstream. Licensed under CC0 1.0 Universal, see [LICENSE](LICENSE).
