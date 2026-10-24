"""Deterministic discrete-event simulation engine.

Execution model
---------------
* One global FIFO queue in front of a pool of identical servers (an idealised
  load balancer). Each server has ``slots_per_server`` independent slots; a
  slot processes one request at a time, taking ``work / server_speed`` seconds.
* Dispatch is work-conserving and bin-packing: whenever a slot is free and the
  queue is non-empty, the head of the queue goes to the lowest-numbered ACTIVE
  server with a free slot. Packing keeps high-numbered servers idle so that
  scale-down can usually terminate them without draining.
* The simulation covers the half-open interval ``[0, duration)``. Events at or
  after ``duration`` are not processed; requests still queued or in service at
  that point become UNFINISHED.

Event ordering
--------------
Events are ordered by ``(time, kind, sequence)``. At equal timestamps the kind
priority is SAMPLE < COMPLETION < SERVER_READY < ARRIVAL < CONTROL, so:

1. metric buckets close *before* anything at their boundary happens;
2. capacity freed by completions and new servers is visible to arrivals at the
   same instant;
3. the controller observes every arrival up to and including its tick time.

``sequence`` is a monotonically increasing insertion counter, which makes ties
within a kind deterministic (FIFO). Arrivals come from a pre-sorted array and
are merged with the heap rather than pushed into it, which halves heap traffic.

Complexity: O((N + E) log H) for N requests, E other events, and heap size H
(bounded by in-flight requests plus pending server/timer events). Memory is
O(N) for the per-request arrays.
"""

from __future__ import annotations

import heapq
import math
import time as wallclock
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum

import numpy as np
import numpy.typing as npt

from app.simulation.config import ScenarioConfig
from app.simulation.entities import (
    REQUEST_TRANSITIONS,
    InvalidTransitionError,
    RequestState,
    ScalingEvent,
    Server,
    ServerState,
)
from app.strategies.base import Observation, ScalingStrategy
from app.workloads.generators import WorkloadTrace

#: Smoothing factor for the per-interval service-time estimate shown to strategies.
SERVICE_ESTIMATE_ALPHA = 0.3
_BUDGET_CHECK_EVERY = 8_192


class EventKind(IntEnum):
    """Event kinds; the integer value is the tie-break priority."""

    SAMPLE = 0
    COMPLETION = 1
    SERVER_READY = 2
    ARRIVAL = 3
    CONTROL = 4


class SimulationBudgetExceededError(RuntimeError):
    """The run exceeded its wall-clock budget and was aborted."""


class InvariantViolationError(AssertionError):
    """An internal consistency check failed (only raised with ``check_invariants``)."""


