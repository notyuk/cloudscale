"""Workload configuration models."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Hard upper bound on any configured arrival rate. Guards against configurations
# that would allocate absurd arrays before the cost estimator can reject them.
MAX_RATE_RPS = 5_000.0


class _WorkloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ConstantWorkload(_WorkloadBase):
    """Deterministic, evenly spaced arrivals at a fixed rate (no randomness)."""

    pattern: Literal["constant"] = "constant"
    rate: float = Field(20.0, gt=0, le=MAX_RATE_RPS, description="Arrivals per second")


class PoissonWorkload(_WorkloadBase):
    """Homogeneous Poisson process: exponential inter-arrival times."""

    pattern: Literal["poisson"] = "poisson"
    rate: float = Field(20.0, gt=0, le=MAX_RATE_RPS, description="Mean arrivals per second")


class SinusoidalWorkload(_WorkloadBase):
    """Non-homogeneous Poisson with lambda(t) = base + amplitude * sin(2*pi*t/period + phase)."""

    pattern: Literal["sinusoidal"] = "sinusoidal"
    base_rate: float = Field(20.0, gt=0, le=MAX_RATE_RPS)
    amplitude: float = Field(15.0, ge=0, le=MAX_RATE_RPS)
    period_s: float = Field(600.0, gt=0, description="Period of one full cycle in seconds")
    phase_rad: float = Field(0.0, ge=-6.3, le=6.3)

    @model_validator(mode="after")
    def _non_negative_rate(self) -> SinusoidalWorkload:
        if self.amplitude > self.base_rate:
            raise ValueError(
                "amplitude must not exceed base_rate, otherwise the arrival rate would be negative"
            )
        return self


class SpikeWorkload(_WorkloadBase):
    """Poisson arrivals at ``base_rate`` with a rectangular spike to ``spike_rate``."""

    pattern: Literal["spike"] = "spike"
    base_rate: float = Field(10.0, gt=0, le=MAX_RATE_RPS)
    spike_rate: float = Field(60.0, gt=0, le=MAX_RATE_RPS)
    spike_start_s: float = Field(600.0, ge=0)
    spike_duration_s: float = Field(300.0, gt=0)

    @model_validator(mode="after")
    def _spike_is_a_spike(self) -> SpikeWorkload:
        if self.spike_rate <= self.base_rate:
            raise ValueError("spike_rate must be greater than base_rate")
        return self


class RampWorkload(_WorkloadBase):
    """Poisson arrivals whose rate changes linearly from start_rate to end_rate."""

    pattern: Literal["ramp"] = "ramp"
    start_rate: float = Field(5.0, gt=0, le=MAX_RATE_RPS)
    end_rate: float = Field(50.0, gt=0, le=MAX_RATE_RPS)


class BurstyWorkload(_WorkloadBase):
    """Two-state Markov-modulated Poisson process (MMPP-2).

    The process alternates between a *normal* state (rate ``base_rate``) and a
    *burst* state (rate ``base_rate * peak_multiplier``). Sojourn times in each
    state are exponential with the configured means.
    """

    pattern: Literal["bursty"] = "bursty"
    base_rate: float = Field(10.0, gt=0, le=MAX_RATE_RPS)
    peak_multiplier: float = Field(5.0, gt=1, le=100)
    mean_burst_s: float = Field(60.0, gt=0)
    mean_gap_s: float = Field(300.0, gt=0)

    @model_validator(mode="after")
    def _peak_rate_bounded(self) -> BurstyWorkload:
        if self.base_rate * self.peak_multiplier > MAX_RATE_RPS:
            raise ValueError(f"base_rate * peak_multiplier must not exceed {MAX_RATE_RPS:g}")
        return self


WorkloadConfig = Annotated[
    ConstantWorkload
    | PoissonWorkload
    | SinusoidalWorkload
    | SpikeWorkload
    | RampWorkload
    | BurstyWorkload,
    Field(discriminator="pattern"),
]


class ServiceTimeConfig(BaseModel):
    """Distribution of per-request work.

    Work is measured in *work units*; one work unit takes one second on a slot
    of a server with ``speed = 1``. The mean is fixed by ``mean_work``; ``cv``
    (coefficient of variation) only applies to the log-normal distribution.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    distribution: Literal["constant", "exponential", "lognormal"] = "exponential"
    mean_work: float = Field(0.2, gt=0, le=3_600, description="Mean work units per request")
    cv: float = Field(1.0, gt=0, le=10, description="Coefficient of variation (lognormal only)")
