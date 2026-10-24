"""Strategy C: predictive autoscaling with Holt's linear trend method.

Each tick the controller observes the arrival rate of the interval that just
ended and updates a level/trend estimate (double exponential smoothing)::

    level_t = alpha * r_t + (1 - alpha) * (level_{t-1} + trend_{t-1})
    trend_t = beta * (level_t - level_{t-1}) + (1 - beta) * trend_{t-1}
    forecast(h) = max(0, level_t + trend_t * h / interval)

The forecast horizon defaults to the provisioning delay plus one control
interval: capacity requested now becomes usable only after the delay, so it
should be sized for the load expected *then*.

Forecast demand in slots follows Little's law (``rate * mean service time``).
Capacity is sized so that demand runs at ``target_utilisation``. With
``reactive_floor`` enabled the controller also never sizes below what the
*current* observed demand needs, which bounds the damage of an under-forecast.

Only past arrivals reach the model: ``obs.arrivals`` counts requests whose
arrival time is at or before ``obs.time``.
"""

from __future__ import annotations

import math

from app.strategies.base import Decision, Observation, ScalingStrategy, replicas_for_slots
from app.strategies.config import PredictiveStrategyConfig


class HoltForecaster:
    """Holt's double exponential smoothing on a regularly sampled series."""

    def __init__(self, alpha: float, beta: float) -> None:
        self.alpha = alpha
        self.beta = beta
        self.level: float | None = None
        self.trend = 0.0
        self.observations = 0

    def update(self, value: float) -> None:
        self.observations += 1
        if self.level is None:
            self.level = value
            return
        previous = self.level
        self.level = self.alpha * value + (1 - self.alpha) * (previous + self.trend)
        self.trend = self.beta * (self.level - previous) + (1 - self.beta) * self.trend

    def forecast(self, steps_ahead: float) -> float:
        if self.level is None:
            return 0.0
        return max(0.0, self.level + self.trend * steps_ahead)


class PredictiveStrategy(ScalingStrategy):
    kind = "predictive"

    def __init__(self, config: PredictiveStrategyConfig) -> None:
        self.config = config
        self.forecaster = HoltForecaster(config.alpha, config.beta)
        self._last_scale_time = -math.inf
        #: Most recent forecast rate (exposed for diagnostics and tests).
        self.last_forecast_rps = 0.0

    def initial_replicas(self, min_replicas: int, max_replicas: int, default: int) -> int:
        return default

    def _backlog_slots(self, obs: Observation, service: float | None) -> float:
        if obs.queue_length == 0:
            return 0.0
        if service is None:
            return float(obs.queue_length)
        return obs.queue_length * service / self.config.backlog_drain_s

    def decide(self, obs: Observation) -> Decision:
        cfg = self.config
        self.forecaster.update(obs.arrival_rate)
        service = obs.service_time_estimate_s
        committed = obs.committed
        slots = obs.slots_per_server

        current_busy = obs.busy_slot_seconds / obs.interval_s if obs.interval_s > 0 else 0.0
        backlog = self._backlog_slots(obs, service)

        # Demand implied by the current interval (what a reactive controller sees).
        if service is None:
            current_demand = current_busy
        else:
            current_demand = max(current_busy, obs.arrival_rate * service)
        floor_needed = replicas_for_slots(
            (current_demand + backlog) / cfg.target_utilisation, slots
        )

        horizon = (
            cfg.horizon_s
            if cfg.horizon_s is not None
            else (obs.provisioning_delay_s + obs.interval_s)
        )
        forecast_rate = self.forecaster.forecast(horizon / obs.interval_s)
        self.last_forecast_rps = forecast_rate

        warm = self.forecaster.observations > cfg.warmup_intervals and service is not None
        if warm:
            assert service is not None
            forecast_demand = forecast_rate * service
            needed = replicas_for_slots((forecast_demand + backlog) / cfg.target_utilisation, slots)
            if cfg.reactive_floor:
                needed = max(needed, floor_needed)
            basis = f"forecast {forecast_rate:.1f} rps @ +{horizon:.0f}s"
        else:
            forecast_demand = current_demand
            needed = floor_needed
            basis = "warm-up (reactive sizing)"

        needed = min(max(needed, obs.min_replicas), obs.max_replicas)
        since_last = obs.time - self._last_scale_time

        if needed > committed:
            if since_last < cfg.scale_up_cooldown_s:
                return Decision(committed, f"hold: scale-up cooldown ({basis})")
            self._last_scale_time = obs.time
            return Decision(min(needed, committed + cfg.max_step_up), f"scale up: {basis}")

        if needed < committed:
            projected_util = (forecast_demand + backlog) / (committed * slots)
            if projected_util >= cfg.lower_threshold:
                return Decision(committed, f"hold: projected util {projected_util:.0%} in band")
            if obs.queue_length > 0 or obs.starting > 0:
                return Decision(committed, "hold: queue non-empty or servers booting")
            if since_last < cfg.scale_down_cooldown_s:
                return Decision(committed, f"hold: scale-down cooldown ({basis})")
            self._last_scale_time = obs.time
            return Decision(max(needed, committed - cfg.max_step_down), f"scale down: {basis}")

        return Decision(committed, f"hold: {basis}")
