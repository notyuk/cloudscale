from __future__ import annotations

import dataclasses
from typing import Any

import numpy as np
import pytest
from pydantic import ValidationError

from app.simulation.config import ClusterConfig, ScenarioConfig
from app.simulation.engine import SimulationEngine
from app.strategies import (
    FixedStrategy,
    FixedStrategyConfig,
    PredictiveStrategy,
    PredictiveStrategyConfig,
    ReactiveStrategy,
    ReactiveStrategyConfig,
    build_strategy,
)
from app.strategies.base import Observation, replicas_for_slots
from app.strategies.predictive import HoltForecaster
from app.workloads.config import PoissonWorkload, RampWorkload, ServiceTimeConfig
from app.workloads.generators import WorkloadTrace, generate_trace


def obs(**overrides: object) -> Observation:
    base = Observation(
        time=15.0,
        interval_s=15.0,
        active=4,
        starting=0,
        draining=0,
        queue_length=0,
        busy_slots=8,
        slots_per_server=4,
        server_speed=1.0,
        min_replicas=1,
        max_replicas=20,
        provisioning_delay_s=60.0,
        arrivals=150,
        completions=150,
        rejections=0,
        busy_slot_seconds=8 * 15.0,
        capacity_slot_seconds=16 * 15.0,
        service_time_estimate_s=0.4,
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def test_replicas_for_slots_rounding() -> None:
    assert replicas_for_slots(0, 4) == 0
    assert replicas_for_slots(4.0000000001, 4) == 1
    assert replicas_for_slots(4.1, 4) == 2


def test_fixed_holds_constant() -> None:
    strategy = FixedStrategy(FixedStrategyConfig(replicas=5))
    assert strategy.initial_replicas(1, 10, 2) == 5
    assert strategy.decide(obs(busy_slot_seconds=16 * 15.0, queue_length=500)).desired_replicas == 5


class TestReactive:
    def make(self, **kw: Any) -> ReactiveStrategy:
        return ReactiveStrategy(ReactiveStrategyConfig(**kw))

    def test_holds_inside_hysteresis_band(self) -> None:
        decision = self.make().decide(obs())  # 50% utilisation
        assert decision.desired_replicas == 4
        assert "band" in decision.reason

    def test_scales_up_with_target_tracking(self) -> None:
        # 15 of 16 slots busy -> ceil(15 / 0.6 / 4) = 7 replicas.
        decision = self.make().decide(obs(busy_slot_seconds=15 * 15.0))
        assert decision.desired_replicas == 7

    def test_backlog_increases_scale_up(self) -> None:
        busy = obs(busy_slot_seconds=16 * 15.0)
        with_queue = obs(busy_slot_seconds=16 * 15.0, queue_length=300)
        assert (
            self.make().decide(with_queue).desired_replicas
            > self.make().decide(busy).desired_replicas
        )

    def test_scale_up_respects_max_step_and_max_replicas(self) -> None:
        hot = obs(busy_slot_seconds=16 * 15.0, queue_length=10_000)
        assert self.make(max_step_up=2).decide(hot).desired_replicas == 6
        assert self.make().decide(dataclasses.replace(hot, max_replicas=8)).desired_replicas == 8

    def test_scale_up_cooldown(self) -> None:
        strategy = self.make(scale_up_cooldown_s=60)
        hot = obs(busy_slot_seconds=16 * 15.0)
        assert strategy.decide(hot).desired_replicas > 4
        again = strategy.decide(dataclasses.replace(hot, time=30.0, active=8))
        assert again.desired_replicas == 8
        assert "cooldown" in again.reason

    def test_does_not_double_count_booting_servers(self) -> None:
        strategy = self.make(scale_up_cooldown_s=0)
        hot = obs(busy_slot_seconds=16 * 15.0, active=4, starting=4)
        decision = strategy.decide(hot)
        assert decision.desired_replicas == 8  # ceil(16/0.6/4)=7 <= committed 8

    def test_scale_down_requires_empty_queue_and_cooldown(self) -> None:
        cold = obs(time=1_000.0, busy_slot_seconds=1 * 15.0)
        assert self.make().decide(cold).desired_replicas == 2  # max_step_down=2
        queued = dataclasses.replace(cold, queue_length=3)
        assert self.make().decide(queued).desired_replicas == 4
        strategy = self.make(scale_down_cooldown_s=300)
        strategy.decide(cold)
        assert (
            strategy.decide(dataclasses.replace(cold, time=1_015.0, active=2)).desired_replicas == 2
        )

    def test_scale_down_floor_is_min_replicas(self) -> None:
        idle = obs(time=1_000.0, busy_slot_seconds=0.0, min_replicas=3)
        assert self.make(max_step_down=10).decide(idle).desired_replicas == 3

    def test_window_averages_utilisation(self) -> None:
        strategy = self.make(observation_window_s=30)
        strategy.decide(obs(time=15.0, busy_slot_seconds=16 * 15.0, active=4))
        # A single cold interval after a hot one averages back into the band.
        decision = strategy.decide(obs(time=30.0, busy_slot_seconds=0.0))
        assert decision.desired_replicas == 4

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"lower_threshold": 0.8, "upper_threshold": 0.7},
            {"target_utilisation": 0.9, "upper_threshold": 0.8},
            {"lower_threshold": 0.6, "target_utilisation": 0.6},
        ],
    )
    def test_invalid_thresholds(self, kwargs: dict[str, float]) -> None:
        with pytest.raises(ValidationError):
            ReactiveStrategyConfig(**kwargs)


