"""The web UI's server.

Runs execute inside this process, on the same event loop that serves the page, so
what a game emits reaches a watching browser directly. Everything is also written to
disk as it happens; the server holds no state that a restart would lose except which
runs are currently in flight (a run interrupted by a restart can be resumed).

    govlab serve          http://127.0.0.1:8765
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from amongagents.agent import prompts
from amongagents.agent.llm import (
    DEFAULT_MODEL,
    EFFORTS,
    PRICING,
    THINKING_MODES,
    LLMConfig,
    check_connection,
    has_api_credentials,
)
from amongagents.envs.configs.game_config import GAME_PRESETS
from amongagents.envs.configs.map_config import connections, map_coords, vent_connections
from amongagents.envs.governance import BALLOTS, PROTOCOLS, THRESHOLDS
from amongagents.envs.player import PLAYER_COLORS
from govlab.design import LABELS, ExperimentSpec, estimate, minimum_detectable_difference
from govlab.runner import Runner
from govlab.store import REPO_ROOT, RunStore, list_runs, runs_dir

WEB = Path(__file__).parent / "web"


class Hub:
    """The runs in flight and the browsers watching them."""

    def __init__(self):
        self.runners: dict[str, Runner] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.watchers: dict[str, set[asyncio.Queue]] = {}

    def active(self, run_id: str) -> bool:
        task = self.tasks.get(run_id)
        return task is not None and not task.done()

    def start(self, store: RunStore) -> None:
        if self.active(store.run_id):
            raise HTTPException(409, "this run is already in progress")
        runner = Runner(store, publish=lambda message: self.publish(store.run_id, message))
        self.runners[store.run_id] = runner
        self.tasks[store.run_id] = asyncio.create_task(runner.run())

    def stop(self, run_id: str) -> None:
        if self.active(run_id):
            self.runners[run_id].stop()

    def publish(self, run_id: str, message: dict) -> None:
        for queue in list(self.watchers.get(run_id, ())):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:  # a browser that stopped reading: let it reconnect
                self.watchers[run_id].discard(queue)

    def watch(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=20000)
        self.watchers.setdefault(run_id, set()).add(queue)
        return queue

    def unwatch(self, run_id: str, queue: asyncio.Queue) -> None:
        self.watchers.get(run_id, set()).discard(queue)

    async def shutdown(self) -> None:
        for run_id in list(self.tasks):
            self.stop(run_id)
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


hub = Hub()


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv(REPO_ROOT / ".env")
    yield
    await hub.shutdown()


app = FastAPI(title="Governance Lab", lifespan=lifespan)


def open_run(run_id: str) -> RunStore:
    path = runs_dir() / run_id
    if "/" in run_id or ".." in run_id or not (path / "manifest.json").exists():
        raise HTTPException(404, f"no run named {run_id}")
    return RunStore(path)


def overview(store: RunStore) -> dict:
    data = store.overview()
    data["active"] = hub.active(store.run_id)
    if data["status"]["state"] == "running" and not data["active"]:
        # the process that was playing it is gone
        data["status"] = {**data["status"], "state": "interrupted"}
    return data


def parse_spec(body: dict) -> ExperimentSpec:
    try:
        return ExperimentSpec.from_dict(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e)) from e


def game_cards(store: RunStore) -> list[dict]:
    """Every finished attempt, plus the games in flight, for the Watch view."""
    keep = (
        "game_id", "slot", "block", "attempt", "seed", "condition", "winner", "reason", "kills",
        "meetings", "wrongful_ejections", "timesteps", "cost_usd", "duration_s", "invalid_reason", "error",
    )
    cards = [
        {**{k: s.get(k) for k in keep}, "status": "valid" if s.get("valid") else "invalid"}
        for s in store.summaries()
    ]
    runner = hub.runners.get(store.run_id)
    if runner and hub.active(store.run_id):
        cards += [{**{k: g.get(k) for k in keep}, "status": "running"} for g in list(runner.running.values())]
    return sorted(cards, key=lambda c: (c["slot"], c["attempt"]))


# --- API ------------------------------------------------------------------------------


@app.get("/api/meta")
def meta() -> dict:
    """Everything the page needs to draw its forms and the map."""
    return {
        "credentials": has_api_credentials(),
        "default_spec": ExperimentSpec().to_dict(),
        "presets": GAME_PRESETS,
        "options": {
            "thresholds": list(THRESHOLDS),
            "protocols": list(PROTOCOLS),
            "ballots": list(BALLOTS),
            "efforts": list(EFFORTS),
            "thinking": list(THINKING_MODES),
        },
        "labels": LABELS,
        "default_model": DEFAULT_MODEL,
        "pricing": PRICING,
        "player_colors": PLAYER_COLORS,
        "map": {
            "rooms": {name: room["coords"] for name, room in map_coords.items()},
            "corridors": connections,
            "vents": vent_connections,
        },
        # the exact words each level adds to what the players read (report appendix A)
        "texts": {
            "threshold": prompts.VOTING_RULE_TEXT,
            "ballot": prompts.BALLOT_TEXT,
            "protocol": prompts.PROTOCOL_TEXT,
            "undisclosed": prompts.VOTING_RULE_UNDISCLOSED,
        },
    }


@app.post("/api/estimate")
async def post_estimate(request: Request) -> dict:
    spec = parse_spec(await request.json())
    guess = estimate(spec)
    # games per level of the factor with the most levels: the weakest main-effect comparison
    most_levels = max(len(spec.thresholds), len(spec.protocols), len(spec.ballots))
    guess["detectable_difference"] = minimum_detectable_difference(spec.n_games // most_levels)
    guess["conditions_list"] = [g.condition for g in spec.conditions()]
    return guess


@app.post("/api/check")
async def post_check(request: Request) -> dict:
    body = await request.json()
    try:
        config = LLMConfig.from_dict({**body, "provider": "anthropic"})
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return await check_connection(config)


@app.get("/api/runs")
def get_runs() -> list[dict]:
    return [overview(store) for store in list_runs()]


@app.post("/api/runs")
async def post_run(request: Request) -> dict:
    spec = parse_spec(await request.json())
    if spec.llm.provider == "anthropic" and not has_api_credentials():
        raise HTTPException(
            409,
            "No Claude API key found. Add ANTHROPIC_API_KEY to the .env file at the repository "
            "root and restart the server, or run with the offline mock players.",
        )
    store = RunStore.create(spec)
    hub.start(store)
    return overview(store)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    store = open_run(run_id)
    return {
        "run": overview(store),
        "spec": store.spec.to_dict(),
        "provenance": store.manifest.get("provenance"),
        "games": game_cards(store),
    }


# stop and resume touch asyncio tasks, so they must run on the event loop (async def),
# not on the worker thread FastAPI gives a plain function
@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict:
    store = open_run(run_id)
    hub.stop(run_id)
    return overview(store)


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str) -> dict:
    store = open_run(run_id)
    if not store.pending_slots():
        raise HTTPException(409, "nothing left to play in this run")
    if store.spec.llm.provider == "anthropic" and not has_api_credentials():
        raise HTTPException(409, "No Claude API key found. Add ANTHROPIC_API_KEY to .env and restart.")
    hub.start(store)
    return overview(store)


@app.get("/api/runs/{run_id}/games/{game}/events")
def get_events(run_id: str, game: str) -> list[dict]:
    store = open_run(run_id)
    if "/" in game or ".." in game:
        raise HTTPException(404, "no such game")
    return store.events(game)


@app.get("/api/runs/{run_id}/results")
def get_results(run_id: str, figures: bool = False) -> dict:
    from govlab.analyze import analyse_run  # the statistics stack takes seconds to import

    store = open_run(run_id)
    return analyse_run(store, write=True, draw=figures)


@app.get("/api/runs/{run_id}/files/{path:path}")
def get_file(run_id: str, path: str) -> FileResponse:
    store = open_run(run_id)
    target = (store.path / path).resolve()
    if store.path.resolve() not in target.parents or not target.is_file():
        raise HTTPException(404, "no such file")
    if not (target.parent.name in ("tables", "analysis", "figures") or target.name == "manifest.json"):
        raise HTTPException(404, "no such file")
    return FileResponse(target, filename=target.name)


@app.get("/api/runs/{run_id}/stream")
async def stream(run_id: str, request: Request, game: str | None = None) -> StreamingResponse:
    """Server-sent events for one run.

    Always carries run and game status. Per-turn events are sent only for the one game
    named in ``game``, so a browser watching one game of eight is not sent the other seven.
    """
    open_run(run_id)
    queue = hub.watch(run_id)

    async def messages():
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if message["kind"] == "event" and message["game_id"] != game:
                    continue
                yield f"data: {json.dumps(message)}\n\n"
        finally:
            hub.unwatch(run_id, queue)

    return StreamingResponse(messages(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- the page -------------------------------------------------------------------------


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


class FreshStatic(StaticFiles):
    """Static files that the browser must revalidate, so an updated UI is never served stale."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", FreshStatic(directory=WEB), name="static")
