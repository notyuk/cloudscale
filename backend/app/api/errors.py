"""Exception handlers. Errors share one JSON shape; tracebacks are only logged."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas import ErrorDetail, ErrorResponse
from app.simulation.engine import SimulationBudgetExceededError
from app.simulation.runner import SimulationLimitError

logger = logging.getLogger("cloudscale.api")


class ServerBusyError(RuntimeError):
    """All simulation workers are occupied."""


def _response(
    code: int, error: str, message: str, details: list[ErrorDetail] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=error, message=message, details=details or [])
    return JSONResponse(status_code=code, content=body.model_dump())


def _validation_details(exc: RequestValidationError) -> list[ErrorDetail]:
    details = []
    for err in exc.errors():
        loc = [part for part in err.get("loc", ()) if isinstance(part, str | int)]
        details.append(
            ErrorDetail(loc=loc, msg=str(err.get("msg", "")), type=str(err.get("type", "")))
        )
    return details


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "The request body failed validation.",
            _validation_details(exc),
        )

    @app.exception_handler(SimulationLimitError)
    async def _limit(request: Request, exc: SimulationLimitError) -> JSONResponse:
        return _response(status.HTTP_422_UNPROCESSABLE_CONTENT, "limit_exceeded", str(exc))

    @app.exception_handler(SimulationBudgetExceededError)
    async def _budget(request: Request, exc: SimulationBudgetExceededError) -> JSONResponse:
        return _response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "simulation_too_expensive",
            f"{exc}. Reduce the duration, arrival rate or number of strategies.",
        )

    @app.exception_handler(ServerBusyError)
    async def _busy(request: Request, exc: ServerBusyError) -> JSONResponse:
        response = _response(status.HTTP_503_SERVICE_UNAVAILABLE, "server_busy", str(exc))
        response.headers["Retry-After"] = "5"
        return response

    @app.exception_handler(ValueError)
    async def _value(request: Request, exc: ValueError) -> JSONResponse:
        # Raised for semantically invalid combinations (e.g. fixed replicas out of bounds).
        return _response(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid_configuration", str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        error = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}.get(
            exc.status_code, "http_error"
        )
        return _response(exc.status_code, error, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return _response(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", "An internal error occurred."
        )
