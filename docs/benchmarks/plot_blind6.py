#!/usr/bin/env python3
"""Charts for the blind6 music-codec listening-test fixtures.

The blind6 directory contains the trial mapping and objective segment metrics.
It does not contain saved listener rankings, so these charts describe objective
quality, not human preference. See docs/blind6-analysis.md.
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
             "No saved listener votes were present; this is objective quality, not human preference. "
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
             "Objective only; no human votes in blind6.",
             fontsize=8, color="#555555")
    fig.savefig(OUT_DIR / "blind6-metric-wins.png", dpi=160, facecolor="white")
    plt.close(fig)
    print("wrote docs/images/blind6-metric-wins.png")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = load()
    stats = summary(data)
    SUMMARY_PATH.write_text(json.dumps(stats, indent=2) + "\n")
    plot_overview(data, stats)
    plot_distributions(data)
    plot_wins(stats)
    print(f"wrote {SUMMARY_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
