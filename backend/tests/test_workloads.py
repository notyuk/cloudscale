from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from pydantic import TypeAdapter, ValidationError

from app.workloads.config import (
    BurstyWorkload,
    ConstantWorkload,
    PoissonWorkload,
    RampWorkload,
    ServiceTimeConfig,
    SinusoidalWorkload,
    SpikeWorkload,
    WorkloadConfig,
)
from app.workloads.generators import (
    WorkloadTrace,
    expected_arrivals,
    generate_trace,
    rate_function,
)

ALL_WORKLOADS = [
    ConstantWorkload(rate=10),
    PoissonWorkload(rate=10),
    SinusoidalWorkload(base_rate=10, amplitude=8, period_s=300),
    SpikeWorkload(base_rate=5, spike_rate=40, spike_start_s=200, spike_duration_s=100),
    RampWorkload(start_rate=2, end_rate=20),
    BurstyWorkload(base_rate=5, peak_multiplier=6, mean_burst_s=30, mean_gap_s=120),
]
SERVICE = ServiceTimeConfig()


@pytest.mark.parametrize("workload", ALL_WORKLOADS, ids=lambda w: w.pattern)
def test_same_seed_is_bit_identical(workload: WorkloadConfig) -> None:
    a = generate_trace(workload, SERVICE, 1_000, seed=7)
    b = generate_trace(workload, SERVICE, 1_000, seed=7)
    np.testing.assert_array_equal(a.arrival_times, b.arrival_times)
    np.testing.assert_array_equal(a.work, b.work)


@pytest.mark.parametrize("workload", ALL_WORKLOADS[1:], ids=lambda w: w.pattern)
def test_different_seeds_differ(workload: WorkloadConfig) -> None:
    a = generate_trace(workload, SERVICE, 1_000, seed=1)
    b = generate_trace(workload, SERVICE, 1_000, seed=2)
    assert not np.array_equal(a.arrival_times, b.arrival_times)


@pytest.mark.parametrize("workload", ALL_WORKLOADS, ids=lambda w: w.pattern)
def test_arrivals_sorted_and_within_window(workload: WorkloadConfig) -> None:
    trace = generate_trace(workload, SERVICE, 1_000, seed=3)
    assert trace.size > 0
    assert np.all(np.diff(trace.arrival_times) >= 0)
    assert trace.arrival_times[0] >= 0
    assert trace.arrival_times[-1] < 1_000
    assert np.all(trace.work > 0)


@pytest.mark.parametrize("workload", ALL_WORKLOADS[:5], ids=lambda w: w.pattern)
def test_count_matches_expected_rate(workload: WorkloadConfig) -> None:
    duration = 2_000.0
    expected = expected_arrivals(workload, duration)
    counts = [generate_trace(workload, SERVICE, duration, seed=s).size for s in range(10)]
    # Poisson count has SD sqrt(mean); the mean of 10 runs is well within 4 SD/sqrt(10).
    assert abs(np.mean(counts) - expected) < 4 * np.sqrt(expected / 10) + 1


def test_bursty_mean_rate_over_long_horizon() -> None:
    workload = BurstyWorkload(base_rate=5, peak_multiplier=5, mean_burst_s=20, mean_gap_s=80)
    duration = 50_000.0
    trace = generate_trace(workload, SERVICE, duration, seed=11)
    assert trace.size / duration == pytest.approx(
        expected_arrivals(workload, duration) / duration, rel=0.08
    )


def test_constant_is_evenly_spaced() -> None:
    trace = generate_trace(ConstantWorkload(rate=4), SERVICE, 10, seed=0)
    assert trace.size == 40
    np.testing.assert_allclose(np.diff(trace.arrival_times), 0.25)


def test_spike_concentrates_arrivals_in_window() -> None:
    workload = SpikeWorkload(base_rate=5, spike_rate=50, spike_start_s=400, spike_duration_s=100)
    t = generate_trace(workload, SERVICE, 1_000, seed=5).arrival_times
    in_spike = np.count_nonzero((t >= 400) & (t < 500))
    before = np.count_nonzero((t >= 200) & (t < 300))
    assert in_spike > 5 * before


def test_ramp_rate_increases() -> None:
    t = generate_trace(
        RampWorkload(start_rate=2, end_rate=40), SERVICE, 1_000, seed=5
    ).arrival_times
    first, last = np.count_nonzero(t < 200), np.count_nonzero(t >= 800)
    assert last > 5 * first


def test_service_distribution_does_not_perturb_arrivals() -> None:
    workload = PoissonWorkload(rate=10)
    a = generate_trace(workload, ServiceTimeConfig(distribution="constant"), 500, seed=9)
    b = generate_trace(workload, ServiceTimeConfig(distribution="lognormal", cv=2), 500, seed=9)
    np.testing.assert_array_equal(a.arrival_times, b.arrival_times)


@pytest.mark.parametrize(
    ("distribution", "cv"), [("constant", 0.0), ("exponential", 1.0), ("lognormal", 2.0)]
)
def test_work_distribution_moments(distribution: Any, cv: float) -> None:
    service = ServiceTimeConfig(distribution=distribution, mean_work=0.5, cv=max(cv, 0.1))
    trace = generate_trace(PoissonWorkload(rate=200), service, 1_000, seed=4)
    assert trace.work.mean() == pytest.approx(0.5, rel=0.05)
    assert trace.work.std() / trace.work.mean() == pytest.approx(cv, abs=0.15)


def test_sinusoid_rate_function_shape() -> None:
    w = SinusoidalWorkload(base_rate=10, amplitude=5, period_s=100)
    rates = rate_function(w, np.array([0.0, 25.0, 75.0]), 100)
    np.testing.assert_allclose(rates, [10, 15, 5])


@pytest.mark.parametrize(
    "payload",
    [
        {"pattern": "sinusoidal", "base_rate": 5, "amplitude": 10},
        {"pattern": "spike", "base_rate": 10, "spike_rate": 5},
        {"pattern": "poisson", "rate": 0},
        {"pattern": "poisson", "rate": -1},
        {"pattern": "constant", "rate": 1e9},
        {"pattern": "bursty", "base_rate": 1000, "peak_multiplier": 50},
        {"pattern": "unknown"},
        {"pattern": "poisson", "rate": 5, "surprise": 1},
    ],
)
def test_invalid_workloads_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter[WorkloadConfig](WorkloadConfig).validate_python(payload)  # type: ignore[arg-type]


def test_trace_validates_ordering() -> None:
    with pytest.raises(ValueError, match="sorted"):
        WorkloadTrace(np.array([2.0, 1.0]), np.array([1.0, 1.0]), 10)
    with pytest.raises(ValueError, match="duration"):
        WorkloadTrace(np.array([11.0]), np.array([1.0]), 10)


def test_trace_arrays_are_read_only() -> None:
    trace = generate_trace(PoissonWorkload(rate=5), SERVICE, 100, seed=1)
    with pytest.raises(ValueError, match="read-only"):
        trace.arrival_times[0] = 0.0
