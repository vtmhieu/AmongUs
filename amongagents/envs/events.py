"""Structured logging.

A game reports what happens through two callables: ``emit`` for game events (kills,
speeches, votes, tallies, ...) and ``llm_log`` for the raw prompt/response of every
model call. Both take one JSON-serialisable dict. Keeping them as plain callables
lets a caller write them to disk, push them to a browser, collect them in a list for
a test, or all three.

Event reference: docs/log-schema.md.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

Emit = Callable[[dict], None]


def discard(record: dict) -> None:
    """An Emit that drops everything."""


class JsonlWriter:
    """Append records to a JSON-lines file, one per line."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def fanout(*sinks: Emit) -> Emit:
    """Combine several sinks into one."""

    def emit(record: dict) -> None:
        for sink in sinks:
            sink(record)

    return emit


def read_jsonl(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
