"""Run the benchmark suite and write configs, raw per-seed results, aggregates and charts.

python experiments/run.py            # full suite (5 seeds, ~5 minutes)
python experiments/run.py --quick    # short scenarios, 2 seeds
python experiments/run.py --check    # quick suite, verify it reproduces exactly
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.simulation.runner import RunLimits, SimulationResult, compare
from experiments.charts import plot_experiment
from experiments.suite import EXPERIMENTS, QUICK, SEEDS, Experiment

ROOT = Path(__file__).resolve().parent
UNLIMITED = RunLimits(
    max_expected_requests=10**9, max_total_expected_requests=10**9, wall_time_budget_s=None
)

METRICS: dict[str, str] = {
    "p95_s": "P95 latency (s)",
    "p99_s": "P99 latency (s)",
    "mean_latency_s": "Mean latency (s)",
    "p95_lower_bound_s": "P95 incl. backlog (s)",
    "sla_violation_pct": "SLA violations (%)",
    "total_cost": "Cost ($)",
    "utilisation": "Utilisation",
    "replicas_mean": "Mean replicas",
    "throughput_rps": "Throughput (req/s)",
    "queue_peak": "Peak queue",
    "unfinished": "Unfinished",
    "scale_events": "Scale events",
}

# Two-sided 95% Student-t critical values by degrees of freedom.
T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}


def metrics_row(result: SimulationResult) -> dict[str, float | None]:
    s = result.summary
    return {
        "p95_s": s.latency.p95_s,
        "p99_s": s.latency.p99_s,
        "mean_latency_s": s.latency.mean_s,
        "p95_lower_bound_s": s.latency_p95_lower_bound_s,
        "sla_violation_pct": s.sla_violation_pct,
        "total_cost": s.total_cost,
        "utilisation": s.utilisation_mean,
        "replicas_mean": s.replicas_mean,
        "throughput_rps": s.throughput_rps,
        "queue_peak": s.queue_length_peak,
        "unfinished": s.requests_unfinished,
        "scale_events": s.scale_up_events + s.scale_down_events,
    }


def aggregate(values: list[float]) -> dict[str, float]:
    n = len(values)
    mean = statistics.fmean(values)
    std = statistics.stdev(values) if n > 1 else 0.0
    half = T95.get(n - 1, 1.96) * std / math.sqrt(n) if n > 1 else 0.0
    return {"mean": mean, "std": std, "ci95": half, "min": min(values), "max": max(values)}


def run_experiment(exp: Experiment, seeds: list[int]) -> dict[str, Any]:
    strategies = exp.strategies()
    runs: list[dict[str, Any]] = []
    examples: dict[str, Any] = {}
    for seed in seeds:
        comparison = compare(exp.scenario(seed), strategies, limits=UNLIMITED)
        for result in comparison.results:
            runs.append(
                {
                    "seed": seed,
                    "strategy": result.strategy.label,
                    "requests": comparison.requests_generated,
                }
                | metrics_row(result)
            )
        if seed == seeds[0]:
            examples = {r.strategy.label: r.timeseries.model_dump() for r in comparison.results}

    summary: dict[str, dict[str, dict[str, float]]] = {}
    for strategy in [s.label or s.type for s in strategies]:
        rows = [r for r in runs if r["strategy"] == strategy]
        summary[strategy] = {
            m: aggregate([r[m] for r in rows if r[m] is not None])
            for m in METRICS
            if any(r[m] is not None for r in rows)
        }
    return {
        "name": exp.name,
        "description": exp.description,
        "config": {
            "scenario": exp.scenario(seeds[0]).model_dump(mode="json"),
            "seeds": seeds,
            "strategies": [s.model_dump(mode="json") for s in strategies],
        },
        "runs": runs,
        "summary": summary,
        "example_timeseries": examples,
    }


def write_lf(path: Path, text: str) -> None:
    """Write with LF endings on every OS, so a Windows run doesn't dirty the committed files."""
    path.write_text(text, encoding="utf-8", newline="\n")


