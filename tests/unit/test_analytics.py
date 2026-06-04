# PROMPT
# Task: Unit-test the pure event→funnel/metrics analytics (shelfsense_common.analytics) used by the
#   Slice 2.6 API, so the rubric-critical invariants are pinned without a database.
# Context: analytics.py turns BehaviorEvents (+ POS Transactions) into the conversion funnel and
#   store metrics, reusing conversion.correlate_conversions. The funnel must be session-based (no
#   double count), staff-excluded (any-flag), and monotonic (purchase ⊆ billing ⊆ zone ⊆ entry).
# Constraints: pure/deterministic, no IO/network; tz-aware UTC timestamps; cover staff exclusion,
#   REENTRY (no double count), conversion-by-window, abandonment, per-zone dwell, and zero-traffic.
# Output: pytest tests asserting stage counts, drop-off bounds, conversion rate, and metric fields.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shelfsense_common.analytics import (
    STAGE_BILLING_QUEUE,
    STAGE_ENTRY,
    STAGE_PURCHASE,
    STAGE_ZONE_VISIT,
    compute_funnel,
    compute_store_metrics,
    customer_visitor_ids,
)
from shelfsense_common.contracts import (
    BehaviorEvent,
    BehaviorEventType,
    EventMetadata,
    Transaction,
)

BASE = datetime(2026, 4, 10, 14, 0, 0, tzinfo=UTC)


def ev(
    visitor: str,
    etype: BehaviorEventType,
    *,
    zone: str | None = None,
    dwell: int = 0,
    staff: bool = False,
    queue_depth: int | None = None,
    offset_s: int = 0,
    conf: float = 0.9,
) -> BehaviorEvent:
    return BehaviorEvent(
        store_id="ST1008",
        camera_id="CAM2",
        visitor_id=visitor,
        event_type=etype,
        timestamp=BASE + timedelta(seconds=offset_s),
        zone_id=zone,
        dwell_ms=dwell,
        is_staff=staff,
        confidence=conf,
        metadata=EventMetadata(queue_depth=queue_depth),
    )


def txn(
    order: str, *, offset_s: int, amount: float = 1000.0, brand: str = "Faces Canada"
) -> Transaction:
    return Transaction(
        transaction_id=order,
        timestamp=BASE + timedelta(seconds=offset_s),
        amount=amount,
        brand=brand,
        line_items=2,
    )


def _stage(funnel, key: str) -> int:
    return next(s.visitors for s in funnel.stages if s.stage == key)


def test_staff_excluded_by_any_flag() -> None:
    events = [
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle"),
        ev("s1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle"),
        ev("s1", BehaviorEventType.ZONE_EXIT, zone="makeup_aisle", dwell=5000, staff=True),
    ]
    assert customer_visitor_ids(events) == {"c1"}


def test_reentry_does_not_double_count() -> None:
    events = [
        ev("c1", BehaviorEventType.ENTRY),
        ev("c1", BehaviorEventType.REENTRY),
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle"),
        ev("c2", BehaviorEventType.ZONE_ENTER, zone="skincare_aisle"),
    ]
    funnel = compute_funnel(events, [])
    assert _stage(funnel, STAGE_ENTRY) == 2  # c1 counted once despite ENTRY + REENTRY
    assert _stage(funnel, STAGE_ZONE_VISIT) == 2


def test_funnel_monotonic_and_conversion() -> None:
    events = [
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle"),
        ev("c1", BehaviorEventType.BILLING_QUEUE_JOIN, zone="checkout", queue_depth=1, offset_s=60),
        ev("c2", BehaviorEventType.ZONE_ENTER, zone="skincare_aisle"),
    ]
    # A sale 2 min after c1 reaches billing → within the 5-min window → c1 converts.
    funnel = compute_funnel(events, [txn("o1", offset_s=180)])

    assert _stage(funnel, STAGE_ENTRY) == 2
    assert _stage(funnel, STAGE_ZONE_VISIT) == 2
    assert _stage(funnel, STAGE_BILLING_QUEUE) == 1
    assert _stage(funnel, STAGE_PURCHASE) == 1
    assert funnel.conversion_rate == 0.5  # 1 converted / 2 unique
    # Monotonic non-increasing counts → every drop-off in [0, 100].
    drops = [s.drop_off_pct for s in funnel.stages if s.drop_off_pct is not None]
    assert all(0.0 <= d <= 100.0 for d in drops)


def test_abandonment_when_no_matching_sale() -> None:
    events = [
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle"),
        ev("c1", BehaviorEventType.BILLING_QUEUE_JOIN, zone="checkout", queue_depth=1, offset_s=60),
    ]
    metrics = compute_store_metrics(events, [])  # no sales → c1 abandons
    assert metrics.converted == 0
    assert metrics.abandoned == 1
    assert metrics.abandonment_rate == 1.0
    assert metrics.max_queue_depth == 1


def test_avg_dwell_by_zone() -> None:
    events = [
        ev("c1", BehaviorEventType.ZONE_EXIT, zone="makeup_aisle", dwell=4000),
        ev("c2", BehaviorEventType.ZONE_EXIT, zone="makeup_aisle", dwell=6000),
        ev("c1", BehaviorEventType.ZONE_EXIT, zone="skincare_aisle", dwell=2000),
    ]
    metrics = compute_store_metrics(events, [])
    assert metrics.avg_dwell_ms_by_zone["makeup_aisle"] == 5000.0
    assert metrics.avg_dwell_ms_by_zone["skincare_aisle"] == 2000.0


def test_zero_traffic_is_safe() -> None:
    funnel = compute_funnel([], [])
    assert [s.visitors for s in funnel.stages] == [0, 0, 0, 0]
    assert funnel.conversion_rate == 0.0
    assert funnel.data_confidence == "low"

    metrics = compute_store_metrics([], [])
    assert metrics.unique_visitors == 0
    assert metrics.abandonment_rate == 0.0
    assert metrics.pos["transaction_count"] == 0


def test_staff_never_join_billing() -> None:
    events = [
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="checkout"),
        # A staff member flagged on their billing event must not count as a billing customer.
        ev("s1", BehaviorEventType.BILLING_QUEUE_JOIN, zone="checkout", queue_depth=1, staff=True),
    ]
    metrics = compute_store_metrics(events, [])
    assert metrics.unique_visitors == 1  # only c1
    assert metrics.abandoned == 0  # s1 excluded from the queue entirely
