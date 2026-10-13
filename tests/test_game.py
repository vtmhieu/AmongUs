"""Whole games played by the scripted mock players."""

import asyncio
import json

import pytest

from amongagents.agent.llm import LLMConfig, make_llm
from amongagents.envs.action import CallMeeting
from amongagents.envs.configs.game_config import STUDY_GAME, validate_game_config
from amongagents.envs.game import AmongUs
from amongagents.envs.governance import SKIP, Governance, tally


def play(seed=0, llm_config=None, game_config=STUDY_GAME, **governance):
    events, calls = [], []
    game = AmongUs(
        make_llm(llm_config or LLMConfig(provider="mock")),
        game_config=game_config,
        governance=Governance(**governance),
        seed=seed,
        emit=events.append,
        llm_log=calls.append,
    )
    summary = asyncio.run(game.run_game())
    return summary, events, calls


def of_type(events, event_type):
    return [e for e in events if e["type"] == event_type]


def strip_timing(events):
    return [{k: v for k, v in e.items() if k not in ("duration_s", "latency_s")} for e in events]


def test_a_game_runs_to_a_result_and_logs_serialisable_events():
    summary, events, calls = play(seed=1)
    assert summary["winner"] in ("crew", "impostor")
    assert events[0]["type"] == "game_start" and events[-1]["type"] == "game_end"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    json.dumps(events)
    json.dumps(calls)


def test_the_same_seed_replays_the_same_game():
    _, first, _ = play(seed=11, threshold="majority")
    _, second, _ = play(seed=11, threshold="majority")
    assert strip_timing(first) == strip_timing(second)


def test_the_seed_fixes_roles_colours_and_tasks_across_conditions():
    """Matched seeds give every condition the same starting position."""
    _, a, _ = play(seed=5)
    _, b, _ = play(seed=5, threshold="majority", protocol="justification", ballot="secret")
    assert a[0]["players"] == b[0]["players"]
    _, c, _ = play(seed=6)
    assert a[0]["players"] != c[0]["players"]


def test_concurrent_games_do_not_disturb_each_other():
    async def together():
        games = [AmongUs(make_llm(LLMConfig(provider="mock")), seed=s) for s in (21, 22, 23)]
        return await asyncio.gather(*(g.run_game() for g in games))

    alone = [play(seed=s)[0] for s in (21, 22, 23)]
    for solo, concurrent in zip(alone, asyncio.run(together())):
        for key in ("winner", "reason", "timesteps", "kills", "meetings", "decisions"):
            assert solo[key] == concurrent[key]


def test_the_engine_counters_agree_with_the_event_log():
    for seed in range(12):
        summary, events, calls = play(seed=seed)
        turns = of_type(events, "turn")
        tallies = of_type(events, "tally")
        assert summary["kills"] == sum(t["action"] == "KILL" for t in turns)
        assert summary["meetings"] == len(tallies)
        # a meeting called in the step that ends the game is never held
        assert len(of_type(events, "meeting_start")) - len(tallies) in (0, 1)
        assert summary["wrongful_ejections"] == sum(t["wrongful"] for t in tallies)
        assert summary["decisions"] == len(turns)
        assert summary["usage"]["calls"] == len([c for c in calls if c["type"] == "llm_call"])
        assert summary["timesteps"] == len(of_type(events, "step"))


def test_every_tally_is_the_rule_applied_to_the_logged_ballots():
    seen = 0
    for threshold in ("plurality", "majority", "supermajority"):
        for seed in range(10):
            _, events, _ = play(seed=seed, threshold=threshold)
            for t in of_type(events, "tally"):
                seen += 1
                assert t["rule"] == threshold
                assert len(t["ballots"]) == t["n_voters"]  # every living player voted
                assert tally(t["ballots"], t["n_voters"], threshold).ejected == t["ejected"]
                assert t["counterfactual"][threshold] == t["ejected"]
                assert t["rule_changed_outcome"] == (len(set(t["counterfactual"].values())) > 1)
    assert seen > 10


def test_an_unreadable_reply_never_becomes_a_consequential_move():
    """The upstream sandbox turned a failed parse into a vote for the last-listed player."""
    config = LLMConfig(provider="mock", mock_malformed_rate=1.0)
    game_config = {**STUDY_GAME, "max_timesteps": 6}
    summary, events, _ = play(seed=2, llm_config=config, game_config=game_config)
    turns = of_type(events, "turn")
    assert turns and all(t["fallback"] and t["reprompts"] == 1 for t in turns)
    assert {t["action"] for t in turns} == {"WAIT"}  # nobody moved, killed or called a meeting
    assert summary["kills"] == 0 and summary["fallbacks"] == summary["decisions"]
    assert (summary["winner"], summary["reason"]) == ("impostor", "timeout")


