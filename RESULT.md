# Results log

Verified summaries of each real run, newest first. Mock runs are never recorded here.

## 2026-10-15 · Main experiment (`runs/20261015-145843-main`) · all hypotheses inconclusive

**Setup.** Frozen at `prereg-v1` (commit `5f5848c`; the manifest records it, working tree clean).
Study preset from pilot 2: 5 players, 1 Impostor, 5 tasks per Crewmate, kill cooldown 2,
30 timesteps. 2×2, 20 games per condition, conditions interleaved, same seed per block. Cap $5.

**Run.** 80/80 games valid, 0 replayed, $2.25 spent. About 75 min of wall time with 4 games in
parallel; 222 s, 73 model calls and $0.028 per game.

### Checks before interpreting

| Check | Result | Verdict |
| --- | --- | --- |
| Coherent play | 100% of turns readable | PASS |
| Baseline win rate | crew wins 19/20 baseline games (95%); 67/80 overall (84%) | **FAIL** (need 15–85%) |
| Governance exercised | 78% of games held a meeting; 0.95 meetings per game | PASS |
| Manipulation check | the threshold changed the outcome in 5 of 76 meetings (7%) | – |
| Protocol compliance | 96% of final-round statements under justification were valid | – |

The baseline gate is a pilot gate; it is reported here because the analysis prints it for every
run. Pilot 2's 60% came from 5 games and was an underestimate. The baseline condition sits near
the ceiling, which leaves little room to show a rule that *raises* the crew's win rate. Report this
as a limitation; it does not invalidate the run (the exclusion rule looks only at whether a game ran
properly, and no game was excluded).

### Conditions

| Condition | n | Crew win | Wrongful removal | Insider ejected | Kills (mean) | Meetings (mean) |
| --- | --- | --- | --- | --- | --- | --- |
| plurality/freeform | 20 | 95% [76, 99] | 5% [1, 24] | 35% [18, 57] | 1.40 | 1.20 |
| plurality/justification | 20 | 85% [64, 95] | 15% [5, 36] | 20% [8, 42] | 1.25 | 0.65 |
| majority/freeform | 20 | 75% [53, 89] | 5% [1, 24] | 20% [8, 42] | 1.60 | 0.90 |
| majority/justification | 20 | 80% [58, 92] | 20% [8, 42] | 40% [22, 61] | 1.45 | 1.05 |

### Confirmatory tests (Holm-corrected family)

| Test | Contrast | Effect [95% CI] | p | p (Holm) |
| --- | --- | --- | --- | --- |
| RQ1a win | majority vs plurality | OR 0.38 [0.11, 1.36] | 0.139 | 0.416 |
| RQ1b kills | majority vs plurality | RR 1.14 [0.88, 1.47] | 0.327 | 0.654 |
| H1 wrongful removal | majority vs plurality | OR 1.30 [0.31, 5.39] | 0.719 | 0.719 |
| RQ2 wrongful removal | justification vs free-form | OR 4.04 [0.78, 20.83] | 0.095 | 0.381 |

Verdicts: H1 inconclusive, H2 inconclusive, H3 (exploratory) inconclusive. No test survives the
correction. Directions, for description only: majority points toward a lower crew win rate and more
kills; justification points toward *more* wrongful removals, the opposite of H2.

### Checks against the project's expectations

- Each summary agrees with its game_end event: 0 mismatches.
- Every tally recomputed independently from its ballots (plurality: a unique top count that is not
  SKIP; majority: more than half of living voters) matches the logged result and both logged
  counterfactuals: 0 mismatches.
- Protocol texts appear only in their own conditions: 0 misplaced.
- Outcomes: crew by tasks 44, crew by ejection 23, Impostor by outnumbering 13, timeouts 0.
  Median game length 16 timesteps.

### Exploratory observations (not tests)

- The five meetings where the threshold mattered: majority blocked the Impostor's ejection twice
  and an innocent's twice; plurality ejected an innocent once where majority would have blocked it.
  This is the trade-off H1 describes, but in 5 cases only.
- 10 wrongful ejections in 9 games (g0002, g0013, g0017, g0027 ×2, g0045, g0048, g0058, g0063,
  g0076), 8 of them under justification. Every one of them is the qualitative sample (`govlab sample`
  asks for 20; there are 10). A question for the coding: does the required ACCUSE line push players
  into naming someone on weak evidence?

## 2026-10-15 · Pilot 2 (`runs/20261015-143442-pilot2`) · GO

**Setup.** As pilot 1, with two game settings changed in all conditions: 5 tasks per Crewmate
(2 common, 2 short, 1 long; 20 crew tasks instead of 12) and kill cooldown 2 instead of 3.
Passed as `--set num_common_tasks=2 --set num_short_tasks=2 --set kill_cooldown=2`; confirmed
in the run's manifest. Cap $2.