def write_outputs(results: list[dict[str, Any]], out: Path, charts: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for res in results:
        folder = out / res["name"]
        folder.mkdir(exist_ok=True)
        write_lf(folder / "config.json", json.dumps(res["config"], indent=2) + "\n")
        with (folder / "runs.csv").open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(res["runs"][0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(res["runs"])
        write_lf(folder / "summary.json", json.dumps(res["summary"], indent=2) + "\n")
        if charts:
            plot_experiment(res, folder)
    combined = {r["name"]: r["summary"] for r in results}
    write_lf(out / "summary.json", json.dumps(combined, indent=2, sort_keys=True) + "\n")
    write_lf(out / "REPORT.md", render_report(results))


def fmt(stat: dict[str, float] | None, digits: int = 3) -> str:
    if stat is None:
        return "—"
    return f"{stat['mean']:.{digits}f} ± {stat['ci95']:.{digits}f}"


def render_report(results: list[dict[str, Any]]) -> str:
    lines = [
        "# Benchmark results",
        "",
        "Generated by `python experiments/run.py`. Values are mean ± 95% confidence half-width",
        "(Student t) across seeds. Each seed generates one trace shared by every strategy.",
        "",
    ]
    columns = [
        ("p95_s", 3),
        ("p95_lower_bound_s", 2),
        ("sla_violation_pct", 2),
        ("total_cost", 3),
        ("utilisation", 3),
        ("replicas_mean", 2),
        ("unfinished", 0),
        ("scale_events", 1),
    ]
    for res in results:
        seeds = res["config"]["seeds"]
        lines += [f"## {res['name']}", "", res["description"], f"Seeds: {seeds}.", ""]
        lines.append("| Strategy | " + " | ".join(METRICS[c] for c, _ in columns) + " |")
        lines.append("|---|" + "---|" * len(columns))
        for strategy, stats in res["summary"].items():
            cells = [fmt(stats.get(c), d) for c, d in columns]
            lines.append(f"| {strategy} | " + " | ".join(cells) + " |")
        lines.append("")
        lines += [f"![{res['name']}]({res['name']}/overview.png)", ""]
    return "\n".join(lines)


def digest(results: list[dict[str, Any]]) -> str:
    """Hash of the per-seed metrics, rounded to 9 significant digits."""

    def round_sig(v: Any) -> Any:
        return float(f"{v:.9g}") if isinstance(v, float) else v

    payload = [[{k: round_sig(v) for k, v in run.items()} for run in r["runs"]] for r in results]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--quick", action="store_true", help="short scenarios, 2 seeds")
    parser.add_argument("--check", action="store_true", help="verify the quick suite reproduces")
    parser.add_argument("--no-charts", action="store_true")
    args = parser.parse_args()

    quick = args.quick or args.check
    experiments = QUICK if quick else EXPERIMENTS
    seeds = SEEDS[:2] if quick else SEEDS
    out = ROOT / ("results-quick" if quick else "results")

    started = time.perf_counter()
    results = [run_experiment(e, seeds) for e in experiments]
    print(
        f"simulated {len(experiments)} experiments x {len(seeds)} seeds "
        f"in {time.perf_counter() - started:.1f}s"
    )
    current = digest(results)

    if args.check:
        again = digest([run_experiment(e, seeds) for e in experiments])
        if again != current:
            print("FAIL: two runs in the same process produced different results")
            return 1
        expected_file = out / "digest.txt"
        if expected_file.exists():
            expected = expected_file.read_text(encoding="utf-8").strip()
            if expected != current:
                print(f"FAIL: digest {current} does not match committed {expected}")
                return 1
            print(f"OK: results match committed digest {expected[:12]}")
        else:
            print("OK: deterministic (no committed digest to compare against)")
        return 0

    write_outputs(results, out, charts=not args.no_charts)
    write_lf(out / "digest.txt", current + "\n")
    print(f"wrote {out} (digest {current[:12]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
