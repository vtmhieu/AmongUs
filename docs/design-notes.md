# Design notes

What the implementation does where the research plan left a choice open, where it
departs from the plan, and what it inherits from the upstream sandbox. Each departure
says how to undo it. Nothing here has been run against a real model yet: see the last
section.

## Departures from the research plan

**1. The model is Claude Haiku 5.5, through Anthropic's own API.**
The plan shortlisted GLM and DeepSeek. Haiku 5.5 does not accept `temperature`, `top_p`
or `top_k`, so "decoding parameters held fixed" means two settings: `effort` (default
`medium`) and `thinking` (default `disabled`). Thinking is off so that the agent's written
`[Thinking Process]` is its only reasoning channel and all of it is in the logs, as in the
upstream design. Both are recorded per game and can be changed in the UI or with
`--effort` / `--thinking`. The plan's model-selection paragraph and its cost risk (R2)
need rewriting: a game is estimated at about two cents.

**2. Players are told which voting rule is in force.**
The plan changed "only the tally function". But upstream's Impostor prompt states that
"the player with the most votes will be ejected", which is false under majority, and a
rule the voters do not know cannot affect how they argue or vote: it would only filter
outcomes mechanically. The meeting instruction now states the rule, with texts of equal
length for each rule (`amongagents/agent/prompts.py`, checked by `tests/test_prompts.py`),
and the sentence in the Impostor prompt is rule-neutral.
*To get the plan's version:* `--no-disclose`, or the switch in the UI.

**3. SKIP is an explicit ballot option.**
The plan's Table 1 and its argument for five players assume one; upstream had none.
A living player who casts no ballot is counted as SKIP, so the denominator is always the
living electorate.

**4. The result of a vote is announced to the living players.**
Upstream told players nothing after a vote; they could only notice an absence. Every
condition gets the same announcement. Under a secret ballot it gives totals only.

**5. An unreadable reply never becomes a move.**
Upstream fell through to the last action in the list: during a vote, a ballot for
whoever was listed last, which biases wrongful removal directly. Now a reply that names no
available action is re-prompted once; after that the turn becomes neutral (abstain, stay
silent, or stand still) and is flagged. A game is excluded and replayed if more than 5%
of its turns were neutralised this way, or if it aborted on an API error
(`govlab/design.py: MAX_FALLBACK_RATE`, `govlab/runner.py: judge`). The rule looks only
at whether the game ran properly, never at its outcome.

**6. The study game gives each Crewmate three tasks and 30 timesteps.**
The plan fixed five agents and one insider and left the rest open. Upstream's five-player
preset gives two one-step tasks and 20 timesteps, which a crew can finish before the
insider gets more than a kill or two, so few games would reach a meeting. The study preset
uses the per-player load of the published seven-player configuration (one common, one
short, one long task). **This is a guess until the pilot.** Tasks per player and the time
limit are the knobs if the baseline win rate falls outside 15–85% or too few games hold a
meeting. *To use upstream's:* `--preset five`.

**7. Every condition starts from the same positions.**
Replicate *k* uses the same seed in all conditions, so roles, colours and tasks are
identical and only the rules differ (a blocked design). The planned tests ignore the
blocking, which makes them conservative, not invalid. *To undo:* `--independent-seeds`.

**8. Damage is the number of kills.**
The plan anticipated a composite of destructive actions. Upstream's Sabotage is an empty
stub, so Kill is the only one, and damage per game ranges over 0–3. The composite is
still computed through `govlab/metrics.py: DAMAGE_WEIGHTS`, so a destructive action added
later only needs a weight.

**9. Figure F2 is an ordered stacked bar, not a violin or box plot.**
A violin fitted to a variable with four possible values draws a shape the data does not
have. The stacked bar shows the whole distribution.

**10. Main effects and the interaction come from different models.**
With treatment coding, the lower-order terms of `outcome ~ threshold * protocol` are
effects at the reference level of the other factor, not main effects. RQ1 and RQ2 are
therefore tested in the additive model, and H3 in the model with the product term.
Reference levels are plurality and free-form. With that coding, "the benefit of
justification is larger under plurality" is a *positive* product term, where the plan's
decision rule says negative; the rule is the same, the sign follows the coding.

**11. A verdict must survive the Holm correction.**
The plan's decision rules read off 95% intervals. Applied to four tests, that would call
something "supported" or "contradicted" far more often than 5% of the time under no
effect. A direction now counts only if the interval excludes no effect *and* the
Holm-adjusted p-value is below 0.05. H3 is exploratory and outside the family.

