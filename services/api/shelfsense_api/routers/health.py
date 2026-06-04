"""Liveness, readiness, and the operational `/health` feed-freshness view."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from shelfsense_common.analytics import feed_status
from shelfsense_common.config import get_settings

from shelfsense_api.db import get_session, ping_db
from shelfsense_api.repository import latest_event_ms_by_store

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. Always 200 if serving."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> dict[str, object]:
    """Readiness: dependencies reachable. 503 if not, so orchestrators hold traffic."""
    deps = {"postgres": ping_db()}
    ready = all(deps.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"ready": ready, "dependencies": deps}


class StoreHealth(BaseModel):
    store_id: str
    last_event_at: datetime
    lag_seconds: float | None
    stale_feed: bool


class HealthResponse(BaseModel):
    status: str  # "ok" | "degraded"
    reference_at: datetime
    strict_now: bool
    stores: list[StoreHealth]


def _to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Operational health: per-store feed freshness + `STALE_FEED`.

    Freshness is **recording-relative** by default — each store is measured against **its own**
    latest ingested event, so a replayed historical clip (of any length) reads healthy and a shorter
    clip isn't falsely flagged against a longer one. Set `HEALTH_STRICT_NOW=true` to compare against
    real wall-clock time (the right behaviour for a live feed, where STALE_FEED is the on-call
    signal). `status` is `degraded` if the DB is unreachable or any store's feed is stale.
    """
    settings = get_settings()
    db_ok = ping_db()
    try:
        with get_session() as session:
            by_store = latest_event_ms_by_store(session)
    except Exception:
        by_store = {}
        db_ok = False

    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    # `reference_at` shown to the caller: real wall-clock now (strict) or the latest event ingested
    # across all stores (recording-relative — so an old replayed clip reads healthy).
    reference_ms = now_ms if settings.health_strict_now else max(by_store.values(), default=now_ms)

    stores: list[StoreHealth] = []
    any_stale = False
    for store_id, last_ms in sorted(by_store.items()):
        # Per-store freshness. In recording-relative mode a fully-replayed clip is *complete*, not
        # stale, so each store is measured against ITS OWN latest event — otherwise a store whose
        # clip simply ends earlier than another's (different clip lengths/start times) would be
        # falsely flagged STALE_FEED against a global reference. STALE_FEED is a live-ops signal, so
        # it fires only in strict mode (against real wall-clock).
        store_reference_ms = now_ms if settings.health_strict_now else last_ms
        fs = feed_status(last_ms, store_reference_ms, settings.health_stale_feed_minutes)
        any_stale = any_stale or fs.stale_feed
        stores.append(
            StoreHealth(
                store_id=store_id,
                last_event_at=_to_dt(last_ms),
                lag_seconds=fs.lag_seconds,
                stale_feed=fs.stale_feed,
            )
        )

    return HealthResponse(
        status="ok" if (db_ok and not any_stale) else "degraded",
        reference_at=_to_dt(reference_ms),
        strict_now=settings.health_strict_now,
        stores=stores,
    )
