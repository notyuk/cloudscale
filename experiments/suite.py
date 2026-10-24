"""Benchmark scenario definitions."""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.simulation.config import ClusterConfig, ScenarioConfig, SlaConfig
from app.strategies import (
    FixedStrategyConfig,
    PredictiveStrategyConfig,
    ReactiveStrategyConfig,
    StrategyConfig,
)
from app.workloads.config import (
    BurstyWorkload,
    PoissonWorkload,
    RampWorkload,
    ServiceTimeConfig,
    SinusoidalWorkload,
    SpikeWorkload,
    WorkloadConfig,
)
from app.workloads.generators import expected_arrivals, peak_rate

SEEDS = [0, 1, 2, 3, 4]
SERVICE = ServiceTimeConfig(distribution="exponential", mean_work=0.2)
CLUSTER = ClusterConfig(
    slots_per_server=4,
    min_replicas=1,
    max_replicas=20,
    initial_replicas=2,
    provisioning_delay_s=60,
)
TARGET = 0.75  # utilisation the fixed baselines are sized for


@dataclass(frozen=True)
class Experiment:
    name: str
    description: str
    workload: WorkloadConfig
    duration_s: float = 3_600.0
    cluster: ClusterConfig = CLUSTER
    extra: tuple[StrategyConfig, ...] = ()

    def scenario(self, seed: int) -> ScenarioConfig:
        return ScenarioConfig(
            duration_s=self.duration_s,
            seed=seed,
            workload=self.workload,
            service=SERVICE,
            cluster=self.cluster,
            sla=SlaConfig(latency_threshold_s=1.0),
            control_interval_s=15.0,
            metrics_interval_s=60.0,
        )

    def fixed_replicas(self, rate: float) -> int:
        slots = rate * SERVICE.mean_work / TARGET
        n = math.ceil(slots / self.cluster.slots_per_server)
        return min(max(n, self.cluster.min_replicas), self.cluster.max_replicas)

    def strategies(self) -> list[StrategyConfig]:
        mean = expected_arrivals(self.workload, self.duration_s) / self.duration_s
        return [
            FixedStrategyConfig(replicas=self.fixed_replicas(mean), label="fixed-mean"),
            FixedStrategyConfig(
                replicas=self.fixed_replicas(peak_rate(self.workload)), label="fixed-peak"
            ),
            ReactiveStrategyConfig(),
            PredictiveStrategyConfig(),
            *self.extra,
        ]


# Same reactive controller with an aggressive scale-down policy, to show how much of the
# post-spike cost comes from the default's conservative scale-down.
FAST_DOWN = ReactiveStrategyConfig(
    label="reactive-fast-down", scale_down_cooldown_s=60, max_step_down=10
)


EXPERIMENTS = [
    Experiment(
        "constant",
        "Steady Poisson traffic at 30 req/s.",
        PoissonWorkload(rate=30),
    ),
    Experiment(
        "periodic",
        "Sinusoidal traffic, 30 ± 20 req/s with a 20 minute period.",
        SinusoidalWorkload(base_rate=30, amplitude=20, period_s=1_200),
    ),
    Experiment(
        "bursty",
        "MMPP: 15 req/s with bursts to 75 req/s (mean 60 s bursts every ~5 min).",
        BurstyWorkload(base_rate=15, peak_multiplier=5, mean_burst_s=60, mean_gap_s=300),
        extra=(FAST_DOWN,),
    ),
    Experiment(
        "spike",
        "10 req/s with a single 5 minute spike to 80 req/s at t = 20 min.",
        SpikeWorkload(base_rate=10, spike_rate=80, spike_start_s=1_200, spike_duration_s=300),
        extra=(FAST_DOWN,),
    ),
    Experiment(
        "ramp",
        "Load growing linearly from 5 to 60 req/s over the hour.",
        RampWorkload(start_rate=5, end_rate=60),
    ),
    Experiment(
        "overload",
        "100 req/s against a cluster capped at 4 servers (80 req/s nominal capacity).",
        PoissonWorkload(rate=100),
        duration_s=1_800.0,
        cluster=CLUSTER.model_copy(update={"max_replicas": 4}),
    ),
]

# Short versions used by CI to check that results reproduce exactly.
QUICK = [
    Experiment(
        "periodic-quick",
        "Sinusoidal traffic over 10 minutes.",
        SinusoidalWorkload(base_rate=30, amplitude=20, period_s=300),
        duration_s=600.0,
    ),
    Experiment(
        "spike-quick",
        "10 req/s with a 2 minute spike to 80 req/s over 10 minutes.",
        SpikeWorkload(base_rate=10, spike_rate=80, spike_start_s=200, spike_duration_s=120),
        duration_s=600.0,
    ),
]
