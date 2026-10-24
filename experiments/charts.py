"""Static charts for the benchmark report (matplotlib, generated from run output)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Same validated categorical order as the dashboard.
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
INK = "#17191c"
MUTED = "#6b7079"
GRID = "#e6e8eb"


def _style(ax: Any, title: str, ylabel: str, xlabel: str = "time (min)") -> None:
    ax.set_title(title, loc="left", fontsize=10, color=INK)
    ax.set_ylabel(ylabel, fontsize=9, color=MUTED)
    ax.set_xlabel(xlabel, fontsize=9, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=MUTED, labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)


def plot_experiment(res: dict[str, Any], folder: Path) -> None:
    examples = res["example_timeseries"]
    threshold = res["config"]["scenario"]["sla"]["latency_threshold_s"]
    labels = list(examples)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4), constrained_layout=True)

    ax = axes[0]
    first = examples[labels[0]]
    minutes = [t / 60 for t in first["t_start"]]
    ax.plot(
        minutes,
        first["arrival_rate_rps"],
        color=MUTED,
        linestyle="--",
        linewidth=1.5,
        label="arrival rate",
    )
    for i, label in enumerate(labels):
        ax.step(
            minutes,
            examples[label]["capacity_rps"],
            where="post",
            color=COLORS[i],
            linewidth=1.8,
            label=label,
        )
    _style(ax, f"{res['name']}: workload vs capacity (seed {res['config']['seeds'][0]})", "req/s")
    ax.set_ylim(bottom=0)
    ax.legend(fontsize=8, frameon=False)

    ax = axes[1]
    for i, label in enumerate(labels):
        p95 = [v if v is not None else float("nan") for v in examples[label]["latency_p95_s"]]
        ax.plot(minutes, p95, color=COLORS[i], linewidth=1.6, label=label)
    ax.axhline(threshold, color=MUTED, linestyle=":", linewidth=1)
    ax.set_yscale("log")
    _style(ax, "P95 latency per minute (log scale)", "seconds")
    ax.legend(fontsize=8, frameon=False)

    ax = axes[2]
    for i, (label, stats) in enumerate(res["summary"].items()):
        if "p95_s" not in stats:
            continue
        ax.errorbar(
            stats["total_cost"]["mean"],
            stats["p95_s"]["mean"],
            xerr=stats["total_cost"]["ci95"],
            yerr=stats["p95_s"]["ci95"],
            fmt="o",
            color=COLORS[i],
            markersize=7,
            capsize=3,
            label=label,
        )
    ax.axhline(threshold, color=MUTED, linestyle=":", linewidth=1)
    ax.set_yscale("log")
    _style(ax, "Cost vs P95 (mean ± 95% CI over seeds)", "P95 latency (s)", "total cost ($)")
    ax.legend(fontsize=8, frameon=False)

    fig.savefig(folder / "overview.png", dpi=110)
    plt.close(fig)