**12. The count model falls back from negative binomial to Poisson.**
Kill counts of 0–3 are usually not overdispersed, in which case the negative binomial
cannot be estimated. Poisson regression with robust standard errors is used then, and the
report says so. Likewise a logistic or Cox model that cannot be estimated (perfect
separation, no ejections) is reported as such, with the exact test standing in.

**13. Detection time counts meetings that reached a vote.**
A meeting called in the same timestep that ends the game is never held. Such meetings are
logged but do not count towards detection time or the number of meetings.

**14. A third pilot gate.**
Besides the plan's two (at least 95% of turns readable; baseline win rate within 15–85%),
the pilot report checks that at least half of the games held a meeting. A game without a
meeting contributes nothing to any governance comparison.

**15. Additions outside the planned design.**
A supermajority threshold and a secret ballot are implemented and tested. They are off by
default and are not in the confirmatory family.

## Fixed in the engine

- Ejected players were left as unreported bodies in the Cafeteria, where they could
  trigger further meetings. They now leave no body.
- Reporting a body used up the emergency-button allowance. Only the button does now.
- Tasks were drawn with replacement, so a player could be given the same task twice.
- The Impostor's "list of impostors" was built before the Impostor was added to it and
  was always empty with one insider.
- Setup randomness came from the global generators, so concurrent games interfered and
  nothing was reproducible. Each game now has its own seeded generator.
- The meeting instruction hard-coded "3 discussion rounds".
- Kills, votes, tallies, ejections, token usage and cost were not logged at all.

## Inherited from upstream, unchanged

These are the same in every condition, but worth knowing when reading results.

- **Ballots are public and sequential by default.** Later voters see earlier votes.
- **Agents see only their last four observations.** Anything older survives only if the
  agent wrote it into its own `[Condensed Memory]`. With five players this is exactly one
  round of other players' statements.
- **A dead Crewmate's tasks stop counting.** A kill can therefore *complete* the crew's
  task win, if the victim held the last unfinished tasks.
- **The insider can kill at timestep 0**, with everyone in the Cafeteria, and the kill
  cooldown keeps counting down during meetings.
- **Players act in a fixed order** (Player 1 first), and a meeting called mid-timestep
  costs the remaining players their turn.
- **The justification check applies to the final discussion round only**, as the plan
  specifies. A statement is re-prompted once; a second miss is kept and logged as
  non-compliant, so compliance is itself measured.

## Still to do, by a person

1. **Run the pilot** and read "Checks before interpreting". Tune tasks and time limit if a
   gate fails, then pilot again.
2. **Freeze before the main run.** The confirmatory family (`govlab/stats.py:
   CONFIRMATORY`), the exclusion rule and the damage weights are constants in code;
   commit and tag (`git tag prereg-v1`) before any main-experiment game is played.
3. **Hand-annotate ten transcripts** (gate G2): `govlab annotate`, fill in the sheet from
   the Watch view, then `govlab validate`. The tests already check the metrics against
   the engine's independent counters on several hundred mock games, but that is not a
   substitute for a person reading real transcripts.
4. **Write the codebook and code the sample** for the qualitative sub-study:
   `govlab sample`, then `govlab kappa` on the two authors' sheets.
5. **Review this code.** The plan commits to line-by-line review by the author who did
   not prompt for it. Nothing here has been merged to `main`.

## Not yet verified

No Claude API key was available when this was built, so **no real model call has been
made**. What that leaves unverified:

- That the API accepts the request as sent. The request body is checked in tests against
  the installed SDK and the documented constraints of Haiku 5.5 (no sampling parameters,
  no prefill, thinking `disabled` only at effort `high` or below), but not against the
  live service. `govlab check` is the first thing to run.
- How Haiku 5.5 actually plays: how often its replies parse, how long games last, whether
  the baseline win rate is usable, whether it ever declines to play the insider (a
  refusal is handled as an unreadable reply and counted). The pilot answers all of these.
- The cost and time estimates in the UI. They are derived from prompt lengths and guesses
  at call counts; the pilot report replaces them with measured values.
- Whether the default of four games in parallel fits the account's rate limits. Rate
  limits are retried by the SDK with backoff, so a run slows down rather than fails, but
  on a new account's limits it may slow down a lot, and a game whose call runs out of
  retries is excluded and replayed. If the pilot shows games excluded for rate limits,
  lower "Games in parallel" (`--concurrency`).
- Whether the system prompt is long enough to be cached (it is close to the 512-token
  minimum). If it is not, cost rises by a fraction of a cent per game and nothing else
  changes; the report shows the share of prompt tokens read from cache.
