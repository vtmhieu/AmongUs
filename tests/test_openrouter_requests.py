import asyncio
import json
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "among-agents"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from amongagents.agent import agent as agent_module
from test_step1_voting import AGENT_CONFIG, GameTestCase


class FakeResponse:
    def __init__(self, data):
        self.status = 200
        self._data = data

    async def json(self):
        return self._data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Stands in for aiohttp.ClientSession; replays responses and records payloads."""

    def __init__(self, responses, payloads):
        self.responses = responses
        self.payloads = payloads

    def post(self, url, headers=None, data=None):
        self.payloads.append(json.loads(data))
        return FakeResponse(self.responses.pop(0))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def reply(content, cost=0.0001):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "cost": cost},
    }


class TestOpenRouterRequests(GameTestCase):
    game_config = {**GameTestCase.game_config}

    def setUp(self):
        AGENT_CONFIG["REASONING"] = {"effort": "low"}
        super().setUp()
        self.game.current_phase = "meeting"
        self.game.discussion_rounds_left = 0
        self.game.check_actions()
        self.agent = self.game.agents[0]

    def tearDown(self):
        AGENT_CONFIG.pop("REASONING", None)
        super().tearDown()

    def run_choose(self, responses):
        payloads = []
        with mock.patch.object(agent_module.aiohttp, "ClientSession", lambda: FakeSession(responses, payloads)):
            action = asyncio.run(self.agent.choose_action(0))
        return action, payloads

    def test_empty_content_does_not_crash_and_falls_back_to_skip(self):
        action, payloads = self.run_choose([reply(None), reply(None)])
        self.assertEqual(len(payloads), 2)  # original call + one re-prompt
        self.assertEqual(repr(action), "VOTE SKIP")
        self.assertTrue(action.fallback)
        self.assertEqual(self.agent.parse_failures, 1)
        self.assertEqual(self.agent.api_failures, 0)

    def test_reasoning_sent_and_usage_summed(self):
        target = next(p for p in self.players if p is not self.agent.player)
        action, payloads = self.run_choose([reply(f"[Action] VOTE {target.name}", cost=0.0002)])
        self.assertEqual(payloads[0]["reasoning"], {"effort": "low"})
        self.assertIs(action.other_player, target)
        self.assertEqual(self.agent.usage, {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.0002})


if __name__ == "__main__":
    unittest.main()
