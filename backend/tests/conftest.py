"""Shared helpers: hand-built traces and a scripted strategy for exact engine tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import pytest

from app.simulation.config import ClusterConfig, ScenarioConfig
from app.simulation.engine import RawRun, SimulationEngine
from app.strategies.base import Decision, Observation, ScalingStrategy
from app.workloads.config import ConstantWorkload
from app.workloads.generators import WorkloadTrace


class ScriptedStrategy(ScalingStrategy):
    """Returns pre-programmed decisions; records every observation it receives."""

    kind = "scripted"

    def __init__(
        self,
        initial: int,
        policy: Callable[[Observation], int] | None = None,
    ) -> None:
        self.initial = initial
        self.policy = policy
        self.observations: list[Observation] = []

    def initial_replicas(self, min_replicas: int, max_replicas: int, default: int) -> int:
        return self.initial

    def decide(self, obs: Observation) -> Decision:
        self.observations.append(obs)
        desired = self.policy(obs) if self.policy else obs.committed
        return Decision(desired, "scripted")


def make_scenario(duration_s: float = 100.0, **cluster: Any) -> ScenarioConfig:
    defaults: dict[str, Any] = {
        "slots_per_server": 1,
        "min_replicas": 1,
        "max_replicas": 10,
        "initial_replicas": 1,
        "provisioning_delay_s": 0.0,
    }
    defaults.update(cluster)
    return ScenarioConfig(
        duration_s=duration_s,
        workload=ConstantWorkload(rate=1.0),
        cluster=ClusterConfig(**defaults),
        control_interval_s=min(10.0, duration_s),
        metrics_interval_s=min(10.0, duration_s),
    )


def make_trace(
    arrivals: Sequence[float], work: Sequence[float], duration_s: float
) -> WorkloadTrace:
    return WorkloadTrace(
        arrival_times=np.asarray(arrivals, dtype=np.float64),
        work=np.asarray(work, dtype=np.float64),
        duration_s=duration_s,
    )


def run_engine(
    scenario: ScenarioConfig,
    arrivals: Sequence[float],
    work: Sequence[float],
    strategy: ScalingStrategy | None = None,
) -> RawRun:
    strategy = strategy or ScriptedStrategy(initial=scenario.cluster.initial_replicas)
    trace = make_trace(arrivals, work, scenario.duration_s)
    return SimulationEngine(scenario, trace, strategy, check_invariants=True).run()


@pytest.fixture
def scripted() -> type[ScriptedStrategy]:
    return ScriptedStrategy
