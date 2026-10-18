#!/usr/bin/env python3
"""Generate the performance figures used by docs/performance.md.

Run from the repository root:
    uv run --with matplotlib python docs/benchmarks/plot_benchmarks.py

The script reads measurements.json and writes PNG files to docs/images/.
It deliberately keeps the figures descriptive: the data comes from one
AAOS/Tensor G2 device and one generated demo track.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[2]
DATA = json.loads((ROOT / "docs/benchmarks/measurements.json").read_text())
OUT = ROOT / "docs/images"
OUT.mkdir(parents=True, exist_ok=True)

INK = "#1f2933"
MUTED = "#667085"
GRID = "#e4e7ec"
BLUE = "#2563eb"
TEAL = "#0f766e"
AMBER = "#b45309"
RED = "#b42318"
PURPLE = "#6941c6"


def style(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def save(fig: plt.Figure, name: str) -> None:
    path = OUT / name
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"wrote {path.relative_to(ROOT)}")


def payload() -> None:
    demo = DATA["demo"]
    labels = ["MP3", "SpectroStream\n(SST)", "SAGE"]
    sizes = [demo["mp3_bytes"] / 1e6, demo["sst_bytes"] / 1e6, demo["sage_bytes"] / 1e6]
    bitrates = [demo["mp3_bitrate_kbps"], demo["sst_bitrate_kbps"], demo["sage_bitrate_kbps"]]
    colors = [AMBER, BLUE, TEAL]

    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0))
    ax = axes[0]
    bars = ax.barh(labels, sizes, color=colors, height=0.56)
    ax.set_xlabel("compressed payload (MB)", color=MUTED)
    ax.set_title("Demo payload", loc="left", color=INK, fontsize=12, weight="bold")
    ax.set_xlim(0, max(sizes) * 1.22)
    for bar, value, nbytes in zip(bars, sizes, [demo["mp3_bytes"], demo["sst_bytes"], demo["sage_bytes"]]):
        ax.text(bar.get_width() + max(sizes) * 0.025, bar.get_y() + bar.get_height() / 2,
                f"{value:.2f} MB  ({nbytes:,} B)", va="center", color=INK, fontsize=9)
    style(ax)

    ax = axes[1]
    bars = ax.barh(labels, bitrates, color=colors, height=0.56)
    ax.set_xlabel("bitrate (kbit/s)", color=MUTED)
    ax.set_title("Representation bitrate", loc="left", color=INK, fontsize=12, weight="bold")
    ax.set_xlim(0, max(bitrates) * 1.22)
    for bar, value in zip(bars, bitrates):
        ax.text(bar.get_width() + max(bitrates) * 0.025, bar.get_y() + bar.get_height() / 2,
                f"{value:.1f} kbit/s", va="center", color=INK, fontsize=9)
    style(ax)

    fig.suptitle("Same 133.6 s generated demo: 320 kbit/s MP3 vs neural token streams",
                 x=0.01, ha="left", color=INK, fontsize=13, weight="bold")
    fig.text(0.01, 0.01, "Measured from the checked-in demo assets; SST is q64, SAGE is rung-128 int8.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    save(fig, "benchmark-payload.png")


def spectrostream_scaling() -> None:
    rows = DATA["spectrostream"]["thread_scaling_30s"]
    threads = [r["threads"] for r in rows]
    rtf = [r["rtf"] for r in rows]
    cores = DATA["spectrostream"]["core_scaling_30s_t4"]
    core_labels = [r["cores"] for r in cores]
    core_rtf = [r["rtf"] for r in cores]

    fig, axes = plt.subplots(1, 2, figsize=(10.4, 4.0))
    ax = axes[0]
    ax.plot(threads, rtf, marker="o", color=BLUE, linewidth=2.2, markersize=6)
    for x, y in zip(threads, rtf):
        ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(0, 9),
                    ha="center", color=INK, fontsize=8)
    ax.axhline(1.0, color=RED, linewidth=1.1, linestyle="--")
    ax.text(8, 1.04, "realtime", color=RED, fontsize=8, ha="right")
    ax.set_xscale("log", base=2)
    ax.set_xticks(threads)
    ax.get_xaxis().set_major_formatter(FuncFormatter(lambda v, _: f"{int(v)}"))
    ax.set_xlabel("TFLite/XNNPACK worker threads", color=MUTED)
    ax.set_ylabel("RTF (decode time / audio duration)", color=MUTED)
    ax.set_title("Thread scaling, 30 s clip", loc="left", color=INK, fontsize=12, weight="bold")
    ax.set_ylim(0.8, max(rtf) * 1.12)
    style(ax)

    ax = axes[1]
    bars = ax.bar([str(c) for c in core_labels], core_rtf, color=[PURPLE, TEAL, BLUE], width=0.58)
    for bar, value in zip(bars, core_rtf):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04, f"{value:.2f}",
                ha="center", color=INK, fontsize=9)
    ax.set_ylim(0, max(core_rtf) * 1.18)
    ax.set_xlabel("CORES affinity limit (threads fixed at 4)", color=MUTED)
    ax.set_ylabel("RTF", color=MUTED)
    ax.set_title("CPU affinity effect, 30 s clip", loc="left", color=INK, fontsize=12, weight="bold")
    style(ax)

    fig.suptitle("SpectroStream f25 FP32 on Tensor G2: more threads help until CPU saturation",
                 x=0.01, ha="left", color=INK, fontsize=13, weight="bold")
    fig.text(0.01, 0.01, "CLI decode, 6 threads / all cores for the 133.6 s track gives RTF 1.51; 30 s scaling runs are separate.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    save(fig, "benchmark-spectrostream-scaling.png")


def spectrostream_breakdown() -> None:
    row = DATA["spectrostream"]["full_track_cli"]
    parts = [
        ("model load", row["model_load_ms"], MUTED),
        ("SST parse", row["sst_parse_ms"], PURPLE),
        ("RVQ dequant", row["rvq_dequant_ms"], AMBER),
        ("LiteRT/XNNPACK", row["inference_ms"], BLUE),
        ("iSTFT", row["istft_ms"], TEAL),
    ]
    labels = [p[0] for p in parts]
    values = [p[1] for p in parts]
    colors = [p[2] for p in parts]

    fig, ax = plt.subplots(figsize=(10.2, 3.4))
    left = 0.0
    for label, value, color in zip(labels, values, colors):
        ax.barh(["full track"], [value], left=left, color=color, height=0.42, label=label)
        if value > row["total_decode_ms"] * 0.03:
            ax.text(left + value / 2, 0, f"{value/1000:.2f}s", ha="center", va="center",
                    color="white", fontsize=8, weight="bold")
        left += value
    ax.set_xlabel("elapsed time (ms)", color=MUTED)
    ax.set_title("SpectroStream f25: where decode time goes (133.6 s audio, T6/C8)",
                 loc="left", color=INK, fontsize=12, weight="bold")
    ax.legend(ncol=5, frameon=False, loc="lower left", bbox_to_anchor=(0, -0.46), fontsize=8)
    ax.text(row["total_decode_ms"] * 0.995, 0.31, f"RTF {row['rtf']:.2f}", ha="right",
            color=RED, fontsize=9, weight="bold")
    style(ax)
    fig.tight_layout()
    save(fig, "benchmark-spectrostream-breakdown.png")


def sage_figure() -> None:
    rows = DATA["sage"]
    rungs = ["rung 128", "rung 256"]
    one = [rows["rung128"]["single_thread_rtf"], rows["rung256"]["single_thread_rtf"]]
    four = [rows["rung128"]["rtf"], rows["rung256"]["rtf"]]
    first = [rows["rung128"]["first_window_ms"], rows["rung256"]["first_window_ms"]]
    pss = [rows["rung128"]["pss_mb"], rows["rung256"]["pss_mb"]]
    model = [rows["rung128"]["model_bytes"] / 1e6, rows["rung256"]["model_bytes"] / 1e6]

    fig, axes = plt.subplots(2, 2, figsize=(10.4, 6.4))
    x = range(len(rungs))
    width = 0.34

    ax = axes[0][0]
    ax.bar([i - width / 2 for i in x], one, width, label="1 thread", color=PURPLE)
    ax.bar([i + width / 2 for i in x], four, width, label="4 threads", color=TEAL)
    ax.set_xticks(list(x)); ax.set_xticklabels(rungs)
    ax.set_ylabel("RTF", color=MUTED); ax.set_title("End-to-end decode RTF", loc="left", color=INK, fontsize=11, weight="bold")
    ax.legend(frameon=False, fontsize=8)
    ax.set_ylim(0, max(one + four) * 1.2)
    for i, (a, b) in enumerate(zip(one, four)):
        ax.text(i - width / 2, a + 0.02, f"{a:.2f}", ha="center", fontsize=8, color=INK)
        ax.text(i + width / 2, b + 0.02, f"{b:.2f}", ha="center", fontsize=8, color=INK)
    style(ax)

    ax = axes[0][1]
    bars = ax.bar(rungs, first, color=[BLUE, AMBER], width=0.55)
    for bar, value in zip(bars, first):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 60, f"{value:.0f} ms",
                ha="center", fontsize=9, color=INK)
    ax.set_ylabel("first decoded window (ms)", color=MUTED)
    ax.set_title("Time to first audio window", loc="left", color=INK, fontsize=11, weight="bold")
    ax.set_ylim(0, max(first) * 1.2)
    style(ax)

    ax = axes[1][0]
    bars = ax.bar(rungs, pss, color=[TEAL, RED], width=0.55)
    for bar, value in zip(bars, pss):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 25, f"{value} MB",
                ha="center", fontsize=9, color=INK)
    ax.set_ylabel("peak process PSS (MB)", color=MUTED)
    ax.set_title("Memory footprint", loc="left", color=INK, fontsize=11, weight="bold")
    ax.set_ylim(0, max(pss) * 1.18)
    style(ax)

    ax = axes[1][1]
    bars = ax.bar(rungs, model, color=[BLUE, PURPLE], width=0.55)
    for bar, value in zip(bars, model):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, f"{value:.1f} MB",
                ha="center", fontsize=9, color=INK)
    ax.set_ylabel("TFLite model size (MB)", color=MUTED)
    ax.set_title("Model size", loc="left", color=INK, fontsize=11, weight="bold")
    ax.set_ylim(0, max(model) * 1.18)
    style(ax)

    fig.suptitle("SAGE on Tensor G2: rung 128 is the better mobile trade-off",
                 x=0.01, ha="left", color=INK, fontsize=13, weight="bold")
    fig.text(0.01, 0.01, "Standalone SAGE benchmark on a 276 s track; values from docs/benchmarks/sage_android_results.json.",
             color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    save(fig, "benchmark-sage.png")


def memory() -> None:
    labels = [
        "SpectroStream CLI (f25)",
        "Android app, SpectroStream",
        "SAGE rung 128 (standalone)",
        "SAGE rung 256 (standalone)",
        "Android app, SAGE",
    ]
    values = [
        DATA["spectrostream"]["full_track_cli"]["process_pss_kb"] / 1000,
        DATA["app"]["pss_kb"]["spectrostream"] / 1000,
        DATA["sage"]["rung128"]["pss_mb"],
        DATA["sage"]["rung256"]["pss_mb"],
        DATA["app"]["pss_kb"]["sage"] / 1000,
    ]
    colors = [BLUE, BLUE, TEAL, RED, TEAL]
    fig, ax = plt.subplots(figsize=(10.2, 4.2))
    bars = ax.barh(labels, values, color=colors, height=0.6)
    ax.invert_yaxis()
    ax.set_xlabel("PSS (MB)", color=MUTED)
    ax.set_title("Observed process memory on the AAOS head unit",
                 loc="left", color=INK, fontsize=13, weight="bold")
    ax.set_xlim(0, max(values) * 1.18)
    for bar, value in zip(bars, values):
        ax.text(bar.get_width() + 18, bar.get_y() + bar.get_height() / 2, f"{value:.0f} MB",
                va="center", color=INK, fontsize=9)
    ax.text(0.01, 0.02,
            "Debug app retains the SpectroStream asset set during the SAGE run; use standalone/CLI numbers for decoder-only comparisons.",
            transform=ax.transAxes, color=MUTED, fontsize=8)
    style(ax)
    fig.tight_layout()
    save(fig, "benchmark-memory.png")


def startup() -> None:
    rows = DATA["app"]["startup_s"]
    labels = ["SpectroStream", "SAGE"]
    values = [rows["spectrostream"], rows["sage"]]
    fig, ax = plt.subplots(figsize=(6.8, 3.6))
    bars = ax.bar(labels, values, color=[BLUE, TEAL], width=0.5)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.12, f"{value:.2f} s",
                ha="center", color=INK, fontsize=10, weight="bold")
    ax.set_ylabel("time to playback (s)", color=MUTED)
    ax.set_title("App time-to-playback, Typical 6 Mbit/s profile",
                 loc="left", color=INK, fontsize=12, weight="bold")
    ax.set_ylim(0, max(values) * 1.25)
    ax.text(0.01, 0.02,
            "Single run per mode, T6/C8, debug build. MP3 was not captured (player did not reach playback state in this session).",
            transform=ax.transAxes, color=MUTED, fontsize=8)
    style(ax)
    fig.tight_layout()
    save(fig, "benchmark-startup.png")


if __name__ == "__main__":
    payload()
    spectrostream_scaling()
    spectrostream_breakdown()
    sage_figure()
    memory()
    startup()
