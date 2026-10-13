"""Support for the two human checks in the research plan.

Qualitative sub-study (plan, steps 6-8): meetings that ended in the ejection of a good
agent are sampled across conditions, exported as readable transcripts with a coding
sheet, coded independently by both authors, and compared with Cohen's kappa.

Parser validation (plan, gate G2): a handful of games are annotated by hand from
their transcripts and compared field by field with the computed metrics.

Neither step involves a model. The codebook itself is the authors' to write.
"""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import numpy as np

from govlab.metrics import game_row
from govlab.store import RunStore

# the per-game fields a person can read off a transcript without computing anything
ANNOTATED_FIELDS = [
    "winner",
    "kills",
    "wrongful_count",
    "meetings",
    "insider_ejected",
    "detection_meeting",
]


# --- qualitative sub-study ------------------------------------------------------------


def wrongful_meetings(store: RunStore) -> list[dict]:
    """Every meeting of a valid game that ejected a Crewmate."""
    found = []
    for summary in store.valid_games():
        events = store.events(summary["game_id"])
        tallies = [e for e in events if e["type"] == "tally"]
        for index, tally in enumerate(tallies, start=1):
            if tally["wrongful"]:
                found.append(
                    {
                        "game_id": summary["game_id"],
                        "condition": summary["condition"],
                        "meeting": index,
                        "engine_meeting": tally["meeting"],
                    }
                )
    return found


def sample_meetings(store: RunStore, n: int = 20, seed: int = 0) -> list[dict]:
    """Up to n wrongful-ejection meetings, spread as evenly over conditions as the data allows."""
    rng = np.random.default_rng(seed)
    by_condition: dict[str, list[dict]] = {}
    for meeting in wrongful_meetings(store):
        by_condition.setdefault(meeting["condition"], []).append(meeting)
    for meetings in by_condition.values():
        rng.shuffle(meetings)
    chosen = []
    while len(chosen) < n and any(by_condition.values()):
        for condition in sorted(by_condition):
            if by_condition[condition] and len(chosen) < n:
                chosen.append(by_condition[condition].pop())
    return chosen


def transcript(store: RunStore, game_id: str, engine_meeting: int) -> str:
    """One meeting as Markdown: what led to it, every statement, every ballot, the result."""
    events = store.events(game_id)
    start = events[0]
    roles = {p["name"]: p["identity"] for p in start["players"]}
    insiders = [name for name, role in roles.items() if role == "Impostor"]
    call = next(
        e for e in events if e["type"] == "meeting_start" and e["meeting"] == engine_meeting
    )
    tally = next(e for e in events if e["type"] == "tally" and e["meeting"] == engine_meeting)
    before = [e for e in events if e["seq"] < call["seq"]]
    kills = [e for e in before if e["type"] == "turn" and e["action"] == "KILL"]

    lines = [
        f"- Condition: **{start['condition']}** (threshold {start['governance']['threshold']}, protocol {start['governance']['protocol']}, {start['governance']['ballot']} ballot)",
        f"- Insider: {', '.join(insiders)}",
        f"- Called by {call['caller']} ({'body report' if call['kind'] == 'report' else 'emergency button'}) at timestep {call['timestep']}; living: {', '.join(call['living'])}",
    ]
    for kill in kills:
        seen = ", ".join(kill["witnesses"]) or "nobody"
        lines.append(
            f"- Earlier, timestep {kill['timestep']}: {kill['player']} killed {kill['target']} in {kill['state']['players'][kill['player']]['location']}, seen by {seen}"
        )
    lines.append("")
    round_index = None
    for e in events:
        if e["type"] != "turn" or e.get("meeting") != engine_meeting or e["phase"] != "meeting":
            continue
        if e["action"] == "SPEAK":
            if e["round"] != round_index:
                round_index = e["round"]
                lines += [
                    f"**Round {round_index + 1}**" + (" (final)" if e.get("final_round") else ""),
                    "",
                ]
            role = "insider" if roles[e["player"]] == "Impostor" else "crew"
            lines += [f"> **{e['player']}** ({role}): " + e["message"].replace("\n", "\n> "), ""]
        elif e["action"] == "VOTE":
            lines.append(f"- {e['player']} votes **{e['target']}**")
    counts = ", ".join(f"{option} {n}" for option, n in tally["counts"].items())
    lines += [
        "",
        f"**Result** ({tally['rule']}, {tally['n_voters']} voters): {tally['ejected']} ejected, a {tally['ejected_identity']}. Votes: {counts}.",
    ]
    other = {rule: out for rule, out in tally["counterfactual"].items() if out != tally["ejected"]}
    if other:
        lines.append(
            "On the same ballots: "
            + "; ".join(f"{rule} would eject {out or 'no one'}" for rule, out in other.items())
            + "."
        )
    return "\n".join(lines)


