"""Autoscaling strategies and the factory that builds them from configuration."""

from __future__ import annotations

from app.strategies.base import Decision, Observation, ScalingStrategy
from app.strategies.config import (
    FixedStrategyConfig,
    PredictiveStrategyConfig,
    ReactiveStrategyConfig,
    StrategyConfig,
)
from app.strategies.fixed import FixedStrategy
from app.strategies.predictive import PredictiveStrategy
from app.strategies.reactive import ReactiveStrategy


def build_strategy(config: StrategyConfig) -> ScalingStrategy:
    """Instantiate a fresh (stateless-at-start) strategy for one simulation run."""
    match config:
        case FixedStrategyConfig():
            return FixedStrategy(config)
        case ReactiveStrategyConfig():
            return ReactiveStrategy(config)
        case PredictiveStrategyConfig():
            return PredictiveStrategy(config)
    raise TypeError(f"unknown strategy config {type(config).__name__}")  # pragma: no cover


__all__ = [
    "Decision",
    "FixedStrategy",
    "FixedStrategyConfig",
    "Observation",
    "PredictiveStrategy",
    "PredictiveStrategyConfig",
    "ReactiveStrategy",
    "ReactiveStrategyConfig",
    "ScalingStrategy",
    "StrategyConfig",
    "build_strategy",
]
