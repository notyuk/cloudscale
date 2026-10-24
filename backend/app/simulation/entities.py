"""Request and server lifecycles.

Request lifecycle (every request ends in exactly one terminal state)::

    PENDING ──arrive──▶ QUEUED ──dispatch──▶ IN_SERVICE ──finish──▶ COMPLETED
       │                  │                     │
       └──queue full──▶ REJECTED               └──sim ends──▶ UNFINISHED
                          └──────sim ends────────────────────▶ UNFINISHED

A request that finds a free slot still passes through QUEUED, with zero wait.

Server lifecycle::

    STARTING ──ready──▶ ACTIVE ──scale down (busy)──▶ DRAINING ──last job done──▶ TERMINATED
       │                  │  ▲                            │
       │                  │  └──────scale up (reuse)──────┘
       │                  └──scale down (idle)──────────────────────────────────▶ TERMINATED
       └──scale down (cancel launch)────────────────────────────────────────────▶ TERMINATED

Only ACTIVE servers receive new work. DRAINING servers finish what they hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class RequestState(IntEnum):
    PENDING = 0
    QUEUED = 1
    IN_SERVICE = 2
    COMPLETED = 3
    REJECTED = 4
    UNFINISHED = 5


REQUEST_TRANSITIONS: dict[RequestState, frozenset[RequestState]] = {
    RequestState.PENDING: frozenset({RequestState.QUEUED, RequestState.REJECTED}),
    RequestState.QUEUED: frozenset({RequestState.IN_SERVICE, RequestState.UNFINISHED}),
    RequestState.IN_SERVICE: frozenset({RequestState.COMPLETED, RequestState.UNFINISHED}),
    RequestState.COMPLETED: frozenset(),
    RequestState.REJECTED: frozenset(),
    RequestState.UNFINISHED: frozenset(),
}

TERMINAL_REQUEST_STATES = frozenset(
    {RequestState.COMPLETED, RequestState.REJECTED, RequestState.UNFINISHED}
)


class ServerState(IntEnum):
    STARTING = 0
    ACTIVE = 1
    DRAINING = 2
    TERMINATED = 3


SERVER_TRANSITIONS: dict[ServerState, frozenset[ServerState]] = {
    ServerState.STARTING: frozenset({ServerState.ACTIVE, ServerState.TERMINATED}),
    ServerState.ACTIVE: frozenset({ServerState.DRAINING, ServerState.TERMINATED}),
    ServerState.DRAINING: frozenset({ServerState.ACTIVE, ServerState.TERMINATED}),
    ServerState.TERMINATED: frozenset(),
}


class InvalidTransitionError(RuntimeError):
    """Raised when the engine attempts an illegal lifecycle transition (a bug)."""


@dataclass(slots=True)
class Server:
    id: int
    state: ServerState
    launched_at: float
    ready_at: float | None = None
    terminated_at: float | None = None
    in_flight: int = 0
    #: Whether this server's id is currently present in the free-slot heap.
    in_free_heap: bool = False
    #: Servers present at t = 0 were never provisioned during the run.
    initial: bool = False

    def transition(self, new: ServerState) -> None:
        if new not in SERVER_TRANSITIONS[self.state]:
            raise InvalidTransitionError(f"server {self.id}: {self.state.name} -> {new.name}")
        self.state = new


@dataclass(frozen=True, slots=True)
class ScalingEvent:
    """A control decision that changed the committed replica count."""

    time: float
    from_replicas: int
    to_replicas: int
    reason: str
    launched: int
    reactivated: int
    cancelled: int
    terminated: int
    drained: int