def export_sample(store: RunStore, n: int = 20, seed: int = 0) -> Path:
    """Write the sampled transcripts and an empty coding sheet under analysis/qualitative/."""
    out = store.path / "analysis" / "qualitative"
    out.mkdir(parents=True, exist_ok=True)
    chosen = sample_meetings(store, n, seed)
    document = [
        f"# Wrongful ejections: {len(chosen)} sampled meetings",
        "",
        f"Run `{store.run_id}`, sample seed {seed}. Code each item in a copy of `coding_sheet.csv`.",
        "",
    ]
    for item, meeting in enumerate(chosen, start=1):
        document += [
            f"## Item {item}: {meeting['game_id']}, meeting {meeting['meeting']}",
            "",
            transcript(store, meeting["game_id"], meeting["engine_meeting"]),
            "",
        ]
    (out / "meetings.md").write_text("\n".join(document), encoding="utf-8")
    with (out / "coding_sheet.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["item", "game_id", "meeting", "condition", "code", "notes"])
        for item, meeting in enumerate(chosen, start=1):
            writer.writerow(
                [item, meeting["game_id"], meeting["meeting"], meeting["condition"], "", ""]
            )
    return out


def cohens_kappa(a: list, b: list) -> float | None:
    """Agreement between two coders beyond chance. None if it is undefined."""
    if len(a) != len(b):
        raise ValueError("the two coders rated a different number of items")
    if not a:
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    count_a, count_b = Counter(a), Counter(b)
    expected = sum(count_a[c] * count_b[c] for c in set(a) | set(b)) / n**2
    if expected == 1:  # both coders used a single, identical code throughout
        return None
    return (observed - expected) / (1 - expected)


def kappa_from_sheets(sheet_a: str | Path, sheet_b: str | Path, column: str = "code") -> dict:
    def codes(path):
        with open(path, newline="", encoding="utf-8") as f:
            return {row["item"]: row[column].strip() for row in csv.DictReader(f)}

    a, b = codes(sheet_a), codes(sheet_b)
    if set(a) != set(b):
        raise ValueError("the two sheets do not list the same items")
    items = sorted(a, key=lambda item: int(item))
    blank = [item for item in items if not a[item] or not b[item]]
    if blank:
        raise ValueError(f"items not yet coded by both authors: {', '.join(blank)}")
    ratings_a, ratings_b = [a[i] for i in items], [b[i] for i in items]
    return {
        "items": len(items),
        "agreement": sum(x == y for x, y in zip(ratings_a, ratings_b)) / len(items),
        "kappa": cohens_kappa(ratings_a, ratings_b),
        "disagreements": [i for i, x, y in zip(items, ratings_a, ratings_b) if x != y],
    }


# --- parser validation ------------------------------------------------------------------


def annotation_template(store: RunStore, n: int = 10, seed: int = 0) -> Path:
    """An empty hand-annotation sheet for n randomly chosen valid games."""
    games = sorted(s["game_id"] for s in store.valid_games())
    rng = np.random.default_rng(seed)
    chosen = sorted(rng.choice(games, size=min(n, len(games)), replace=False)) if games else []
    out = store.path / "analysis" / "annotations_template.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["game_id", *ANNOTATED_FIELDS])
        for game in chosen:
            writer.writerow([game] + [""] * len(ANNOTATED_FIELDS))
    return out


def _same(computed, annotated: str) -> bool:
    annotated = annotated.strip().lower()
    if computed is None:
        return annotated in ("", "none", "na", "n/a", "-")
    try:
        return float(computed) == float(annotated)
    except (TypeError, ValueError):
        return str(computed).lower() == annotated


def agreement(store: RunStore, annotations: str | Path) -> dict:
    """Field-by-field agreement between hand annotations and the computed metrics."""
    with open(annotations, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    compared = agreed = 0
    by_field = {field: [0, 0] for field in ANNOTATED_FIELDS}
    mismatches = []
    for row in rows:
        computed = game_row(store.events(row["game_id"]))
        for field in ANNOTATED_FIELDS:
            if field not in row:
                continue
            compared += 1
            by_field[field][1] += 1
            if _same(computed[field], row[field]):
                agreed += 1
                by_field[field][0] += 1
            else:
                mismatches.append(
                    {
                        "game_id": row["game_id"],
                        "field": field,
                        "annotated": row[field],
                        "computed": computed[field],
                    }
                )
    return {
        "games": len(rows),
        "fields": compared,
        "agreed": agreed,
        "rate": agreed / compared if compared else None,
        "by_field": {field: {"agreed": a, "of": n} for field, (a, n) in by_field.items()},
        "mismatches": mismatches,
    }