**Run.** 20/20 games valid, 0 replayed, $0.49 spent. About 18 min of wall time with 4 games in
parallel; 194 s, 65 model calls and $0.024 per game.

### Gates

| Gate | Result | Need | Verdict |
| --- | --- | --- | --- |
| Coherent play | 100% of 1,302 turns readable | ≥ 95% | PASS |
| Baseline win rate | crew wins 3/5 baseline games (60%); 16/20 overall (80%) | 15–85% | PASS |
| Governance exercised | 65% of games held a meeting; 0.70 meetings per game | ≥ 50% | PASS |

Also reported: the vote threshold changed who was ejected in 0 of 14 meetings; 100% of
final-round statements under the justification protocol were compliant.

### What the games look like

- Outcomes: crew by tasks 12, crew by ejecting the Impostor 4, Impostor by outnumbering 4.
- Games still end early: timestep 5–19 of 30 (median 13.5, pilot 1: 13). The win-rate change
  came from more kills and ejections, not from longer games; no game hit the time limit.
- 27 kills in 20 games (1.35 per game). 6 ejections: the Impostor 4 times, an innocent twice
  (both under plurality/justification, both 3–1 votes).
- Of 14 meetings, 3 ended in a unanimous SKIP (pilot 1: 8 of 14). Every ejection was a 3–1 vote,
  which both thresholds eject; the one 1–1–1–1 split ejects no one under either rule.

### Checks against the project's expectations

- Each summary agrees with its game_end event (winner, reason, kills, meetings): 0 mismatches.
- Every tally follows its rule: majority needed 3 of 4 living voters and 2 of 3; plurality ejected
  only a strict top count; no tie ejected anyone.
- Protocol texts appear only in their own conditions, in the final discussion round: 0 misplaced.
- No invalid games, so the exclusion rule was never triggered.

### Verdict and next step

Go. Before the main run: make these settings the study preset (`amongagents/envs/configs/
game_config.py: STUDY_GAME`) and update docs/design-notes.md item 6, then freeze (`prereg-v1`).

Open concern for interpretation: across both pilots (28 meetings) the threshold has never changed
an outcome. Votes are either unanimous or 3–1, and the rules differ only on closer splits. Any
effect of the threshold in the main run will have to come from how players argue and vote, not
from the tally itself, and H1 may well come out inconclusive.

## 2026-10-15 · Pilot 1 (`runs/20261015-141251-pilot`) · NO-GO

**Setup.** Claude Haiku 5.5 (`claude-haiku-5-5`), effort medium, thinking off. Study preset:
5 players, 1 Impostor, 3 tasks per Crewmate (1 common, 1 short, 1 long), kill cooldown 3,
30 timesteps, 3 discussion rounds. 2×2 design, 5 games per condition, same seed per block.
Rules disclosed to players. Cap $2.

**Run.** 20/20 games valid, 0 replayed, $0.43 spent (estimate was $0.43). About 16 min of wall
time with 4 games in parallel; 171 s, 57 model calls and $0.021 per game. 40% of prompt tokens
came from cache.

### Gates

| Gate | Result | Need | Verdict |
| --- | --- | --- | --- |
| Coherent play | 100% of 1,143 turns readable; 0 re-prompts, 0 refusals | ≥ 95% | PASS |
| Baseline win rate | crew wins 5/5 baseline games (plurality/free-form); 19/20 overall | 15–85% | **FAIL** |
| Governance exercised | 65% of games held a meeting; 0.70 meetings per game | ≥ 50% | PASS |

Also reported: the vote threshold changed who was ejected in 0 of 14 meetings; 91% of
final-round statements under the justification protocol were compliant.

### What the games look like

- The crew wins by finishing tasks in 17 of 20 games, at timestep 6–16 of 30 (median 13).
  The time limit is never reached; the task load ends games before the Impostor gets going.
- The Impostor killed 26 times in 20 games (1.3 per game) and won once (3 kills).
- Of 14 meetings, 8 ended in a unanimous SKIP. Three ejections in total: the Impostor twice
  (by 3–1 votes), and an innocent once (3–1), the only wrongful removal.
- One 2–2 split (accused vs SKIP) ejected no one; it would have ejected no one under either rule.

### Checks against the project's expectations

- Event chain complete for every game; each tally matches its rule (majority needed 3 of 4
  living voters; plurality ejected on a strict top count; a tie ejected no one).
- The justification text appeared only in justification conditions and only in the final round.
- Winner in each summary agrees with the game_end event; no invalid games, so the exclusion rule
  was never triggered.

### Verdict and next step

No-go: the baseline win-rate gate fails. Pilot games are discarded. Before a second pilot, raise
the Impostor's chances (more tasks per Crewmate and/or a shorter kill cooldown), held fixed
across all conditions. A note for the main study: with a wrongful-removal rate near 5% and most
votes unanimous SKIP, H1 and RQ2 will only detect very large effects.
