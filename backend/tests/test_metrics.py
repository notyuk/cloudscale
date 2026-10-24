from __future__ import annotations

import numpy as np
import pytest

from app.metrics.compute import latency_histogram, summarise, timeseries
from app.simulation.config import CostConfig, ScenarioConfig, SlaConfig
from tests.conftest import ScriptedStrategy, make_scenario, run_engine


def with_sla(
    scenario: ScenarioConfig, threshold: float, penalty: float = 0.0, price: float = 0.0
) -> ScenarioConfig:
    return scenario.model_copy(
        update={
            "sla": SlaConfig(latency_threshold_s=threshold, penalty_per_violation=penalty),
            "cost": CostConfig(server_price_per_hour=price),
        }
    )


def test_latency_percentiles_and_throughput() -> None:
    scenario = make_scenario(duration_s=100.0, initial_replicas=4)
    work = [1.0, 2.0, 3.0, 4.0]
    run = run_engine(scenario, [0.0, 10.0, 20.0, 30.0], work)
    s = summarise(run, scenario)
    assert s.requests_completed == 4
    assert s.latency.mean_s == pytest.approx(2.5)
    assert s.latency.median_s == pytest.approx(2.5)
    assert s.latency.p95_s == pytest.approx(np.percentile(work, 95))
    assert s.latency.max_s == 4.0
    assert s.throughput_rps == pytest.approx(0.04)


def test_cost_is_server_hours_times_price() -> None:
    scenario = with_sla(
        make_scenario(duration_s=3_600.0, initial_replicas=2, max_replicas=4), 1.0, price=0.5
    )
    s = summarise(run_engine(scenario, [], []), scenario)
    assert s.server_hours == pytest.approx(2.0)
    assert s.compute_cost == pytest.approx(1.0)
    assert s.cost_per_completed_request is None


def test_sla_counts_completed_unfinished_and_rejected() -> None:
    scenario = with_sla(make_scenario(duration_s=10.0, max_pending=1), 1.5, penalty=2.0)
    # r0: latency 1 (ok); r1 queued behind r0, latency 2 (violation); r2 rejected;
    # r3 arrives at 9.8 and is in service at the end (age 0.2: undetermined).
    run = run_engine(scenario, [0.0, 0.0, 0.0, 9.8], [1.0, 1.0, 1.0, 5.0])
    s = summarise(run, scenario)
    assert s.requests_rejected == 1
    assert s.requests_unfinished == 1
    assert s.sla_violations == 2
    assert s.sla_undetermined == 1
    assert s.sla_violation_pct == pytest.approx(100 * 2 / 3)
    assert s.sla_penalty_cost == 4.0
    assert s.total_cost == s.compute_cost + 4.0


def test_backlog_is_visible_in_lower_bound_percentiles() -> None:
    # One slot, 20 long jobs: few complete, the backlog's age must surface.
    scenario = make_scenario(duration_s=100.0)
    run = run_engine(scenario, [0.0] * 20, [30.0] * 20)
    s = summarise(run, scenario)
    assert s.requests_completed == 3
    assert s.requests_unfinished == 17
    assert s.requests_unfinished_in_service == 1
    assert s.latency_p95_lower_bound_s == pytest.approx(100.0)
    assert s.max_wait_s == pytest.approx(100.0)  # still waiting at the end


def test_zero_requests_produce_nulls_not_nan() -> None:
    scenario = make_scenario(duration_s=50.0)
    s = summarise(run_engine(scenario, [], []), scenario)
    assert s.requests_total == 0
    assert s.latency.mean_s is None
    assert s.latency.p99_s is None
    assert s.sla_violation_pct is None
    assert s.mean_wait_s is None
    assert s.utilisation_mean == 0.0
    assert latency_histogram(run_engine(scenario, [], [])).counts == []


def test_zero_completions() -> None:
    scenario = make_scenario(duration_s=10.0)
    s = summarise(run_engine(scenario, [1.0], [100.0]), scenario)
    assert s.requests_completed == 0
    assert s.latency.median_s is None
    assert s.cost_per_completed_request is None
    assert s.latency_p95_lower_bound_s == pytest.approx(9.0)


def test_time_weighted_means_use_elapsed_time() -> None:
    # Many events in a short interval must not dominate the average.
    scenario = make_scenario(duration_s=100.0)
    arrivals = [0.0] * 2 + list(np.linspace(50, 50.5, 50))
    run = run_engine(scenario, arrivals, [1.0] * 2 + [0.001] * 50)
    s = summarise(run, scenario)
    # Queue holds 1 request during [0, 1) and nothing else of note.
    assert s.queue_length_mean == pytest.approx(0.01, abs=1e-3)
    assert s.utilisation_mean == pytest.approx((2 + 0.05) / 100, rel=1e-6)


def test_replica_mean_and_peak() -> None:
    scenario = make_scenario(duration_s=100.0, provisioning_delay_s=10.0)
    decisions = {50.0: 3}
    strategy = ScriptedStrategy(initial=1, policy=lambda o: decisions.get(o.time, o.committed))
    s = summarise(run_engine(scenario, [], [], strategy), scenario)
    assert s.replicas_mean == pytest.approx((100 + 2 * 50) / 100)
    assert s.replicas_peak == 3
    assert s.servers_launched == 2
    assert s.provisioning_delay_mean_s == 10.0
    assert s.scale_up_events == 1


def test_timeseries_buckets_reconcile_with_summary() -> None:
    scenario = with_sla(make_scenario(duration_s=95.0, initial_replicas=2), 0.5, price=3.6)
    rng = np.random.default_rng(0)
    arrivals = np.sort(rng.uniform(0, 95, 200)).tolist()
    run = run_engine(scenario, arrivals, rng.exponential(0.4, 200).tolist())
    s = summarise(run, scenario)
    ts = timeseries(run, scenario)
    assert len(ts.t_start) == 10
    assert ts.t_end[-1] == 95.0
    assert sum(ts.arrivals) == s.requests_total
    assert sum(ts.completions) == s.requests_completed
    assert sum(ts.sla_violations) == s.sla_violations - (s.requests_unfinished - s.sla_undetermined)
    assert ts.cost_cumulative[-1] == pytest.approx(s.compute_cost)
    weighted = np.dot(ts.queue_length_mean, np.subtract(ts.t_end, ts.t_start)) / 95.0
    assert weighted == pytest.approx(s.queue_length_mean)
    assert sum(ts.busy_slot_seconds) / sum(ts.capacity_slot_seconds) == pytest.approx(
        s.utilisation_mean
    )


def test_histogram_counts_completed_requests() -> None:
    scenario = make_scenario(initial_replicas=3)
    run = run_engine(scenario, [0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
    hist = latency_histogram(run)
    assert sum(hist.counts) == 3
    assert len(hist.bin_edges) == len(hist.counts) + 1


def test_histogram_handles_identical_latencies() -> None:
    # Regression (found by Hypothesis): constant latencies used to raise in np.histogram.
    scenario = make_scenario(initial_replicas=3)
    hist = latency_histogram(run_engine(scenario, [0.0, 1.0, 2.0], [1.0, 1.0, 1.0]))
    assert sum(hist.counts) == 3
    assert hist.bin_edges[0] == 0.0
