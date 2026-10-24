"""Scenario configuration. Time in seconds, prices per server-hour."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.workloads.config import (
    ServiceTimeConfig,
    SinusoidalWorkload,
    SpikeWorkload,
    WorkloadConfig,
)

MAX_DURATION_S = 86_400.0
MAX_SERIES_POINTS = 2_000


class ClusterConfig(BaseModel):
    """Physical constraints of the simulated server pool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    slots_per_server: int = Field(
        4, ge=1, le=256, description="Concurrent requests one server can process"
    )
    server_speed: float = Field(
        1.0, gt=0, le=100, description="Work units processed per second by each slot"
    )
    min_replicas: int = Field(1, ge=1, le=1_000)
    max_replicas: int = Field(20, ge=1, le=1_000)
    initial_replicas: int = Field(2, ge=1, le=1_000, description="Warm servers at t = 0")
    provisioning_delay_s: float = Field(
        60.0, ge=0, le=3_600, description="Time from launch until a server accepts work"
    )
    max_pending: int = Field(
        10_000, ge=0, le=1_000_000, description="Queue capacity; arrivals beyond it are rejected"
    )

    @model_validator(mode="after")
    def _bounds(self) -> ClusterConfig:
        if self.min_replicas > self.max_replicas:
            raise ValueError("min_replicas must not exceed max_replicas")
        if not self.min_replicas <= self.initial_replicas <= self.max_replicas:
            raise ValueError("initial_replicas must lie within [min_replicas, max_replicas]")
        return self


class SlaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    latency_threshold_s: float = Field(
        1.0, gt=0, le=3_600, description="A request violates the SLA if latency exceeds this"
    )
    penalty_per_violation: float = Field(
        0.0, ge=0, le=1_000, description="Optional cost charged per SLA violation"
    )


class CostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    server_price_per_hour: float = Field(
        0.10, ge=0, le=1_000, description="Charged while a server is starting, active or draining"
    )


class ScenarioConfig(BaseModel):
    """Everything that defines an experiment except the strategy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    duration_s: float = Field(3_600.0, gt=0, le=MAX_DURATION_S)
    seed: int = Field(42, ge=0, le=2**32 - 1)
    workload: WorkloadConfig = Field(default_factory=SinusoidalWorkload)
    service: ServiceTimeConfig = Field(default_factory=ServiceTimeConfig)
    cluster: ClusterConfig = Field(default_factory=ClusterConfig)
    sla: SlaConfig = Field(default_factory=SlaConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    control_interval_s: float = Field(
        15.0, gt=0, le=3_600, description="How often the autoscaler is consulted"
    )
    metrics_interval_s: float = Field(
        15.0, gt=0, le=3_600, description="Width of time-series buckets"
    )

    @model_validator(mode="after")
    def _consistent(self) -> ScenarioConfig:
        if self.control_interval_s > self.duration_s:
            raise ValueError("control_interval_s must not exceed duration_s")
        if self.duration_s / self.metrics_interval_s > MAX_SERIES_POINTS:
            raise ValueError(
                f"duration_s / metrics_interval_s must not exceed {MAX_SERIES_POINTS} buckets"
            )
        if isinstance(self.workload, SpikeWorkload) and (
            self.workload.spike_start_s >= self.duration_s
        ):
            raise ValueError("spike_start_s must be before the end of the simulation")
        return self
