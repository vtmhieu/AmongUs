"""Plays the games of a run.

Games are taken from the schedule in order by a fixed number of workers, so the
interleaving of conditions is preserved while several games are in flight. A game
that aborts on an API error, or in which too many replies were unreadable, is
recorded as invalid and its slot is played again, up to ``max_attempts`` times.

A run can be stopped and resumed: only slots without a valid game are played.
"""

from __future__ import annotations

import asyncio
import shutil
import traceback
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone

from amongagents.agent.llm import LLM, FatalLLMError, LLMError, cost_usd, make_llm
from amongagents.agent.mock import MOCK_MODEL
from amongagents.envs.events import JsonlWriter, discard
from amongagents.envs.game import AmongUs
from amongagents.envs.governance import Governance
from govlab.store import RunStore, game_id

Publish = Callable[[dict], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def judge(summary: dict, max_fallback_rate: float) -> str | None:
    """Why a finished game must be excluded, or None if it is valid.

    This is the study's exclusion rule. It looks only at whether the game ran
    properly, never at how it came out.
    """
    if summary.get("error"):
        return "error"
    if not summary.get("winner"):
        return "unfinished"
    decisions = summary.get("decisions", 0)
    if decisions == 0:
        return "no_decisions"
    if summary.get("fallbacks", 0) / decisions > max_fallback_rate:
        return "unreadable_replies"
    return None


class Runner:
    retry_delay = 5.0  # seconds before a slot's next attempt, times the attempt number

    def __init__(self, store: RunStore, publish: Publish = discard, llm: LLM | None = None):
        self.store = store
        self.spec = store.spec
        self.publish = publish
        self._llm = llm
        self._workers: list[asyncio.Task] = []
        self._stopping = False
        self._fatal: str | None = None
        self.running: dict[str, dict] = {}  # game_id -> what is known about a game in flight
        self.cost = sum(s.get("cost_usd") or 0 for s in store.summaries())

    @property
    def model(self) -> str:
        return MOCK_MODEL if self.spec.llm.provider == "mock" else self.spec.llm.model

    def over_budget(self) -> bool:
        return self.spec.budget_usd is not None and self.cost >= self.spec.budget_usd

    def stop(self) -> None:
        """Abandon the games in flight. Their slots stay pending and can be resumed."""
        self._stopping = True
        for worker in self._workers:
            worker.cancel()

    async def run(self) -> dict:
        """Play every pending slot. Returns the run's overview."""
        store = self.store
        try:
            llm = self._llm or make_llm(
                self.spec.llm, max_concurrency=max(8, 2 * self.spec.concurrency)
            )
        except LLMError as e:
            return self._finish("failed", str(e))

        store.set_status("running")
        self._publish_run()
        queue = deque(store.pending_slots())

        async def worker():
            while queue and not self._stopping and self._fatal is None and not self.over_budget():
                await self._play_slot(llm, queue.popleft())

        self._workers = [asyncio.create_task(worker()) for _ in range(self.spec.concurrency)]
        try:
            outcomes = await asyncio.gather(*self._workers, return_exceptions=True)
        finally:
            # reached with an exception only if this task itself is cancelled (shutdown)
            for worker in self._workers:
                worker.cancel()
            store.set_status("stopped")
            await llm.close()
        crashed = [o for o in outcomes if isinstance(o, Exception)]
        if crashed and not self._fatal:
            self._fatal = f"runner error: {type(crashed[0]).__name__}: {crashed[0]}"

        if self._fatal:
            return self._finish("failed", self._fatal)
        if self._stopping:
            return self._finish("stopped")
        if store.pending_slots() and self.over_budget():
            return self._finish("budget", f"budget of ${self.spec.budget_usd:.2f} reached")
        return self._finish("completed")

    def _finish(self, state: str, error: str | None = None) -> dict:
        self.store.set_status(state, error)
        self._publish_run()
        return self.store.overview()

    def _publish_run(self) -> None:
        self.publish({"kind": "run", "run": self.store.overview()})

    async def _play_slot(self, llm: LLM, slot: dict) -> None:
        played = sum(1 for s in self.store.summaries() if s["slot"] == slot["slot"])
        for attempt in range(played + 1, self.spec.max_attempts + 1):
            if attempt > played + 1:  # the SDK has already backed off within the failed game
                await asyncio.sleep(min(30.0, self.retry_delay * (attempt - played - 1)))
            summary = await self._play(llm, slot, attempt)
            if summary["valid"] or self._stopping or self._fatal:
                return

    async def _play(self, llm: LLM, slot: dict, attempt: int) -> dict:
        game = game_id(slot["slot"], attempt)
        directory = self.store.game_dir(game)
        if directory.exists():  # left behind by an attempt that was stopped part-way
            shutil.rmtree(directory)
        write_event = JsonlWriter(directory / "events.jsonl")
        info = {
            "game_id": game,
            "slot": slot["slot"],
            "block": slot["block"],
            "attempt": attempt,
            "seed": slot["seed"],
            "condition": slot["condition"],
            "governance": slot["governance"],
            "model": self.model,
            "started": _now(),
        }

        def emit(event: dict) -> None:
            write_event(event)
            self.publish({"kind": "event", "game_id": game, "event": event})

        engine = AmongUs(
            llm,
            game_config=self.spec.game,
            governance=Governance.from_dict(slot["governance"]),
            seed=slot["seed"],
            game_id=game,
            emit=emit,
            llm_log=JsonlWriter(directory / "llm.jsonl"),
        )
        self.running[game] = info
        self.publish({"kind": "game", "game": {**info, "status": "running"}})
        error = None
        try:
            result = await engine.run_game()
        except asyncio.CancelledError:
            self.running.pop(game, None)
            self.publish({"kind": "game", "game": {**info, "status": "cancelled"}})
            raise
        except FatalLLMError as e:
            # not this game's fault and not fixable by replaying it: end the run
            self._fatal = str(e)
            result, error = engine.summary(), str(e)
            for worker in self._workers:
                if worker is not asyncio.current_task():
                    worker.cancel()
        except LLMError as e:
            result, error = engine.summary(), str(e)
        except Exception as e:  # a bug in the engine must not take the other games down
            result, error = engine.summary(), f"{type(e).__name__}: {e}"
            (directory / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")

        summary = {**info, **result, "error": error, "finished": _now()}
        summary["invalid_reason"] = judge(summary, self.spec.max_fallback_rate)
        summary["valid"] = summary["invalid_reason"] is None
        summary["cost_usd"] = cost_usd(summary["usage"], self.model)
        self.running.pop(game, None)
        if not self._fatal:  # a fatal error does not use up one of the slot's attempts
            self.store.write_summary(game, summary)
        self.cost += summary["cost_usd"] or 0
        self.publish(
            {
                "kind": "game",
                "game": {**summary, "status": "valid" if summary["valid"] else "invalid"},
            }
        )
        self._publish_run()
        return summary


async def run_experiment(
    store: RunStore, publish: Publish = discard, llm: LLM | None = None
) -> dict:
    return await Runner(store, publish=publish, llm=llm).run()
