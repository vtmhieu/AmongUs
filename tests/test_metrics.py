"""The dependent variables, checked on hand-built event logs and against the engine."""

import asyncio

import pytest

from amongagents.agent.llm import LLMConfig, make_llm
from amongagents.envs.game import AmongUs
from amongagents.envs.governance import Governance, counterfactuals
from govlab.design import ExperimentSpec
from govlab.metrics import action_rows, build_tables, game_row, meeting_rows
from govlab.runner import Runner
from govlab.store import RunStore

CREW = ["Player 1: red", "Player 2: blue", "Player 3: green", "Player 4: pink"]
INSIDER = "Player 5: cyan"
EVERYONE = CREW + [INSIDER]


def log(steps, turns=(), tallies=(), winner="impostor", reason="timeout"):
    """A minimal event log. steps: [(phase, alive)], tallies: [(ballots, ejected)]."""
    events = [
        {
            "game_id": "g", "seq": 1, "type": "game_start", "timestep": 0, "phase": "task", "meeting": 0,
            "seed": 1, "condition": "plurality/freeform",
            "governance": {"threshold": "plurality", "protocol": "freeform", "ballot": "public", "disclose_rules": True},
            "model": {"provider": "mock", "model": "claude-haiku-5-5", "effort": "medium", "thinking": "disabled"},
            "players": [{"name": n, "identity": "Crewmate"} for n in CREW] + [{"name": INSIDER, "identity": "Impostor"}],
        }
    ]
    for t, (phase, alive) in enumerate(steps):
        events.append({"game_id": "g", "type": "step", "timestep": t, "phase": phase, "meeting": 0, "alive": alive})
    for timestep, player, action, extra in turns:
        events.append({
            "game_id": "g", "seq": 0, "type": "turn", "timestep": timestep, "phase": "task", "meeting": None,
            "player": player, "identity": "Impostor" if player == INSIDER else "Crewmate",
            "action": action, "fallback": False, "reprompts": 0, **extra,
        })
    for index, (ballots, ejected) in enumerate(tallies, start=1):
        n = len(ballots)
        counts = {}
        for target in ballots.values():
            counts[target] = counts.get(target, 0) + 1
        cf = counterfactuals(ballots, n)
        events.append({
            "game_id": "g", "type": "meeting_start", "timestep": index, "phase": "meeting", "meeting": index,
            "caller": CREW[0], "caller_identity": "Crewmate", "kind": "report", "bodies": [CREW[3]],
        })
        events.append({
            "game_id": "g", "type": "tally", "timestep": index, "phase": "meeting", "meeting": index,
            "rule": "plurality", "ballots": ballots, "counts": counts, "n_voters": n, "required": None,
            "ejected": ejected, "ejected_identity": None if ejected is None else "Impostor" if ejected == INSIDER else "Crewmate",
            "wrongful": ejected is not None and ejected != INSIDER, "skips": counts.get("SKIP", 0),
            "counterfactual": cf, "rule_changed_outcome": len(set(cf.values())) > 1,
        })
    events.append({
        "game_id": "g", "type": "game_end", "timestep": len(steps), "phase": "task", "meeting": len(tallies),
        "winner": winner, "reason": reason, "timesteps": len(steps), "decisions": 40, "fallbacks": 2,
        "reprompts": 3, "refusals": 0, "duration_s": 12.5,
        "usage": {"calls": 43, "input_tokens": 4000, "output_tokens": 900, "cache_read_tokens": 30000, "cache_write_tokens": 3500},
        "state": {"tasks": {"done": 3, "total": 9}, "players": {n: {"alive": True} for n in EVERYONE}},
    })
    return events


def test_damage_is_the_number_of_kills():
    kill = lambda t, target: (t, INSIDER, "KILL", {"target": target})  # noqa: E731
    row = game_row(log([("task", EVERYONE)] * 6, turns=[kill(1, CREW[0]), kill(4, CREW[1]), (2, CREW[2], "MOVE", {})]))
    assert row["kills"] == 2 and row["damage"] == 2.0


def test_wrongful_removal_counts_ejected_crewmates_only():
    two_for = lambda target: {CREW[0]: target, CREW[1]: target, CREW[2]: "SKIP", INSIDER: CREW[0]}  # noqa: E731
    row = game_row(log([("task", EVERYONE)] * 4, tallies=[(two_for(CREW[2]), CREW[2]), (two_for(INSIDER), INSIDER)], winner="crew", reason="ejected"))
    assert (row["wrongful_any"], row["wrongful_count"]) == (1, 1)
    assert row["ejections"] == 2

    none = game_row(log([("task", EVERYONE)] * 4, tallies=[(two_for("SKIP"), None)]))
    assert (none["wrongful_any"], none["wrongful_count"], none["ejections"]) == (0, 0, 0)


def test_detection_time_is_the_meeting_that_first_ejects_the_insider():
    ballots = {CREW[0]: INSIDER, CREW[1]: INSIDER, CREW[2]: INSIDER, INSIDER: CREW[0]}
    split = {CREW[0]: CREW[1], CREW[1]: CREW[0], CREW[2]: "SKIP", INSIDER: "SKIP"}
    row = game_row(log([("task", EVERYONE)] * 5, tallies=[(split, None), (split, None), (ballots, INSIDER)], winner="crew", reason="ejected"))
    assert (row["insider_ejected"], row["detection_meeting"], row["time"], row["event"]) == (1, 3, 3, 1)
    assert row["detection_timestep"] == 3


