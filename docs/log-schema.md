# Log schema

Everything a run writes, and what each field means. The analysis reads only
`events.jsonl`; `llm.jsonl` is the raw record behind it.

## `games/<game_id>/events.jsonl`

One JSON object per line, in order. Every event has:

| Field | Meaning |
|---|---|
| `game_id` | `g<slot>-<attempt>`, e.g. `g0007-2` |
| `seq` | 1, 2, 3 … within the game |
| `type` | one of the types below |
| `timestep` | game time when it happened |
| `phase` | `task` or `meeting` |
| `meeting` | meetings called so far (for a turn: the meeting it belongs to, else null) |

### `game_start`
`seed`, `condition`, `governance` (`threshold`, `protocol`, `ballot`, `disclose_rules`),
`game_config`, `model` (provider, model, effort, thinking, max_tokens),
`players` (name, color, identity, tasks), `state`.

### `step`
Emitted at the start of every timestep. `alive`: names of living players. Task-phase
steps with an insider alive add up to **exposure**.

### `turn`
One player's action.

| Field | Meaning |
|---|---|
| `player`, `identity` | who acted, and their role |
| `action` | `MOVE`, `VENT`, `COMPLETE TASK`, `COMPLETE FAKE TASK`, `KILL`, `CALL MEETING`, `VIEW MONITOR`, `SPEAK`, `VOTE`, or `WAIT` (a neutralised turn) |
| `text` | the action as offered to the player |
| `from`, `to` | for `MOVE` and `VENT` |
| `task` | for task actions |
| `target` | victim of a `KILL`; for a `VOTE`, a player's name or `SKIP` |
| `witnesses` | for `KILL`: other living players in the room |
| `kind` | for `CALL MEETING`: `report` or `button` |
| `message` | for `SPEAK`: the statement |
| `round` | meeting turns: discussion rounds completed before this one (0 in the first) |
| `final_round` | `SPEAK` only: whether this is the last discussion round |
| `justification` | final-round `SPEAK` only: `{accused, evidence}` if the statement satisfies the protocol, else null. Parsed under both protocols; required only under `justification` |
| `thought` | the reply's `[Thinking Process]` |
| `fallback` | true if no action could be read and the turn was neutralised |
| `reprompts` | extra model calls this turn needed |
| `refused` | the model declined to answer |
| `usage` | `calls`, `input_tokens` (uncached), `output_tokens`, `cache_read_tokens`, `cache_write_tokens` |
| `latency_s` | time spent in model calls |
| `state` | snapshot after the action (see below) |

A `CALL MEETING` turn is logged just after the `meeting_start` it causes.

### `meeting_start`
`caller`, `caller_identity`, `kind` (`report` / `button`), `location`,
`bodies` (dead players not yet reported), `living`.

### `tally`
The result of a vote.

| Field | Meaning |
|---|---|
| `rule` | the threshold in force |
| `ballots` | voter → target or `SKIP` |
| `counts` | option → votes |
| `n_voters` | living players |
| `required` | votes a player needed (null under plurality) |
| `ejected`, `ejected_identity` | who was removed, if anyone |
| `wrongful` | a Crewmate was removed |
| `skips` | SKIP votes |
| `counterfactual` | rule → who that rule would have ejected on the same ballots |
| `rule_changed_outcome` | the rules do not all agree: the manipulation check |

### `game_end`
`winner` (`crew` / `impostor`), `reason` (`ejected`, `tasks`, `outnumbered`, `timeout`),
`timesteps`, `meetings` (held), `kills`, `wrongful_ejections`, `decisions`, `fallbacks`,
`reprompts`, `refusals`, `usage`, `duration_s`, `state`.

### `state`
`players`: name → `{location, alive, tasks_done}`; `tasks`: `{done, total}` over the
tasks of living Crewmates.

## `games/<game_id>/llm.jsonl`

- `type: "agent"`, once per player: `player`, `identity`, `model`, `system_prompt`.
- `type: "llm_call"`, once per model call: `timestep`, `phase`, `player`, `identity`,
  `attempt` (0, or 1 for a re-prompt), `prompt` (the user message), `response` (raw
  text), `matched_action`, `stop_reason`, `model` (as returned by the API), `request_id`,
  `latency_s`, `usage`.

## `games/<game_id>/summary.json`

The `game_end` fields plus `slot`, `block`, `attempt`, `seed`, `condition`, `governance`,
`model`, `started`, `finished`, `error`, `valid`, `invalid_reason`
(`error`, `unfinished`, `no_decisions`, `unreadable_replies`), `cost_usd`.

## `tables/`

Built from the valid games: for each slot, its last attempt, if valid.

- **`games.csv`**, one row per game: the design factors; `crew_win`; `kills`, `damage`,
  `exposure`; `wrongful_any`, `wrongful_count`; `insider_ejected`, `detection_meeting`,
  and the survival pair `time`, `event` (meetings until the insider is first ejected,
  censored at the number of meetings held); `meetings`, `ejections`,
  `rule_changed_outcome`; protocol compliance; data quality; tokens, `cost_usd`,
  `duration_s`.
- **`meetings.csv`**, one row per meeting that reached a vote: who called it and why, the
  ballots and counts, the outcome (`correct`, `wrongful`, `none`), and `under_<rule>` for
  each threshold.
- **`actions.csv`**, one row per turn.
