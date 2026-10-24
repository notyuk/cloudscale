"""Result schemas for metrics."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class LatencyStats(_Model):
    """Response time (completion - arrival) of *completed* requests."""

    mean_s: float | None
    median_s: float | None
    p95_s: float | None
    p99_s: float | None
    max_s: float | None


class SummaryMetrics(_Model):
    # Request accounting: total = completed + rejected + unfinished.
    requests_total: int
    requests_completed: int
    requests_rejected: int = Field(description="Refused on arrival because the queue was full")
    requests_unfinished: int = Field(description="Queued or in service when the simulation ended")
    requests_unfinished_queued: int
    requests_unfinished_in_service: int

    throughput_rps: float = Field(description="Completed requests / duration")
    latency: LatencyStats
    latency_p95_lower_bound_s: float | None = Field(
        description="P95 over completed latencies plus elapsed age of unfinished requests; "
        "a lower bound on the true P95 when there is a backlog"
    )
    latency_p99_lower_bound_s: float | None
    mean_wait_s: float | None = Field(description="Mean queueing delay of requests that started")
    max_wait_s: float | None = Field(
        description="Longest queueing delay, including requests still waiting at the end"
    )

    queue_length_mean: float = Field(description="Time-weighted mean queue length")
    queue_length_peak: int

    utilisation_mean: float | None = Field(
        description="Busy slot-seconds / serving slot-seconds (serving = active + busy draining)"
    )
    paid_utilisation_mean: float | None = Field(
        description="Busy slot-seconds / billed slot-seconds (includes booting servers)"
    )
    replicas_mean: float = Field(description="Time-weighted mean billed servers")
    replicas_peak: int
    scale_up_events: int
    scale_down_events: int
    servers_launched: int
    launches_cancelled: int
    provisioning_delay_mean_s: float | None

    server_hours: float
    compute_cost: float
    sla_penalty_cost: float
    total_cost: float
    cost_per_completed_request: float | None

    sla_threshold_s: float
    sla_violations: int = Field(
        description="Completed over threshold + unfinished already older than threshold + rejected"
    )
    sla_undetermined: int = Field(
        description="Unfinished requests younger than the threshold; outcome unknown"
    )
    sla_violation_pct: float | None = Field(
        description="100 * violations / (requests_total - sla_undetermined)"
    )


class TimeSeries(_Model):
    """Column-oriented bucketed series; bucket i covers [t_start[i], t_end[i]).

    Raw integrals (``*_seconds``) are included so every derived value can be
    recomputed independently from the response.
    """

    t_start: list[float]
    t_end: list[float]
    arrivals: list[int]
    arrival_rate_rps: list[float]
    completions: list[int]
    rejections: list[int]
    sla_violations: list[int]
    latency_mean_s: list[float | None]
    latency_p95_s: list[float | None]
    queue_length_mean: list[float]
    queue_length_end: list[int]
    active_end: list[int]
    starting_end: list[int]
    draining_end: list[int]
    replicas_mean: list[float]
    utilisation: list[float | None]
    capacity_rps: list[float] = Field(
        description="Serving slots * server_speed / mean_work: nominal sustainable throughput"
    )
    busy_slot_seconds: list[float]
    capacity_slot_seconds: list[float]
    paid_server_seconds: list[float]
    cost: list[float]
    cost_cumulative: list[float]


class Histogram(_Model):
    bin_edges: list[float]
    counts: list[int]


class ScalingEventModel(_Model):
    time_s: float
    from_replicas: int
    to_replicas: int
    reason: str
    launched: int
    reactivated: int
    cancelled: int
    terminated: int
    drained: int
