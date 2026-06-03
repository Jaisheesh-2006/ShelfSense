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
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from shelfsense_common.contracts import (
    BehaviorEvent,
    BehaviorEventType,
    CameraRole,
    Transaction,
)
from shelfsense_common.conversion import (
    DEFAULT_LOW_SAMPLE,
    DEFAULT_WINDOW_MS,
    BillingPresence,
    correlate_conversions,
    pos_day_metrics,
)
from shelfsense_common.stores import DEFAULT_STORE_ID, get_store

# Funnel stage keys, in spec order (Entry -> Zone Visit -> Billing Queue -> Purchase).
STAGE_ENTRY = "entry"
STAGE_ZONE_VISIT = "zone_visit"
STAGE_BILLING_QUEUE = "billing_queue"
STAGE_PURCHASE = "purchase"

# Anomaly severities + types (Slice 2.7).
SEV_INFO = "INFO"
SEV_WARN = "WARN"
SEV_CRITICAL = "CRITICAL"
ANOMALY_QUEUE_SPIKE = "QUEUE_SPIKE"
ANOMALY_CONVERSION_DROP = "CONVERSION_DROP"
ANOMALY_DEAD_ZONE = "DEAD_ZONE"

_ZONE_EVENT_TYPES = {
    BehaviorEventType.ZONE_ENTER,
    BehaviorEventType.ZONE_DWELL,
    BehaviorEventType.ZONE_EXIT,
}


def _is_customer_zone_event(e: BehaviorEvent, customers: set[str]) -> bool:
    """A zone event (with a zone) made by a non-staff customer."""
    return e.event_type in _ZONE_EVENT_TYPES and e.zone_id is not None and e.visitor_id in customers


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
    # billing funnel stage — a track that dips below the staff uniform-colour threshold on its JOIN
    # event but is staff overall must not inflate the observed queue.
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


# --------------------------------------------------------------------------------------------------
# Slice 2.7 — heatmap, anomalies, feed health (all pure)
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ZoneCell:
    zone: str
    visits: int  # distinct customers who visited the zone
    avg_dwell_ms: float
    score: float  # 0-100, visits normalised to the busiest zone (=100)


@dataclass(frozen=True)
class Heatmap:
    zones: list[ZoneCell]
    data_confidence: str


@dataclass(frozen=True)
class Anomaly:
    type: str
    severity: str  # INFO | WARN | CRITICAL
    message: str
    suggested_action: str
    zone_id: str | None = None
    value: float | None = None


@dataclass(frozen=True)
class FeedStatus:
    last_event_ms: int | None
    reference_ms: int
    lag_seconds: float | None
    stale_feed: bool


def _customer_visitors_by_zone(
    events: list[BehaviorEvent], customers: set[str]
) -> dict[str, set[str]]:
    """Distinct customer visitor-ids per zone (from any zone event)."""
    by_zone: dict[str, set[str]] = {}
    for e in events:
        if _is_customer_zone_event(e, customers):
            by_zone.setdefault(e.zone_id, set()).add(e.visitor_id)  # type: ignore[arg-type]
    return by_zone


def monitored_customer_zones(store_id: str = DEFAULT_STORE_ID) -> set[str]:
    """Customer-facing zones a camera actually covers (excludes the entrance + the staff stockroom).

    These are the zones a *dead-zone* anomaly can reason about — we only know a zone is empty if a
    camera watches it. Derived from the store's config (registry), tracking the layout per store,
    not a constant. An unknown store id yields an empty set (no zones to assert silence on).
    """
    store = get_store(store_id)
    if store is None:
        return set()
    return {
        cam.primary_zone.value
        for cam in store.cameras
        if cam.is_customer_area and cam.role is not CameraRole.ENTRANCE
    }


def compute_heatmap(
    events: Iterable[BehaviorEvent],
    *,
    low_sample_threshold: int = DEFAULT_LOW_SAMPLE,
) -> Heatmap:
    """Per-zone visit frequency + avg dwell, with a 0-100 score normalised to the busiest zone."""
    events = list(events)
    customers = customer_visitor_ids(events)
    visitors_by_zone = _customer_visitors_by_zone(events, customers)
    visits = {zone: len(ids) for zone, ids in visitors_by_zone.items()}
    avg_dwell = _avg_dwell_by_zone(events, customers)
    max_visits = max(visits.values(), default=0)

    zones = [
        ZoneCell(
            zone=zone,
            visits=visits.get(zone, 0),
            avg_dwell_ms=avg_dwell.get(zone, 0.0),
            score=round(100.0 * visits.get(zone, 0) / max_visits, 1) if max_visits else 0.0,
        )
        for zone in sorted(set(visits) | set(avg_dwell))
    ]
    confidence = "low" if len(customers) < low_sample_threshold else "ok"
    return Heatmap(zones=zones, data_confidence=confidence)


def feed_status(last_event_ms: int | None, reference_ms: int, stale_minutes: int) -> FeedStatus:
    """Decide whether a store's feed is stale, given a reference clock (pure).

    `reference_ms` is recording-relative (latest ingested event) or wall-clock — the caller chooses.
    No events at all ⇒ stale (nothing has ever arrived).
    """
    if last_event_ms is None:
        return FeedStatus(None, reference_ms, None, True)
    lag_seconds = max(0.0, (reference_ms - last_event_ms) / 1000.0)
    return FeedStatus(
        last_event_ms, reference_ms, round(lag_seconds, 1), lag_seconds > stale_minutes * 60
    )


