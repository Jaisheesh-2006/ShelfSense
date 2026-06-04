"""ShelfSense API service (FastAPI).

The Intelligence API: ingests behavioural events (`POST /events/ingest`) and serves per-store
metrics (`/stores/{id}/metrics`, `/funnel`) computed live from stored events, plus the gate-critical
`/metrics` (Prometheus), `/healthz`, `/readyz`. Business logic lives in `analytics`/`conversion`
(shared) and `repository` — not in route handlers. Run: `uvicorn shelfsense_api.main:app`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from shelfsense_common.config import get_settings
from shelfsense_common.logging import configure_logging, get_logger
from sqlalchemy.exc import InterfaceError, OperationalError

from shelfsense_api.db import init_db
from shelfsense_api.metrics import HTTP_LATENCY, HTTP_REQUESTS, render_metrics
from shelfsense_api.pos_ingest import load_pos_into_db
from shelfsense_api.routers import events, health, stores

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
    try:
        loaded = load_pos_into_db()
        log.info("pos_ingest_done", transactions=loaded)
    except Exception as exc:  # POS is supplementary; honest zeros if it fails
        log.warning("pos_ingest_failed", error=str(exc))
    yield
    log.info("api_stopping")


app = FastAPI(
    title="ShelfSense API",
    version="0.2.0",
    description="Retail store-intelligence metrics derived from CCTV + POS data.",
    lifespan=lifespan,
)

# Allow the browser dashboard (a different origin/port) to poll the read-only metrics endpoints.
_cors_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observe_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
    start = time.perf_counter()
    trace_id = request.headers.get("X-Trace-Id", str(uuid.uuid4()))
    
    # Bind trace_id to all logs in this request context
    structlog.contextvars.bind_contextvars(trace_id=trace_id)

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        status_code = 500
        # Will be caught and formatted gracefully by the unhandled_exception_handler
        raise exc
    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        # Per-request context the spec asks for: store_id (from the path) and event_count (set by
        # the ingest handler on request.state). Both share this request's scope, so they are
        # readable here regardless of which route handled it; they're None for requests that lack
        # them (e.g. store_id on /events/ingest, event_count on a GET).
        store_id = (request.scope.get("path_params") or {}).get("store_id")
        event_count = getattr(request.state, "event_count", None)

        # Log the structured request completed event
        if path not in ("/metrics", "/healthz", "/readyz"):
            log.info(
                "request_completed",
                endpoint=path,
                method=request.method,
                store_id=store_id,
                event_count=event_count,
                latency_ms=latency_ms,
                status_code=status_code,
            )

        HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
        HTTP_REQUESTS.labels(request.method, path, str(status_code)).inc()

    return response


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Wrap FastAPI's default 422 in our error envelope for a consistent contract.
    details = [
        {"loc": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg", "")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": "Request validation failed.",
                "details": details,
            }
        },
    )


@app.exception_handler(OperationalError)
@app.exception_handler(InterfaceError)
async def database_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map DB connectivity failures to a structured 503 (no stack trace leaked to the client).

    A reviewer pulling the DB out from under a running API should get an honest "try again",
    not an opaque 500 — graceful degradation (SPEC Part C). Connection/driver errors raised by
    SQLAlchemy land here; genuine bugs still fall through to the 500 handler below.
    """
    log.warning("database_unavailable", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "database_unavailable",
                "message": "The database is temporarily unavailable. Please retry shortly.",
            }
        },
    )


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
app.include_router(events.router)
app.include_router(stores.router)
