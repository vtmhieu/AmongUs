# Governance experiment in the Among Us sandbox

II2202 course project (Rong Jin, Hieu Vu): does the team's voting rule limit the damage
an undisclosed malicious agent does? See README.md for the study and
docs/design-notes.md for every decision that departs from the research plan.
**Where the study stands and what is still open: docs/status.md.** Read it first.

## Commands

```bash
uv pip install -e ".[dev]"                 # into .venv
.venv/bin/python -m pytest                 # all tests, ~20 s, no network, no API key
.venv/bin/python -m pytest tests/test_governance.py -k majority
.venv/bin/ruff check . && .venv/bin/ruff format .
.venv/bin/govlab serve                     # web UI on :8765
.venv/bin/govlab run --mock --games 5      # whole pipeline with scripted players, free
```

## Where things are

- `amongagents/` is the game, forked from upstream. `envs/governance.py` (rules, tally)
  and `agent/parsing.py` (reply → action) are pure and have no game state.
- `govlab/` is the study: `design` → `runner` → `store` → `metrics` → `stats` →
  `analyze`. `server.py` and `web/` are the UI (plain ES modules, no build step).
- A game talks to the outside through two callables, `emit(event)` and `llm_log(record)`.
  docs/log-schema.md is the contract.

## Rules of this codebase

- **Metrics are derived from `events.jsonl` only.** Never compute a dependent variable
  from engine state directly; add a field to an event, then read it in `metrics.py`.
  `tests/test_metrics.py` checks the two routes agree.
- **Conditions must differ only in the manipulated text.** The governance texts in
  `agent/prompts.py` are length-matched per group and `tests/test_prompts.py` enforces it.
  Changing one variant means changing its siblings.
- **The confirmatory family, exclusion rule and damage weights are constants**
  (`stats.CONFIRMATORY`, `design.MAX_FALLBACK_RATE`, `metrics.DAMAGE_WEIGHTS`). Once the
  repository is tagged `prereg-v1`, do not change them; anything new is exploratory.
- **A model reply never becomes a move by guessing.** `match_action` returns None when
  unsure; the caller re-prompts once, then takes a neutral turn. Keep it that way: a
  guessed vote biases the study's main outcome.
- **The human checks are the authors' own work.** Never fill in, suggest values for or
  pre-code the sheets in `docs/human-checks/`: G2 and Cohen's κ measure human judgement.
  Running `govlab validate` / `govlab kappa` on sheets the authors filled is fine.
- **Tests never call a model.** Use `LLMConfig(provider="mock")`, or point the SDK at an
  `httpx2.MockTransport` as `tests/test_llm.py` does. Do not use real credentials in
  tests even if they are present in the environment.
- **Setup randomness uses `game.rng`, play randomness `game.play_rng`.** Never the global
  `random` / `np.random`: games run concurrently in one process.
- Text from a model (speeches, thoughts, names) reaches the page as text nodes only. Use
  `h()` / `add()` / `fill()` from `web/dom.js`, never `innerHTML`.

## Claude API specifics

- Model `claude-haiku-5-5` via the `anthropic` SDK (`agent/llm.py`). It rejects
  `temperature`, `top_p`, `top_k` and assistant prefill, and has no server-side refusal
  fallback. Settings that can be pinned: `effort` and `thinking`.
- With no credentials the SDK fails only at request time, with a bare `TypeError`.
  `AnthropicLLM.__init__` checks up front and raises `FatalLLMError` instead.
- `FatalLLMError` (bad key, unknown model, bad request) ends a run; `LLMError`
  (rate limit, overload, network, after the SDK's own retries) only invalidates the game,
  which is then replayed.

## Gotchas

- Branch from `main`. Do not base work on, or merge from, the `II2202` branch.
- `runs/` is ignored, except the study's three runs, which are committed as the record.
  Do not edit them. Tests write to a temp directory via `GOVLAB_RUNS`.
- If the Claude desktop app's preview launcher hangs starting the server from
  `.claude/launch.json`, macOS is probably waiting on a folder-permission prompt for the
  project directory. Start `govlab serve` from a shell and open the URL instead.
- The server imports the statistics stack lazily (it takes seconds). Keep `govlab.analyze`
  and `govlab.stats` out of module-level imports in `server.py` and `cli.py`.
- The mock players are a test double. Their results must never be presented as findings.
