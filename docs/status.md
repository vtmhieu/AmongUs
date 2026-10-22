# Where the study stands

Last updated 2026-10-22. For a co-author picking the project up, and for the coding agent
working with them: read this first, then CLAUDE.md.

The experiment is finished. The pilots set the game, the analysis was frozen at the tag
`prereg-v1` (commit `5f5848c`), and the main run (80 games, 20 per condition, $2.25) was
played on that commit. Every confirmatory test is inconclusive after correction.
[RESULT.md](../RESULT.md) has the numbers and the checks behind them. What is left is human
work: the two hand checks and the report's last placeholders. No more games are needed.

## Getting it

```bash
git clone https://github.com/vtmhieu/AmongUs.git && cd AmongUs
git checkout governance-lab               # GitHub's default branch, II2202, is the old one
uv venv && uv pip install -e ".[dev]"
.venv/bin/govlab serve                    # http://127.0.0.1:8765, then Results or Watch
```

None of this needs an API key. A key (in `.env`, never committed) is only needed to play
new games.

## What is where

| What | Where |
|---|---|
| The study and how to run it | [README.md](../README.md) |
| Verified results of each run, newest first | [RESULT.md](../RESULT.md) |
| Every departure from the research plan | [design-notes.md](design-notes.md) |
| Log formats | [log-schema.md](log-schema.md) |
| Pilot 1 (no-go), pilot 2 (go), main run | `runs/20261015-141251-pilot`, `runs/20261015-143442-pilot2`, `runs/20261015-145843-main` |
| The main run's analysis | `runs/20261015-145843-main/analysis/`: `report.md`, `results.json`, `figures/F1…F5`; tables in `tables/` |
| The two hand checks | [human-checks/](human-checks/README.md) |
| The report | `Final Report Third Final Draft.docx` is current; the first and second drafts are kept |
| The freeze | tag `prereg-v1` = `5f5848c`; each run's `manifest.json` records the commit it ran on |

Each game folder holds `events.jsonl` (what the analysis reads), `llm.jsonl` (every prompt
and raw reply) and `summary.json`.

To check that the numbers come from the logs, rebuild the analysis in place:

```bash
.venv/bin/govlab analyze runs/20261015-145843-main     # a few seconds, no key
git status                                             # what changed, if anything
```

On 2026-10-22 this gave identical tables, `report.md`, `results.json` and PNG figures. The
PDF figures differ only in their embedded creation date; `git checkout -- runs/` puts the
committed ones back.

## The results in brief

- 80 of 80 games valid. The crew won 84% overall, and 95% in the baseline condition
  (plurality, free-form): a ceiling, reported as a limitation.
- The threshold changed the outcome of 5 of 76 votes. Most votes were unanimous or 3–1,
  and both rules decide those the same way.
- Confirmatory tests, Holm-corrected: win rate OR 0.38 (p 0.42), kills RR 1.14 (p 0.65),
  wrongful removal by threshold OR 1.30 (p 0.72), wrongful removal by protocol OR 4.04
  (p 0.38). H1, H2 and H3 are inconclusive.
- Exploratory: the map in the prompt (from upstream) lists vents but not corridors, so
  agents guess which walks are possible. A false belief about the map decided 3 of the 10
  wrongful ejections. The text is the same in every condition, so it is a construct-validity
  limitation, not a confound. The prompt stays as frozen.

## Still open (the authors' work)

| # | Task | Who | How |
|---|---|---|---|
| 1 | Gate G2: hand-annotate ten games | one author | [human-checks/README.md](human-checks/README.md), then `govlab validate runs/20261015-145843-main docs/human-checks/g2_annotations.csv` |
| 2 | Agree the codebook | both | `human-checks/codebook.md` is a draft |
| 3 | Code the ten wrongful ejections | each author on their own sheet, without seeing the other's | then `govlab kappa docs/human-checks/coding_sheet_hieu.csv docs/human-checks/coding_sheet_rong.csv --column <dimension>` |
| 4 | Fill the third draft's placeholders | both | §3.2 the G2 result; §3.4 κ, raw agreement and the agreed codes; A.3 the codebook as used |
| 5 | Settle the AI-use paragraph | both | It says Rong Jin reviewed the code; the plan requires the reviewer to be the author who did not prompt it. The code commits (`4b0c0df`…`997f025`) are under Rong's account. Check, then remove the bracketed note |
| 6 | Merge into `main` | either | pull request from `governance-lab` |

## Rules for an agent working here

- **Do not fill in, suggest values for, or pre-code anything in `docs/human-checks/`.** G2
  and κ measure human judgement; a model's answers make them meaningless. Explaining the
  codebook, or running `govlab validate` and `govlab kappa` on sheets the authors filled,
  is fine.
- Nothing frozen changes: the prompts, the game preset, `stats.CONFIRMATORY`,
  `design.MAX_FALLBACK_RATE`, `metrics.DAMAGE_WEIGHTS`. Anything new is exploratory and
  says so.
- The three committed runs are the record: do not edit them. New runs get their own
  folders, which git ignores.
- Mock results are never findings.
