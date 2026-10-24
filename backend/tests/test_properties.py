"""Property-based tests: invariants that must hold for *any* valid configuration.

Hypothesis generates small random scenarios across every workload pattern and
strategy. The engine runs with ``check_invariants=True``, which re-verifies
server counters, slot capacity, work conservation, queue bounds and replica
bounds after every single event. On top of that, each test checks end-to-end
properties of the request records.
"""

from __future__ import annotations

import numpy as np
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.simulation.config import ClusterConfig, CostConfig, ScenarioConfig, SlaConfig
from app.simulation.engine import SimulationEngine
from app.simulation.entities import RequestState
from app.simulation.runner import compare, run_on_trace
from app.strategies import (
    FixedStrategyConfig,
    PredictiveStrategyConfig,
    ReactiveStrategyConfig,
    StrategyConfig,
    build_strategy,
)
from app.workloads.config import (
    BurstyWorkload,
    PoissonWorkload,
    RampWorkload,
    ServiceTimeConfig,
    SinusoidalWorkload,
    SpikeWorkload,
)
from app.workloads.generators import generate_trace

workloads = st.one_of(
    st.builds(PoissonWorkload, rate=st.floats(0.5, 30)),
    st.builds(
        SinusoidalWorkload,
        base_rate=st.floats(5, 20),
        amplitude=st.floats(0, 5),
        period_s=st.floats(30, 300),
    ),
    st.builds(
        SpikeWorkload,
        base_rate=st.floats(1, 5),
        spike_rate=st.floats(10, 40),
        spike_start_s=st.floats(0, 50),
        spike_duration_s=st.floats(10, 100),
    ),
    st.builds(RampWorkload, start_rate=st.floats(1, 20), end_rate=st.floats(1, 20)),
    st.builds(
        BurstyWorkload,
        base_rate=st.floats(1, 5),
        peak_multiplier=st.floats(2, 6),
        mean_burst_s=st.floats(5, 30),
        mean_gap_s=st.floats(10, 60),
    ),
)


@st.composite
def clusters(draw: st.DrawFn) -> ClusterConfig:
    lo = draw(st.integers(1, 3))
    hi = draw(st.integers(lo, 8))
    return ClusterConfig(
        slots_per_server=draw(st.integers(1, 4)),
        server_speed=draw(st.floats(0.5, 2)),
        min_replicas=lo,
        max_replicas=hi,
        initial_replicas=draw(st.integers(lo, hi)),
        provisioning_delay_s=draw(st.sampled_from([0.0, 5.0, 20.0, 45.0])),
        max_pending=draw(st.sampled_from([0, 5, 50, 10_000])),
    )


@st.composite
def scenarios(draw: st.DrawFn) -> ScenarioConfig:
    return ScenarioConfig(
        duration_s=draw(st.floats(60, 180)),
        seed=draw(st.integers(0, 2**32 - 1)),
        workload=draw(workloads),
        service=ServiceTimeConfig(
            distribution=draw(st.sampled_from(["constant", "exponential", "lognormal"])),
            mean_work=draw(st.floats(0.05, 1.0)),
            cv=draw(st.floats(0.2, 2)),
        ),
        cluster=draw(clusters()),
        sla=SlaConfig(
            latency_threshold_s=draw(st.floats(0.1, 5)), penalty_per_violation=draw(st.floats(0, 1))
        ),
        cost=CostConfig(server_price_per_hour=draw(st.floats(0, 5))),
        control_interval_s=draw(st.sampled_from([5.0, 10.0, 15.0])),
        metrics_interval_s=draw(st.sampled_from([5.0, 10.0, 15.0])),
    )


def strategy_configs(cluster: ClusterConfig) -> st.SearchStrategy[StrategyConfig]:
    return st.one_of(
        st.builds(
            FixedStrategyConfig, replicas=st.integers(cluster.min_replicas, cluster.max_replicas)
        ),
        st.builds(
            ReactiveStrategyConfig,
            scale_up_cooldown_s=st.sampled_from([0.0, 30.0]),
            scale_down_cooldown_s=st.sampled_from([0.0, 60.0]),
            max_step_down=st.integers(1, 3),
        ),
        st.builds(
            PredictiveStrategyConfig,
            warmup_intervals=st.integers(0, 3),
            reactive_floor=st.booleans(),
            scale_down_cooldown_s=st.sampled_from([0.0, 60.0]),
        ),
    )


