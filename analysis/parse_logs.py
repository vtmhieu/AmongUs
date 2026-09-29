"""Turn experiment logs into analysis tables (research plan step 2, gate G2).

Reads events.jsonl and summary.json from one or more experiment directories and
writes three tables:

    games.csv     one row per game: condition, outcome and every dependent variable
    meetings.csv  one row per meeting: caller, ballots, ejection, counterfactual tally
    actions.csv   one row per logged event: kills, meeting starts, speeches, votes

usage: python analysis/parse_logs.py expt-logs/<run> [expt-logs/<run> ...] --out parsed/
"""

import argparse
import json
import os
from collections import defaultdict

import pandas as pd

CREW_WIN_CODES = {2, 3}
DEFAULT_CONDITION = "plurality/freeform"  # runs logged before the governance flags existed


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def game_key(run, game_index):
    return f"{run}#{game_index}"


def load_run(run_dir):
    """Return (events by game_index, summary by game_index) for one experiment directory."""
    events = defaultdict(list)
    for event in read_jsonl(os.path.join(run_dir, "events.jsonl")):
        events[int(event["game_index"])].append(event)
    summaries = {}
    for line in read_jsonl(os.path.join(run_dir, "summary.json")):
        for name, summary in line.items():
            # a crashed game can be written twice; the last line wins
            summaries[int(name.split()[-1])] = summary
    return events, summaries


def players_from_summary(summary):
    return {
        v["name"]: v
        for k, v in summary.items()
        if k.startswith("Player ") and isinstance(v, dict)
    }


