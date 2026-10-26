"""Reactive autoscaler: utilisation thresholds trigger, target tracking sizes."""

from __future__ import annotations

import math
from collections import deque

from app.strategies.base import Decision, Observation, ScalingStrategy, replicas_for_slots
from app.strategies.config import ReactiveStrategyConfig


class ReactiveStrategy(ScalingStrategy):
    kind = "reactive"

    def __init__(self, config: ReactiveStrategyConfig) -> None:
        self.config = config
        # (tick time, interval seconds, busy slot-seconds, capacity slot-seconds)
        self._window: deque[tuple[float, float, float, float]] = deque()
        self._last_scale_time = -math.inf

    def initial_replicas(self, min_replicas: int, max_replicas: int, default: int) -> int:
        return default

    def _window_stats(self, obs: Observation) -> tuple[float, float]:
        """Return (utilisation, mean busy slots) over the observation window."""
        self._window.append(
            (obs.time, obs.interval_s, obs.busy_slot_seconds, obs.capacity_slot_seconds)
        )
        while self._window and self._window[0][0] <= obs.time - self.config.observation_window_s:
            self._window.popleft()
        span = sum(w[1] for w in self._window)
        busy = sum(w[2] for w in self._window)
        capacity = sum(w[3] for w in self._window)
        utilisation = busy / capacity if capacity > 0 else 1.0 if obs.queue_length > 0 else 0.0
        return utilisation, (busy / span if span > 0 else 0.0)

    def _backlog_slots(self, obs: Observation) -> float:
        """Extra slots needed to clear the queue within ``backlog_drain_s``."""
        if obs.queue_length == 0:
            return 0.0
        service = obs.service_time_estimate_s
        if service is None:
            # No completion observed yet: assume each queued request needs a slot.
            return float(obs.queue_length)
        return obs.queue_length * service / self.config.backlog_drain_s

    def decide(self, obs: Observation) -> Decision:
        cfg = self.config
        utilisation, mean_busy = self._window_stats(obs)
        committed = obs.committed
        since_last = obs.time - self._last_scale_time

        demand_slots = mean_busy + self._backlog_slots(obs)
        needed = replicas_for_slots(demand_slots / cfg.target_utilisation, obs.slots_per_server)

        if utilisation > cfg.upper_threshold:
            if since_last < cfg.scale_up_cooldown_s:
                return Decision(committed, f"hold: scale-up cooldown ({utilisation:.0%} util)")
            if needed <= committed:
                return Decision(committed, "hold: required capacity already provisioned/booting")
            desired = min(needed, committed + cfg.max_step_up, obs.max_replicas)
            if desired <= committed:
                return Decision(committed, "hold: at max_replicas")
            self._last_scale_time = obs.time
            return Decision(
                desired, f"scale up: util {utilisation:.0%} > {cfg.upper_threshold:.0%}"
            )

        if utilisation < cfg.lower_threshold:
            if obs.queue_length > 0 or obs.starting > 0:
                return Decision(committed, "hold: queue non-empty or servers booting")
            if since_last < cfg.scale_down_cooldown_s:
                return Decision(committed, "hold: scale-down cooldown")
            desired = max(needed, committed - cfg.max_step_down, obs.min_replicas)
            if desired >= committed:
                return Decision(committed, "hold: at minimum required capacity")
            self._last_scale_time = obs.time
            return Decision(
                desired, f"scale down: util {utilisation:.0%} < {cfg.lower_threshold:.0%}"
            )

        return Decision(committed, "hold: within hysteresis band")
