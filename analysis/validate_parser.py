"""Validate the log parser against hand annotations (research plan gate G2: >= 95% field agreement).

Two steps:

1. transcripts -- sample games and write a readable transcript for each, built from the raw
   agent logs (agent-logs-compact.json), not from events.jsonl, so annotation is independent of
   the parser. Also writes annotations.csv with one blank row per sampled game.

   python analysis/validate_parser.py transcripts parsed/games.csv --n 10 --out validation/

2. compare -- after both annotators fill annotations.csv, score it against games.csv.

   python analysis/validate_parser.py compare parsed/games.csv validation/annotations.csv
"""

import argparse
import json
import os
import re
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_logs import read_jsonl  # noqa: E402

ANNOTATED_FIELDS = [
    "crew_win",  # 1 if crewmates won, else 0
    "damage",  # number of kills by the insider
    "wrongful_removal_count",  # crewmates ejected by vote
    "insider_ejected",  # 1 if the insider was ejected by vote
    "detection_meeting",  # meeting number that ejected the insider, or the number of meetings held if never
    "n_meetings",
]
AGREEMENT_TARGET = 0.95

INSTRUCTIONS = """\
Annotation instructions
- Fill one row of annotations.csv from this transcript only; do not open the parsed tables.
- Meetings are numbered 1, 2, ... in the order they are called.
- A vote with no valid "VOTE ..." action counts as VOTE SKIP. When a player was re-prompted,
  use their last response for that step.
- Apply the ejection rule named in the header to the votes of each meeting:
  plurality = one option with strictly the most votes (SKIP counts as an option; tie or SKIP -> no one);
  majority  = a player with more than half of the living voters.
- damage = kills by the insider. detection_meeting = the meeting that ejected the insider,
  or the number of meetings held if the insider was never ejected.
"""


def action_text(response):
    match = re.search(r"\[Action\]\s*(.*)", response or "", re.DOTALL)
    text = (match.group(1) if match else response or "").strip()
    return " ".join(text.split())[:400]


def write_transcript(game, run_dir, path):
    records = [
        r for r in read_jsonl(os.path.join(run_dir, "agent-logs-compact.json"))
        if r["game_index"] == f"Game {game['game_index']}"
    ]
    lines = [
        f"Game {game['game_id']}",
        f"Condition: {game['condition']} (ejection rule: {game['vote_threshold']})",
        f"Insider: {game['insiders']}",
        f"Result: {game['winner_reason']}",
        "",
        INSTRUCTIONS,
        "step | player (identity) | phase | action",
    ]
    for r in records:
        prompt = r["interaction"]["prompt"]
        phase = prompt.get("Phase", "") if isinstance(prompt, dict) else ""
        retry = " (re-prompt)" if isinstance(prompt, dict) and ("Reprompt" in prompt or "Note" in prompt) else ""
        player = r["player"]
        lines.append(
            f"{r['step']} | {player['name']} ({player['identity']}) | {phase}{retry} | "
            f"{action_text(r['interaction'].get('full_response'))}"
        )
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def make_transcripts(games_csv, n, out, seed, logs_root):
    games = pd.read_csv(games_csv)
    valid = games[games["valid"] == 1]
    sample = valid.sample(n=min(n, len(valid)), random_state=seed)
    os.makedirs(out, exist_ok=True)
    for _, game in sample.iterrows():
        name = game["game_id"].replace("#", "_game")
        write_transcript(game, os.path.join(logs_root, game["run"]), os.path.join(out, f"{name}.txt"))
    template = sample[["game_id"]].copy()
    for field in ANNOTATED_FIELDS:
        template[field] = ""
    template.to_csv(os.path.join(out, "annotations.csv"), index=False)
    print(f"Wrote {len(sample)} transcripts and annotations.csv to {out}/")


def agreement(games, annotations):
    """Return (per-field agreement, overall agreement, list of mismatches)."""
    merged = annotations.merge(games, on="game_id", how="left", suffixes=("_hand", "_parser"))
    per_field, mismatches = {}, []
    matches = total = 0
    for field in ANNOTATED_FIELDS:
        hand, parsed = merged[f"{field}_hand"], merged[f"{field}_parser"]
        filled = hand.notna()
        same = [
            int(float(h)) == int(float(p)) if pd.notna(p) else False
            for h, p in zip(hand[filled], parsed[filled])
        ]
        per_field[field] = sum(same) / len(same) if same else float("nan")
        matches += sum(same)
        total += len(same)
        for gid, h, p, ok in zip(merged["game_id"][filled], hand[filled], parsed[filled], same):
            if not ok:
                mismatches.append((gid, field, h, p))
    return per_field, (matches / total if total else float("nan")), mismatches


def compare(games_csv, annotations_csv):
    per_field, overall, mismatches = agreement(pd.read_csv(games_csv), pd.read_csv(annotations_csv))
    for field, value in per_field.items():
        print(f"{field:>24}: {value:.1%}")
    print(f"{'overall':>24}: {overall:.1%} (target {AGREEMENT_TARGET:.0%})")
    for gid, field, h, p in mismatches:
        print(f"  mismatch {gid} {field}: hand={h} parser={p}")
    return overall >= AGREEMENT_TARGET


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("transcripts")
    t.add_argument("games_csv")
    t.add_argument("--n", type=int, default=10)
    t.add_argument("--out", default="validation")
    t.add_argument("--seed", type=int, default=0)
    t.add_argument("--logs_root", default="expt-logs")
    c = sub.add_parser("compare")
    c.add_argument("games_csv")
    c.add_argument("annotations_csv")
    args = parser.parse_args()

    if args.command == "transcripts":
        make_transcripts(args.games_csv, args.n, args.out, args.seed, args.logs_root)
    else:
        sys.exit(0 if compare(args.games_csv, args.annotations_csv) else 1)


if __name__ == "__main__":
    main()