class TestPredictive:
    def test_holt_recovers_linear_trend(self) -> None:
        holt = HoltForecaster(alpha=0.5, beta=0.3)
        for t in range(50):
            holt.update(10 + 2 * t)
        assert holt.forecast(5) == pytest.approx(10 + 2 * 54, rel=0.01)

    def test_holt_forecast_never_negative(self) -> None:
        holt = HoltForecaster(alpha=0.9, beta=0.9)
        for value in [100, 50, 10, 0]:
            holt.update(value)
        assert holt.forecast(10) == 0.0

    def test_warmup_uses_reactive_sizing(self) -> None:
        strategy = PredictiveStrategy(PredictiveStrategyConfig(warmup_intervals=3))
        decision = strategy.decide(obs())
        assert "warm-up" in decision.reason

    def test_scales_ahead_of_rising_demand(self) -> None:
        cfg = PredictiveStrategyConfig(warmup_intervals=2, scale_up_cooldown_s=0)
        strategy = PredictiveStrategy(cfg)
        decision = None
        for k in range(1, 8):
            rate_arrivals = 15 * (10 + 5 * k)  # rate rising by 5 rps each tick
            decision = strategy.decide(obs(time=15.0 * k, arrivals=rate_arrivals))
        assert decision is not None
        current_need = replicas_for_slots(45 * 0.4 / 0.6, 4)
        assert strategy.last_forecast_rps > 45
        assert decision.desired_replicas > current_need

    def test_reactive_floor_prevents_underprovisioning(self) -> None:
        cfg = PredictiveStrategyConfig(warmup_intervals=0, scale_up_cooldown_s=0)
        strategy = PredictiveStrategy(cfg)
        strategy.decide(obs(arrivals=1_500))  # level 100 rps
        # A collapse in observed rate with a still-full cluster and queue must not scale down.
        decision = strategy.decide(
            obs(time=30.0, arrivals=0, queue_length=50, busy_slot_seconds=16 * 15.0)
        )
        assert decision.desired_replicas >= 4


def test_build_strategy_factory() -> None:
    assert isinstance(build_strategy(FixedStrategyConfig()), FixedStrategy)
    assert isinstance(build_strategy(ReactiveStrategyConfig()), ReactiveStrategy)
    assert isinstance(build_strategy(PredictiveStrategyConfig()), PredictiveStrategy)


def _decisions(scenario: ScenarioConfig, trace: WorkloadTrace, config: object) -> list[tuple]:  # type: ignore[type-arg]
    engine = SimulationEngine(scenario, trace, build_strategy(config))  # type: ignore[arg-type]
    return engine.run().decisions


@pytest.mark.parametrize(
    "config", [ReactiveStrategyConfig(), PredictiveStrategyConfig()], ids=["reactive", "predictive"]
)
def test_no_future_data_leakage(config: object) -> None:
    """Decisions up to time t must not depend on arrivals after t.

    Two traces share every request before t=1500 and differ wildly afterwards
    (the second has a huge surge). Every decision at or before t=1500 must match.
    """
    duration, cut = 3_000.0, 1_500.0
    scenario = ScenarioConfig(
        duration_s=duration,
        workload=RampWorkload(start_rate=5, end_rate=30),
        service=ServiceTimeConfig(mean_work=0.3),
        cluster=ClusterConfig(slots_per_server=4, max_replicas=50, provisioning_delay_s=60),
    )
    base = generate_trace(scenario.workload, scenario.service, duration, seed=3)
    surge = generate_trace(PoissonWorkload(rate=200), scenario.service, duration, seed=4)
    keep = base.arrival_times < cut
    late = surge.arrival_times >= cut
    altered = WorkloadTrace(
        arrival_times=np.concatenate([base.arrival_times[keep], surge.arrival_times[late]]),
        work=np.concatenate([base.work[keep], surge.work[late]]),
        duration_s=duration,
    )
    a = [d for d in _decisions(scenario, base, config) if d[0] <= cut]
    b = [d for d in _decisions(scenario, altered, config) if d[0] <= cut]
    assert a == b
    full_a = _decisions(scenario, base, config)
    full_b = _decisions(scenario, altered, config)
    assert full_a != full_b  # sanity: the surge does change later decisions