def test_an_unreadable_ballot_is_an_abstention():
    game = AmongUs(make_llm(LLMConfig(provider="mock", mock_malformed_rate=1.0)), seed=4)
    game.initialize_game()
    game.current_phase = "meeting"
    game.discussion_rounds_left = 0
    game.update_map()
    for agent in game.agents:
        asyncio.run(game.agent_step(agent))
    assert set(game.ballots.values()) == {SKIP}
    assert len(game.ballots) == len(game.players)


def test_occasional_bad_replies_are_recovered_by_the_reprompt():
    summary, events, _ = play(seed=3, llm_config=LLMConfig(provider="mock", mock_malformed_rate=0.2))
    assert summary["reprompts"] > 0
    assert summary["fallbacks"] < summary["reprompts"]


def test_justification_is_checked_in_the_final_round_only():
    checked = 0
    for seed in range(15):
        _, events, _ = play(seed=seed, protocol="justification")
        for t in of_type(events, "turn"):
            if t["action"] != "SPEAK":
                continue
            assert ("justification" in t) == t["final_round"]
            if t["final_round"]:
                checked += 1
                assert t["justification"] is not None  # the mock always complies
                assert "ACCUSE:" in t["message"]
    assert checked > 10


def test_freeform_statements_are_parsed_but_not_required_to_comply():
    for seed in range(15):
        _, events, _ = play(seed=seed, protocol="freeform")
        finals = [t for t in of_type(events, "turn") if t.get("final_round")]
        assert all(t["justification"] is None and t["reprompts"] == 0 for t in finals)


def test_public_votes_are_seen_as_they_are_cast_and_secret_votes_are_not():
    def observations_during_vote(ballot):
        seen = []
        for seed in range(20):
            _, _, calls = play(seed=seed, ballot=ballot)
            seen += [c["prompt"] for c in calls if c["type"] == "llm_call" and "Meeting phase - Voting" in c["prompt"]]
        return seen

    public = observations_during_vote("public")
    secret = observations_during_vote("secret")
    assert public and secret
    assert any(" VOTE Player" in p.split("Observation history:")[1].split("Action history:")[0] for p in public)
    assert not any(" VOTE " in p.split("Observation history:")[1].split("Action history:")[0] for p in secret)


def test_the_result_of_a_vote_is_announced_to_the_living():
    for seed in range(20):
        game = AmongUs(make_llm(LLMConfig(provider="mock")), seed=seed)
        asyncio.run(game.run_game())
        if game.meetings_held:
            survivors = [p for p in game.players if p.is_alive]
            assert any("Vote result:" in o for p in survivors for o in p.observation_history)
            return
    pytest.fail("no meeting in 20 games")


def test_an_ejected_player_leaves_no_body_to_report():
    for seed in range(40):
        game = AmongUs(make_llm(LLMConfig(provider="mock")), seed=seed)
        game.initialize_game()
        outcome = game.check_game_over()
        while not outcome:
            asyncio.run(game.game_step())
            outcome = game.check_game_over()
            ejected_this_step = game.current_phase == "task" and any(
                not p.is_alive and p.reported_death for p in game.players
            )
            if ejected_this_step and not outcome:
                game.check_actions()
                for player in game.living():
                    reports = [a for a in player.available_actions if isinstance(a, CallMeeting) and a.reports_body]
                    unreported = [p for p in game.players if not p.is_alive and not p.reported_death]
                    assert bool(reports) <= bool(unreported)
                return
    pytest.fail("no ejection followed by more play in 40 games")


def test_reporting_a_body_does_not_use_up_the_emergency_button():
    reports = 0
    for seed in range(30):
        game = AmongUs(make_llm(LLMConfig(provider="mock")), seed=seed)
        events = []
        game._emit = events.append
        asyncio.run(game.run_game())
        meetings = of_type(events, "meeting_start")
        reports += sum(m["kind"] == "report" for m in meetings)
        assert game.button_num == sum(m["kind"] == "button" for m in meetings)
    assert reports > 0


@pytest.mark.parametrize(
    "change",
    [
        {"num_players": 2},
        {"num_impostors": 3},  # not a strict minority of five
        {"num_common_tasks": 0, "num_short_tasks": 0, "num_long_tasks": 0},
        {"max_timesteps": 0},
        {"discussion_rounds": "3"},
    ],
)
def test_unplayable_configs_are_rejected(change):
    with pytest.raises(ValueError):
        validate_game_config({**STUDY_GAME, **change})


def test_a_config_must_be_complete():
    with pytest.raises(ValueError):
        validate_game_config({"num_players": 5})
