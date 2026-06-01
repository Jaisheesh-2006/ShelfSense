"""Per-store endpoints — `GET /stores/{id}/{metrics,funnel,heatmap,anomalies}`.

Thin adapters: load the store's events + POS sales from the DB, hand them to the pure
`shelfsense_common.analytics` functions, and shape the result as Pydantic responses. No business
logic lives here (it is all in `analytics`/`conversion`, which are unit-tested without a DB).
Outputs are computed live per request (real-time, never cached/hardcoded).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from shelfsense_common.analytics import (
    compute_funnel,
    compute_heatmap,
    compute_store_metrics,
    detect_anomalies,
)
from shelfsense_common.config import Settings, get_settings
from shelfsense_common.contracts import BehaviorEvent, Transaction

from shelfsense_api.db import get_session
from shelfsense_api.repository import fetch_events, fetch_transactions

router = APIRouter(prefix="/stores", tags=["stores"])


class FunnelStageOut(BaseModel):
    stage: str
    visitors: int
    drop_off_pct: float | None = None


class FunnelResponse(BaseModel):
    store_id: str
    stages: list[FunnelStageOut]
    conversion_rate: float
    data_confidence: str


class PosMetrics(BaseModel):
    transaction_count: int
    total_gmv: float
    avg_basket: float
    top_department: str | None = None
    peak_hour: int | None = None


class MetricsResponse(BaseModel):
    store_id: str
    unique_visitors: int
    conversion_rate: float
    data_confidence: str
    converted: int
    abandoned: int
    abandonment_rate: float
    avg_dwell_ms_by_zone: dict[str, float]
    max_queue_depth: int
    pos: PosMetrics


def _load(store_id: str) -> tuple[Settings, list[BehaviorEvent], list[Transaction]]:
    settings = get_settings()
    with get_session() as session:
        events = fetch_events(session, store_id)
        txns = fetch_transactions(session)
    return settings, events, txns


@router.get("/{store_id}/funnel", response_model=FunnelResponse)
def store_funnel(store_id: str) -> FunnelResponse:
    settings, events, txns = _load(store_id)
    funnel = compute_funnel(
        events,
        txns,
        window_ms=settings.pos_correlation_window_ms,
        low_sample_threshold=settings.conversion_low_sample_threshold,
    )
    return FunnelResponse(
        store_id=store_id,
        stages=[
            FunnelStageOut(stage=st.stage, visitors=st.visitors, drop_off_pct=st.drop_off_pct)
            for st in funnel.stages
        ],
        conversion_rate=funnel.conversion_rate,
        data_confidence=funnel.data_confidence,
    )


@router.get("/{store_id}/metrics", response_model=MetricsResponse)
def store_metrics(store_id: str) -> MetricsResponse:
    settings, events, txns = _load(store_id)
    metrics = compute_store_metrics(
        events,
        txns,
        store_tz=settings.store_timezone,
        window_ms=settings.pos_correlation_window_ms,
        low_sample_threshold=settings.conversion_low_sample_threshold,
    )
    return MetricsResponse(
        store_id=store_id,
        unique_visitors=metrics.unique_visitors,
        conversion_rate=metrics.conversion_rate,
        data_confidence=metrics.data_confidence,
        converted=metrics.converted,
        abandoned=metrics.abandoned,
        abandonment_rate=metrics.abandonment_rate,
        avg_dwell_ms_by_zone=metrics.avg_dwell_ms_by_zone,
        max_queue_depth=metrics.max_queue_depth,
        pos=PosMetrics(**metrics.pos),
    )


class ZoneCellOut(BaseModel):
    zone: str
    visits: int
    avg_dwell_ms: float
    score: float  # 0-100, normalised to the busiest zone


class HeatmapResponse(BaseModel):
    store_id: str
    zones: list[ZoneCellOut]
    data_confidence: str


class AnomalyOut(BaseModel):
    type: str
    severity: str
    message: str
    suggested_action: str
    zone_id: str | None = None
    value: float | None = None


class AnomaliesResponse(BaseModel):
    store_id: str
    evaluated_at: datetime | None  # the latest event time (recording-relative); null if no events
    anomalies: list[AnomalyOut]


@router.get("/{store_id}/heatmap", response_model=HeatmapResponse)
def store_heatmap(store_id: str) -> HeatmapResponse:
    settings, events, _ = _load(store_id)
    heatmap = compute_heatmap(
        events, low_sample_threshold=settings.conversion_low_sample_threshold
    )
    return HeatmapResponse(
        store_id=store_id,
        zones=[
            ZoneCellOut(
                zone=z.zone, visits=z.visits, avg_dwell_ms=z.avg_dwell_ms, score=z.score
            )
            for z in heatmap.zones
        ],
        data_confidence=heatmap.data_confidence,
    )


@router.get("/{store_id}/anomalies", response_model=AnomaliesResponse)
def store_anomalies(store_id: str) -> AnomaliesResponse:
    settings, events, txns = _load(store_id)
    anomalies = detect_anomalies(
        events,
        txns,
        store_tz=settings.store_timezone,
        window_ms=settings.pos_correlation_window_ms,
        low_sample_threshold=settings.conversion_low_sample_threshold,
        queue_warn=settings.anomaly_queue_depth_warn,
        queue_critical=settings.anomaly_queue_depth_critical,
        conversion_baseline=settings.anomaly_conversion_baseline,
        conversion_drop_pct=settings.anomaly_conversion_drop_pct,
        dead_zone_minutes=settings.anomaly_dead_zone_minutes,
        open_hour=settings.store_open_hour,
        close_hour=settings.store_close_hour,
    )
    evaluated_at = max((e.timestamp for e in events), default=None)
    return AnomaliesResponse(
        store_id=store_id,
        evaluated_at=evaluated_at,
        anomalies=[
            AnomalyOut(
                type=a.type,
                severity=a.severity,
                message=a.message,
                suggested_action=a.suggested_action,
                zone_id=a.zone_id,
                value=a.value,
            )
            for a in anomalies
        ],
    )
