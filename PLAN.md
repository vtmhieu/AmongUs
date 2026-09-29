# Plan: running the II2202 experiment in the AmongUs sandbox

## Context
`II2202_Research_plan.pdf` describes a 2×2 between-games experiment:
- **Factors:** vote threshold (plurality vs absolute majority) × discussion protocol (free-form vs mandatory justification).
- **Setup:** 5 agents, 1 insider (impostor), one hosted model (GLM or DeepSeek), at least 20 games per condition.
- **Outcomes:** good-team win, damage absorbed, wrongful removal, detection time.
- **Schedule:** tasks T1–T8 over 6 weeks, with gates G1 (sandbox runs), G2 (parser ≥95% agreement) and G3 (pilot within budget).

This repo is the 7vik/AmongUs sandbox (`main.py`, game logic in `among-agents/amongagents/`). It runs, and one Ollama run (`expt-logs/.../exp_3`) finished. **It does not yet support the experiment.** The steps below build the missing pieces in the order the research plan's gates need them.

## Where the code does not match the research plan (fix these first)
| # | Finding | Location | Consequence / action |
|---|---|---|---|
| 1 | No skip or abstain ballot option. Table 1 and the "5 is the smallest team" argument assume one. | `envs/action.py:114-124` | Add a `SKIP` vote target. |
| 2 | A reply that fails to parse becomes a vote for the **last listed player**. So does a failed API call, which returns `SPEAK: ...`. | `agent/agent.py:259`, `168-201` | This biases wrongful removal directly. Re-prompt once, then abstain, and log `parse_failed` / `api_failed`. |
| 3 | Kills, votes, tallies and ejections are **not logged**. They exist only in `important_activity_log`. | `envs/game.py:354-389`, `286-291` | Risk R3 has happened, so add a structured event log. |
| 4 | Token `usage` is discarded, and there are no seeds, no condition field and no game duration. | `agent.py`, `main.py`, `utils.py` | The run metadata required by Table 1 is missing. |
| 5 | Sabotage is a stub. The insider's only destructive action is **Kill**. | `envs/action.py:236-242` | Damage absorbed equals the kill count (0–3 with 5 players). Say so in the report and keep a count model or switch to ordinal. |
| 6 | Votes are sequential and public. Players also see only their **last 4 observations**. | `game.py:498-512`, `player.py:132` | Keep this fixed (it is the same in all four conditions) and list it as a validity note. |
| 7 | The 5/1 preset exists but can't be chosen from the CLI. `MEETING_PHASE_INSTRUCTION` hardcodes "3 rounds". | `main.py:43`, `game_config.py:13-23`, `neutral_prompts.py:174` | Add a CLI flag and build the instruction text from the config. |

## Implementation steps (mapped to the research plan's tasks)

### T1 – Reproduce and configure (W1, gate G1)
- **`main.py`:**
  - Add `--game_config {three,five,seven}` (default `five`).
  - Make `--name` take effect (`utils.py:20`).
  - Fix `--display_ui` (`type=bool` bug).
- **Dev loop:** run 3 games of 5/1 on Ollama (free, per the README guide) to shake out bugs.
- **Real check:** run 3 games through OpenRouter with a candidate model (e.g. `deepseek/…`, `z-ai/glm-…`; confirm exact IDs on OpenRouter).
  - The research plan says the model is accessed "through its provider's API". Either add a `base_url` / API-key setting in `agent.py:57-64`, or change the report text to say OpenRouter.
- **Output:** write the log-schema audit in a short `docs/log_schema.md` (M1).

### T1/T2 – Instrumentation (the prerequisite for everything else)
- **New `events.jsonl`** under the run dir, one line per event, each tagged with `game_index`, `condition`, `seed`, `timestep` and `meeting_index`:
  - `kill` (killer, victim, room, witnesses) – `game.py:286-291` / `Kill.execute`
  - `meeting_start` (caller, `report|button`) – `CallMeeting.execute` (`action.py:61-98`)
  - `speech` (speaker, round, text, justification-parse result)
  - `vote` (voter, target or `SKIP`, `parsed_ok`)
  - `tally` (counts, threshold used, ejected or None, **counterfactual decision under the other threshold**). The last field is the manipulation check. Source: `voteout()`.
  - `game_end` (winner, reason, timesteps, n_meetings, duration)
- **`agent.py` `send_request`:**
  - Keep `usage` (prompt and completion tokens) and log non-200 responses.
  - Add up tokens and cost per game into `summary.json`, together with the model ID actually returned.
- **Seeds:** give each game its own `random.Random(seed)` held on the env. Use it in `initialize_players` (`game.py:111-156`), in task assignment (`task.py:85-113`) and for model choice. Record the seed in `summary.json`. Games run concurrently in one process, so global seeding would not isolate them.
- **Crash handling:** a game that crashes must still write a summary line with `valid=false` and the reason. This feeds the exclusion and regeneration rule.

