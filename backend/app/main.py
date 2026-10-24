"""FastAPI app factory.

Env vars: CLOUDSCALE_CORS_ORIGINS, CLOUDSCALE_MAX_CONCURRENT, CLOUDSCALE_MAX_BODY_BYTES.
"""

from __future__ import annotations

import logging
import os
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import __version__
from app.api.errors import register_error_handlers
from app.api.middleware import BodySizeLimitMiddleware
from app.api.routes import router


def create_app(
    *,
    cors_origins: list[str] | None = None,
    max_concurrent: int | None = None,
    max_body_bytes: int | None = None,
    queue_timeout_s: float = 10.0,
) -> FastAPI:
    if cors_origins is None:
        raw = os.environ.get("CLOUDSCALE_CORS_ORIGINS", "http://localhost:3000")
        cors_origins = [o.strip() for o in raw.split(",") if o.strip()]
    if max_concurrent is None:
        max_concurrent = int(os.environ.get("CLOUDSCALE_MAX_CONCURRENT", "2"))
    if max_body_bytes is None:
        max_body_bytes = int(os.environ.get("CLOUDSCALE_MAX_BODY_BYTES", "65536"))

    app = FastAPI(
        title="CloudScale API",
        version=__version__,
        description=(
            "Deterministic discrete-event simulation of autoscaling strategies. "
            "All times are seconds of simulated time; prices are per server-hour."
        ),
    )
    app.state.simulation_semaphore = threading.BoundedSemaphore(max_concurrent)
    app.state.queue_timeout_s = queue_timeout_s
    app.state.max_body_bytes = max_body_bytes

    register_error_handlers(app)
    app.include_router(router)
    app.add_middleware(GZipMiddleware, minimum_size=2_048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_body_bytes)
    return app


logging.basicConfig(level=logging.INFO)
app = create_app()
