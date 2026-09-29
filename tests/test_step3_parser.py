import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "among-agents"))
sys.path.insert(0, os.path.join(ROOT, "analysis"))

from amongagents.envs.action import CallMeeting, Kill, Vote
from amongagents.envs.configs.game_config import FIVE_MEMBER_GAME
from amongagents.envs.game import AmongUs
from parse_logs import parse_runs
from validate_parser import ANNOTATED_FIELDS, agreement, make_transcripts

AGENT_CONFIG = {
    "Impostor": "LLM",
    "Crewmate": "LLM",
    "IMPOSTOR_LLM_CHOICES": ["ollama/test-model"],
    "CREWMATE_LLM_CHOICES": ["ollama/test-model"],
}


def play_scripted_game(run_dir, game_index=1, config=FIVE_MEMBER_GAME):
    """Kill at step 0, meeting 1 wrongly ejects a crewmate, meeting 2 ejects the insider."""
    with mock.patch.dict(os.environ, {"EXPERIMENT_PATH": run_dir}):
        game = AmongUs(game_config=config, agent_config=AGENT_CONFIG, game_index=game_index, seed=11)
        game.initialize_game()
        insider = next(p for p in game.players if p.identity == "Impostor")
        c1, c2, c3, c4 = [p for p in game.players if p.identity == "Crewmate"]

        def meeting(step, caller, ballots):
            game.timestep = step
            CallMeeting(caller.location).execute(game, caller)
            game.timestep = step + 1
            game.discussion_rounds_left = 0
            game.vote_info_one_round = {}  # as meeting_phase does before voting
            for voter, target in ballots:
                Vote(voter.location, target).execute(game, voter)
            game.voteout()

        game.timestep = 0
        Kill(insider.location, c1).execute(game, insider)
        meeting(1, c2, [(c2, c4), (c3, c4), (insider, c4), (c4, insider)])
        meeting(3, c3, [(c2, insider), (c3, insider), (insider, c2)])
        game.timestep = 5
        game.report_winner(game.check_game_over())
        return game


class TestParseScriptedGame(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmp.name, "run_a")
        os.makedirs(self.run_dir)
        play_scripted_game(self.run_dir)
        self.games, self.meetings, self.actions = parse_runs([self.run_dir])

    def tearDown(self):
        self.tmp.cleanup()

    def test_game_row(self):
        g = self.games.iloc[0]
        self.assertEqual(g["game_id"], "run_a#1")
        self.assertEqual(g["condition"], "plurality/freeform")
        self.assertEqual(g["seed"], 11)
        self.assertEqual(g["winner"], 2)
        self.assertEqual(g["crew_win"], 1)
        self.assertEqual(g["damage"], 1)
        self.assertEqual(g["wrongful_removal"], 1)
        self.assertEqual(g["wrongful_removal_count"], 1)
        self.assertEqual(g["insider_ejected"], 1)
        self.assertEqual(g["detection_meeting"], 2)
        self.assertEqual(g["detection_censored"], 0)
        self.assertEqual(g["n_meetings"], 2)
        self.assertEqual(g["timesteps"], 5)
        self.assertEqual(g["exposure"], 3)  # task steps 0, 1, 3 before the insider's ejection at step 4
        self.assertEqual(g["valid"], 1)

    def test_meeting_rows(self):
        m1, m2 = self.meetings.sort_values("meeting_index").to_dict("records")
        self.assertTrue(m1["wrongful_ejection"])
        self.assertEqual(m1["n_living_voters"], 4)
        # called from the Cafeteria, so a button meeting; it still reports the body
        self.assertEqual(m1["kind"], "button")
        self.assertEqual(m1["bodies_reported"], 1)
        self.assertTrue(m2["correct_ejection"])
        self.assertEqual(m2["votes_for_insider"], 2)
        # 2 of 3 living voters: both rules eject, so the decisions agree
        self.assertFalse(m2["decisions_differ"])

    def test_action_rows(self):
        counts = self.actions["type"].value_counts().to_dict()
        self.assertEqual(counts, {"vote": 7, "meeting_start": 2, "kill": 1})
        kill = self.actions[self.actions["type"] == "kill"].iloc[0]
        self.assertEqual(kill["actor_identity"], "Impostor")
        self.assertEqual(kill["target_identity"], "Crewmate")


