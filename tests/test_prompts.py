"""The governance texts: what each condition tells the players, and that they match in length."""

import itertools

import pytest

from amongagents.agent.agent import build_system_prompt
from amongagents.agent.llm import LLMConfig, make_llm
from amongagents.agent.prompts import BALLOT_TEXT, PROTOCOL_TEXT, VOTING_RULE_TEXT
from amongagents.envs.game import AmongUs
from amongagents.envs.governance import BALLOTS, PROTOCOLS, THRESHOLDS, Governance


def words(text: str) -> int:
    return len(text.split())


@pytest.mark.parametrize("texts", [VOTING_RULE_TEXT, BALLOT_TEXT, PROTOCOL_TEXT])
def test_variants_of_a_manipulated_text_have_the_same_length(texts):
    """Conditions must not differ in how much the players read (a threat to validity in the plan)."""
    for a, b in itertools.combinations(texts.values(), 2):
        assert abs(words(a) - words(b)) <= 0.1 * max(words(a), words(b)), (a, b)


def test_every_level_has_a_text():
    assert set(VOTING_RULE_TEXT) == set(THRESHOLDS)
    assert set(PROTOCOL_TEXT) == set(PROTOCOLS)
    assert set(BALLOT_TEXT) == set(BALLOTS)


def new_game(**governance) -> AmongUs:
    game = AmongUs(make_llm(LLMConfig(provider="mock")), governance=Governance(**governance), seed=3)
    game.initialize_game()
    return game


def meeting_prompt(game: AmongUs, rounds_left: int) -> str:
    game.current_phase = "meeting"
    game.discussion_rounds_left = rounds_left
    game.update_map()
    return game.players[0].location_info


def test_the_rule_in_force_is_stated_in_the_meeting():
    for threshold in THRESHOLDS:
        prompt = meeting_prompt(new_game(threshold=threshold), rounds_left=3)
        assert VOTING_RULE_TEXT[threshold] in prompt
        assert all(VOTING_RULE_TEXT[other] not in prompt for other in THRESHOLDS if other != threshold)


def test_the_rule_can_be_withheld():
    prompt = meeting_prompt(new_game(threshold="majority", disclose_rules=False), rounds_left=3)
    assert "more than half" not in prompt
    assert "SKIP" in prompt  # players still learn that abstaining is possible


def test_the_protocol_text_appears_only_in_the_final_discussion_round():
    game = new_game(protocol="justification")
    assert "ACCUSE:" not in meeting_prompt(game, rounds_left=3)
    assert "ACCUSE:" not in meeting_prompt(game, rounds_left=2)
    assert "ACCUSE:" in meeting_prompt(game, rounds_left=1)
    assert "ACCUSE:" not in meeting_prompt(game, rounds_left=0)  # voting


def test_freeform_gets_the_neutral_text_in_the_same_round():
    game = new_game(protocol="freeform")
    assert "no required format" in meeting_prompt(game, rounds_left=1)
    assert "no required format" not in meeting_prompt(game, rounds_left=2)


def test_the_number_of_discussion_rounds_comes_from_the_config():
    game = AmongUs(
        make_llm(LLMConfig(provider="mock")),
        game_config={**new_game().game_config, "discussion_rounds": 2},
        seed=3,
    )
    game.initialize_game()
    assert "a total of 2 discussion rounds" in meeting_prompt(game, rounds_left=2)


def test_the_impostor_is_told_who_the_impostors_are_and_no_voting_rule():
    game = new_game()
    impostor = next(p for p in game.players if p.identity == "Impostor")
    prompt = build_system_prompt(impostor, [impostor.name])
    assert f"List of impostors: ['{impostor.name}']" in prompt
    assert "most votes" not in prompt  # the rule belongs to the condition, not the role
