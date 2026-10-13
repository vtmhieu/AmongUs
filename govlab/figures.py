"""The five planned figures (research plan, Table 2), drawn for the written report.

F1  good-team win rate by condition, 95% Wilson intervals
F2  damage absorbed by condition (distribution of kills per game)
F3  cumulative damage against game time
F4  wrongful-removal rate by condition, 95% Wilson intervals
F5  Kaplan-Meier detection curves

All five are drawn from charts.chart_data(), the same data the web UI renders.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from govlab.charts import KILL_BINS, KILL_COLOURS, LABELS, THRESHOLD_COLOURS  # noqa: E402

INK, SECONDARY, MUTED, GRID, AXIS = "#141413", "#52514e", "#898781", "#e8e6dc", "#c3c2b7"
COLOURS = THRESHOLD_COLOURS["light"]

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.size": 9,
        "axes.edgecolor": AXIS,
        "axes.labelcolor": SECONDARY,
        "axes.titlesize": 10,
        "axes.titleweight": "bold",
        "axes.titlelocation": "left",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "axes.axisbelow": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelcolor": SECONDARY,
        "ytick.labelcolor": SECONDARY,
        "ytick.left": False,
        "legend.frameon": False,
        "figure.dpi": 110,
        "savefig.dpi": 220,
        "savefig.bbox": "tight",
    }
)


def _save(fig, out: Path, name: str) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("png", "pdf"):
        path = out / f"{name}.{ext}"
        fig.savefig(path)
        paths.append(path.name)
    plt.close(fig)
    return paths


def _legend(ax, thresholds: list[str]) -> None:
    if len(thresholds) < 2:  # one series is named by the title; a legend would repeat it
        return
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLOURS[t]) for t in thresholds]
    ax.legend(handles, [LABELS[t] for t in thresholds], loc="upper right", ncols=len(thresholds), bbox_to_anchor=(1, 1.16))


def _rate_bars(data: dict, measure: str, title: str, ylabel: str):
    thresholds, groups = data["thresholds"], data["groups"]
    fig, ax = plt.subplots(figsize=(max(3.6, 1.5 * len(groups) * len(thresholds) * 0.62 + 1.4), 3.2))
    width = 0.17
    for gi, group in enumerate(groups):
        for ti, threshold in enumerate(thresholds):
            cell = data["cells"].get(f"{threshold}|{group['key']}")
            if cell is None or cell[measure]["p"] is None:
                continue
            p = cell[measure]
            x = gi + (ti - (len(thresholds) - 1) / 2) * (width + 0.07)
            ax.bar(x, p["p"], width=width, color=COLOURS[threshold], linewidth=0)
            ax.plot([x, x], [p["low"], p["high"]], color=INK, linewidth=1.1, solid_capstyle="butt")
            ax.text(x, min(p["high"] + 0.035, 1.07), f"{p['p']:.0%}", ha="center", va="bottom", color=INK, fontsize=8.5)
            ax.text(x, -0.045, f"n={p['n']}", ha="center", va="top", color=MUTED, fontsize=7)
    ax.set_xticks(range(len(groups)), [g["label"] for g in groups])
    ax.tick_params(axis="x", length=0, pad=14)
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_ylabel(ylabel)
    ax.set_title(title, pad=22)
    ax.axhline(0, color=AXIS, linewidth=0.8)
    _legend(ax, thresholds)
    return fig


def _panels(data: dict, title: str, height: float = 3.0):
    groups = data["groups"]
    fig, axes = plt.subplots(1, len(groups), figsize=(3.4 * len(groups) + 0.6, height), sharey=True, squeeze=False)
    fig.suptitle(title, x=0.02, ha="left", fontsize=10, fontweight="bold", y=1.04)
    return fig, axes[0]


def _end_labels(ax, ends: list[tuple[float, float, str]], min_gap: float) -> None:
    """Value labels at line ends, moved apart just enough not to overprint each other."""
    placed: list[float] = []
    for x, y, text in sorted(ends, key=lambda e: e[1]):
        if placed and y - placed[-1] < min_gap:
            y = placed[-1] + min_gap
        placed.append(y)
        ax.text(x, y, text, va="center", fontsize=8, color=INK)


def _line(ax, xs, ys, colour, step: bool = False) -> None:
    """A 2px series line over a casing in the surface colour, so crossings stay legible."""
    draw = (lambda *a, **k: ax.step(*a, where="post", **k)) if step else ax.plot
    draw(xs, ys, color="white", linewidth=4, solid_capstyle="round")
    draw(xs, ys, color=colour, linewidth=2, solid_capstyle="round")


def _line_legend(fig, thresholds: list[str]) -> None:
    if len(thresholds) < 2:
        return
    handles = [plt.Line2D([0], [0], color=COLOURS[t], linewidth=2) for t in thresholds]
    fig.legend(handles, [LABELS[t] for t in thresholds], loc="upper right", ncols=len(thresholds), bbox_to_anchor=(0.99, 1.07))


def win_rate(data: dict):
    return _rate_bars(data, "win", "Good-team win rate by condition", "Games won by the crew")


def wrongful_removal(data: dict):
    return _rate_bars(data, "wrongful", "Wrongful-removal rate by condition", "Games with a good agent ejected")


def damage(data: dict):
    cells = list(data["cells"].values())
    fig, ax = plt.subplots(figsize=(6.4, 0.5 * len(cells) + 1.5))
    ax.grid(False)
    colours = KILL_COLOURS["light"]
    for row, cell in enumerate(cells):
        left = 0.0
        for i, bin_label in enumerate(KILL_BINS):
            share = cell["kills"][bin_label] / cell["n"]
            if share == 0:
                continue
            ax.barh(row, share, left=left, height=0.5, color=colours[i], edgecolor="white", linewidth=1.5)
            if share >= 0.09:  # a label only where it fits inside its segment
                ax.text(left + share / 2, row, f"{share:.0%}", ha="center", va="center", fontsize=7.5, color="white" if i >= 2 else INK)
            left += share
        ax.text(1.02, row, f"mean {cell['kills_mean']:.2f}", va="center", ha="left", color=SECONDARY, fontsize=8)
    ax.set_yticks(range(len(cells)), [c["label"] for c in cells])
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_xlabel("Share of games")
    ax.tick_params(axis="y", length=0)
    ax.spines["bottom"].set_visible(False)
    ax.set_title("Damage absorbed: kills by the insider per game", pad=26)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colours]
    ax.legend(handles, [f"{b} kills" if b != "1" else "1 kill" for b in KILL_BINS], loc="lower left", ncols=4, bbox_to_anchor=(0, 1.0), columnspacing=1.2, handlelength=1.2)
    return fig


def cumulative_damage(data: dict):
    fig, axes = _panels(data, "Cumulative damage against game time")
    top = max((p["mean"] for c in data["cells"].values() for p in c["cumulative"]), default=1) or 1
    for ax, group in zip(axes, data["groups"]):
        ends = []
        for threshold in data["thresholds"]:
            cell = data["cells"].get(f"{threshold}|{group['key']}")
            if cell is None:
                continue
            xs = [p["t"] for p in cell["cumulative"]]
            ys = [p["mean"] for p in cell["cumulative"]]
            _line(ax, xs, ys, COLOURS[threshold])
            ends.append((xs[-1] + 0.5, ys[-1], f"{ys[-1]:.2f}"))
        _end_labels(ax, ends, min_gap=0.075 * top)
        ax.set_title(group["label"], fontweight="normal", color=SECONDARY)
        ax.set_xlabel("Timestep")
        ax.set_xlim(0, data["max_timestep"] * 1.12)
        ax.set_ylim(0, top * 1.12)
    axes[0].set_ylabel("Mean kills per game so far")
    _line_legend(fig, data["thresholds"])
    return fig


def detection(data: dict):
    fig, axes = _panels(data, "Detection: share of games with the insider not yet ejected")
    horizon = max(data["max_meetings"], 1)
    for ax, group in zip(axes, data["groups"]):
        ends = []
        for threshold in data["thresholds"]:
            cell = data["cells"].get(f"{threshold}|{group['key']}")
            if cell is None:
                continue
            xs = [p["t"] for p in cell["survival"]] + [max(cell["meetings_max"], 1)]
            ys = [p["s"] for p in cell["survival"]] + [cell["survival"][-1]["s"]]
            _line(ax, xs, ys, COLOURS[threshold], step=True)
            ends.append((xs[-1] + 0.07, ys[-1], f"{ys[-1]:.0%}"))
        _end_labels(ax, ends, min_gap=0.08)
        ax.set_title(group["label"], fontweight="normal", color=SECONDARY)
        ax.set_xlabel("Meetings held")
        ax.set_xticks(range(horizon + 1))
        ax.set_xlim(0, horizon + 0.45)
        ax.set_ylim(0, 1.04)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    axes[0].set_ylabel("Insider still in the game")
    _line_legend(fig, data["thresholds"])
    return fig


FIGURES = {
    "F1_win_rate": win_rate,
    "F2_damage": damage,
    "F3_cumulative_damage": cumulative_damage,
    "F4_wrongful_removal": wrongful_removal,
    "F5_detection": detection,
}


def draw_all(data: dict, out: Path) -> dict[str, list[str]]:
    """Draw every figure into out as PNG and PDF. Returns {figure: [file names]}."""
    if not data or not data.get("cells"):
        return {}
    return {name: _save(draw(data), out, name) for name, draw in FIGURES.items()}
