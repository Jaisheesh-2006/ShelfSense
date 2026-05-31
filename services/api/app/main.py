"""ShelfSense API service (FastAPI).

Read surface for business insights + the gate-critical `/metrics`, `/healthz`, `/readyz`.
Business logic lives in routers/services, not here. Run: `uvicorn app.main:app`.
"""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.db import init_db
from app.metrics import HTTP_LATENCY, HTTP_REQUESTS, render_metrics
from app.routers import business, health
from shelfsense_common.config import get_settings
from shelfsense_common.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(service_name="api", level=settings.log_level)
log = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("api_starting", environment=settings.environment)
    try:
        init_db()
        log.info("db_initialised")
    except Exception as exc:  # don't crash the process; readiness will report not-ready
        log.warning("db_init_failed", error=str(exc))
    yield
    log.info("api_stopping")


app = FastAPI(
    title="ShelfSense API",
    version="0.1.0",
    description="Retail store-intelligence metrics derived from CCTV + POS data.",
    lifespan=lifespan,
)


@app.middleware("http")
async def observe_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
    start = time.perf_counter()
    response = await call_next(request)
    # Use the route template (not the raw path) to keep metric cardinality bounded.
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
    HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "An unexpected error occurred."}},
    )


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


@app.get("/", include_in_schema=False)
def root() -> dict[str, str]:
    return {"service": "shelfsense-api", "docs": "/docs", "metrics": "/metrics"}


app.include_router(health.router)
app.include_router(business.router)