### T2 – Parser and validation (W2, gate G2)
- **`analysis/parse_logs.py`:** turns `events.jsonl` + `summary.json` into `games.csv`, `meetings.csv` and `actions.csv`. The columns follow Table 1, plus `exposure` (task rounds the insider was alive), `wrongful_removal_{any,count}` and `detection_meeting` / `censored`.
- **`analysis/validate_parser.py`:** compares parser output with a hand-annotation CSV template for 10 transcripts and reports field agreement (target ≥ 95%).

### T3 – Governance factors as config flags (W2–W3)
- **New `envs/voting.py`:** a pure function `tally(ballots, living_voters, threshold) -> ejected | None`.
  - **Plurality:** the option with most votes (SKIP counts as an option). A tie or a SKIP win means no ejection.
  - **Majority:** a player needs more than half of the living voters.
  - `voteout()` calls this function and also computes the counterfactual result for the other threshold.
- **Game config keys:** `vote_threshold: plurality|majority` and `discussion_protocol: freeform|justification`. Expose both as CLI flags.
- **Discussion protocol**, in `meeting_phase` (`game.py:316-352`) and the prompts:
  - Before the final discussion round, insert either the justification instruction (`ACCUSE: <player|none>` + `EVIDENCE: …`) or a **length-matched neutral text**.
  - Add a regex format check that re-prompts once in the justification condition.
  - Put the texts in `neutral_prompts.py` so Appendix A can quote them verbatim.
- **`tests/test_voting.py`** (replaces the placeholder test): ties, all-skip, a SKIP plurality, a shrinking electorate (5→4→3 voters), and a case where majority and plurality disagree. Plus a test that a parse failure becomes an abstention.

### T4 – Pilot (W3, gate G3)
- **New `run_experiment.py`:**
  - Builds a shuffled, interleaved schedule of (condition, seed).
  - Limits concurrency to respect API rate limits.
  - Retries transient failures and regenerates invalid games.
  - Takes `--games_per_condition` and `--model`.
- **Pilot runs:** 5 games per condition for each shortlisted model.
- **`analysis/pilot_report.py`:** reports, per model:
  - cost and time per game
  - parse-valid rate (≥ 95% required)
  - baseline win rate (must fall in [0.15, 0.85])
  - share of meetings where the thresholds diverge
  - variance of the outcomes
- **Decisions:** choose the model and the runs per condition (15, 20 or 30).

### T5 – Freeze (W3)
- **`analysis/analyze.py`** is the one script behind every result:
  - logistic regression (threshold × protocol) and Fisher's exact test
  - negative binomial GLM with a log-exposure offset, plus Mann–Whitney with Cliff's delta
  - two-proportion test with risk difference
  - Kaplan–Meier, log-rank test and Cox model (lifelines)
  - Holm correction
  - figures F1–F5
- Add pinned `statsmodels`, `scipy`, `lifelines` and `matplotlib` to `requirements-mac.txt`.
- Commit the exclusion criteria (e.g. more than N fallbacks per game counts as invalid) and the damage definition, then `git tag prereg-v1` before the main runs.

### T6–T8 – Run, analyse, package (W4–W6)
- **Main runs:** `run_experiment.py` with the frozen settings, split across both laptops. Use different seed ranges and a separate run dir for each machine.
- **Qualitative sub-study:** `analysis/sample_wrongful.py` exports 20 wrongful-ejection meetings as transcripts for double-coding. `analysis/kappa.py` computes Cohen's κ.
- **Package:** tag a release containing logs, parsed tables, the script and a README section on how to reproduce.

## Critical files
- `main.py` (CLI, run loop)
- `among-agents/amongagents/envs/game.py` (meeting_phase, voteout, check_game_over, logging)
- `among-agents/amongagents/envs/action.py` (Vote, Kill, CallMeeting)
- `among-agents/amongagents/agent/agent.py` (send_request, choose_action fallback)
- `among-agents/amongagents/agent/neutral_prompts.py` (meeting / justification text)
- `among-agents/amongagents/envs/configs/game_config.py`
- `utils.py`
- New: `envs/voting.py`, `run_experiment.py`, `analysis/*`, `tests/test_voting.py`

## Verification
- **Unit tests:** `pytest tests/` covers the tally logic and the parse-failure fallback.
- **Smoke test:** Ollama 5/1 games, one per condition, run end-to-end. `events.jsonl` should have a kill, meeting, vote, tally and game_end chain for each game, and the counterfactual tally should appear.
- **Parser:** `parse_logs.py` runs on those games, and hand-checking one game against its transcript matches.
- **Pilot:** OpenRouter pilot runs produce `pilot_report.py` output with cost per game and parse-valid rate. That output is the evidence for gate G3.
- **Dry run of the analysis:** `analyze.py` runs on the pilot data and produces all five figures before the freeze.

## Recommended order to start now
1. Instrumentation, SKIP vote and the parse-failure fix.
2. Config flags and the tally module with tests.
3. The parser.
4. The interleaved runner.
5. The pilot.

Items 1–2 are what gates G1 and G2 depend on.