class TestParseEdgeCases(unittest.TestCase):
    def test_interrupted_and_censored_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            events = [
                {"game_index": 1, "seed": 5, "timestep": 0, "meeting_index": 1, "phase": "meeting",
                 "type": "meeting_start", "caller": "Player 1: red", "caller_identity": "Crewmate",
                 "kind": "button", "location": "Cafeteria", "bodies_reported": []},
                {"game_index": 1, "seed": 5, "timestep": 1, "meeting_index": 1, "phase": "meeting",
                 "type": "tally", "rule": "plurality", "counts": {"SKIP": 3}, "ballots": {},
                 "n_living_voters": 5, "ejected": None, "ejected_identity": None},
            ]
            with open(os.path.join(tmp, "events.jsonl"), "w") as f:
                f.write("\n".join(json.dumps(e) for e in events) + "\n")
            games, meetings, _ = parse_runs([tmp])
        g = games.iloc[0]
        self.assertEqual(g["valid"], 0)
        self.assertIn("no summary", g["error"])
        self.assertEqual(g["condition"], "plurality/freeform")  # pre-governance logs default to baseline
        self.assertEqual(g["detection_censored"], 1)
        self.assertEqual(g["detection_meeting"], 1)
        self.assertEqual(len(meetings), 1)

    def test_condition_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = {**FIVE_MEMBER_GAME, "vote_threshold": "majority", "discussion_protocol": "justification"}
            play_scripted_game(tmp, config=config)
            games, meetings, _ = parse_runs([tmp])
        self.assertEqual(games.iloc[0]["condition"], "majority/justification")
        # meeting 1: 3 of 4 votes is a majority, so the crewmate is still ejected
        self.assertEqual(games.iloc[0]["wrongful_removal_count"], 1)


class TestValidation(unittest.TestCase):
    def test_agreement(self):
        games = pd.DataFrame([
            {"game_id": "a#1", "crew_win": 1, "damage": 1, "wrongful_removal_count": 1,
             "insider_ejected": 1, "detection_meeting": 2, "n_meetings": 2},
            {"game_id": "a#2", "crew_win": 0, "damage": 3, "wrongful_removal_count": 0,
             "insider_ejected": 0, "detection_meeting": 1, "n_meetings": 1},
        ])
        annotations = games.copy()
        annotations.loc[1, "damage"] = 2
        per_field, overall, mismatches = agreement(games, annotations)
        self.assertEqual(per_field["damage"], 0.5)
        self.assertAlmostEqual(overall, 11 / 12)
        self.assertEqual(mismatches, [("a#2", "damage", 2, 3)])

    def test_transcripts_and_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs_root = os.path.join(tmp, "expt-logs")
            run_dir = os.path.join(logs_root, "run_a")
            os.makedirs(run_dir)
            play_scripted_game(run_dir)
            with open(os.path.join(run_dir, "agent-logs-compact.json"), "w") as f:
                f.write(json.dumps({
                    "game_index": "Game 1", "step": 2,
                    "player": {"name": "Player 1: red", "identity": "Crewmate"},
                    "interaction": {"prompt": {"Phase": "Meeting phase"},
                                    "full_response": "[Thinking Process] hmm\n[Action] VOTE Player 2: blue"},
                }) + "\n")
            games, _, _ = parse_runs([run_dir])
            games_csv = os.path.join(tmp, "games.csv")
            games.to_csv(games_csv, index=False)
            out = os.path.join(tmp, "validation")
            make_transcripts(games_csv, 10, out, seed=0, logs_root=logs_root)
            template = pd.read_csv(os.path.join(out, "annotations.csv"))
            with open(os.path.join(out, "run_a_game1.txt")) as f:
                transcript = f.read()
        self.assertEqual(list(template.columns), ["game_id"] + ANNOTATED_FIELDS)
        self.assertIn("2 | Player 1: red (Crewmate) | Meeting phase | VOTE Player 2: blue", transcript)


if __name__ == "__main__":
    unittest.main()
