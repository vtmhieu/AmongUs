"""The web UI's API, driven in-process."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from govlab import server


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(server, "has_api_credentials", lambda: False)
    monkeypatch.setattr(server, "hub", server.Hub())
    with TestClient(server.app) as test_client:
        yield test_client


def mock_spec(client, **changes):
    spec = client.get("/api/meta").json()["default_spec"]
    spec.update(name="ui test", games_per_condition=1, concurrency=4)
    spec["llm"] = {**spec["llm"], "provider": "mock"}
    spec.update(changes)
    return spec


def wait_until_done(client, run_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()["run"]
        if not run["active"]:
            return run
        time.sleep(0.05)
    raise AssertionError("the run did not finish")


def test_meta_describes_everything_the_page_draws(client):
    meta = client.get("/api/meta").json()
    assert meta["credentials"] is False
    assert meta["default_model"] == "claude-haiku-5-5"
    assert len(meta["map"]["rooms"]) == 14 and "Cafeteria" in meta["map"]["rooms"]
    assert set(meta["options"]["thresholds"]) == {"plurality", "majority", "supermajority"}
    # the exact condition texts are shown in the UI (and quoted in the report's appendix)
    assert "more than half" in meta["texts"]["threshold"]["majority"]
    assert "ACCUSE:" in meta["texts"]["protocol"]["justification"]
    assert meta["presets"]["study"]["num_players"] == 5


def test_the_page_and_its_assets_are_served_fresh(client):
    assert "Governance Lab" in client.get("/").text
    for asset in ("app.js", "styles.css", "watch.js", "charts.js"):
        response = client.get(f"/static/{asset}")
        assert response.status_code == 200
        assert (
            response.headers["cache-control"] == "no-cache"
        )  # an updated UI is never served stale


def test_estimate_validates_the_design(client):
    spec = mock_spec(client)
    guess = client.post(
        "/api/estimate", json={**spec, "games_per_condition": 20, "llm": {"provider": "anthropic"}}
    ).json()
    assert guess["games"] == 80 and guess["conditions"] == 4
    assert 0 < guess["cost_usd"] < 10
    assert guess["detectable_difference"] == pytest.approx(0.29, abs=0.02)

    bad = client.post("/api/estimate", json={**spec, "thresholds": []})
    assert bad.status_code == 422 and "at least one level" in bad.json()["detail"]
    assert client.post("/api/estimate", json={**spec, "typo": 1}).status_code == 422


def test_a_claude_run_is_refused_clearly_without_a_key(client):
    spec = mock_spec(client)
    spec["llm"]["provider"] = "anthropic"
    response = client.post("/api/runs", json=spec)
    assert response.status_code == 409
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]
    assert client.get("/api/runs").json() == []  # nothing was created


def test_a_mock_run_from_start_to_results(client):
    run = client.post("/api/runs", json=mock_spec(client)).json()
    run_id = run["run_id"]
    assert run["active"] and run["total"] == 4

    done = wait_until_done(client, run_id)
    assert done["status"]["state"] == "completed" and done["valid"] == 4

    detail = client.get(f"/api/runs/{run_id}").json()
    assert [g["status"] for g in detail["games"]] == ["valid"] * 4
    assert {g["condition"] for g in detail["games"]} == set(done["conditions"])
    assert detail["spec"]["llm"]["provider"] == "mock"

    game = detail["games"][0]["game_id"]
    events = client.get(f"/api/runs/{run_id}/games/{game}/events").json()
    assert events[0]["type"] == "game_start" and events[-1]["type"] == "game_end"
    assert all("state" in e for e in events if e["type"] == "turn")  # enough to replay the map

    results = client.get(f"/api/runs/{run_id}/results").json()
    assert results["ok"] and results["is_mock"] and results["n_games"] == 4
    assert len(results["charts"]["cells"]) == 4 and len(results["quality"]["gates"]) == 3
    json.dumps(results)

    assert [r["run_id"] for r in client.get("/api/runs").json()] == [run_id]
    assert client.post(f"/api/runs/{run_id}/resume").status_code == 409  # nothing left to play


def test_files_can_be_downloaded_but_not_escaped(client):
    run_id = client.post("/api/runs", json=mock_spec(client)).json()["run_id"]
    wait_until_done(client, run_id)
    client.get(f"/api/runs/{run_id}/results")

    games = client.get(f"/api/runs/{run_id}/files/tables/games.csv")
    assert games.status_code == 200 and games.text.startswith("game_id,")
    assert client.get(f"/api/runs/{run_id}/files/analysis/report.md").status_code == 200
    assert client.get(f"/api/runs/{run_id}/files/manifest.json").status_code == 200
    # raw model logs and anything outside the run stay out of reach of the download route
    for path in ("games/g0000-1/llm.jsonl", "../../pyproject.toml", "%2e%2e/%2e%2e/.env"):
        assert client.get(f"/api/runs/{run_id}/files/{path}").status_code == 404


def test_unknown_runs_and_games_are_404(client):
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/..%2f..").status_code == 404
    assert client.post("/api/runs/nope/stop").status_code == 404


def test_a_run_can_be_stopped_and_resumed_from_the_ui(client):
    slow = mock_spec(client, games_per_condition=3, concurrency=1)
    slow["llm"]["mock_latency"] = 0.01
    run_id = client.post("/api/runs", json=slow).json()["run_id"]
    time.sleep(0.3)
    client.post(f"/api/runs/{run_id}/stop")
    stopped = wait_until_done(client, run_id)
    assert stopped["status"]["state"] == "stopped" and stopped["valid"] < 12

    fast = client.get(f"/api/runs/{run_id}").json()["spec"]
    assert fast["llm"]["mock_latency"] == 0.01  # resume replays the same design
    assert client.post(f"/api/runs/{run_id}/resume").json()["active"]
    client.post(f"/api/runs/{run_id}/stop")
    wait_until_done(client, run_id)


def test_a_run_left_running_by_a_dead_server_reads_as_interrupted(client):
    from govlab.design import ExperimentSpec
    from govlab.store import RunStore

    store = RunStore.create(ExperimentSpec.from_dict(mock_spec(client)))
    store.set_status("running")  # as if the process had been killed mid-run
    run = client.get(f"/api/runs/{store.run_id}").json()["run"]
    assert run["status"]["state"] == "interrupted" and run["active"] is False


def test_the_stream_sends_run_and_game_status_and_only_the_watched_games_turns(client, monkeypatch):
    """The publish/subscribe path the browser's live view depends on."""
    hub = server.hub
    queue = hub.watch("r")
    hub.publish("r", {"kind": "run", "run": {}})
    hub.publish("r", {"kind": "event", "game_id": "g1", "event": {"seq": 1}})
    assert queue.qsize() == 2
    hub.unwatch("r", queue)
    hub.publish("r", {"kind": "run", "run": {}})
    assert queue.qsize() == 2  # no longer delivered
