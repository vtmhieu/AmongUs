"""Running an experiment: validity, regeneration, stopping, resuming, budget."""

import asyncio

import pytest

from amongagents.agent.llm import FatalLLMError, LLMConfig, LLMError
from amongagents.agent.mock import MockLLM
from govlab.design import ExperimentSpec
from govlab.runner import Runner, judge
from govlab.store import RunStore, list_runs


def spec(**changes) -> ExperimentSpec:
    defaults = dict(name="test", games_per_condition=2, concurrency=4, llm=LLMConfig(provider="mock"))
    return ExperimentSpec(**{**defaults, **changes})


def run(store: RunStore, llm=None, publish=None) -> dict:
    return asyncio.run(Runner(store, publish=publish or (lambda m: None), llm=llm).run())


class Flaky(MockLLM):
    """A mock that raises on its n-th call, once."""

    def __init__(self, fail_on_call: int, error: Exception):
        super().__init__(LLMConfig(provider="mock"))
        self.calls, self.fail_on_call, self.error = 0, fail_on_call, error

    async def complete(self, system, user, *, seed=None):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise self.error
        return await super().complete(system, user, seed=seed)


def test_a_run_plays_every_slot_and_records_it(tmp_path):
    store = RunStore.create(spec(), tmp_path)
    messages = []
    overview = run(store, publish=messages.append)

    assert overview["status"]["state"] == "completed"
    assert overview["valid"] == overview["total"] == 8
    assert {s["condition"] for s in store.valid_games()} == set(overview["conditions"])
    for summary in store.summaries():
        directory = store.game_dir(summary["game_id"])
        assert (directory / "events.jsonl").exists() and (directory / "llm.jsonl").exists()
        assert summary["valid"] and summary["attempt"] == 1 and summary["winner"]
        assert summary["seed"] == store.schedule[summary["slot"]]["seed"]
    assert not store.pending_slots()
    # what a live viewer is sent
    kinds = {m["kind"] for m in messages}
    assert kinds == {"run", "game", "event"}
    assert sum(m["kind"] == "game" and m["game"]["status"] == "valid" for m in messages) == 8


def test_the_manifest_records_what_produced_the_run(tmp_path):
    store = RunStore.create(spec(), tmp_path)
    manifest = RunStore(store.path).manifest
    assert ExperimentSpec.from_dict(manifest["spec"]) == store.spec
    assert len(manifest["schedule"]) == 8
    assert set(manifest["provenance"]) == {"commit", "dirty", "python", "anthropic_sdk"}
    assert [s.run_id for s in list_runs(tmp_path)] == [store.run_id]


def test_a_game_that_aborts_on_an_api_error_is_played_again(tmp_path):
    store = RunStore.create(spec(games_per_condition=1, concurrency=1), tmp_path)
    overview = run(store, llm=Flaky(fail_on_call=10, error=LLMError("rate limited after retries")))

    attempts = [s for s in store.summaries() if s["slot"] == 0]
    assert [(a["attempt"], a["valid"], a["invalid_reason"]) for a in attempts] == [(1, False, "error"), (2, True, None)]
    assert "rate limited" in attempts[0]["error"]
    assert overview["valid"] == 4 and overview["attempts"] == 5
    assert [s["game_id"] for s in store.valid_games() if s["slot"] == 0] == ["g0000-2"]


def test_games_with_too_many_unreadable_replies_are_excluded(tmp_path):
    unreadable = LLMConfig(provider="mock", mock_malformed_rate=0.6)
    store = RunStore.create(spec(games_per_condition=1, max_attempts=2, llm=unreadable), tmp_path)
    overview = run(store)

    assert overview["status"]["state"] == "completed"  # the run ends; the slots are simply lost
    assert overview["valid"] == 0 and overview["failed"] == 4 and overview["attempts"] == 8
    assert {s["invalid_reason"] for s in store.summaries()} == {"unreadable_replies"}
    assert store.valid_games() == []


def test_an_error_no_retry_can_fix_ends_the_run_at_once(tmp_path):
    store = RunStore.create(spec(concurrency=1), tmp_path)
    overview = run(store, llm=Flaky(fail_on_call=5, error=FatalLLMError("AuthenticationError: invalid x-api-key")))

    assert overview["status"]["state"] == "failed"
    assert "invalid x-api-key" in overview["status"]["error"]
    assert store.summaries() == []  # the attempt is not charged to the slot
    assert len(store.pending_slots()) == 8


def test_without_credentials_the_run_fails_before_any_game(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "no-profile"))
    store = RunStore.create(spec(llm=LLMConfig()), tmp_path)
    overview = run(store)
    assert overview["status"]["state"] == "failed"
    assert "ANTHROPIC_API_KEY" in overview["status"]["error"]
    assert not (store.path / "games").exists()


def test_a_stopped_run_can_be_resumed_without_replaying_finished_games(tmp_path):
    slow = LLMConfig(provider="mock", mock_latency=0.002)
    store = RunStore.create(spec(games_per_condition=3, concurrency=2, llm=slow), tmp_path)

    async def stop_after_two_games():
        runner = Runner(store)
        finished = []

        def publish(message):
            if message["kind"] == "game" and message["game"]["status"] == "valid":
                finished.append(message["game"]["game_id"])
                if len(finished) == 2:
                    runner.stop()

        runner.publish = publish
        return await runner.run()

    overview = asyncio.run(stop_after_two_games())
    assert overview["status"]["state"] == "stopped"
    done_before = {s["game_id"] for s in store.summaries()}
    assert 2 <= len(done_before) < 12

    overview = run(RunStore(store.path))
    assert overview["status"]["state"] == "completed" and overview["valid"] == 12
    assert done_before <= {s["game_id"] for s in store.summaries()}
    assert len(store.summaries()) == 12  # nothing was played twice


def test_the_budget_stops_new_games_from_starting(tmp_path):
    # priced as Haiku 5.5 but played by the mock, so the test spends nothing
    priced = spec(games_per_condition=5, concurrency=1, llm=LLMConfig(), budget_usd=0.002)
    store = RunStore.create(priced, tmp_path)
    overview = run(store, llm=MockLLM(LLMConfig(provider="mock")))

    assert overview["status"]["state"] == "budget"
    assert 0 < overview["valid"] < 20
    assert overview["cost_usd"] >= 0.002
    assert store.pending_slots()


@pytest.mark.parametrize(
    "summary, reason",
    [
        ({"winner": "crew", "decisions": 100, "fallbacks": 5}, None),  # exactly at the limit
        ({"winner": "crew", "decisions": 100, "fallbacks": 6}, "unreadable_replies"),
        ({"winner": "crew", "decisions": 100, "fallbacks": 0, "error": "API error 529"}, "error"),
        ({"decisions": 40, "fallbacks": 0}, "unfinished"),
        ({"winner": "impostor", "decisions": 0, "fallbacks": 0}, "no_decisions"),
    ],
)
def test_the_exclusion_rule(summary, reason):
    assert judge(summary, max_fallback_rate=0.05) == reason


def test_the_exclusion_rule_never_looks_at_the_outcome():
    for winner in ("crew", "impostor"):
        for kills in (0, 3):
            assert judge({"winner": winner, "kills": kills, "decisions": 50, "fallbacks": 0}, 0.05) is None
