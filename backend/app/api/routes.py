"""API endpoints."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, get_args

from fastapi import APIRouter, Request

from app import __version__
from app.api.errors import ServerBusyError
from app.api.schemas import (
    MAX_COMPARE_STRATEGIES,
    CompareRequest,
    DefaultsResponse,
    ErrorResponse,
    HealthResponse,
    LimitsDescription,
    RunRequest,
    StrategyDescription,
    default_strategies,
)
from app.simulation.config import ScenarioConfig
from app.simulation.runner import (
    DEFAULT_LIMITS,
    RESULT_SCHEMA_VERSION,
    ComparisonResult,
    SimulationResult,
    compare,
)
from app.strategies.config import (
    FixedStrategyConfig,
    PredictiveStrategyConfig,
    ReactiveStrategyConfig,
)
from app.workloads.config import WorkloadConfig

router = APIRouter()

StrategyModel = FixedStrategyConfig | ReactiveStrategyConfig | PredictiveStrategyConfig

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    413: {"model": ErrorResponse, "description": "Request body too large"},
    422: {"model": ErrorResponse, "description": "Invalid or too expensive configuration"},
    503: {"model": ErrorResponse, "description": "All simulation workers busy"},
}

STRATEGY_DOCS: list[tuple[type[StrategyModel], str, str]] = [
    (FixedStrategyConfig, "Fixed capacity", "Constant replica count; the cost/latency baseline."),
    (
        ReactiveStrategyConfig,
        "Reactive (utilisation)",
        "Scales when windowed utilisation leaves a hysteresis band, sizing by target tracking "
        "with cooldowns and backlog awareness.",
    ),
    (
        PredictiveStrategyConfig,
        "Predictive (Holt forecast)",
        "Forecasts arrival rate one provisioning delay ahead with double exponential smoothing "
        "and provisions for the forecast, optionally floored by current demand.",
    ),
]


@contextmanager
def simulation_slot(request: Request) -> Iterator[None]:
    """Bound concurrent simulations; CPU-bound work must not pile up unboundedly."""
    semaphore: threading.BoundedSemaphore = request.app.state.simulation_semaphore
    if not semaphore.acquire(timeout=request.app.state.queue_timeout_s):
        raise ServerBusyError("All simulation workers are busy; retry shortly.")
    try:
        yield
    finally:
        semaphore.release()


@router.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__, schema_version=RESULT_SCHEMA_VERSION)


@router.get("/strategies", response_model=list[StrategyDescription], tags=["meta"])
def strategies() -> list[StrategyDescription]:
    return [
        StrategyDescription(
            type=model.model_fields["type"].default,
            name=name,
            description=description,
            parameters_schema=model.model_json_schema(),
            defaults=model().model_dump(),
        )
        for model, name, description in STRATEGY_DOCS
    ]


@router.get("/config/defaults", response_model=DefaultsResponse, tags=["meta"])
def defaults(request: Request) -> DefaultsResponse:
    patterns = [
        member.model_fields["pattern"].default for member in get_args(get_args(WorkloadConfig)[0])
    ]
    return DefaultsResponse(
        scenario=ScenarioConfig(),
        strategies=default_strategies(),
        workload_patterns=patterns,
        limits=LimitsDescription(
            max_expected_requests_per_run=DEFAULT_LIMITS.max_expected_requests,
            max_total_expected_requests=DEFAULT_LIMITS.max_total_expected_requests,
            max_compare_strategies=MAX_COMPARE_STRATEGIES,
            max_body_bytes=request.app.state.max_body_bytes,
            wall_time_budget_s=DEFAULT_LIMITS.wall_time_budget_s,
        ),
    )


@router.post(
    "/simulations/run",
    response_model=SimulationResult,
    responses=ERROR_RESPONSES,
    tags=["simulations"],
    summary="Run one strategy against a scenario",
)
def run(body: RunRequest, request: Request) -> SimulationResult:
    with simulation_slot(request):
        return compare(body.scenario, [body.strategy]).results[0]


@router.post(
    "/simulations/compare",
    response_model=ComparisonResult,
    responses=ERROR_RESPONSES,
    tags=["simulations"],
    summary="Run several strategies against one shared, seeded trace",
)
def compare_strategies(body: CompareRequest, request: Request) -> ComparisonResult:
    with simulation_slot(request):
        return compare(body.scenario, body.strategies)
