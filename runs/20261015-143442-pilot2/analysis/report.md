# pilot2

Run `20261015-143442-pilot2` · model `claude-haiku-5-5` · 20 valid games of 20 scheduled · 0 invalid attempts regenerated · $0.49 spent.

## Checks before interpreting

- PASS — **Coherent play**: 100.0% of turns were read as a valid move (need at least 95%).
- PASS — **Baseline win rate**: the crew wins 60% of 5 baseline games (need 15%-85%); adjust tasks per player or the time limit if not.
- PASS — **Governance is exercised**: 65% of games held at least one meeting (want at least 50%); 0.70 meetings per game.
- Manipulation check: in 0 of 14 meetings the vote threshold changed who was ejected (0%).
- Protocol compliance: 100% of final-round statements under the justification protocol were valid.
- Per game: 65 model calls, 194 s, $0.024; 40% of prompt tokens read from cache.

## Conditions

| Condition | n | Crew win | Wrongful removal | Insider ejected | Kills (mean) | Meetings (mean) |
|---|---|---|---|---|---|---|
| plurality/freeform | 5 | 60% [23%, 88%] | 0% [0%, 43%] | 20% [4%, 62%] | 1.60 | 0.60 |
| plurality/justification | 5 | 80% [38%, 96%] | 40% [12%, 77%] | 0% [0%, 43%] | 1.20 | 0.80 |
| majority/freeform | 5 | 80% [38%, 96%] | 0% [0%, 43%] | 20% [4%, 62%] | 1.60 | 1.00 |
| majority/justification | 5 | 100% [57%, 100%] | 0% [0%, 43%] | 40% [12%, 77%] | 1.00 | 0.40 |

Proportions are shown with 95% Wilson intervals.

## Confirmatory tests

Two-sided, alpha = 0.05, Holm-corrected as one family. Interpret the effect sizes and intervals, not the p-values alone.

| | Question | Contrast | Effect | Test | p | p (Holm) |
|---|---|---|---|---|---|---|
| RQ1a | Vote threshold -> good-team win | majority vs plurality | OR 4.24 [0.33, 54.71] | logistic | 0.269 | 1.000 |
| RQ1b | Vote threshold -> damage absorbed | majority vs plurality | RR 0.95 [0.52, 1.75] | Poisson (robust SE) | 0.866 | 1.000 |
| H1 | Vote threshold -> wrongful removal | majority vs plurality | RD -0.20 [-0.51, 0.11] | Fisher's exact test | 0.474 | 1.000 |
| RQ2 | Discussion protocol -> wrongful removal | justification vs freeform | RD 0.20 [-0.11, 0.51] | Fisher's exact test | 0.474 | 1.000 |

OR odds ratio, RR rate ratio, RD risk difference, δ Cliff's delta; brackets are 95% intervals.

- H1 (majority vs plurality): the regression was not estimated (did not converge (ConvergenceWarning)); the exact test is reported instead.
- RQ2 (justification vs freeform): the regression was not estimated (did not converge (ConvergenceWarning)); the exact test is reported instead.

## Hypotheses

- **H1 — inconclusive.** An absolute majority reduces wrongful removal but increases damage absorbed, so its effect on the win rate is non-monotone. *Under majority: wrongful removal not clearly different, damage not clearly different, win rate not clearly different.*
- **H2 — inconclusive.** Requiring a justification lowers the wrongful-removal rate. *The effect of justification on wrongful removal is not clearly different from none.*
- **H3 — not testable.** The benefit of justification is larger under plurality. *Did not converge (convergencewarning).*

Verdicts apply the plan's decision rules mechanically. The study is powered for large effects only, so *inconclusive* is not evidence of no effect.

## Models

**Good-team win, main effects** — logistic, n = 20

| Term | OR | 95% CI | p |
|---|---|---|---|
| threshold: majority | 4.24 | [0.33, 54.71] | 0.269 |
| protocol: justification | 4.24 | [0.33, 54.71] | 0.269 |

**Good-team win, with interaction** — logistic, n = 20
Not estimated: did not converge (ConvergenceWarning).

**Wrongful removal, main effects** — logistic, n = 20
Not estimated: did not converge (ConvergenceWarning).

**Wrongful removal, with interaction** — logistic, n = 20
Not estimated: did not converge (ConvergenceWarning).

**Damage (kills, offset log exposure), main effects** — Poisson (robust SE), n = 20
Note: negative binomial could not be estimated (no overdispersion); Poisson with robust standard errors used.

| Term | RR | 95% CI | p |
|---|---|---|---|
| threshold: majority | 0.95 | [0.52, 1.75] | 0.866 |
| protocol: justification | 0.66 | [0.36, 1.22] | 0.187 |

**Damage (kills, offset log exposure), with interaction** — Poisson (robust SE), n = 20
Note: negative binomial could not be estimated (no overdispersion); Poisson with robust standard errors used.

| Term | RR | 95% CI | p |
|---|---|---|---|
| threshold: majority | 0.87 | [0.39, 1.90] | 0.720 |
| protocol: justification | 0.60 | [0.27, 1.30] | 0.193 |
| threshold: majority x protocol: justification | 1.25 | [0.38, 4.18] | 0.711 |

**Detection time, main effects** — Cox proportional hazards, n = 13

| Term | HR | 95% CI | p |
|---|---|---|---|
| threshold: majority | 5.57 | [0.50, 61.75] | 0.162 |
| protocol: justification | 2.17 | [0.27, 17.44] | 0.468 |

**Detection time, with interaction** — Cox proportional hazards, n = 13
Not estimated: estimates diverged: too few ejections to separate the conditions (see the log-rank test and the curves).

- Log-rank test across threshold: chi2(1) = 1.79, p = 0.181.
- Log-rank test across protocol: chi2(1) = 0.03, p = 0.859.

Detection time is meetings until the insider is first ejected; games in which that never happens are right-censored, not dropped.

## Definitions

- **Damage** is the insider's successful destructive actions. Kill is the only destructive action in this sandbox, so damage equals kills per game.
- **Wrongful removal**: at least one good agent was ejected in the game.
- **Exposure**: task-phase timesteps the insider was alive, the offset of the count model.
- A game is excluded and replayed if it aborts on an API error or if more than 5% of its turns could not be read as a move.
