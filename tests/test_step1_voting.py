import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "among-agents"))

from amongagents.envs.action import Vote
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME
from amongagents.envs.game import AmongUs

AGENT_CONFIG = {
    "Impostor": "LLM",
    "Crewmate": "LLM",
    "IMPOSTOR_LLM_CHOICES": ["ollama/test-model"],
    "CREWMATE_LLM_CHOICES": ["ollama/test-model"],
}


class GameTestCase(unittest.TestCase):
    game_config = FIVE_MEMBER_GAME

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_patch = mock.patch.dict(os.environ, {"EXPERIMENT_PATH": self.tmp.name})
        self.env_patch.start()
        self.game = AmongUs(game_config=self.game_config, agent_config=AGENT_CONFIG, game_index=1, seed=7)
        self.game.initialize_game()
        self.players = self.game.players

    def tearDown(self):
        self.env_patch.stop()
        self.tmp.cleanup()

    def start_voting(self):
        self.game.current_phase = "meeting"
        self.game.discussion_rounds_left = 0

    def cast(self, voter, target):
        Vote(voter.location, target).execute(self.game, voter)

    def events(self, event_type):
        with open(os.path.join(self.tmp.name, "events.jsonl")) as f:
            return [e for e in map(json.loads, f) if e["type"] == event_type]


class TestVoteout(GameTestCase):
    def test_unique_plurality_ejects(self):
        self.start_voting()
        p1, p2, p3, p4, p5 = self.players
        self.cast(p1, p2)
        self.cast(p3, p2)
        self.cast(p4, p5)
        self.cast(p5, None)
        self.cast(p2, p1)
        self.game.voteout()
        self.assertFalse(p2.is_alive)
        tally = self.events("tally")[-1]
        self.assertEqual(tally["ejected"], p2.name)
        self.assertEqual(tally["counts"][p2.name], 2)
        self.assertEqual(tally["counts"]["SKIP"], 1)
        self.assertEqual(tally["n_living_voters"], 5)

    def test_tie_ejects_no_one(self):
        self.start_voting()
        p1, p2, p3, p4, _ = self.players
        self.cast(p1, p2)
        self.cast(p2, p1)
        self.game.voteout()
        self.assertTrue(all(p.is_alive for p in self.players))
        self.assertIsNone(self.events("tally")[-1]["ejected"])

    def test_skip_plurality_ejects_no_one(self):
        self.start_voting()
        p1, p2, p3, _, _ = self.players
        self.cast(p1, None)
        self.cast(p2, None)
        self.cast(p3, p1)
        self.game.voteout()
        self.assertTrue(all(p.is_alive for p in self.players))
        self.assertIsNone(self.events("tally")[-1]["ejected"])

    def test_all_skip_and_empty_do_not_crash(self):
        self.start_voting()
        for p in self.players:
            self.cast(p, None)
        self.game.voteout()
        self.start_voting()
        self.game.voteout()  # no ballots at all
        self.assertTrue(all(p.is_alive for p in self.players))
        self.assertEqual(len(self.events("tally")), 2)

    def test_vote_event_fields(self):
        self.start_voting()
        p1, p2 = self.players[:2]
        self.cast(p1, p2)
        vote = self.events("vote")[-1]
        self.assertEqual(vote["voter"], p1.name)
        self.assertEqual(vote["target"], p2.name)
        self.assertEqual(vote["target_identity"], p2.identity)
        self.assertFalse(vote["fallback"])
        self.assertEqual(vote["game_index"], 1)
        self.assertEqual(vote["seed"], 7)


class TestVoteOptions(GameTestCase):
    def test_skip_first_and_excludes_self_and_dead(self):
        self.start_voting()
        p1, p2 = self.players[:2]
        p2.is_alive = False
        options = Vote.can_execute_actions(self.game, p1)
        self.assertEqual(repr(options[0]), "VOTE SKIP")
        targets = [o.other_player for o in options[1:]]
        self.assertNotIn(p1, targets)
        self.assertNotIn(p2, targets)
        self.assertEqual(len(targets), 3)


class TestAgentFallback(GameTestCase):
    def run_choose(self, agent, responses):
        async def fake_send(messages):
            agent.last_usage = {}
            return responses.pop(0)

        with mock.patch.object(agent, "send_request", side_effect=fake_send) as send:
            action = asyncio.run(agent.choose_action(0))
        return action, send.call_count

    def voting_agent(self):
        self.start_voting()
        self.game.check_actions()
        return self.game.agents[0]

    def test_garbage_vote_becomes_skip(self):
        agent = self.voting_agent()
        action, calls = self.run_choose(agent, ["no idea", "still nothing"])
        self.assertEqual(calls, 2)
        self.assertEqual(repr(action), "VOTE SKIP")
        self.assertTrue(action.fallback)
        self.assertEqual(agent.parse_failures, 1)

    def test_reprompt_recovers_valid_vote(self):
        agent = self.voting_agent()
        target = self.players[1] if agent.player is not self.players[1] else self.players[2]
        action, calls = self.run_choose(agent, ["garbage", f"[Action] VOTE {target.name}"])
        self.assertEqual(calls, 2)
        self.assertIs(action.other_player, target)
        self.assertFalse(action.fallback)
        self.assertEqual(agent.parse_failures, 0)

    def test_api_failure_skips_reprompt(self):
        agent = self.voting_agent()

        async def failed_send(messages):
            agent.last_usage = None
            return "SPEAK: ..."

        with mock.patch.object(agent, "send_request", side_effect=failed_send) as send:
            action = asyncio.run(agent.choose_action(0))
        self.assertEqual(send.call_count, 1)
        self.assertEqual(repr(action), "VOTE SKIP")


class TestSeeding(unittest.TestCase):
    def roles(self, seed):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"EXPERIMENT_PATH": tmp}):
            game = AmongUs(game_config=FIVE_MEMBER_GAME, agent_config=AGENT_CONFIG, seed=seed)
            game.initialize_game()
            return [(p.name, p.identity, [t.name for t in p.tasks]) for p in game.players]

    def test_same_seed_same_setup(self):
        self.assertEqual(self.roles(3), self.roles(3))


if __name__ == "__main__":
    unittest.main()
