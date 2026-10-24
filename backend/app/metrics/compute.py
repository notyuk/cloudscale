"""Summary metrics and time series derived from a raw run."""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt

from app.metrics.models import (
    Histogram,
    LatencyStats,
    ScalingEventModel,
    SummaryMetrics,
    TimeSeries,
)
from app.simulation.config import ScenarioConfig
from app.simulation.engine import RawRun
from app.simulation.entities import RequestState

FloatArray = npt.NDArray[np.float64]

HISTOGRAM_BINS = 40


def _opt(value: float) -> float | None:
    return None if math.isnan(value) or math.isinf(value) else float(value)


def _percentile(values: FloatArray, q: float) -> float | None:
    return float(np.percentile(values, q)) if values.size else None


def _ratio(num: float, den: float) -> float | None:
    return num / den if den > 0 else None


def latency_stats(latencies: FloatArray) -> LatencyStats:
    if latencies.size == 0:
        return LatencyStats(mean_s=None, median_s=None, p95_s=None, p99_s=None, max_s=None)
    p50, p95, p99 = np.percentile(latencies, [50, 95, 99])
    return LatencyStats(
        mean_s=float(latencies.mean()),
        median_s=float(p50),
        p95_s=float(p95),
        p99_s=float(p99),
        max_s=float(latencies.max()),
    )


def peak_concurrent_servers(run: RawRun) -> int:
    """Maximum number of simultaneously billed servers (sweep over lifetimes)."""
    deltas: list[tuple[float, int]] = []
    for server in run.servers:
        deltas.append((server.launched_at, 1))
        end = server.terminated_at if server.terminated_at is not None else run.duration_s
        deltas.append((end, -1))
    # At equal times process terminations (-1) before launches (+1).
    deltas.sort()
    current = peak = 0
    for _, delta in deltas:
        current += delta
        peak = max(peak, current)
    return peak


def summarise(run: RawRun, scenario: ScenarioConfig) -> SummaryMetrics:
    duration = run.duration_s
    states = run.states
    completed = states == RequestState.COMPLETED
    rejected = states == RequestState.REJECTED
    unfinished = states == RequestState.UNFINISHED
    started = ~np.isnan(run.start_times)
    unfinished_queued = unfinished & ~started
    unfinished_in_service = unfinished & started

    latencies = run.completion_times[completed] - run.arrival_times[completed]
    unfinished_ages = duration - run.arrival_times[unfinished]
    censored = np.concatenate([latencies, unfinished_ages])

    waits = run.start_times[started] - run.arrival_times[started]
    still_waiting = duration - run.arrival_times[unfinished_queued]
    all_waits = np.concatenate([waits, still_waiting])

    final = run.snapshots[-1].integrals
    slots = scenario.cluster.slots_per_server
    server_hours = final.paid_servers / 3600.0
    compute_cost = server_hours * scenario.cost.server_price_per_hour

    threshold = scenario.sla.latency_threshold_s
    violations = (
        int(np.count_nonzero(latencies > threshold))
        + int(np.count_nonzero(unfinished_ages > threshold))
        + int(np.count_nonzero(rejected))
    )
    undetermined = int(np.count_nonzero(unfinished_ages <= threshold))
    evaluated = states.size - undetermined
    penalty = violations * scenario.sla.penalty_per_violation
    n_completed = int(np.count_nonzero(completed))

    launched = [s for s in run.servers if not s.initial]
    delays = [s.ready_at - s.launched_at for s in launched if s.ready_at is not None]

    return SummaryMetrics(
        requests_total=int(states.size),
        requests_completed=n_completed,
        requests_rejected=int(np.count_nonzero(rejected)),
        requests_unfinished=int(np.count_nonzero(unfinished)),
        requests_unfinished_queued=int(np.count_nonzero(unfinished_queued)),
        requests_unfinished_in_service=int(np.count_nonzero(unfinished_in_service)),
        throughput_rps=n_completed / duration,
        latency=latency_stats(latencies),
        latency_p95_lower_bound_s=_percentile(censored, 95),
        latency_p99_lower_bound_s=_percentile(censored, 99),
        mean_wait_s=float(waits.mean()) if waits.size else None,
        max_wait_s=float(all_waits.max()) if all_waits.size else None,
        queue_length_mean=final.queue / duration,
        queue_length_peak=run.peak_queue_length,
        utilisation_mean=_ratio(final.busy_slots, final.capacity_slots),
        paid_utilisation_mean=_ratio(final.busy_slots, final.paid_servers * slots),
        replicas_mean=final.paid_servers / duration,
        replicas_peak=peak_concurrent_servers(run),
        scale_up_events=sum(1 for e in run.scaling_events if e.to_replicas > e.from_replicas),
        scale_down_events=sum(1 for e in run.scaling_events if e.to_replicas < e.from_replicas),
        servers_launched=len(launched),
        launches_cancelled=sum(
            1 for s in launched if s.ready_at is None and s.terminated_at is not None
        ),
        provisioning_delay_mean_s=float(np.mean(delays)) if delays else None,
        server_hours=server_hours,
        compute_cost=compute_cost,
        sla_penalty_cost=penalty,
        total_cost=compute_cost + penalty,
        cost_per_completed_request=_ratio(compute_cost, n_completed),
        sla_threshold_s=threshold,
        sla_violations=violations,
        sla_undetermined=undetermined,
        sla_violation_pct=_opt(100.0 * violations / evaluated) if evaluated else None,
    )


