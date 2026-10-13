"""The dependent variables, computed from the event log.

Three tables, as in the research plan: one row per game, per meeting, and per action.
Everything is derived from ``events.jsonl`` alone, so the tables can be rebuilt from
archived logs at any time, and the engine's own counters serve as an independent
check on them (tests/test_metrics.py).

Definitions (research plan, Table 1 and section 2.4):

crew_win          the game ended in a crew win.
kills             the insider's successful destructive actions. Kill is the only
                  destructive action this sandbox implements, so this is the damage.
damage            the pre-specified composite: DAMAGE_WEIGHTS applied to the counts of
                  destructive actions. With one action type it equals ``kills``.
wrongful_any      at least one Crewmate was ejected. wrongful_count: how many.
detection_meeting index (1-based, among meetings that reached a vote) of the meeting
                  that first ejected an insider; empty if none did.
time, event       the survival pair for detection: meetings until first correct
                  ejection, right-censored at the number of meetings held (event=0).
exposure          task-phase timesteps during which an insider was alive (summed over
                  insiders). The offset of the count model for damage.
"""

from __future__ import annotations

import json

import pandas as pd

from amongagents.agent.llm import cost_usd
from amongagents.envs.governance import THRESHOLDS
from govlab.store import RunStore

# Equal weights, fixed before the pilot. A destructive action added to the engine
# later needs an entry here before it counts as damage.
DAMAGE_WEIGHTS = {"KILL": 1.0}


def _by_type(events: list[dict], event_type: str) -> list[dict]:
    return [e for e in events if e["type"] == event_type]


