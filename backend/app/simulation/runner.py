"""Runs strategies against a scenario and builds result documents."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from app.metrics.compute import latency_histogram, scaling_events, summarise, timeseries
from app.metrics.models import Histogram, ScalingEventModel, SummaryMetrics, TimeSeries
from app.simulation.config import ScenarioConfig
from app.simulation.engine import SimulationEngine
from app.strategies import FixedStrategyConfig, StrategyConfig, build_strategy
from app.workloads.generators import WorkloadTrace, expected_arrivals, generate_trace, peak_rate

#: Bump on any backwards-incompatible change to the result document.
RESULT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class RunLimits:
    """Guards against configurations that would exhaust CPU or memory."""

    max_expected_requests: int = 1_000_000
    max_total_expected_requests: int = 2_500_000
    max_peak_rate_rps: float = 5_000.0
    wall_time_budget_s: float | None = 30.0


DEFAULT_LIMITS = RunLimits()


class SimulationLimitError(ValueError):
    """The configuration is valid but too expensive to simulate under the limits."""


class RuntimeInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    wall_time_ms: float
    events_processed: int


class StrategyInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str
    config: StrategyConfig


class SimulationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(RESULT_SCHEMA_VERSION)
    strategy: StrategyInfo
    summary: SummaryMetrics
    timeseries: TimeSeries
    scaling_events: list[ScalingEventModel]
    latency_histogram: Histogram
    runtime: RuntimeInfo


class ComparisonResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(RESULT_SCHEMA_VERSION)
    scenario: ScenarioConfig
    requests_generated: int
    results: list[SimulationResult]


def strategy_label(config: StrategyConfig) -> str:
    if config.label:
        return config.label
    if isinstance(config, FixedStrategyConfig):
        return f"fixed ({config.replicas})"
    return config.type


def validate_combination(scenario: ScenarioConfig, strategy: StrategyConfig) -> None:
    cluster = scenario.cluster
    if isinstance(strategy, FixedStrategyConfig) and not (
        cluster.min_replicas <= strategy.replicas <= cluster.max_replicas
    ):
        raise ValueError(
            f"fixed strategy replicas ({strategy.replicas}) must lie within "
            f"[min_replicas, max_replicas] = [{cluster.min_replicas}, {cluster.max_replicas}]"
        )


def check_limits(scenario: ScenarioConfig, n_strategies: int, limits: RunLimits) -> float:
    """Reject expensive configurations *before* generating the trace."""
    expected = expected_arrivals(scenario.workload, scenario.duration_s)
    if peak_rate(scenario.workload) > limits.max_peak_rate_rps:
        raise SimulationLimitError(
            f"peak arrival rate exceeds {limits.max_peak_rate_rps:g} requests/s"
        )
    if expected > limits.max_expected_requests:
        raise SimulationLimitError(
            f"expected {expected:,.0f} requests per run; the limit is "
            f"{limits.max_expected_requests:,}. Reduce duration_s or the arrival rate."
        )
    if expected * n_strategies > limits.max_total_expected_requests:
        raise SimulationLimitError(
            f"comparison would simulate ~{expected * n_strategies:,.0f} requests in total; "
            f"the limit is {limits.max_total_expected_requests:,}. Compare fewer strategies "
            "or shorten the scenario."
        )
    return expected


def run_on_trace(
    scenario: ScenarioConfig,
    strategy_config: StrategyConfig,
    trace: WorkloadTrace,
    *,
    limits: RunLimits = DEFAULT_LIMITS,
    check_invariants: bool = False,
) -> SimulationResult:
    validate_combination(scenario, strategy_config)
    engine = SimulationEngine(
        scenario,
        trace,
        build_strategy(strategy_config),
        wall_time_budget_s=limits.wall_time_budget_s,
        check_invariants=check_invariants,
    )
    raw = engine.run()
    return SimulationResult(
        strategy=StrategyInfo(label=strategy_label(strategy_config), config=strategy_config),
        summary=summarise(raw, scenario),
        timeseries=timeseries(raw, scenario),
        scaling_events=scaling_events(raw),
        latency_histogram=latency_histogram(raw),
        runtime=RuntimeInfo(
            wall_time_ms=round(raw.wall_time_s * 1000, 3), events_processed=raw.events_processed
        ),
    )


def compare(
    scenario: ScenarioConfig,
    strategies: list[StrategyConfig],
    *,
    limits: RunLimits = DEFAULT_LIMITS,
    check_invariants: bool = False,
) -> ComparisonResult:
    """Run every strategy against one shared, seeded trace."""
    for strategy in strategies:
        validate_combination(scenario, strategy)
    check_limits(scenario, len(strategies), limits)
    trace = generate_trace(scenario.workload, scenario.service, scenario.duration_s, scenario.seed)
    results = [
        run_on_trace(scenario, s, trace, limits=limits, check_invariants=check_invariants)
        for s in strategies
    ]
    return ComparisonResult(scenario=scenario, requests_generated=trace.size, results=results)


def run_simulation(
    scenario: ScenarioConfig,
    strategy: StrategyConfig,
    *,
    limits: RunLimits = DEFAULT_LIMITS,
    check_invariants: bool = False,
) -> SimulationResult:
    return compare(scenario, [strategy], limits=limits, check_invariants=check_invariants).results[
        0
    ]