def _bucket_stat(
    values: FloatArray, bucket: npt.NDArray[np.intp], n: int, q: float | None
) -> list[float | None]:
    """Per-bucket mean (q=None) or percentile of ``values`` grouped by ``bucket`` index."""
    out: list[float | None] = [None] * n
    if values.size == 0:
        return out
    order = np.argsort(bucket, kind="stable")
    sorted_buckets = bucket[order]
    sorted_values = values[order]
    bounds = np.searchsorted(sorted_buckets, np.arange(n + 1))
    for i in range(n):
        chunk = sorted_values[bounds[i] : bounds[i + 1]]
        if chunk.size:
            out[i] = float(chunk.mean()) if q is None else float(np.percentile(chunk, q))
    return out


def timeseries(run: RawRun, scenario: ScenarioConfig) -> TimeSeries:
    snaps = run.snapshots
    edges = np.array([s.time for s in snaps], dtype=np.float64)
    n = len(snaps) - 1
    widths = np.diff(edges)

    def count(times: FloatArray) -> list[int]:
        return [int(c) for c in np.histogram(times, bins=edges)[0]] if n else []

    def bucket_of(times: FloatArray) -> npt.NDArray[np.intp]:
        return np.clip(np.searchsorted(edges, times, side="right") - 1, 0, n - 1)

    states = run.states
    completed = states == RequestState.COMPLETED
    rejected = states == RequestState.REJECTED
    done_at = run.completion_times[completed]
    latencies = done_at - run.arrival_times[completed]
    threshold = scenario.sla.latency_threshold_s
    violation_times = np.concatenate([done_at[latencies > threshold], run.arrival_times[rejected]])
    rejections = count(run.arrival_times[rejected])
    lat_bucket = bucket_of(done_at)

    def diff(attr: str) -> FloatArray:
        values = np.array([getattr(s.integrals, attr) for s in snaps], dtype=np.float64)
        return np.diff(values)

    busy = diff("busy_slots")
    capacity = diff("capacity_slots")
    paid = diff("paid_servers")
    queue = diff("queue")
    price_per_s = scenario.cost.server_price_per_hour / 3600.0
    cost = paid * price_per_s
    nominal_rate = scenario.cluster.server_speed / scenario.service.mean_work

    arrivals = count(run.arrival_times)
    return TimeSeries(
        t_start=edges[:-1].tolist(),
        t_end=edges[1:].tolist(),
        arrivals=arrivals,
        arrival_rate_rps=(np.array(arrivals, dtype=np.float64) / widths).tolist() if n else [],
        completions=count(done_at),
        rejections=rejections,
        sla_violations=count(violation_times),
        latency_mean_s=_bucket_stat(latencies, lat_bucket, n, None),
        latency_p95_s=_bucket_stat(latencies, lat_bucket, n, 95),
        queue_length_mean=(queue / widths).tolist(),
        queue_length_end=[s.queue_length for s in snaps[1:]],
        active_end=[s.active for s in snaps[1:]],
        starting_end=[s.starting for s in snaps[1:]],
        draining_end=[s.draining for s in snaps[1:]],
        replicas_mean=(paid / widths).tolist(),
        utilisation=[
            (float(b / c) if c > 0 else None) for b, c in zip(busy, capacity, strict=True)
        ],
        capacity_rps=(capacity / widths * nominal_rate).tolist(),
        busy_slot_seconds=busy.tolist(),
        capacity_slot_seconds=capacity.tolist(),
        paid_server_seconds=paid.tolist(),
        cost=cost.tolist(),
        cost_cumulative=np.cumsum(cost).tolist(),
    )


def latency_histogram(run: RawRun) -> Histogram:
    completed = run.states == RequestState.COMPLETED
    latencies = run.completion_times[completed] - run.arrival_times[completed]
    if latencies.size == 0:
        return Histogram(bin_edges=[], counts=[])
    # Anchor at zero so identical latencies (e.g. constant work, no queueing) still
    # produce finite-width bins, and charts share an intuitive origin.
    counts, edges = np.histogram(latencies, bins=HISTOGRAM_BINS, range=(0.0, latencies.max()))
    return Histogram(bin_edges=edges.tolist(), counts=[int(c) for c in counts])


def scaling_events(run: RawRun) -> list[ScalingEventModel]:
    return [
        ScalingEventModel(
            time_s=e.time,
            from_replicas=e.from_replicas,
            to_replicas=e.to_replicas,
            reason=e.reason,
            launched=e.launched,
            reactivated=e.reactivated,
            cancelled=e.cancelled,
            terminated=e.terminated,
            drained=e.drained,
        )
        for e in run.scaling_events
    ]
