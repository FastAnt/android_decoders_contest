#!/usr/bin/env python3
"""Charts for the blind6 music-codec listening-test data.

The checked-in data contains the trial mapping, objective segment metrics, and
one saved single-listener ranking session. The objective charts and the
listening-result charts are generated separately. See docs/blind6-analysis.md.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
DATA_PATH = ROOT / "docs" / "benchmarks" / "blind6_mapping.json"
OUT_DIR = ROOT / "docs" / "images"
SUMMARY_PATH = ROOT / "docs" / "benchmarks" / "blind6_summary.json"
LISTENING_PATH = ROOT / "docs" / "benchmarks" / "blind6_listening_results.json"

CODECS = ["same", "sage", "spectrum"]
LABELS = {"same": "SAME-S", "sage": "SAGE", "spectrum": "SpectroStream"}
COLORS = {"same": "#2A9D5C", "sage": "#3D8BFF", "spectrum": "#D1495B"}
METRICS = {
    "si_sdr_db": ("SI-SDR (dB)", "higher"),
    "waveform_snr_db": ("Waveform SNR (dB)", "higher"),
    "mrstft": ("MR-STFT", "lower"),
    "logmel": ("Log-mel distance", "lower"),
    "icc_out": ("ICC", "higher"),
    "side_mid_db_out": ("Side/mid (dB)", "higher"),
}


def load() -> dict:
    return json.loads(DATA_PATH.read_text())


def load_listening() -> dict:
    return json.loads(LISTENING_PATH.read_text())


def summary(data: dict) -> dict:
    trials = data["trials"]
    out = {"trials": len(trials), "tracks": sorted({t["track"] for t in trials})}
    out["per_codec"] = {}
    for codec in CODECS:
        out["per_codec"][codec] = {}
        for metric in METRICS:
            values = [t["seg_metrics"][codec][metric] for t in trials]
            out["per_codec"][codec][metric] = {
                "mean": round(statistics.mean(values), 4),
                "median": round(statistics.median(values), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
            }
    out["wins"] = {}
    for metric, (_, direction) in METRICS.items():
        counts: Counter[str] = Counter()
        for trial in trials:
            values = {c: trial["seg_metrics"][c][metric] for c in CODECS}
            best = min(values.values()) if direction == "lower" else max(values.values())
            winners = [c for c, value in values.items() if abs(value - best) < 1e-9]
            for codec in winners:
                counts[codec] += 1 / len(winners)
        out["wins"][metric] = {c: round(counts[c], 2) for c in CODECS}
    return out


def style(ax) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x" if ax.get_xlabel() else "y", alpha=0.18)
    ax.set_axisbelow(True)


def plot_overview(data: dict, stats: dict) -> None:
    trials = data["trials"]
    x = [t["id"] for t in trials]

    fig, axes = plt.subplots(2, 2, figsize=(13.2, 9.0), facecolor="white")
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.09, top=0.88, wspace=0.28, hspace=0.34)

    ax = axes[0][0]
    for codec in CODECS:
        values = [t["seg_metrics"][codec]["si_sdr_db"] for t in trials]
        ax.plot(x, values, marker="o", markersize=3.5, linewidth=1.2,
                color=COLORS[codec], alpha=0.85, label=LABELS[codec])
        mean = stats["per_codec"][codec]["si_sdr_db"]["mean"]
        ax.axhline(mean, color=COLORS[codec], linestyle="--", linewidth=1.0, alpha=0.7)
    ax.set_title("SI-SDR per trial (higher is better)", loc="left", fontweight="bold")
    ax.set_xlabel("blind6 trial")
    ax.set_ylabel("dB")
    ax.set_xlim(0, len(trials) + 1)
    ax.legend(frameon=False, fontsize=8, ncol=3)
    style(ax)

    ax = axes[0][1]
    for codec in CODECS:
        values = [t["seg_metrics"][codec]["logmel"] for t in trials]
        ax.plot(x, values, marker="o", markersize=3.5, linewidth=1.2,
                color=COLORS[codec], alpha=0.85, label=LABELS[codec])
        mean = stats["per_codec"][codec]["logmel"]["mean"]
        ax.axhline(mean, color=COLORS[codec], linestyle="--", linewidth=1.0, alpha=0.7)
    ax.set_title("Log-mel distance per trial (lower is better)", loc="left", fontweight="bold")
    ax.set_xlabel("blind6 trial")
    ax.set_ylabel("distance")
    ax.set_xlim(0, len(trials) + 1)
    ax.legend(frameon=False, fontsize=8, ncol=3)
    style(ax)

    ax = axes[1][0]
    metric_order = ["si_sdr_db", "waveform_snr_db", "mrstft", "logmel", "icc_out"]
    y = list(range(len(metric_order)))
    left = [0.0] * len(metric_order)
    for codec in CODECS:
        values = [stats["wins"][m][codec] for m in metric_order]
        bars = ax.barh(y, values, left=left, color=COLORS[codec], height=0.55,
                       label=LABELS[codec])
        for bar, value, base in zip(bars, values, left):
            if value >= 1:
                ax.text(base + value / 2, bar.get_y() + bar.get_height() / 2,
                        f"{value:.0f}", ha="center", va="center", fontsize=8,
                        color="white", fontweight="bold")
        left = [a + b for a, b in zip(left, values)]
    ax.set_yticks(y)
    ax.set_yticklabels([METRICS[m][0].replace(" (dB)", "") for m in metric_order])
    ax.set_xlim(0, len(trials))
    ax.set_xlabel("trials won (of 30)")
    ax.set_title("Objective metric wins per trial", loc="left", fontweight="bold")
    ax.invert_yaxis()
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="lower right")
    style(ax)

    ax = axes[1][1]
    for codec in CODECS:
        xs = [t["seg_metrics"][codec]["si_sdr_db"] for t in trials]
        ys = [t["seg_metrics"][codec]["logmel"] for t in trials]
        ax.scatter(xs, ys, s=18, color=COLORS[codec], alpha=0.45, edgecolors="none")
        ax.scatter([statistics.mean(xs)], [statistics.mean(ys)], s=170,
                   color=COLORS[codec], edgecolors="white", linewidths=1.4,
                   marker="*", zorder=5)
    ax.set_title("Trade-off: waveform vs spectral", loc="left", fontweight="bold")
    ax.set_xlabel("SI-SDR (higher is better) →")
    ax.set_ylabel("log-mel distance (lower is better) ↓")
    style(ax)

    handles = [plt.Line2D([0], [0], color=COLORS[c], lw=3, label=LABELS[c]) for c in CODECS]
    fig.legend(handles=handles, loc="upper right", ncol=3, frameon=False, fontsize=9)
    fig.suptitle("Blind6: objective segment metrics from 30 × 6 s trials",
                 x=0.01, ha="left", fontsize=16, fontweight="bold")
    fig.text(0.01, 0.015,
             "Source: docs/benchmarks/blind6_mapping.json (same_codec blind6 fixtures). "
             "Objective metrics only; the saved single-listener ranking is shown separately. "
             "Stars are means; dashed lines are means.",
             fontsize=8, color="#555555")
    fig.savefig(OUT_DIR / "blind6-overview.png", dpi=160, facecolor="white")
    plt.close(fig)
    print("wrote docs/images/blind6-overview.png")


def plot_distributions(data: dict) -> None:
    trials = data["trials"]
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.4), facecolor="white")
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.16, top=0.86, wspace=0.28)

    for ax, metric, title, better in [
        (axes[0], "si_sdr_db", "SI-SDR (higher is better)", "higher"),
        (axes[1], "logmel", "Log-mel distance (lower is better)", "lower"),
    ]:
        values = [[t["seg_metrics"][c][metric] for t in trials] for c in CODECS]
        box = ax.boxplot(values, patch_artist=True, widths=0.5,
                         medianprops={"color": "#222222", "linewidth": 1.5},
                         whiskerprops={"color": "#555555"},
                         capprops={"color": "#555555"},
                         flierprops={"marker": "o", "markersize": 3,
                                     "markerfacecolor": "#999999",
                                     "markeredgecolor": "none", "alpha": 0.6})
        for patch, codec in zip(box["boxes"], CODECS):
            patch.set_facecolor(COLORS[codec])
            patch.set_alpha(0.35)
            patch.set_edgecolor(COLORS[codec])
        for index, (codec, series) in enumerate(zip(CODECS, values), start=1):
            jitter = [(i % 7 - 3) * 0.018 for i in range(len(series))]
            ax.scatter([index + j for j in jitter], series, s=14,
                       color=COLORS[codec], alpha=0.65, edgecolors="none", zorder=3)
        ax.set_xticks([1, 2, 3])
        ax.set_xticklabels([LABELS[c] for c in CODECS])
        ax.set_title(title, loc="left", fontweight="bold")
        ax.set_ylim(min(min(v) for v in values) * 0.95 if better == "higher" else 0,
                    max(max(v) for v in values) * 1.05)
        ax.grid(axis="y", alpha=0.18)
        ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)

    fig.suptitle("Blind6: objective metric distributions", x=0.01, ha="left",
                 fontsize=16, fontweight="bold")
    fig.text(0.01, 0.02,
             "30 six-second segments; box = IQR, line = median, dots = trials. "
             "No listener votes stored in blind6.",
             fontsize=8, color="#555555")
    fig.savefig(OUT_DIR / "blind6-distributions.png", dpi=160, facecolor="white")
    plt.close(fig)
    print("wrote docs/images/blind6-distributions.png")


def plot_wins(stats: dict) -> None:
    metric_order = ["si_sdr_db", "waveform_snr_db", "mrstft", "logmel", "icc_out"]
    fig, ax = plt.subplots(figsize=(10.8, 5.4), facecolor="white")
    fig.subplots_adjust(left=0.25, right=0.98, bottom=0.16, top=0.86)
    y = list(range(len(metric_order)))
    left = [0.0] * len(metric_order)
    for codec in CODECS:
        values = [stats["wins"][m][codec] for m in metric_order]
        bars = ax.barh(y, values, left=left, color=COLORS[codec], height=0.55,
                       label=LABELS[codec])
        for bar, value, base in zip(bars, values, left):
            if value >= 1:
                ax.text(base + value / 2, bar.get_y() + bar.get_height() / 2,
                        f"{value:.0f}", ha="center", va="center", color="white",
                        fontsize=9, fontweight="bold")
        left = [a + b for a, b in zip(left, values)]
    ax.set_yticks(y)
    ax.set_yticklabels([METRICS[m][0] for m in metric_order])
    ax.invert_yaxis()
    ax.set_xlim(0, 30)
    ax.set_xlabel("trials won (of 30; ties split)")
    ax.set_title("Blind6 objective metric wins", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=3, loc="lower right", fontsize=9)
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.02, 0.03,
             "Direction: SI-SDR/SNR/ICC/side-mid higher is better; MR-STFT/log-mel lower is better. "
             "Objective metrics only; see blind6-listening-results.png for the single-listener result.",
             fontsize=8, color="#555555")
    fig.savefig(OUT_DIR / "blind6-metric-wins.png", dpi=160, facecolor="white")
    plt.close(fig)
    print("wrote docs/images/blind6-metric-wins.png")


def plot_listening(listening: dict) -> None:
    order = ["spectrum", "sage", "same"]
    scores = listening["scores"]
    points = [scores[c]["points"] for c in order]
    first = [scores[c]["first"] for c in order]
    second = [scores[c]["second"] for c in order]
    third = [scores[c]["third"] for c in order]
    names = [LABELS[c] for c in order]

    fig, axes = plt.subplots(1, 2, figsize=(12.8, 6.4), facecolor="white")
    fig.subplots_adjust(left=0.18, right=0.98, bottom=0.16, top=0.84, wspace=0.38)

    ax = axes[0]
    bars = ax.barh(names, points, color=[COLORS[c] for c in order], height=0.55)
    ax.set_xlim(0, 92)
    ax.set_xlabel("listening points (3 / 2 / 1 per trial)")
    ax.set_title("Points: 80 · 77 · 37", loc="left", fontweight="bold")
    for bar, value in zip(bars, points):
        ax.text(value + 1.5, bar.get_y() + bar.get_height() / 2, f"{value}",
                va="center", fontsize=13, fontweight="bold")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)

    ax = axes[1]
    y = list(range(len(order)))
    left = [0.0] * len(order)
    rank_data = [
        ("1st", first, "#222222"),
        ("2nd", second, "#777777"),
        ("3rd", third, "#C9C9C9"),
    ]
    for label, values, color in rank_data:
        bars = ax.barh(y, values, left=left, color=color, height=0.55, label=label,
                       edgecolor="white", linewidth=0.8)
        for bar, value, base in zip(bars, values, left):
            if value:
                ax.text(base + value / 2, bar.get_y() + bar.get_height() / 2,
                        f"{value}", ha="center", va="center", fontsize=9,
                        color="white" if color == "#222222" else "#222222",
                        fontweight="bold")
        left = [a + b for a, b in zip(left, values)]
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.set_xlim(0, 30)
    ax.set_xlabel("trials (first / second / third)")
    ax.set_title("Rank distribution", loc="left", fontweight="bold")
    ax.invert_yaxis()
    ax.legend(frameon=False, ncol=3, loc="lower right", fontsize=9)
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)

    fig.suptitle("Blind6 listening result: SpectroStream 80, SAGE 77, SAME-S 37",
                 x=0.01, ha="left", fontsize=16, fontweight="bold")
    fig.text(0.01, 0.02,
             "One saved listener session, 30 six-second trials, points 3/2/1; ties allowed. "
             "First places are tied at 20/20; SpectroStream wins on second places (10 vs 7). "
             "Single-listener result, not a population study.",
             fontsize=8, color="#555555")
    fig.savefig(OUT_DIR / "blind6-listening-results.png", dpi=160, facecolor="white")
    plt.close(fig)
    print("wrote docs/images/blind6-listening-results.png")


def plot_points_by_track(listening: dict) -> None:
    track_order = ["t027", "t064", "t082", "t116", "umbrella"]
    track_names = {
        "t027": "Folk #27",
        "t064": "Metal #64",
        "t082": "Pop #82",
        "t116": "Hip-Hop #116",
        "umbrella": "Umbrella (pop)",
    }
    order = ["spectrum", "sage", "same"]
    fig, ax = plt.subplots(figsize=(10.8, 5.6), facecolor="white")
    fig.subplots_adjust(left=0.24, right=0.98, bottom=0.16, top=0.84)
    y = list(range(len(track_order)))
    left = [0.0] * len(track_order)
    for codec in order:
        values = [listening["points_by_track"][t][codec] for t in track_order]
        bars = ax.barh(y, values, left=left, color=COLORS[codec], height=0.55,
                       label=LABELS[codec])
        for bar, value, base in zip(bars, values, left):
            if value >= 3:
                ax.text(base + value / 2, bar.get_y() + bar.get_height() / 2,
                        f"{value}", ha="center", va="center", fontsize=8,
                        color="white", fontweight="bold")
        left = [a + b for a, b in zip(left, values)]
    ax.set_yticks(y)
    ax.set_yticklabels([track_names[t] for t in track_order])
    ax.invert_yaxis()
    ax.set_xlim(0, 54)
    ax.set_xlabel("listening points across 6 trials (max 18 per codec)")
    ax.set_title("Listening points by track", loc="left", fontweight="bold")
    ax.legend(frameon=False, ncol=3, loc="lower right", fontsize=9)
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.02, 0.03,
             "Each track contributes 6 trials; points 3/2/1 with ties allowed. "
             "SpectroStream leads two tracks, SAGE leads two, Pop #82 is tied.",
             fontsize=8, color="#555555")
    fig.savefig(OUT_DIR / "blind6-points-by-track.png", dpi=160, facecolor="white")
    plt.close(fig)
    print("wrote docs/images/blind6-points-by-track.png")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load()
    listening = load_listening()
    stats = summary(data)
    SUMMARY_PATH.write_text(json.dumps(stats, indent=2) + "\n")
    plot_overview(data, stats)
    plot_distributions(data)
    plot_wins(stats)
    plot_listening(listening)
    plot_points_by_track(listening)
    print(f"wrote {SUMMARY_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
