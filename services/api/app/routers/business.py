"""Business-insight endpoints (the 35-mark bucket).

Every value is computed from the database — never hardcoded. When analytics has not yet written
data the endpoints return honest zeros/empties (not fabricated numbers), and become meaningful as
the pipeline fills the tables. Metric definitions: docs/wiki/BUSINESS_RULES.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db import Transaction, VisitSession, get_session

router = APIRouter(prefix="/api/v1", tags=["business"])

# Ordered funnel stages. A session's `funnel_stage` is the furthest stage it reached.
FUNNEL_STAGES = ["entered", "browsed", "approached_checkout", "purchased"]


class FunnelStage(BaseModel):
    stage: str
    sessions: int
    rate_from_prev: float | None = None


class FunnelResponse(BaseModel):
    stages: list[FunnelStage]
    overall_conversion: float


class ConversionResponse(BaseModel):
    footfall: int
    transactions: int
    conversion_rate: float
    note: str


class FootfallSummary(BaseModel):
    total_footfall: int
    total_sessions: int
    staff_sessions: int


def _stage_index(stage: str) -> int:
    return FUNNEL_STAGES.index(stage) if stage in FUNNEL_STAGES else 0


@router.get("/footfall/summary", response_model=FootfallSummary)
def footfall_summary() -> FootfallSummary:
    with get_session() as s:
        total = s.scalar(select(func.count()).select_from(VisitSession)) or 0
        staff = (
            s.scalar(
                select(func.count()).select_from(VisitSession).where(VisitSession.is_staff.is_(True))
            )
            or 0
        )
    return FootfallSummary(total_footfall=total - staff, total_sessions=total, staff_sessions=staff)


@router.get("/funnel", response_model=FunnelResponse)
def funnel() -> FunnelResponse:
    """Session-based funnel with monotonic drop-off (each session counted once per stage)."""
    with get_session() as s:
        rows = s.execute(
            select(VisitSession.funnel_stage, func.count())
            .where(VisitSession.is_staff.is_(False))
            .group_by(VisitSession.funnel_stage)
        ).all()

    # Sessions whose furthest stage == k.
    reached_exactly = dict.fromkeys(FUNNEL_STAGES, 0)
    for stage, count in rows:
        if stage in reached_exactly:
            reached_exactly[stage] = count

    # Sessions reaching AT LEAST stage k (cumulative from the deepest stage backwards).
    stages: list[FunnelStage] = []
    prev_count: int | None = None
    for i, stage in enumerate(FUNNEL_STAGES):
        at_least = sum(reached_exactly[st] for st in FUNNEL_STAGES[i:])
        rate = None if prev_count in (None, 0) else round(at_least / prev_count, 4)
        stages.append(FunnelStage(stage=stage, sessions=at_least, rate_from_prev=rate))
        prev_count = at_least

    entered = stages[0].sessions if stages else 0
    purchased = stages[-1].sessions if stages else 0
    overall = round(purchased / entered, 4) if entered else 0.0
    return FunnelResponse(stages=stages, overall_conversion=overall)


@router.get("/conversion", response_model=ConversionResponse)
def conversion() -> ConversionResponse:
    """Conversion = transactions / footfall. See window caveat in BUSINESS_RULES.md."""
    with get_session() as s:
        footfall = (
            s.scalar(
                select(func.count()).select_from(VisitSession).where(VisitSession.is_staff.is_(False))
            )
            or 0
        )
        txns = s.scalar(select(func.count()).select_from(Transaction)) or 0
    rate = round(txns / footfall, 4) if footfall else 0.0
    return ConversionResponse(
        footfall=footfall,
        transactions=txns,
        conversion_rate=rate,
        note=(
            "Video window (~2 min) and POS window (full day) differ; see BUSINESS_RULES.md "
            "for the comparable-window methodology."
        ),
    )


@router.get("/sessions")
def list_sessions(limit: int = Query(50, le=500), offset: int = 0) -> dict[str, object]:
    with get_session() as s:
        total = s.scalar(select(func.count()).select_from(VisitSession)) or 0
        rows = s.scalars(
            select(VisitSession).order_by(VisitSession.started_ms.desc()).limit(limit).offset(offset)
        ).all()
    items = [
        {
            "id": r.id,
            "camera_id": r.camera_id,
            "entry_zone": r.entry_zone,
            "started_ms": r.started_ms,
            "ended_ms": r.ended_ms,
            "duration_ms": r.duration_ms,
            "funnel_stage": r.funnel_stage,
            "total_dwell_ms": r.total_dwell_ms,
            "is_staff": r.is_staff,
        }
        for r in rows
    ]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/kpis")
def kpis() -> dict[str, object]:
    summary = footfall_summary()
    conv = conversion()
    return {
        "footfall": summary.total_footfall,
        "transactions": conv.transactions,
        "conversion_rate": conv.conversion_rate,
    }