SETTINGS = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@SETTINGS
@given(data=st.data())
def test_engine_invariants_hold(data: st.DataObject) -> None:
    scenario = data.draw(scenarios())
    strategy_cfg = data.draw(strategy_configs(scenario.cluster))
    trace = generate_trace(scenario.workload, scenario.service, scenario.duration_s, scenario.seed)
    engine = SimulationEngine(
        scenario,
        trace,
        build_strategy(strategy_cfg),
        check_invariants=True,
    )
    run = engine.run()
    cluster = scenario.cluster
    states = run.states

    # Every request has exactly one terminal state.
    assert set(np.unique(states).tolist()) <= {
        RequestState.COMPLETED,
        RequestState.REJECTED,
        RequestState.UNFINISHED,
    }

    # Causality: start >= arrival, completion > start, service = work / speed.
    started = ~np.isnan(run.start_times)
    assert np.all(run.start_times[started] >= run.arrival_times[started])
    done = states == RequestState.COMPLETED
    assert np.all(started[done])
    assert np.all(run.completion_times[done] > run.start_times[done])
    np.testing.assert_allclose(
        run.completion_times[done] - run.start_times[done],
        run.work[done] / cluster.server_speed,
        rtol=1e-9,
        atol=1e-9,
    )
    assert np.all(run.completion_times[done] < scenario.duration_s)
    # Non-completed requests never have a completion time; rejected ones never start.
    assert np.all(np.isnan(run.completion_times[~done]))
    assert not np.any(started[states == RequestState.REJECTED])

    # Replica bounds across every scaling decision.
    for event in run.scaling_events:
        assert cluster.min_replicas <= event.to_replicas <= cluster.max_replicas

    # Concurrency never exceeds the slots of the servers that existed.
    if done.any():
        starts = run.start_times[started]
        ends = np.where(done[started], run.completion_times[started], scenario.duration_s)
        times = np.concatenate([starts, ends])
        deltas = np.concatenate([np.ones(starts.size), -np.ones(ends.size)])
        order = np.lexsort((deltas, times))  # ends (-1) before starts at equal times
        assert np.cumsum(deltas[order]).max() <= cluster.max_replicas * cluster.slots_per_server

    # Server lifecycle consistency.
    for server in run.servers:
        if server.ready_at is not None:
            assert server.ready_at >= server.launched_at
            if not server.initial:
                assert server.ready_at - server.launched_at == cluster.provisioning_delay_s
        if server.terminated_at is not None:
            assert server.terminated_at >= server.launched_at


@SETTINGS
@given(data=st.data())
def test_summary_is_consistent_and_non_negative(data: st.DataObject) -> None:
    scenario = data.draw(scenarios())
    strategy_cfg = data.draw(strategy_configs(scenario.cluster))
    trace = generate_trace(scenario.workload, scenario.service, scenario.duration_s, scenario.seed)
    result = run_on_trace(scenario, strategy_cfg, trace)
    s = result.summary
    assert s.requests_total == s.requests_completed + s.requests_rejected + s.requests_unfinished
    assert s.compute_cost >= 0
    assert s.total_cost >= s.compute_cost
    assert s.server_hours >= 0
    assert s.queue_length_mean >= 0
    assert 0 <= (s.utilisation_mean or 0) <= 1 + 1e-9
    assert scenario.cluster.min_replicas - 1e-9 <= s.replicas_mean
    assert s.replicas_peak <= scenario.cluster.max_replicas
    assert 0 <= s.sla_violations <= s.requests_total
    if s.sla_violation_pct is not None:
        assert 0 <= s.sla_violation_pct <= 100
    if s.latency.p95_s is not None:
        assert s.latency.median_s <= s.latency.p95_s <= s.latency.p99_s <= s.latency.max_s  # type: ignore[operator]
    ts = result.timeseries
    assert sum(ts.arrivals) == s.requests_total
    assert all(c >= 0 for c in ts.cost)


@settings(max_examples=10, deadline=None)
@given(scenario=scenarios())
def test_identical_seeds_give_identical_results(scenario: ScenarioConfig) -> None:
    strategies: list[StrategyConfig] = [
        FixedStrategyConfig(replicas=scenario.cluster.min_replicas),
        ReactiveStrategyConfig(),
        PredictiveStrategyConfig(),
    ]
    a = compare(scenario, strategies)
    b = compare(scenario, strategies)
    strip = {"results": {"__all__": {"runtime"}}}
    assert a.model_dump(exclude=strip) == b.model_dump(exclude=strip)
