"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from shelfsense_api.db import ping_db
from shelfsense_api.redis_client import ping_redis

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Always 200 if serving."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> dict[str, object]:
    """Readiness: dependencies reachable. 503 if not, so orchestrators hold traffic."""
    deps = {"postgres": ping_db(), "redis": ping_redis()}
    ready = all(deps.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": ready, "dependencies": deps}
