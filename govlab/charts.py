"""The data behind the five planned figures, in one shape for both renderers.

The written report draws them with matplotlib (figures.py); the web UI draws the same
data as SVG. Keeping one source means the two can never disagree.

Encoding. Colour carries the vote threshold and nothing else: at most three hues, which
is as many as stay distinguishable for colour-blind readers when every pair is compared.
The other factors (discussion protocol, ballot) are positions: bar groups in F1 and F4,
panels in F3 and F5. Kill counts take the values 0-3, so F2 shows their whole
distribution as an ordered stacked bar rather than a violin fitted to four values.

Palette validated with the dataviz skill's validate_palette.js against the UI's card
surfaces (#FAF9F5 light, #262624 dark).
"""

from __future__ import annotations

import pandas as pd

from amongagents.envs.governance import BALLOTS, PROTOCOLS, THRESHOLDS
from govlab.stats import kaplan_meier, proportion

THRESHOLD_COLOURS = {
    "light": {"plurality": "#2a78d6", "majority": "#eb6834", "supermajority": "#1baf7a"},
    "dark": {"plurality": "#3987e5", "majority": "#d95926", "supermajority": "#199e70"},
}
# 0, 1, 2 and 3-or-more kills: one hue, ordered so that "more" stands out from the surface
KILL_BINS = ["0", "1", "2", "3+"]
KILL_COLOURS = {
    "light": ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"],
    "dark": ["#1c5cab", "#3987e5", "#86b6ef", "#cde2fb"],
}

LABELS = {
    "plurality": "Plurality",
    "majority": "Majority",
    "supermajority": "Supermajority",
    "freeform": "Free-form",
    "justification": "Justification",
    "public": "Public ballot",
    "secret": "Secret ballot",
}


def condition_label(threshold: str, protocol: str, ballot: str, ballots_vary: bool) -> str:
    label = f"{LABELS[threshold]} · {LABELS[protocol]}"
    return f"{label} · {LABELS[ballot]}" if ballots_vary else label


def chart_data(games: pd.DataFrame, actions: pd.DataFrame) -> dict:
    if len(games) == 0:
        return {}
    thresholds = [t for t in THRESHOLDS if t in set(games["threshold"])]
    ballots_vary = games["ballot"].nunique() > 1
    groups = []
    for ballot in BALLOTS:
        for protocol in PROTOCOLS:
            cell = games[(games["protocol"] == protocol) & (games["ballot"] == ballot)]
            if len(cell):
                label = LABELS[protocol] + (f" · {LABELS[ballot]}" if ballots_vary else "")
                groups.append({"key": f"{protocol}/{ballot}", "protocol": protocol, "ballot": ballot, "label": label})

    max_timestep = int(games["timesteps"].max())
    kills = actions[actions["action"] == "KILL"] if len(actions) else actions
    cells = {}
    for group in groups:
        for threshold in thresholds:
            cell = games[
                (games["threshold"] == threshold)
                & (games["protocol"] == group["protocol"])
                & (games["ballot"] == group["ballot"])
            ]
            if len(cell) == 0:
                continue
            n = len(cell)
            binned = cell["kills"].clip(upper=3).value_counts()
            # mean kills so far per game at each timestep; a finished game keeps its total
            kill_steps = kills[kills["game_id"].isin(cell["game_id"])]["timestep"] if len(kills) else []
            cumulative = [
                {"t": t, "mean": float(sum(1 for step in kill_steps if step < t) / n)}
                for t in range(max_timestep + 1)
            ]
            cells[f"{threshold}|{group['key']}"] = {
                "condition": cell.iloc[0]["condition"],
                "threshold": threshold,
                "group": group["key"],
                "label": condition_label(threshold, group["protocol"], group["ballot"], ballots_vary),
                "n": n,
                "win": proportion(int(cell["crew_win"].sum()), n),
                "wrongful": proportion(int(cell["wrongful_any"].sum()), n),
                "kills": {b: int(binned.get(i, 0)) for i, b in enumerate(KILL_BINS)},
                "kills_mean": float(cell["kills"].mean()),
                "cumulative": cumulative,
                "survival": kaplan_meier(cell["time"], cell["event"]),
                "meetings_max": int(cell["time"].max()),
            }
    return {
        "thresholds": thresholds,
        "groups": groups,
        "cells": cells,
        "max_timestep": max_timestep,
        "max_meetings": int(games["time"].max()),
        "labels": LABELS,
        "colours": {"threshold": THRESHOLD_COLOURS, "kills": KILL_COLOURS},
        "kill_bins": KILL_BINS,
    }
