import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "among-agents"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from amongagents.agent.neutral_prompts import (
    FREEFORM_INSTRUCTION,
    JUSTIFICATION_INSTRUCTION,
    JUSTIFICATION_REPROMPT,
)
from amongagents.envs.action import Speak
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME
from amongagents.envs.discussion import parse_justification
from amongagents.envs.game import AmongUs
from amongagents.envs.voting import MAJORITY, PLURALITY, SKIP, tally
from test_step1_voting import AGENT_CONFIG, GameTestCase


class TestTally(unittest.TestCase):
    def test_plurality(self):
        self.assertEqual(tally({"A": 2, "B": 1, SKIP: 1}, 4, PLURALITY), "A")
        self.assertIsNone(tally({"A": 2, "B": 2}, 4, PLURALITY))  # tie
        self.assertIsNone(tally({"A": 1, SKIP: 2}, 3, PLURALITY))  # SKIP wins
        self.assertIsNone(tally({"A": 2, SKIP: 2}, 4, PLURALITY))  # tie with SKIP
        self.assertIsNone(tally({}, 5, PLURALITY))

    def test_majority_needs_more_than_half_of_living_voters(self):
        self.assertEqual(tally({"A": 3, "B": 2}, 5, MAJORITY), "A")
        self.assertIsNone(tally({"A": 2, "B": 1, SKIP: 1}, 4, MAJORITY))  # exactly half is not enough
        self.assertEqual(tally({"A": 3, SKIP: 1}, 4, MAJORITY), "A")
        self.assertIsNone(tally({SKIP: 5}, 5, MAJORITY))
        self.assertIsNone(tally({}, 5, MAJORITY))

    def test_shrinking_electorate(self):
        # the same two votes are a majority of 3 living voters but not of 4 or 5
        self.assertEqual(tally({"A": 2, "B": 1}, 3, MAJORITY), "A")
        self.assertIsNone(tally({"A": 2, "B": 1, SKIP: 1}, 4, MAJORITY))
        self.assertIsNone(tally({"A": 2, "B": 1, "C": 1, SKIP: 1}, 5, MAJORITY))

    def test_thresholds_diverge_with_four_or_more_voters(self):
        counts = {"A": 2, "B": 1, SKIP: 1}
        self.assertEqual(tally(counts, 4, PLURALITY), "A")
        self.assertIsNone(tally(counts, 4, MAJORITY))

    def test_unknown_threshold(self):
        with self.assertRaises(ValueError):
            tally({"A": 1}, 1, "unanimity")


class TestParseJustification(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(
            parse_justification("ACCUSE: Player 3: red | EVIDENCE: I saw them vent in Admin."),
            ("Player 3: red", "I saw them vent in Admin."),
        )
        self.assertEqual(
            parse_justification('"accuse: NONE | evidence: nobody was seen near the body"'),
            ("NONE", "nobody was seen near the body"),
        )
        self.assertEqual(parse_justification("ACCUSE: Player 2 | EVIDENCE: x")[0], "Player 2")

    def test_invalid(self):
        self.assertIsNone(parse_justification("I think Player 3 is sus."))
        self.assertIsNone(parse_justification("ACCUSE: Player 3: red | EVIDENCE: "))
        self.assertIsNone(parse_justification("ACCUSE: the red one | EVIDENCE: they vented"))
        self.assertIsNone(parse_justification(None))


class TestInstructions(unittest.TestCase):
    def test_freeform_instruction_is_length_matched(self):
        a, b = len(JUSTIFICATION_INSTRUCTION), len(FREEFORM_INSTRUCTION)
        self.assertLess(abs(a - b) / a, 0.10)

    def test_invalid_factor_levels_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"EXPERIMENT_PATH": tmp}):
            with self.assertRaises(ValueError):
                AmongUs(game_config={**FIVE_MEMBER_GAME, "vote_threshold": "unanimity"}, agent_config=AGENT_CONFIG)
            with self.assertRaises(ValueError):
                AmongUs(game_config={**FIVE_MEMBER_GAME, "discussion_protocol": "debate"}, agent_config=AGENT_CONFIG)


