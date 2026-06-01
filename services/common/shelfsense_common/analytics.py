"""Event-derived analytics — the funnel and store metrics, computed from behavioural events.

Pure logic (no IO, no DB, no FastAPI), so it is fully unit-testable and the Slice 2.6 API reuses it
verbatim (the same reason `conversion.py` lives here). Inputs are the prescribed `BehaviorEvent`s
([[EVENT_SCHEMA]]) plus the POS `Transaction`s; outputs are plain dataclasses the API wraps in
Pydantic responses.

Rubric-critical invariants (BUSINESS_RULES.md):
- **Session is the unit, no double-counting:** every figure is a count of *distinct* `visitor_id`s,
  so re-entries (same id) never inflate a stage.
- **Staff excluded** by the any-flag rule: a visitor is staff if *any* of their events is flagged.
- **Funnel stages are cumulative subsets** (purchase ⊆ billing ⊆ zone_visit ⊆ entry), so drop-off is
  always in [0, 100] and a purchaser is correctly also counted at every earlier stage.
- **Entry = unique in-store customers**, not door-crossings — ADR-0007 (crossings ≈ 0 on 2-min
  clips).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from shelfsense_common.contracts import BehaviorEvent, BehaviorEventType, Transaction
from shelfsense_common.conversion import (
    DEFAULT_LOW_SAMPLE,
    DEFAULT_WINDOW_MS,
    BillingPresence,
    correlate_conversions,
    pos_day_metrics,
)

# Funnel stage keys, in spec order (Entry -> Zone Visit -> Billing Queue -> Purchase).
STAGE_ENTRY = "entry"
STAGE_ZONE_VISIT = "zone_visit"
STAGE_BILLING_QUEUE = "billing_queue"
STAGE_PURCHASE = "purchase"

_ZONE_EVENT_TYPES = {
    BehaviorEventType.ZONE_ENTER,
    BehaviorEventType.ZONE_DWELL,
    BehaviorEventType.ZONE_EXIT,
}


def staff_visitor_ids(events: Iterable[BehaviorEvent]) -> set[str]:
    """Visitor ids flagged as staff by the **any-flag** rule (one staff event ⇒ staff visitor)."""
    flagged: dict[str, bool] = {}
    for e in events:
        flagged[e.visitor_id] = flagged.get(e.visitor_id, False) or e.is_staff
    return {vid for vid, is_staff in flagged.items() if is_staff}


def customer_visitor_ids(events: Iterable[BehaviorEvent]) -> set[str]:
    """Distinct non-staff visitor ids — the conversion denominator (unique visitors)."""
    events = list(events)
    return {e.visitor_id for e in events} - staff_visitor_ids(events)


def billing_presences(
    events: Iterable[BehaviorEvent], customers: set[str]
) -> list[BillingPresence]:
    """Billing-zone presences for *customers only* (staff never join the queue)."""
    return [
        BillingPresence(visitor_id=e.visitor_id, timestamp=e.timestamp)
        for e in events
        if e.event_type == BehaviorEventType.BILLING_QUEUE_JOIN and e.visitor_id in customers
    ]


@dataclass(frozen=True)
class FunnelStage:
    stage: str
    visitors: int
    drop_off_pct: float | None  # None for the first stage (nothing to drop from)


@dataclass(frozen=True)
class Funnel:
    stages: list[FunnelStage]
    conversion_rate: float
    data_confidence: str


@dataclass(frozen=True)
class StoreMetrics:
    unique_visitors: int
    conversion_rate: float
    data_confidence: str
    converted: int
    abandoned: int
    abandonment_rate: float
    avg_dwell_ms_by_zone: dict[str, float]
    max_queue_depth: int
    pos: dict


def _stage_sets(
    events: list[BehaviorEvent],
    transactions: Iterable[Transaction],
    window_ms: int,
    low_sample_threshold: int,
) -> tuple[dict[str, set[str]], float, str]:
    """Compute the cumulative visitor-id set reaching each funnel stage, plus conversion rate."""
    customers = customer_visitor_ids(events)
    presences = billing_presences(events, customers)
    conv = correlate_conversions(
        presences, transactions, customers, window_ms, low_sample_threshold
    )

    purchase = set(conv.converted_visitor_ids)
    # A purchaser implies billing; a billing visitor implies a zone visit — enforce the subset
    # chain so the funnel is monotonic regardless of event ordering/gaps.
    billing = {p.visitor_id for p in presences} | purchase
    zone_visit = {
        e.visitor_id
        for e in events
        if e.event_type in _ZONE_EVENT_TYPES and e.visitor_id in customers
    } | billing
    entry = customers | zone_visit

    sets = {
        STAGE_ENTRY: entry,
        STAGE_ZONE_VISIT: zone_visit,
        STAGE_BILLING_QUEUE: billing,
        STAGE_PURCHASE: purchase,
    }
    return sets, conv.conversion_rate, conv.data_confidence


def compute_funnel(
    events: Iterable[BehaviorEvent],
    transactions: Iterable[Transaction],
    *,
    window_ms: int = DEFAULT_WINDOW_MS,
    low_sample_threshold: int = DEFAULT_LOW_SAMPLE,
) -> Funnel:
    """Entry → Zone Visit → Billing Queue → Purchase, with per-stage drop-off %."""
    events = list(events)
    sets, conversion_rate, confidence = _stage_sets(
        events, transactions, window_ms, low_sample_threshold
    )

    order = [STAGE_ENTRY, STAGE_ZONE_VISIT, STAGE_BILLING_QUEUE, STAGE_PURCHASE]
    stages: list[FunnelStage] = []
    prev: int | None = None
    for stage in order:
        count = len(sets[stage])
        drop: float | None = None
        if prev is not None:
            drop = round((1 - count / prev) * 100, 1) if prev > 0 else 0.0
        stages.append(FunnelStage(stage=stage, visitors=count, drop_off_pct=drop))
        prev = count

    return Funnel(stages=stages, conversion_rate=conversion_rate, data_confidence=confidence)


def _avg_dwell_by_zone(events: list[BehaviorEvent], customers: set[str]) -> dict[str, float]:
    """Average dwell (ms) per zone from customers' ZONE_EXIT events.

    Each ZONE_EXIT carries that visit's total dwell, so a plain mean per zone is correct.
    """
    buckets: dict[str, list[int]] = {}
    for e in events:
        if (
            e.event_type == BehaviorEventType.ZONE_EXIT
            and e.zone_id is not None
            and e.visitor_id in customers
        ):
            buckets.setdefault(e.zone_id, []).append(e.dwell_ms)
    return {zone: round(sum(d) / len(d), 1) for zone, d in buckets.items()}


def compute_store_metrics(
    events: Iterable[BehaviorEvent],
    transactions: Iterable[Transaction],
    *,
    store_tz: str = "Asia/Kolkata",
    window_ms: int = DEFAULT_WINDOW_MS,
    low_sample_threshold: int = DEFAULT_LOW_SAMPLE,
) -> StoreMetrics:
    """Headline store KPIs computed live from ingested events + POS sales."""
    events = list(events)
    txns = list(transactions)
    customers = customer_visitor_ids(events)
    presences = billing_presences(events, customers)
    conv = correlate_conversions(presences, txns, customers, window_ms, low_sample_threshold)

    billing_visitors = {p.visitor_id for p in presences}
    abandonment_rate = (
        round(len(conv.abandoned_visitor_ids) / len(billing_visitors), 4)
        if billing_visitors
        else 0.0
    )

    # Queue depth is a customer metric, so exclude staff (any-flag) to stay consistent with the
    # billing funnel stage — a track that dips below the staff-darkness threshold on its JOIN event
    # but is staff overall must not inflate the observed queue.
    depths = [
        e.metadata.queue_depth
        for e in events
        if e.event_type == BehaviorEventType.BILLING_QUEUE_JOIN
        and e.metadata.queue_depth is not None
        and e.visitor_id in customers
    ]

    return StoreMetrics(
        unique_visitors=len(customers),
        conversion_rate=conv.conversion_rate,
        data_confidence=conv.data_confidence,
        converted=len(conv.converted_visitor_ids),
        abandoned=len(conv.abandoned_visitor_ids),
        abandonment_rate=abandonment_rate,
        avg_dwell_ms_by_zone=_avg_dwell_by_zone(events, customers),
        max_queue_depth=max(depths) if depths else 0,
        pos=pos_day_metrics(txns, store_tz),
    )
