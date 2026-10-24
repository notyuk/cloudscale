"""Strategy A: fixed capacity baseline."""

from __future__ import annotations

from app.strategies.base import Decision, Observation, ScalingStrategy
from app.strategies.config import FixedStrategyConfig


class FixedStrategy(ScalingStrategy):
    """Holds a constant replica count for the entire run.

    The replicas are warm at t = 0, so the baseline never pays a provisioning
    delay. Any other behaviour would penalise the baseline for a cold start that
    a real statically provisioned fleet would not have.
    """

    kind = "fixed"

    def __init__(self, config: FixedStrategyConfig) -> None:
        self.config = config

    def initial_replicas(self, min_replicas: int, max_replicas: int, default: int) -> int:
        return min(max(self.config.replicas, min_replicas), max_replicas)

    def decide(self, obs: Observation) -> Decision:
        return Decision(self.config.replicas, "fixed capacity")