def parse_game(run, game_index, events, summary):
    """Build the games row, meeting rows and action rows for one game."""
    gid = game_key(run, game_index)
    summary = summary or {}
    players = players_from_summary(summary)
    insiders = sorted(name for name, p in players.items() if p["identity"] == "Impostor")
    config = summary.get("config", {})
    condition = summary.get("condition") or (events[0].get("condition") if events else None) or DEFAULT_CONDITION
    vote_threshold, discussion_protocol = condition.split("/")

    by_type = defaultdict(list)
    for event in events:
        by_type[event["type"]].append(event)

    kills = [e for e in by_type["kill"]]
    tallies = sorted(by_type["tally"], key=lambda e: e["meeting_index"])
    votes = by_type["vote"]
    speeches = by_type["speech"]
    game_end = by_type["game_end"][-1] if by_type["game_end"] else None

    # meetings
    meeting_starts = {e["meeting_index"]: e for e in by_type["meeting_start"]}
    meeting_rows = []
    for t in tallies:
        m = t["meeting_index"]
        start = meeting_starts.get(m, {})
        m_votes = [v for v in votes if v["meeting_index"] == m]
        m_speeches = [s for s in speeches if s["meeting_index"] == m]
        final_checks = [s["justification_ok"] for s in m_speeches if "justification_ok" in s]
        insider_votes = [v["target"] for v in m_votes if v["voter"] in insiders]
        meeting_rows.append({
            "game_id": gid,
            "meeting_index": m,
            "timestep": t["timestep"],
            "condition": condition,
            "caller": start.get("caller"),
            "caller_identity": start.get("caller_identity"),
            "kind": start.get("kind"),
            "bodies_reported": len(start.get("bodies_reported", [])),
            "n_living_voters": t["n_living_voters"],
            "n_votes": len(m_votes),
            "n_skip": t["counts"].get("SKIP", 0),
            "n_fallback_votes": sum(v["fallback"] for v in m_votes),
            "votes_for_insider": sum(v["target"] in insiders for v in m_votes),
            "insider_vote": insider_votes[0] if insider_votes else None,
            "rule": t["rule"],
            "ejected": t["ejected"],
            "ejected_identity": t["ejected_identity"],
            "correct_ejection": t["ejected_identity"] == "Impostor",
            "wrongful_ejection": t["ejected_identity"] == "Crewmate",
            "counterfactual_rule": t.get("counterfactual_rule"),
            "counterfactual_ejected": t.get("counterfactual_ejected"),
            "decisions_differ": t.get("decisions_differ"),
            "n_speeches": len(m_speeches),
            "n_justification_checked": len(final_checks),
            "n_justification_failed": sum(not ok for ok in final_checks),
            "counts": json.dumps(t["counts"]),
        })

    # timesteps: every game step is either a task step or a meeting step
    timesteps = summary.get("timesteps")
    if timesteps is None:
        timesteps = max((e["timestep"] for e in events), default=-1) + 1
    meeting_steps = {t["timestep"] for t in tallies}
    task_steps = [s for s in range(timesteps) if s not in meeting_steps]

    # detection: first meeting that ejects an insider; right-censored at the last meeting held
    first_correct = next((r for r in meeting_rows if r["correct_ejection"]), None)
    n_meetings = len(meeting_rows)
    insider_out_step = first_correct["timestep"] if first_correct else timesteps
    exposure = sum(1 for s in task_steps if s < insider_out_step)

    winner = summary.get("winner")
    valid = bool(summary.get("valid", winner is not None)) and game_end is not None
    error = summary.get("error")
    if not summary:
        error = "no summary (run interrupted)"
    elif game_end is None and not error:
        error = "no game_end event"

    wrongful = [r for r in meeting_rows if r["wrongful_ejection"]]
    models = sorted({p.get("model") for p in players.values() if p.get("model")})
    game_row = {
        "game_id": gid,
        "run": run,
        "game_index": game_index,
        "condition": condition,
        "vote_threshold": vote_threshold,
        "discussion_protocol": discussion_protocol,
        "seed": summary.get("seed", events[0].get("seed") if events else None),
        "game_config_name": summary.get("game_config_name"),
        "num_players": config.get("num_players"),
        "num_impostors": config.get("num_impostors"),
        "model": ";".join(models) or None,
        "insiders": ";".join(insiders) or None,
        "winner": winner,
        "winner_reason": summary.get("winner_reason"),
        "crew_win": None if winner is None else int(winner in CREW_WIN_CODES),
        "damage": sum(1 for k in kills if k["killer"] in insiders or not insiders),
        "wrongful_removal": int(bool(wrongful)),
        "wrongful_removal_count": len(wrongful),
        "insider_ejected": int(first_correct is not None),
        "detection_meeting": first_correct["meeting_index"] if first_correct else n_meetings,
        "detection_censored": int(first_correct is None),
        "exposure": exposure,
        "timesteps": timesteps,
        "n_meetings": n_meetings,
        "n_meetings_diverging": sum(bool(r["decisions_differ"]) for r in meeting_rows),
        "n_votes": len(votes),
        "n_fallback_votes": sum(v["fallback"] for v in votes),
        "n_justification_failed": sum(r["n_justification_failed"] for r in meeting_rows),
        "duration_s": summary.get("duration_s", game_end.get("duration_s") if game_end else None),
        "prompt_tokens": summary.get("prompt_tokens"),
        "completion_tokens": summary.get("completion_tokens"),
        "cost": summary.get("cost"),
        "api_failures": summary.get("api_failures"),
        "parse_failures": summary.get("parse_failures"),
        "valid": int(valid),
        "error": error,
    }

    action_rows = []
    for e in events:
        if e["type"] in ("tally", "game_end"):
            continue
        actor = e.get("killer") or e.get("voter") or e.get("speaker") or e.get("caller")
        action_rows.append({
            "game_id": gid,
            "type": e["type"],
            "timestep": e["timestep"],
            "meeting_index": e["meeting_index"],
            "phase": e.get("phase"),
            "actor": actor,
            "actor_identity": e.get("voter_identity") or e.get("speaker_identity") or e.get("caller_identity")
            or (players.get(actor, {}).get("identity") if actor else None),
            "target": e.get("victim") or e.get("target") or e.get("accused"),
            "target_identity": e.get("target_identity")
            or (players.get(e["victim"], {}).get("identity") if e.get("victim") else None),
            "room": e.get("room") or e.get("location"),
            "witnesses": ";".join(e["witnesses"]) if "witnesses" in e else None,
            "kind": e.get("kind"),
            "round": e.get("round"),
            "fallback": e.get("fallback"),
            "justification_ok": e.get("justification_ok"),
            "message": e.get("message"),
        })

    return game_row, meeting_rows, action_rows


def parse_runs(run_dirs):
    games, meetings, actions = [], [], []
    for run_dir in run_dirs:
        run = os.path.basename(os.path.normpath(run_dir))
        events, summaries = load_run(run_dir)
        for game_index in sorted(set(events) | set(summaries)):
            g, m, a = parse_game(run, game_index, events.get(game_index, []), summaries.get(game_index))
            games.append(g)
            meetings.extend(m)
            actions.extend(a)
    return pd.DataFrame(games), pd.DataFrame(meetings), pd.DataFrame(actions)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", help="Experiment directories under expt-logs/.")
    parser.add_argument("--out", default="parsed", help="Output directory for the CSV tables.")
    args = parser.parse_args()

    games, meetings, actions = parse_runs(args.runs)
    os.makedirs(args.out, exist_ok=True)
    games.to_csv(os.path.join(args.out, "games.csv"), index=False)
    meetings.to_csv(os.path.join(args.out, "meetings.csv"), index=False)
    actions.to_csv(os.path.join(args.out, "actions.csv"), index=False)

    n_valid = int(games["valid"].sum()) if len(games) else 0
    print(f"{len(games)} games ({n_valid} valid), {len(meetings)} meetings, {len(actions)} actions -> {args.out}/")
    if len(games):
        print(games.groupby("condition")["valid"].agg(games="count", valid="sum").to_string())


if __name__ == "__main__":
    main()