@dataclass(slots=True)
class Integrals:
    """Cumulative time integrals of cluster state, in (quantity x seconds)."""

    queue: float = 0.0  # request-seconds waiting
    busy_slots: float = 0.0  # slot-seconds spent processing
    capacity_slots: float = 0.0  # slot-seconds available to serve (see `serving_slots`)
    paid_servers: float = 0.0  # server-seconds billed (starting + active + draining)

    def copy(self) -> Integrals:
        return Integrals(self.queue, self.busy_slots, self.capacity_slots, self.paid_servers)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Cluster state at a metrics bucket boundary."""

    time: float
    integrals: Integrals
    active: int
    starting: int
    draining: int
    queue_length: int
    busy_slots: int


@dataclass(slots=True)
class RawRun:
    """Everything the engine produced; metrics are derived from this."""

    arrival_times: npt.NDArray[np.float64]
    work: npt.NDArray[np.float64]
    start_times: npt.NDArray[np.float64]  # NaN if never started
    completion_times: npt.NDArray[np.float64]  # NaN if not completed
    states: npt.NDArray[np.int8]
    servers: list[Server]
    snapshots: list[Snapshot]
    scaling_events: list[ScalingEvent]
    peak_queue_length: int
    events_processed: int
    wall_time_s: float
    duration_s: float
    decisions: list[tuple[float, int, str]] = field(default_factory=list)


class SimulationEngine:
    """Runs one strategy against one trace. Instances are single-use."""

    def __init__(
        self,
        scenario: ScenarioConfig,
        trace: WorkloadTrace,
        strategy: ScalingStrategy,
        *,
        wall_time_budget_s: float | None = None,
        check_invariants: bool = False,
    ) -> None:
        if trace.duration_s != scenario.duration_s:
            raise ValueError("trace duration does not match scenario duration")
        self.scenario = scenario
        self.cluster = scenario.cluster
        self.trace = trace
        self.strategy = strategy
        self.wall_time_budget_s = wall_time_budget_s
        self.check_invariants = check_invariants

        n = trace.size
        self._arrivals: list[float] = trace.arrival_times.tolist()
        self._work: list[float] = trace.work.tolist()
        self._state: list[RequestState] = [RequestState.PENDING] * n
        self._start: list[float] = [math.nan] * n
        self._completion: list[float] = [math.nan] * n

        self.now = 0.0
        self._heap: list[tuple[float, int, int, int, int]] = []
        self._seq = 0
        self._queue: deque[int] = deque()
        self._peak_queue = 0

        self._servers: list[Server] = []
        self._live: dict[int, Server] = {}
        self._free_heap: list[int] = []
        self._n_active = 0
        self._n_starting = 0
        self._n_draining = 0
        self._busy_active = 0
        self._busy_draining = 0

        self._integrals = Integrals()
        self._snapshots: list[Snapshot] = []
        self._scaling_events: list[ScalingEvent] = []
        self._decisions: list[tuple[float, int, str]] = []

        # Per-control-interval accumulators (reset at each control tick).
        self._ctl_integrals_at_last_tick = Integrals()
        self._ctl_last_time = 0.0
        self._ctl_arrivals = 0
        self._ctl_completions = 0
        self._ctl_rejections = 0
        self._ctl_service_sum = 0.0
        self._service_estimate: float | None = None
        self._events = 0

    # ------------------------------------------------------------------ helpers

    def _push(self, t: float, kind: EventKind, a: int = 0, b: int = 0) -> None:
        heapq.heappush(self._heap, (t, int(kind), self._seq, a, b))
        self._seq += 1

    def _set_request_state(self, rid: int, new: RequestState) -> None:
        old = self._state[rid]
        if new not in REQUEST_TRANSITIONS[old]:
            raise InvalidTransitionError(f"request {rid}: {old.name} -> {new.name}")
        self._state[rid] = new

    def _serving_slots(self) -> int:
        """Slots able to do work: all slots of ACTIVE servers plus occupied DRAINING slots."""
        return self._n_active * self.cluster.slots_per_server + self._busy_draining

    def _advance(self, t: float) -> None:
        """Accumulate time integrals of the state held constant over [now, t)."""
        dt = t - self.now
        if dt > 0:
            acc = self._integrals
            acc.queue += len(self._queue) * dt
            acc.busy_slots += (self._busy_active + self._busy_draining) * dt
            acc.capacity_slots += (
                self._n_active * self.cluster.slots_per_server + self._busy_draining
            ) * dt
            acc.paid_servers += (self._n_active + self._n_starting + self._n_draining) * dt
        self.now = t

    # --------------------------------------------------------------- servers

    def _new_server(self, state: ServerState, initial: bool = False) -> Server:
        server = Server(id=len(self._servers), state=state, launched_at=self.now, initial=initial)
        self._servers.append(server)
        self._live[server.id] = server
        return server

    def _mark_free(self, server: Server) -> None:
        if (
            not server.in_free_heap
            and server.state is ServerState.ACTIVE
            and server.in_flight < self.cluster.slots_per_server
        ):
            heapq.heappush(self._free_heap, server.id)
            server.in_free_heap = True

    def _peek_free(self) -> Server | None:
        """Lowest-id ACTIVE server with a free slot; lazily discards stale heap entries."""
        slots = self.cluster.slots_per_server
        while self._free_heap:
            server = self._servers[self._free_heap[0]]
            if server.state is ServerState.ACTIVE and server.in_flight < slots:
                return server
            heapq.heappop(self._free_heap)
            server.in_free_heap = False
        return None

    def _launch(self) -> None:
        server = self._new_server(ServerState.STARTING)
        self._n_starting += 1
        self._push(self.now + self.cluster.provisioning_delay_s, EventKind.SERVER_READY, server.id)

    def _terminate(self, server: Server) -> None:
        if server.in_flight:
            raise InvalidTransitionError(f"server {server.id} terminated with work in flight")
        match server.state:
            case ServerState.STARTING:
                self._n_starting -= 1
            case ServerState.ACTIVE:
                self._n_active -= 1
            case ServerState.DRAINING:
                self._n_draining -= 1
        server.transition(ServerState.TERMINATED)
        server.terminated_at = self.now
        del self._live[server.id]

    def _drain(self, server: Server) -> None:
        server.transition(ServerState.DRAINING)
        self._n_active -= 1
        self._n_draining += 1
        self._busy_active -= server.in_flight
        self._busy_draining += server.in_flight

    def _reactivate(self, server: Server) -> None:
        server.transition(ServerState.ACTIVE)
        self._n_draining -= 1
        self._n_active += 1
        self._busy_draining -= server.in_flight
        self._busy_active += server.in_flight
        self._mark_free(server)

    # -------------------------------------------------------------- dispatch

    def _dispatch(self) -> None:
        slots = self.cluster.slots_per_server
        speed = self.cluster.server_speed
        queue = self._queue
        while queue:
            server = self._peek_free()
            if server is None:
                return
            rid = queue.popleft()
            self._set_request_state(rid, RequestState.IN_SERVICE)
            self._start[rid] = self.now
            server.in_flight += 1
            self._busy_active += 1
            if server.in_flight >= slots:
                heapq.heappop(self._free_heap)
                server.in_free_heap = False
            self._push(self.now + self._work[rid] / speed, EventKind.COMPLETION, rid, server.id)

    # ---------------------------------------------------------------- events

    def _on_arrival(self, rid: int) -> None:
        self._ctl_arrivals += 1
        queue = self._queue
        if (queue or self._peek_free() is None) and len(queue) >= self.cluster.max_pending:
            self._set_request_state(rid, RequestState.REJECTED)
            self._ctl_rejections += 1
            return
        self._set_request_state(rid, RequestState.QUEUED)
        queue.append(rid)
        self._dispatch()
        self._peak_queue = max(self._peak_queue, len(queue))

    def _on_completion(self, rid: int, sid: int) -> None:
        self._set_request_state(rid, RequestState.COMPLETED)
        self._completion[rid] = self.now
        self._ctl_completions += 1
        self._ctl_service_sum += self.now - self._start[rid]
        server = self._servers[sid]
        server.in_flight -= 1
        if server.state is ServerState.ACTIVE:
            self._busy_active -= 1
            self._mark_free(server)
            self._dispatch()
        elif server.state is ServerState.DRAINING:
            self._busy_draining -= 1
            if server.in_flight == 0:
                self._terminate(server)
        else:  # pragma: no cover - guarded by lifecycle checks
            raise InvalidTransitionError(f"completion on {server.state.name} server {sid}")

    def _on_server_ready(self, sid: int) -> None:
        server = self._servers[sid]
        if server.state is not ServerState.STARTING:
            return  # launch was cancelled by a scale-down before it finished booting
        server.transition(ServerState.ACTIVE)
        server.ready_at = self.now
        self._n_starting -= 1
        self._n_active += 1
        self._mark_free(server)
        self._dispatch()

    def _observation(self) -> Observation:
        interval = self.now - self._ctl_last_time
        previous = self._ctl_integrals_at_last_tick
        if self._ctl_completions:
            mean = self._ctl_service_sum / self._ctl_completions
            if self._service_estimate is None:
                self._service_estimate = mean
            else:
                self._service_estimate += SERVICE_ESTIMATE_ALPHA * (mean - self._service_estimate)
        return Observation(
            time=self.now,
            interval_s=interval,
            active=self._n_active,
            starting=self._n_starting,
            draining=self._n_draining,
            queue_length=len(self._queue),
            busy_slots=self._busy_active + self._busy_draining,
            slots_per_server=self.cluster.slots_per_server,
            server_speed=self.cluster.server_speed,
            min_replicas=self.cluster.min_replicas,
            max_replicas=self.cluster.max_replicas,
            provisioning_delay_s=self.cluster.provisioning_delay_s,
            arrivals=self._ctl_arrivals,
            completions=self._ctl_completions,
            rejections=self._ctl_rejections,
            busy_slot_seconds=self._integrals.busy_slots - previous.busy_slots,
            capacity_slot_seconds=self._integrals.capacity_slots - previous.capacity_slots,
            service_time_estimate_s=self._service_estimate,
        )

    def _on_control(self) -> None:
        obs = self._observation()
        self._ctl_integrals_at_last_tick = self._integrals.copy()
        self._ctl_last_time = self.now
        self._ctl_arrivals = self._ctl_completions = self._ctl_rejections = 0
        self._ctl_service_sum = 0.0

        decision = self.strategy.decide(obs)
        target = min(
            max(decision.desired_replicas, self.cluster.min_replicas), self.cluster.max_replicas
        )
        self._decisions.append((self.now, target, decision.reason))
        self._apply_scaling(target, decision.reason)

    def _apply_scaling(self, target: int, reason: str) -> None:
        committed = self._n_active + self._n_starting
        if target == committed:
            return
        launched = reactivated = cancelled = terminated = drained = 0
        if target > committed:
            need = target - committed
            # Reuse warm draining servers first: they are already paid for and ready.
            for server in sorted(
                (s for s in self._live.values() if s.state is ServerState.DRAINING),
                key=lambda s: s.id,
            ):
                if need == 0:
                    break
                self._reactivate(server)
                reactivated += 1
                need -= 1
            for _ in range(need):
                self._launch()
                launched += 1
            self._dispatch()
        else:
            excess = committed - target
            # 1. Cancel launches that have not finished booting (newest first).
            for server in sorted(
                (s for s in self._live.values() if s.state is ServerState.STARTING),
                key=lambda s: -s.id,
            ):
                if excess == 0:
                    break
                self._terminate(server)
                cancelled += 1
                excess -= 1
            # 2. Remove active servers, least loaded first; idle ones stop immediately,
            #    busy ones drain (no new work, finish in-flight requests, then stop).
            for server in sorted(
                (s for s in self._live.values() if s.state is ServerState.ACTIVE),
                key=lambda s: (s.in_flight, -s.id),
            ):
                if excess == 0:
                    break
                if server.in_flight == 0:
                    self._terminate(server)
                    terminated += 1
                else:
                    self._drain(server)
                    drained += 1
                excess -= 1
        self._scaling_events.append(
            ScalingEvent(
                time=self.now,
                from_replicas=committed,
                to_replicas=target,
                reason=reason,
                launched=launched,
                reactivated=reactivated,
                cancelled=cancelled,
                terminated=terminated,
                drained=drained,
            )
        )

    def _snapshot(self) -> None:
        self._snapshots.append(
            Snapshot(
                time=self.now,
                integrals=self._integrals.copy(),
                active=self._n_active,
                starting=self._n_starting,
                draining=self._n_draining,
                queue_length=len(self._queue),
                busy_slots=self._busy_active + self._busy_draining,
            )
        )

    # ------------------------------------------------------------ invariants

    def _verify(self) -> None:
        slots = self.cluster.slots_per_server
        live = list(self._live.values())
        counts = dict.fromkeys(ServerState, 0)
        busy = {ServerState.ACTIVE: 0, ServerState.DRAINING: 0}
        for server in live:
            counts[server.state] += 1
            if not 0 <= server.in_flight <= slots:
                raise InvariantViolationError(f"server {server.id} in_flight={server.in_flight}")
            if server.state is ServerState.STARTING and server.in_flight:
                raise InvariantViolationError(f"booting server {server.id} has work")
            if server.state in busy:
                busy[server.state] += server.in_flight
        expected = (self._n_starting, self._n_active, self._n_draining)
        actual = (
            counts[ServerState.STARTING],
            counts[ServerState.ACTIVE],
            counts[ServerState.DRAINING],
        )
        if expected != actual:
            raise InvariantViolationError(f"server counters {expected} != {actual}")
        if (busy[ServerState.ACTIVE], busy[ServerState.DRAINING]) != (
            self._busy_active,
            self._busy_draining,
        ):
            raise InvariantViolationError("busy-slot counters out of sync")
        if self._busy_active > self._n_active * slots:
            raise InvariantViolationError("capacity exceeded")
        if self._queue and self._peek_free() is not None:
            raise InvariantViolationError("work-conservation violated: idle slot with queue")
        if len(self._queue) > max(self.cluster.max_pending, 0):
            raise InvariantViolationError("queue exceeds max_pending")
        committed = self._n_active + self._n_starting
        if self._events and not (
            self.cluster.min_replicas <= committed <= self.cluster.max_replicas
        ):
            raise InvariantViolationError(f"committed replicas {committed} out of bounds")

    # ------------------------------------------------------------------ run

    def run(self) -> RawRun:
        cfg = self.scenario
        duration = cfg.duration_s
        started = wallclock.perf_counter()
        deadline = (
            started + self.wall_time_budget_s if self.wall_time_budget_s is not None else math.inf
        )

        initial = self.strategy.initial_replicas(
            self.cluster.min_replicas, self.cluster.max_replicas, self.cluster.initial_replicas
        )
        for _ in range(initial):
            server = self._new_server(ServerState.ACTIVE, initial=True)
            server.ready_at = 0.0
            self._n_active += 1
            self._mark_free(server)

        self._snapshot()  # t = 0
        k = 1
        while k * cfg.metrics_interval_s < duration:
            self._push(k * cfg.metrics_interval_s, EventKind.SAMPLE)
            k += 1
        self._push(cfg.control_interval_s, EventKind.CONTROL, 1)

        arrivals = self._arrivals
        n = len(arrivals)
        i = 0
        heap = self._heap
        arrival_kind = int(EventKind.ARRIVAL)
        while True:
            next_arrival = arrivals[i] if i < n else math.inf
            if heap and (heap[0][0], heap[0][1]) < (next_arrival, arrival_kind):
                t, kind, _, a, b = heapq.heappop(heap)
                if t >= duration:
                    break
                self._advance(t)
                if kind == EventKind.COMPLETION:
                    self._on_completion(a, b)
                elif kind == EventKind.SERVER_READY:
                    self._on_server_ready(a)
                elif kind == EventKind.SAMPLE:
                    self._snapshot()
                else:  # CONTROL; `a` is the tick index, avoiding cumulative float drift
                    self._on_control()
                    nxt = (a + 1) * cfg.control_interval_s
                    if nxt < duration:
                        self._push(nxt, EventKind.CONTROL, a + 1)
            else:
                if next_arrival >= duration:
                    break
                self._advance(next_arrival)
                self._on_arrival(i)
                i += 1

            self._events += 1
            if self.check_invariants:
                self._verify()
            if self._events % _BUDGET_CHECK_EVERY == 0 and wallclock.perf_counter() > deadline:
                raise SimulationBudgetExceededError(
                    f"simulation exceeded its {self.wall_time_budget_s:g}s wall-clock budget"
                )

        self._advance(duration)
        self._snapshot()
        for rid, state in enumerate(self._state):
            if state is RequestState.QUEUED or state is RequestState.IN_SERVICE:
                self._set_request_state(rid, RequestState.UNFINISHED)
            elif state is RequestState.PENDING:  # pragma: no cover - trace is within [0, T)
                raise InvalidTransitionError(f"request {rid} never arrived")

        return RawRun(
            arrival_times=self.trace.arrival_times,
            work=self.trace.work,
            start_times=np.asarray(self._start, dtype=np.float64),
            completion_times=np.asarray(self._completion, dtype=np.float64),
            states=np.asarray(self._state, dtype=np.int8),
            servers=self._servers,
            snapshots=self._snapshots,
            scaling_events=self._scaling_events,
            peak_queue_length=self._peak_queue,
            events_processed=self._events,
            wall_time_s=wallclock.perf_counter() - started,
            duration_s=duration,
            decisions=self._decisions,
        )
