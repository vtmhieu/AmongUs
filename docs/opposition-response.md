# Response to the opposition report

**Draft by Claude for the authors to edit and sign.** Opponent: Vivienne Curewitz, report
dated 2026-10-19, on the second draft. Section numbers below refer to the revised report
(`Final Report Third Draft.docx`).

We thank the opponent for a careful review. Most of the points were correct and led to
changes; where we disagree we say why.

## Summary and §3.2: alignment from question to conclusion

**Only a 2–1–1 vote separates the thresholds.** Correct, and the point goes further than
the review states. No vote in the main run had five voters: 59 had four and 17 had three.
With three voters the two rules always agree; with four they differ only on a 2–1–1 vote
with a player on top. That pattern occurred five times, and the rule changed the outcome
each time. §3.2 now explains the 5-of-76 manipulation check this way, and §4.1 and §4.4
draw the consequence: larger teams are needed for the threshold to bind.

**H1's "non-monotone" effect cannot be observed with two levels.** Agreed. H1 is
pre-registered, so we did not change it, but §1.3 now says that with two levels it reduces
to a trade-off: fewer wrongful removals and more damage, with no net gain in win rate.

**"Win rate is reported as a percentage, not a difference."** Table 4 did report the
between-group effect as an odds ratio, but the decision rule spoke of an interval that
"includes zero", which fits a risk difference rather than an odds ratio. Table 4 now also
reports the risk difference with its interval, for example −12.5 percentage points
[−28.7, 4.1] for the win rate. The underlying concern is fair: H1's win-rate condition is
met by a non-significant difference, which a small study meets easily. §4.2 now says so,
and that only an equivalence test could show a difference is absent. H1 was not supported
in any case, because wrongful removal was not lower under majority.

**The damage model divides out H1's mechanism.** Correct in principle: the exposure
offset turns the test into a comparison of kill rates per timestep of the insider's life.
§2.5 now explains this, and Table 4 adds the pre-specified unadjusted comparison
(1.53 vs 1.33 kills, Cliff's δ = 0.16, p = 0.17). In this run the mechanism did not
operate: the insider was alive about as long under both rules (13.9 vs 13.8 task
timesteps), so the two comparisons agree.

**Table 4's row labels.** The caption now says which row tests which part of RQ1, H1
and H2.

**§4.4 draws a conclusion from an inconclusive result.** Agreed. §4.4 now says the study
cannot tell whether governance is a weak lever or the study was too small, and names
what would distinguish the two.

## Issue 4.1: most games were won on tasks

Partly agreed. Of the 44 task wins, 18 never reached a vote, so governance could not affect
them; the other 26 did hold votes. Voting also shaped outcomes: 7 of the insider's 13 wins
came in games with a wrongful ejection, six of them within one timestep of the vote. But the
core point stands: the task race dilutes any effect of the rules on the win rate. §4.1 and
§4.2 now say this. Changing the game was not possible after the pre-registered run, but §4.4
proposes a game the good team can win only by voting, as in Werewolf, for future work.

## Issue 4.2: the method reads like a plan

Agreed. A new §2.3 describes how a game runs: timesteps, the actions available, meetings
of three rounds with one statement per agent per round, and the vote. It also says what
each agent receives every turn: the system prompt with role, rules, map and voting rule;
its location, its last four observations and actions, its tasks, the available actions,
and its own notes. §2.4 now describes the procedure as carried out, and the weekly
objectives, budget and gate terminology of the plan have been removed.

## Issue 4.3: numerical methods

- **Cliff's δ and Mann–Whitney promised but not reported.** Correct. They had been
  computed but were left out; Table 4 now reports them, together with the risk differences.
- **The damage figure shows four conditions rather than majority vs plurality.** The figure (now Figure 3) shows
  the four cells as planned in Table 2. The pooled majority-versus-plurality comparison
  is in Table 4 and the text.
- **"Timestep" is undefined.** Correct. It is now defined in §2.5: one round in which every
  living player acts once.
- **Meetings as the time axis for cumulative damage.** We kept timesteps. Games held 0.95
  meetings on average and at most three, so a meeting axis would have two or three points.
  The caption now says that a finished game keeps its final total, which is why the curves
  flatten as games end.

## §5: communication

Agreed. The report has been rewritten in shorter sentences, terms are defined where they
are first used, leftovers from the research plan have been removed, and the main text now
fits in nine pages.