def detect_anomalies(
    events: Iterable[BehaviorEvent],
    transactions: Iterable[Transaction],
    *,
    store_id: str = DEFAULT_STORE_ID,
    store_tz: str = "Asia/Kolkata",
    window_ms: int = DEFAULT_WINDOW_MS,
    low_sample_threshold: int = DEFAULT_LOW_SAMPLE,
    queue_warn: int = 3,
    queue_critical: int = 5,
    conversion_baseline: float = 0.15,
    conversion_drop_pct: float = 0.30,
    dead_zone_minutes: int = 30,
    open_hour: int = 12,
    close_hour: int = 22,
) -> list[Anomaly]:
    """Active anomalies (queue spike / conversion drop / dead zone), each with severity + action.

    Honest by construction: the conversion-drop and dead-zone checks **stand down** when the data
    can't support them (low sample, or a window shorter than the dead-zone horizon) and say so as
    INFO, rather than firing false WARN/CRITICAL alerts on the 2-min clip. All values compute from
    input (no hardcoding).
    """
    events = list(events)
    txns = list(transactions)
    metrics = compute_store_metrics(
        events,
        txns,
        store_tz=store_tz,
        window_ms=window_ms,
        low_sample_threshold=low_sample_threshold,
    )
    anomalies: list[Anomaly] = []

    # 1) Queue spike — from the (staff-excluded) observed checkout depth.
    qd = metrics.max_queue_depth
    if qd >= queue_critical or qd >= queue_warn:
        anomalies.append(
            Anomaly(
                type=ANOMALY_QUEUE_SPIKE,
                severity=SEV_CRITICAL if qd >= queue_critical else SEV_WARN,
                message=f"Checkout queue depth reached {qd} customers.",
                suggested_action="Open an additional checkout till to clear the queue.",
                value=float(qd),
            )
        )

    # 2) Conversion drop vs the configured baseline — only when the sample is trustworthy.
    if metrics.data_confidence != "ok":
        anomalies.append(
            Anomaly(
                type=ANOMALY_CONVERSION_DROP,
                severity=SEV_INFO,
                message=(
                    "Insufficient data (low sample) to evaluate conversion against the baseline; "
                    "no 7-day history on this dataset."
                ),
                suggested_action="Collect a longer window before alerting on conversion.",
                value=metrics.conversion_rate,
            )
        )
    else:
        threshold = conversion_baseline * (1.0 - conversion_drop_pct)
        if metrics.conversion_rate <= threshold:
            anomalies.append(
                Anomaly(
                    type=ANOMALY_CONVERSION_DROP,
                    severity=SEV_CRITICAL if metrics.conversion_rate == 0.0 else SEV_WARN,
                    message=(
                        f"Conversion {metrics.conversion_rate:.2%} is below the "
                        f"{conversion_baseline:.0%} baseline (drop threshold {threshold:.2%})."
                    ),
                    suggested_action="Investigate checkout friction, staffing, or promotions.",
                    value=metrics.conversion_rate,
                )
            )

    # 3) Dead zone — needs at least `dead_zone_minutes` of observed history to assert silence.
    anomalies.extend(
        _dead_zone_anomalies(events, store_id, store_tz, dead_zone_minutes, open_hour, close_hour)
    )
    return anomalies


def _dead_zone_anomalies(
    events: list[BehaviorEvent],
    store_id: str,
    store_tz: str,
    dead_zone_minutes: int,
    open_hour: int,
    close_hour: int,
) -> list[Anomaly]:
    if not events:
        return []
    ts = [int(e.timestamp.timestamp() * 1000) for e in events]
    reference_ms, span_ms = max(ts), max(ts) - min(ts)
    horizon_ms = dead_zone_minutes * 60 * 1000

    if span_ms < horizon_ms:
        return [
            Anomaly(
                type=ANOMALY_DEAD_ZONE,
                severity=SEV_INFO,
                message=(
                    f"Observed window ({span_ms // 60000} min) is shorter than the "
                    f"{dead_zone_minutes}-min dead-zone horizon; cannot assert a dead zone."
                ),
                suggested_action="N/A on this clip; the check activates on longer/live feeds.",
            )
        ]

    # Only meaningful during trading hours (a closed store is *expected* to be quiet).
    ref_local = datetime.fromtimestamp(reference_ms / 1000, tz=UTC).astimezone(ZoneInfo(store_tz))
    if not (open_hour <= ref_local.hour < close_hour):
        return []

    customers = customer_visitor_ids(events)
    last_visit: dict[str, int] = {}
    for e in events:
        if not _is_customer_zone_event(e, customers):
            continue
        ts_ms = int(e.timestamp.timestamp() * 1000)
        last_visit[e.zone_id] = max(last_visit.get(e.zone_id, 0), ts_ms)  # type: ignore[index]

    dead: list[Anomaly] = []
    for zone in sorted(monitored_customer_zones(store_id)):
        seen = last_visit.get(zone)
        if seen is not None and (reference_ms - seen) <= horizon_ms:
            continue
        msg = f"No customer visits to '{zone}' for over {dead_zone_minutes} min during open hours."
        dead.append(
            Anomaly(
                type=ANOMALY_DEAD_ZONE,
                severity=SEV_WARN,
                message=msg,
                suggested_action="Check merchandising/signage or staff coverage for this zone.",
                zone_id=zone,
            )
        )
    return dead