class TestMajorityVoteout(GameTestCase):
    game_config = {**FIVE_MEMBER_GAME, "vote_threshold": MAJORITY}

    def test_plurality_winner_without_majority_stays(self):
        self.start_voting()
        p1, p2, p3, p4, p5 = self.players
        self.cast(p1, p2)
        self.cast(p3, p2)
        self.cast(p4, p5)
        self.cast(p5, None)
        self.cast(p2, p1)
        self.game.voteout()
        self.assertTrue(p2.is_alive)
        tally_event = self.events("tally")[-1]
        self.assertEqual(tally_event["rule"], MAJORITY)
        self.assertIsNone(tally_event["ejected"])
        self.assertEqual(tally_event["counterfactual_rule"], PLURALITY)
        self.assertEqual(tally_event["counterfactual_ejected"], p2.name)
        self.assertTrue(tally_event["decisions_differ"])
        self.assertEqual(tally_event["condition"], "majority/freeform")

    def test_majority_ejects(self):
        self.start_voting()
        p1, p2, p3, p4, p5 = self.players
        for voter in (p1, p3, p4):
            self.cast(voter, p2)
        self.cast(p2, p1)
        self.cast(p5, None)
        self.game.voteout()
        self.assertFalse(p2.is_alive)
        self.assertFalse(self.events("tally")[-1]["decisions_differ"])


class ProtocolTestCase(GameTestCase):
    def enter_round(self, rounds_left):
        self.game.current_phase = "meeting"
        self.game.discussion_rounds_left = rounds_left
        self.game.update_map()

    def speak_step(self, replies):
        """Run one agent_step for player 1, whose model returns the given SPEAK messages in turn."""
        agent = self.game.agents[0]
        calls = []

        async def fake_choose(timestep, note=None):
            calls.append(note)
            action = Speak(agent.player.location)
            action.message = replies.pop(0)
            return action

        with mock.patch.object(agent, "choose_action", side_effect=fake_choose):
            asyncio.run(self.game.agent_step(agent))
        return calls


class TestJustificationProtocol(ProtocolTestCase):
    game_config = {**FIVE_MEMBER_GAME, "discussion_protocol": "justification"}

    def test_instruction_only_in_final_round(self):
        self.enter_round(2)
        self.assertNotIn(JUSTIFICATION_INSTRUCTION, self.players[0].location_info)
        self.enter_round(1)
        self.assertIn(JUSTIFICATION_INSTRUCTION, self.players[0].location_info)
        self.assertNotIn(FREEFORM_INSTRUCTION, self.players[0].location_info)
        self.enter_round(0)  # voting
        self.assertNotIn(JUSTIFICATION_INSTRUCTION, self.players[0].location_info)

    def test_bad_format_reprompted_once(self):
        self.enter_round(1)
        calls = self.speak_step(["Player 3 is sus", "ACCUSE: Player 3 | EVIDENCE: they vented"])
        self.assertEqual(calls, [None, JUSTIFICATION_REPROMPT])
        speech = self.events("speech")[-1]
        self.assertTrue(speech["justification_ok"])
        self.assertEqual(speech["accused"], "Player 3")

    def test_second_miss_kept_and_flagged(self):
        self.enter_round(1)
        calls = self.speak_step(["nope", "still nope"])
        self.assertEqual(len(calls), 2)
        speech = self.events("speech")[-1]
        self.assertFalse(speech["justification_ok"])
        self.assertEqual(speech["message"], "still nope")

    def test_no_check_in_earlier_rounds(self):
        self.enter_round(2)
        calls = self.speak_step(["free talk"])
        self.assertEqual(calls, [None])
        self.assertNotIn("justification_ok", self.events("speech")[-1])


class TestFreeformProtocol(ProtocolTestCase):
    def test_neutral_instruction_in_final_round_and_no_check(self):
        self.enter_round(1)
        self.assertIn(FREEFORM_INSTRUCTION, self.players[0].location_info)
        self.assertNotIn(JUSTIFICATION_INSTRUCTION, self.players[0].location_info)
        calls = self.speak_step(["free talk"])
        self.assertEqual(calls, [None])
        speech = self.events("speech")[-1]
        self.assertTrue(speech["final_round"])
        self.assertNotIn("justification_ok", speech)


if __name__ == "__main__":
    unittest.main()