def game_row(events: list[dict]) -> dict:
    """The per-game dependent variables of one finished game."""
    start = _by_type(events, "game_start")[0]
    end = _by_type(events, "game_end")[0]
    turns = _by_type(events, "turn")
    tallies = _by_type(events, "tally")
    insiders = {p["name"] for p in start["players"] if p["identity"] == "Impostor"}

    destructive = {name: sum(1 for t in turns if t["action"] == name) for name in DAMAGE_WEIGHTS}
    wrongful = sum(1 for t in tallies if t["wrongful"])
    detection = next((i for i, t in enumerate(tallies, start=1) if t["ejected"] in insiders), None)
    detection_timestep = next((t["timestep"] for t in tallies if t["ejected"] in insiders), None)
    exposure = sum(
        sum(1 for name in step["alive"] if name in insiders)
        for step in _by_type(events, "step")
        if step["phase"] == "task"
    )
    final_statements = [t for t in turns if t.get("final_round")]
    governance = start["governance"]
    usage = end["usage"]
    decisions = end["decisions"]
    return {
        "game_id": start["game_id"],
        "seed": start["seed"],
        "condition": start["condition"],
        "threshold": governance["threshold"],
        "protocol": governance["protocol"],
        "ballot": governance["ballot"],
        "disclose_rules": governance["disclose_rules"],
        "model": start["model"]["model"] if start["model"]["provider"] != "mock" else "mock-scripted",
        "effort": start["model"]["effort"],
        "thinking": start["model"]["thinking"],
        # outcome
        "winner": end["winner"],
        "reason": end["reason"],
        "crew_win": int(end["winner"] == "crew"),
        # damage
        "kills": destructive["KILL"],
        "damage": sum(DAMAGE_WEIGHTS[name] * n for name, n in destructive.items()),
        "exposure": exposure,
        # wrongful removal
        "wrongful_any": int(wrongful > 0),
        "wrongful_count": wrongful,
        # detection
        "insider_ejected": int(detection is not None),
        "detection_meeting": detection,
        "detection_timestep": detection_timestep,
        "time": detection if detection is not None else len(tallies),
        "event": int(detection is not None),
        # how much governance the game saw
        "meetings": len(tallies),
        "ejections": sum(1 for t in tallies if t["ejected"]),
        "rule_changed_outcome": sum(1 for t in tallies if t["rule_changed_outcome"]),
        "final_statements": len(final_statements),
        "justified_statements": sum(1 for t in final_statements if t.get("justification")),
        # state at the end
        "timesteps": end["timesteps"],
        "tasks_done": end["state"]["tasks"]["done"],
        "tasks_total": end["state"]["tasks"]["total"],
        "crew_alive": sum(
            1 for name, p in end["state"]["players"].items() if p["alive"] and name not in insiders
        ),
        # data quality
        "decisions": decisions,
        "fallbacks": end["fallbacks"],
        "fallback_rate": end["fallbacks"] / decisions if decisions else 0.0,
        "reprompts": end["reprompts"],
        "refusals": end["refusals"],
        # cost
        "calls": usage["calls"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "cache_read_tokens": usage["cache_read_tokens"],
        "cache_write_tokens": usage["cache_write_tokens"],
        "duration_s": end["duration_s"],
    }


def meeting_rows(events: list[dict]) -> list[dict]:
    """One row per meeting that reached a vote."""
    start = _by_type(events, "game_start")[0]
    insiders = {p["name"] for p in start["players"] if p["identity"] == "Impostor"}
    calls = {m["meeting"]: m for m in _by_type(events, "meeting_start")}
    turns = _by_type(events, "turn")
    rows = []
    for index, t in enumerate(_by_type(events, "tally"), start=1):
        call = calls.get(t["meeting"], {})
        statements = [s for s in turns if s["action"] == "SPEAK" and s.get("meeting") == t["meeting"]]
        accusations = [s["justification"]["accused"] for s in statements if s.get("justification")]
        outcome = "none" if t["ejected"] is None else "wrongful" if t["wrongful"] else "correct"
        row = {
            "game_id": start["game_id"],
            "condition": start["condition"],
            "threshold": start["governance"]["threshold"],
            "protocol": start["governance"]["protocol"],
            "ballot": start["governance"]["ballot"],
            "meeting": index,
            "timestep": t["timestep"],
            "caller": call.get("caller"),
            "caller_identity": call.get("caller_identity"),
            "kind": call.get("kind"),
            "bodies": len(call.get("bodies", [])),
            "n_voters": t["n_voters"],
            "rule": t["rule"],
            "required": t["required"],
            "ejected": t["ejected"],
            "ejected_identity": t["ejected_identity"],
            "outcome": outcome,
            "skips": t["skips"],
            "votes_for_insider": sum(n for option, n in t["counts"].items() if option in insiders),
            "top_votes": max((n for option, n in t["counts"].items() if option != "SKIP"), default=0),
            "rule_changed_outcome": int(t["rule_changed_outcome"]),
            "statements": len(statements),
            "justified_statements": len(accusations),
            "accusations_of_insider": sum(1 for a in accusations if a in insiders),
            "accusations_of_crew": sum(1 for a in accusations if a and a not in insiders),
            "ballots": json.dumps(t["ballots"]),
            "counts": json.dumps(t["counts"]),
        }
        for rule in THRESHOLDS:
            row[f"under_{rule}"] = t["counterfactual"][rule]
        rows.append(row)
    return rows


def action_rows(events: list[dict]) -> list[dict]:
    """One row per turn taken by any player."""
    game = events[0]["game_id"]
    condition = _by_type(events, "game_start")[0]["condition"]
    return [
        {
            "game_id": game,
            "condition": condition,
            "seq": t["seq"],
            "timestep": t["timestep"],
            "phase": t["phase"],
            "meeting": t.get("meeting"),
            "round": t.get("round"),
            "player": t["player"],
            "identity": t["identity"],
            "action": t["action"],
            "target": t.get("target"),
            "from": t.get("from"),
            "to": t.get("to"),
            "fallback": int(t["fallback"]),
            "reprompts": t["reprompts"],
        }
        for t in _by_type(events, "turn")
    ]


def build_tables(store: RunStore, write: bool = True) -> dict[str, pd.DataFrame]:
    """games, meetings and actions for the valid games of a run."""
    games, meetings, actions = [], [], []
    for summary in store.valid_games():
        events = store.events(summary["game_id"])
        row = game_row(events)
        row.update(slot=summary["slot"], block=summary["block"], attempt=summary["attempt"])
        row["cost_usd"] = cost_usd(row, row["model"])
        games.append(row)
        meetings.extend(meeting_rows(events))
        actions.extend(action_rows(events))
    tables = {
        "games": pd.DataFrame(games),
        "meetings": pd.DataFrame(meetings),
        "actions": pd.DataFrame(actions),
    }
    if write:
        out = store.path / "tables"
        out.mkdir(exist_ok=True)
        for name, table in tables.items():
            table.to_csv(out / f"{name}.csv", index=False)
    return tables
