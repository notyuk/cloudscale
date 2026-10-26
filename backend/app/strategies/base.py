"""Strategy interface.

Strategies only receive an Observation built from past events, so they can't
see the workload trace. Replica bounds are enforced by the engine.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything a strategy may know at a control tick.

    Interval quantities cover ``(time - interval_s, time]``.
    """

    time: float
    interval_s: float

    # Instantaneous cluster state.
    active: int
    starting: int
    draining: int
    queue_length: int
    busy_slots: int

    # Static cluster parameters (known in advance, not workload data).
    slots_per_server: int
    server_speed: float
    min_replicas: int
    max_replicas: int
    provisioning_delay_s: float

    # Aggregates over the last control interval.
    arrivals: int
    completions: int
    rejections: int
    busy_slot_seconds: float
    capacity_slot_seconds: float

    # Exponentially weighted mean of observed service durations of *completed*
    # requests, in seconds. ``None`` until the first completion.
    service_time_estimate_s: float | None

    @property
    def committed(self) -> int:
        """Servers that are running or have been paid for and are booting."""
        return self.active + self.starting

    @property
    def utilisation(self) -> float:
        """Time-weighted fraction of serving slots that were busy in the interval."""
        if self.capacity_slot_seconds <= 0:
            return 1.0 if self.busy_slot_seconds > 0 or self.queue_length > 0 else 0.0
        return self.busy_slot_seconds / self.capacity_slot_seconds

    @property
    def arrival_rate(self) -> float:
        return self.arrivals / self.interval_s if self.interval_s > 0 else 0.0


@dataclass(frozen=True, slots=True)
class Decision:
    """A strategy's answer: the total number of committed replicas it wants."""

    desired_replicas: int
    reason: str


class ScalingStrategy(ABC):
    """Base class for autoscaling controllers."""

    #: Stable identifier, e.g. ``"reactive"``.
    kind: str

    @abstractmethod
    def initial_replicas(self, min_replicas: int, max_replicas: int, default: int) -> int:
        """Warm replicas present at t = 0 (already provisioned, no delay)."""

    @abstractmethod
    def decide(self, obs: Observation) -> Decision:
        """Return the desired committed replica count for this tick."""


def replicas_for_slots(slots: float, slots_per_server: int) -> int:
    """Smallest server count providing at least ``slots`` slots.

    A small epsilon prevents float noise (e.g. 3.0000000004) from adding a server.
    """
    if slots <= 0:
        return 0
    return math.ceil(slots / slots_per_server - 1e-9)
