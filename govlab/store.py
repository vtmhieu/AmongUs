"""Where a run lives on disk.

    runs/<run_id>/
        manifest.json            the design, the schedule, and what produced it
        status.json              running / completed / stopped / failed
        games/<game_id>/
            events.jsonl         structured game events (what the analysis reads)
            llm.jsonl            every prompt and raw reply (the primary record)
            summary.json         the game's result, validity and cost
        tables/                  games.csv, meetings.csv, actions.csv
        analysis/                results.json, report.md, figures

A slot of the schedule may be played more than once (an invalid game is regenerated).
Each attempt is its own game, ``g0007-1``, ``g0007-2``; the analysis uses the last
attempt of each slot, and only if it is valid.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from amongagents.agent.mock import MOCK_MODEL
from amongagents.envs.events import read_jsonl
from govlab.design import ExperimentSpec

REPO_ROOT = Path(__file__).resolve().parent.parent


def runs_dir() -> Path:
    return Path(os.environ.get("GOVLAB_RUNS", REPO_ROOT / "runs"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def provenance() -> dict:
    """What code and libraries produced a run."""
    import anthropic

    status = _git("status", "--porcelain")
    return {
        "commit": _git("rev-parse", "HEAD"),
        "dirty": bool(status) if status is not None else None,
        "python": platform.python_version(),
        "anthropic_sdk": anthropic.__version__,
    }


def write_json(path: Path, data) -> None:
    """Write atomically, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def game_id(slot: int, attempt: int) -> str:
    return f"g{slot:04d}-{attempt}"


class RunStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.manifest = read_json(self.path / "manifest.json")
        if self.manifest is None:
            raise FileNotFoundError(f"{self.path} is not a run directory (no manifest.json)")
        self.run_id = self.manifest["run_id"]
        self.spec = ExperimentSpec.from_dict(self.manifest["spec"])
        self.schedule = self.manifest["schedule"]

    @classmethod
    def create(cls, spec: ExperimentSpec, root: str | Path | None = None) -> RunStore:
        root = Path(root) if root else runs_dir()
        slug = re.sub(r"[^a-z0-9]+", "-", spec.name.lower()).strip("-") or "experiment"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_id = f"{stamp}-{slug}"
        path = root / run_id
        suffix = 1
        while path.exists():
            suffix += 1
            path = root / f"{run_id}-{suffix}"
        write_json(
            path / "manifest.json",
            {
                "run_id": path.name,
                "name": spec.name,
                "created": _now(),
                "spec": spec.to_dict(),
                "schedule": spec.schedule(),
                "provenance": provenance(),
            },
        )
        store = cls(path)
        store.set_status("created")
        return store

    # --- status ---------------------------------------------------------------

    def set_status(self, state: str, error: str | None = None) -> None:
        write_json(self.path / "status.json", {"state": state, "error": error, "updated": _now()})

    def status(self) -> dict:
        return read_json(self.path / "status.json", {"state": "unknown", "error": None})

    # --- games ----------------------------------------------------------------

    def game_dir(self, game: str) -> Path:
        return self.path / "games" / game

    def write_summary(self, game: str, summary: dict) -> None:
        write_json(self.game_dir(game) / "summary.json", summary)

    def summaries(self) -> list[dict]:
        """Every attempt that finished, valid or not, in slot then attempt order."""
        found = []
        for path in sorted((self.path / "games").glob("*/summary.json")):
            summary = read_json(path)
            if summary:
                found.append(summary)
        return sorted(found, key=lambda s: (s["slot"], s["attempt"]))

    def final_games(self) -> dict[int, dict]:
        """slot -> the summary of its last attempt."""
        final = {}
        for summary in self.summaries():
            final[summary["slot"]] = summary
        return final

    def valid_games(self) -> list[dict]:
        """The games the analysis uses: one per slot, the last attempt, if valid."""
        return [s for s in self.final_games().values() if s.get("valid")]

    def pending_slots(self) -> list[dict]:
        """Slots still to be played: no valid game yet, and attempts left."""
        attempts: dict[int, list[dict]] = {}
        for summary in self.summaries():
            attempts.setdefault(summary["slot"], []).append(summary)
        pending = []
        for slot in self.schedule:
            played = attempts.get(slot["slot"], [])
            if any(s.get("valid") for s in played):
                continue
            if len(played) < self.spec.max_attempts:
                pending.append(slot)
        return pending

    def events(self, game: str) -> list[dict]:
        return read_jsonl(self.game_dir(game) / "events.jsonl")

    def llm_calls(self, game: str) -> list[dict]:
        return read_jsonl(self.game_dir(game) / "llm.jsonl")

    # --- overview -------------------------------------------------------------

    def overview(self) -> dict:
        """A small description of the run for lists and progress bars."""
        summaries = self.summaries()
        final = self.final_games()
        valid = [s for s in final.values() if s.get("valid")]
        return {
            "run_id": self.run_id,
            "name": self.manifest["name"],
            "created": self.manifest["created"],
            "status": self.status(),
            "provider": self.spec.llm.provider,
            "model": MOCK_MODEL if self.spec.llm.provider == "mock" else self.spec.llm.model,
            "conditions": [g.condition for g in self.spec.conditions()],
            "games_per_condition": self.spec.games_per_condition,
            "total": len(self.schedule),
            "valid": len(valid),
            "failed": sum(
                1
                for slot, s in final.items()
                if not s.get("valid")
                and sum(1 for a in summaries if a["slot"] == slot) >= self.spec.max_attempts
            ),
            "attempts": len(summaries),
            "cost_usd": sum(s.get("cost_usd") or 0 for s in summaries),
        }


def list_runs(root: str | Path | None = None) -> list[RunStore]:
    root = Path(root) if root else runs_dir()
    stores = []
    for manifest in sorted(root.glob("*/manifest.json"), reverse=True):
        try:
            stores.append(RunStore(manifest.parent))
        except (FileNotFoundError, KeyError, ValueError, TypeError):
            continue  # not a run of this version of the tool
    return stores
