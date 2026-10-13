"""Reading an action out of a model's reply."""

import pytest

from amongagents.agent.parsing import match_action, neutral_action, split_reply
from amongagents.envs.action import CallMeeting, CompleteTask, Kill, MoveTo, Speak, Vote, Wait


class P:
    def __init__(self, name):
        self.name = name


class T:
    name = "Fix Wiring"


RED, BLUE, GREEN = P("Player 1: red"), P("Player 2: blue"), P("Player 3: green")


def votes():
    return [Vote("Cafeteria", RED), Vote("Cafeteria", BLUE), Vote("Cafeteria", None)]


def task_actions():
    return [
        MoveTo("Cafeteria", "Weapons"),
        MoveTo("Cafeteria", "Admin"),
        CallMeeting("Cafeteria"),
        CompleteTask("Cafeteria", T()),
        Kill("Cafeteria", BLUE),
    ]


class TestSplitReply:
    def test_full_format(self):
        reply = split_reply(
            "[Condensed Memory]\nI am in Admin.\n[Thinking Process]\nGo to my task.\n[Action] MOVE from Admin to O2"
        )
        assert reply.memory == "I am in Admin."
        assert reply.thought == "Go to my task."
        assert reply.action_text == "MOVE from Admin to O2"

    def test_tags_are_case_insensitive_and_may_be_bold(self):
        reply = split_reply(
            "**[condensed memory]**\nm\n**[THINKING PROCESS]**\nt\n**[Action]** SKIP VOTE"
        )
        assert (reply.memory, reply.thought) == ("m", "t")
        assert reply.action_text.strip("* ") == "SKIP VOTE"

    def test_the_last_action_tag_wins(self):
        reply = split_reply(
            "[Thinking Process]\nI will choose under [Action] below.\n[Action] SKIP VOTE"
        )
        assert reply.action_text == "SKIP VOTE"

    def test_without_tags_the_whole_reply_is_the_action(self):
        reply = split_reply("  VOTE Player 1: red  ")
        assert (reply.memory, reply.thought, reply.action_text) == (
            None,
            None,
            "VOTE Player 1: red",
        )


class TestMatchAction:
    def test_verbatim(self):
        assert (
            repr(match_action("MOVE from Cafeteria to Admin", task_actions()))
            == "MOVE from Cafeteria to Admin"
        )
        assert (
            repr(match_action("COMPLETE TASK - Fix Wiring", task_actions()))
            == "COMPLETE TASK - Fix Wiring"
        )
        assert repr(match_action("KILL Player 2: blue", task_actions())) == "KILL Player 2: blue"

    @pytest.mark.parametrize(
        "text",
        [
            "vote player 2: blue",
            "**VOTE Player 2: blue**",
            "VOTE Player 2 - blue.",
            "2. VOTE Player 2: blue",
            "VOTE Player 2",
            "Vote for Player 2",
        ],
    )
    def test_forgiving_about_case_punctuation_and_colour(self, text):
        assert match_action(text, votes()).target == "Player 2: blue"

    @pytest.mark.parametrize("text", ["SKIP VOTE", "skip vote", "VOTE SKIP", "Skip", "I abstain"])
    def test_skip(self, text):
        assert match_action(text, votes()).target == "SKIP"

    def test_the_first_action_named_is_the_choice(self):
        action = match_action(
            "MOVE from Cafeteria to Weapons\n\n(I considered KILL Player 2: blue but there are witnesses.)",
            task_actions(),
        )
        assert repr(action) == "MOVE from Cafeteria to Weapons"

    def test_bare_index(self):
        assert repr(match_action("2", task_actions())) == "MOVE from Cafeteria to Admin"
        assert repr(match_action(" 5. ", task_actions())) == "KILL Player 2: blue"
        assert match_action("9", task_actions()) is None

    def test_speak_keeps_the_message_and_its_line_breaks(self):
        speak = [Speak("Cafeteria")]
        action = match_action(
            'SPEAK: "I was in Admin.\nACCUSE: NONE\nEVIDENCE: nothing seen"', speak
        )
        assert action.message == "I was in Admin.\nACCUSE: NONE\nEVIDENCE: nothing seen"

    def test_speak_with_no_words_is_silence(self):
        assert match_action("SPEAK:", [Speak("Cafeteria")]).message == "..."

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "I am not sure what to do.",
            "VOTE Player 3: green",  # not on the ballot
            "VOTE Player 7",
            "Player 2 is suspicious",  # names a player but casts no vote
            "MOVE from Cafeteria to Medbay",  # not an available move
        ],
    )
    def test_never_guesses(self, text):
        assert match_action(text, votes()) is None

    def test_a_statement_without_the_speak_keyword_is_not_a_speech(self):
        assert match_action("I think it was Player 2.", [Speak("Cafeteria")]) is None


class TestNeutralAction:
    def test_a_voter_abstains(self):
        assert neutral_action(votes(), "Cafeteria").target == "SKIP"

    def test_a_speaker_stays_silent(self):
        action = neutral_action([Speak("Cafeteria")], "Cafeteria")
        assert isinstance(action, Speak) and action.message == "..."

    def test_in_the_task_phase_the_player_stands_still(self):
        action = neutral_action(task_actions(), "Cafeteria")
        assert isinstance(action, Wait)
