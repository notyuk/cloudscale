"""Request/response envelopes for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.simulation.config import ScenarioConfig
from app.strategies.config import (
    FixedStrategyConfig,
    PredictiveStrategyConfig,
    ReactiveStrategyConfig,
    StrategyConfig,
)

MAX_COMPARE_STRATEGIES = 5


def default_strategies() -> list[StrategyConfig]:
    return [FixedStrategyConfig(), ReactiveStrategyConfig(), PredictiveStrategyConfig()]


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioConfig = Field(default_factory=ScenarioConfig)
    strategy: StrategyConfig = Field(default_factory=ReactiveStrategyConfig)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: ScenarioConfig = Field(default_factory=ScenarioConfig)
    strategies: list[StrategyConfig] = Field(
        default_factory=default_strategies,
        min_length=1,
        max_length=MAX_COMPARE_STRATEGIES,
    )


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    schema_version: str


class StrategyDescription(BaseModel):
    type: str
    name: str
    description: str
    parameters_schema: dict[str, object]
    defaults: dict[str, object]


class LimitsDescription(BaseModel):
    max_expected_requests_per_run: int
    max_total_expected_requests: int
    max_compare_strategies: int
    max_body_bytes: int
    wall_time_budget_s: float | None


class DefaultsResponse(BaseModel):
    scenario: ScenarioConfig
    strategies: list[StrategyConfig]
    workload_patterns: list[str]
    limits: LimitsDescription


class ErrorDetail(BaseModel):
    loc: list[str | int] = Field(default_factory=list)
    msg: str
    type: str


class ErrorResponse(BaseModel):
    """Every non-2xx response has this shape."""

    error: str = Field(description="Machine-readable error code")
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
