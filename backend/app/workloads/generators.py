"""Seeded workload generation.

A workload trace is a pair of equally sized arrays: sorted arrival times and
per-request work. Generation is fully vectorised with NumPy and uses *local*
``numpy.random.Generator`` instances derived from an explicit seed, so the same
configuration and seed always yield bit-identical traces.

Arrival times and work use independent child streams of one ``SeedSequence``.
Changing the service-time distribution therefore never perturbs the arrival
times, which keeps comparisons between scenarios meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

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

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class WorkloadTrace:
    """An immutable, fully materialised request trace."""

    arrival_times: FloatArray
    work: FloatArray
    duration_s: float

    def __post_init__(self) -> None:
        if self.arrival_times.shape != self.work.shape:
            raise ValueError("arrival_times and work must have the same length")
        if self.arrival_times.size and (
            self.arrival_times[0] < 0 or self.arrival_times[-1] >= self.duration_s
        ):
            raise ValueError("arrival times must lie in [0, duration)")
        if np.any(np.diff(self.arrival_times) < 0):
            raise ValueError("arrival times must be sorted")
        if np.any(self.work <= 0):
            raise ValueError("work must be strictly positive")
        # Freeze the arrays so a trace shared between strategy runs cannot be mutated.
        self.arrival_times.setflags(write=False)
        self.work.setflags(write=False)

    @property
    def size(self) -> int:
        return int(self.arrival_times.size)


def rate_function(workload: WorkloadConfig, t: FloatArray, duration_s: float) -> FloatArray:
    """Evaluate the *intended* arrival rate lambda(t) in requests/second.

    For the bursty MMPP the rate is a random process, so this returns its
    long-run mean rate. Used for cost estimation and for plotting.
    """
    match workload:
        case ConstantWorkload(rate=rate) | PoissonWorkload(rate=rate):
            return np.full_like(t, rate, dtype=np.float64)
        case SinusoidalWorkload():
            return workload.base_rate + workload.amplitude * np.sin(
                2 * np.pi * t / workload.period_s + workload.phase_rad
            )
        case SpikeWorkload():
            in_spike = (t >= workload.spike_start_s) & (
                t < workload.spike_start_s + workload.spike_duration_s
            )
            return np.where(in_spike, workload.spike_rate, workload.base_rate)
        case RampWorkload():
            frac = np.clip(t / duration_s, 0.0, 1.0)
            return workload.start_rate + (workload.end_rate - workload.start_rate) * frac
        case BurstyWorkload():
            p_burst = workload.mean_burst_s / (workload.mean_burst_s + workload.mean_gap_s)
            mean = workload.base_rate * (1 + p_burst * (workload.peak_multiplier - 1))
            return np.full_like(t, mean, dtype=np.float64)
    raise TypeError(f"unsupported workload {type(workload).__name__}")  # pragma: no cover


def expected_arrivals(workload: WorkloadConfig, duration_s: float) -> float:
    """Expected number of arrivals in [0, duration) (numerical integral of lambda)."""
    grid = np.linspace(0.0, duration_s, 4097)
    return float(np.trapezoid(rate_function(workload, grid, duration_s), grid))


def peak_rate(workload: WorkloadConfig) -> float:
    """Upper bound on lambda(t), used as the thinning envelope."""
    match workload:
        case ConstantWorkload(rate=rate) | PoissonWorkload(rate=rate):
            return rate
        case SinusoidalWorkload():
            return workload.base_rate + workload.amplitude
        case SpikeWorkload():
            return workload.spike_rate
        case RampWorkload():
            return max(workload.start_rate, workload.end_rate)
        case BurstyWorkload():
            return workload.base_rate * workload.peak_multiplier
    raise TypeError(f"unsupported workload {type(workload).__name__}")  # pragma: no cover


def _homogeneous_poisson(
    rng: np.random.Generator, rate: float, start: float, end: float
) -> FloatArray:
    """Poisson process on [start, end): N ~ Poisson(rate*T), then sorted uniforms.

    Conditional on N, the arrival times of a homogeneous Poisson process are
    distributed as order statistics of N uniforms, which is much faster than
    accumulating exponential gaps in Python.
    """
    span = end - start
    if span <= 0 or rate <= 0:
        return np.empty(0, dtype=np.float64)
    n = int(rng.poisson(rate * span))
    times = start + rng.random(n) * span
    times.sort()
    return times


def _thinned_poisson(
    rng: np.random.Generator, workload: WorkloadConfig, duration_s: float
) -> FloatArray:
    """Non-homogeneous Poisson process via Lewis-Shedler thinning."""
    envelope = peak_rate(workload)
    candidates = _homogeneous_poisson(rng, envelope, 0.0, duration_s)
    accept_prob = rate_function(workload, candidates, duration_s) / envelope
    keep = rng.random(candidates.size) < accept_prob
    return candidates[keep]


def _mmpp_arrivals(
    rng: np.random.Generator, workload: BurstyWorkload, duration_s: float
) -> FloatArray:
    """Two-state MMPP: alternate exponential sojourns, Poisson arrivals within each."""
    segments: list[FloatArray] = []
    t = 0.0
    in_burst = False
    burst_rate = workload.base_rate * workload.peak_multiplier
    while t < duration_s:
        mean = workload.mean_burst_s if in_burst else workload.mean_gap_s
        end = min(duration_s, t + float(rng.exponential(mean)))
        rate = burst_rate if in_burst else workload.base_rate
        segments.append(_homogeneous_poisson(rng, rate, t, end))
        t = end
        in_burst = not in_burst
    return np.concatenate(segments) if segments else np.empty(0, dtype=np.float64)


def generate_arrivals(
    workload: WorkloadConfig, duration_s: float, rng: np.random.Generator
) -> FloatArray:
    """Generate sorted arrival times in [0, duration_s)."""
    match workload:
        case ConstantWorkload(rate=rate):
            # Evenly spaced; offset by half a gap so arrivals do not coincide with t=0 ticks.
            gap = 1.0 / rate
            times = np.arange(gap / 2, duration_s, gap, dtype=np.float64)
        case PoissonWorkload(rate=rate):
            times = _homogeneous_poisson(rng, rate, 0.0, duration_s)
        case SinusoidalWorkload() | SpikeWorkload() | RampWorkload():
            times = _thinned_poisson(rng, workload, duration_s)
        case BurstyWorkload():
            times = _mmpp_arrivals(rng, workload, duration_s)
        case _:  # pragma: no cover
            raise TypeError(f"unsupported workload {type(workload).__name__}")
    return times[times < duration_s]


def generate_work(service: ServiceTimeConfig, n: int, rng: np.random.Generator) -> FloatArray:
    """Draw per-request work (strictly positive) with the configured mean."""
    match service.distribution:
        case "constant":
            work = np.full(n, service.mean_work, dtype=np.float64)
        case "exponential":
            work = rng.exponential(service.mean_work, n)
        case "lognormal":
            # Parameterise so that E[X] = mean_work and SD[X]/E[X] = cv.
            sigma2 = np.log1p(service.cv**2)
            mu = np.log(service.mean_work) - sigma2 / 2
            work = rng.lognormal(mu, np.sqrt(sigma2), n)
    # Exponential draws can be exactly 0.0 with vanishing probability; clamp to keep
    # the "work > 0" invariant without measurably changing the distribution.
    return np.maximum(work, 1e-9)


def generate_trace(
    workload: WorkloadConfig,
    service: ServiceTimeConfig,
    duration_s: float,
    seed: int,
) -> WorkloadTrace:
    """Generate a reproducible trace from configuration and seed."""
    arrival_seq, work_seq = np.random.SeedSequence(seed).spawn(2)
    arrivals = generate_arrivals(workload, duration_s, np.random.default_rng(arrival_seq))
    work = generate_work(service, arrivals.size, np.random.default_rng(work_seq))
    return WorkloadTrace(arrival_times=arrivals, work=work, duration_s=duration_s)