def test_a_game_that_never_ejects_the_insider_is_censored_not_dropped():
    split = {CREW[0]: CREW[1], CREW[1]: CREW[0], CREW[2]: "SKIP", INSIDER: "SKIP"}
    row = game_row(log([("task", EVERYONE)] * 5, tallies=[(split, None), (split, None)]))
    assert (row["insider_ejected"], row["detection_meeting"]) == (0, None)
    assert (row["time"], row["event"]) == (2, 0)  # censored at the number of meetings held

    no_meeting = game_row(log([("task", EVERYONE)] * 5))
    assert (no_meeting["time"], no_meeting["event"], no_meeting["meetings"]) == (0, 0, 0)


def test_exposure_counts_task_steps_with_the_insider_alive():
    steps = [("task", EVERYONE), ("task", EVERYONE), ("meeting", EVERYONE), ("task", CREW), ("task", CREW)]
    assert game_row(log(steps))["exposure"] == 2  # meetings and steps after the ejection do not count


def test_cost_and_quality_fields_are_carried_through():
    row = game_row(log([("task", EVERYONE)]))
    assert row["fallback_rate"] == pytest.approx(0.05)
    assert (row["calls"], row["cache_read_tokens"], row["duration_s"]) == (43, 30000, 12.5)
    assert row["model"] == "mock-scripted"
    assert (row["tasks_done"], row["tasks_total"], row["crew_alive"]) == (3, 9, 4)


def test_a_meeting_row_records_the_vote_and_what_other_rules_would_do():
    # 2-1-1 among four voters: plurality ejects, majority does not
    ballots = {CREW[0]: INSIDER, CREW[1]: INSIDER, CREW[2]: CREW[0], INSIDER: CREW[1]}
    (row,) = meeting_rows(log([("task", EVERYONE)] * 3, tallies=[(ballots, INSIDER)], winner="crew", reason="ejected"))
    assert row["outcome"] == "correct" and row["votes_for_insider"] == 2 and row["top_votes"] == 2
    assert row["rule_changed_outcome"] == 1
    assert (row["under_plurality"], row["under_majority"], row["under_supermajority"]) == (INSIDER, None, None)
    assert (row["kind"], row["bodies"], row["n_voters"]) == ("report", 1, 4)


def play(seed, **governance):
    events = []
    game = AmongUs(make_llm(LLMConfig(provider="mock")), governance=Governance(**governance), seed=seed, emit=events.append)
    return asyncio.run(game.run_game()), events


def test_metrics_from_the_log_agree_with_the_engines_own_counters():
    """Two independent routes to the same numbers (the plan's parser-validation gate)."""
    fields = 0
    for seed in range(25):
        for governance in ({}, {"threshold": "majority", "protocol": "justification"}):
            summary, events = play(seed, **governance)
            row = game_row(events)
            pairs = [
                (row["kills"], summary["kills"]),
                (row["wrongful_count"], summary["wrongful_ejections"]),
                (row["meetings"], summary["meetings"]),
                (row["crew_win"], int(summary["winner"] == "crew")),
                (row["timesteps"], summary["timesteps"]),
                (row["decisions"], summary["decisions"]),
                (row["condition"], summary["condition"]),
            ]
            assert all(a == b for a, b in pairs), (seed, governance, pairs)
            fields += len(pairs)
            # internal consistency of the derived variables
            assert row["event"] == row["insider_ejected"] == int(summary["reason"] == "ejected")
            assert row["time"] == (row["detection_meeting"] if row["event"] else row["meetings"])
            assert row["wrongful_any"] == int(row["wrongful_count"] > 0)
            assert 1 <= row["exposure"] <= row["timesteps"]
            assert len(meeting_rows(events)) == row["meetings"]
            assert len(action_rows(events)) == row["decisions"]
    assert fields == 350


def test_tables_hold_one_game_per_slot_the_last_valid_attempt(tmp_path):
    from amongagents.agent.llm import LLMError
    from tests.test_runner import Flaky

    spec = ExperimentSpec(name="t", games_per_condition=2, concurrency=1, llm=LLMConfig(provider="mock"))
    store = RunStore.create(spec, tmp_path)
    asyncio.run(Runner(store, llm=Flaky(fail_on_call=10, error=LLMError("boom"))).run())
    assert len(store.summaries()) == 9  # one slot was played twice

    tables = build_tables(store)
    games = tables["games"]
    assert len(games) == 8 and games["slot"].is_unique
    assert "g0000-2" in set(games["game_id"]) and "g0000-1" not in set(games["game_id"])
    assert set(tables["meetings"]["game_id"]) <= set(games["game_id"])
    assert set(tables["actions"]["game_id"]) == set(games["game_id"])
    for name in ("games", "meetings", "actions"):
        assert (store.path / "tables" / f"{name}.csv").exists()
