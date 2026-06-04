# PROMPT
# Task: Unit-test the Slice 2.7 pure analytics — heatmap normalisation, anomaly detection
#   (queue spike / conversion drop / dead zone), and feed-staleness — without a database.
# Context: analytics.compute_heatmap/detect_anomalies/feed_status power /stores/{id}/{heatmap,
#   anomalies} and /health. The detectors must be HONEST: stand down (INFO) when the data can't
#   support a verdict (low sample, or window shorter than the dead-zone horizon).
# Constraints: pure/deterministic, tz-aware UTC; cover busiest-zone=100 scaling, WARN/CRITICAL queue
#   thresholds, conversion-drop only at ok confidence, dead-zone dormant on a short window, lag.
# Output: pytest tests asserting scores, severities, types, and stale booleans.
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shelfsense_common.analytics import (
    ANOMALY_CONVERSION_DROP,
    ANOMALY_DEAD_ZONE,
    ANOMALY_QUEUE_SPIKE,
    SEV_CRITICAL,
    SEV_INFO,
    SEV_WARN,
    compute_heatmap,
    detect_anomalies,
    feed_status,
)
from shelfsense_common.contracts import (
    BehaviorEvent,
    BehaviorEventType,
    EventMetadata,
    Transaction,
)

# 08:30 UTC == 14:00 Asia/Kolkata — inside the 12–22 trading window (for dead-zone tests).
BASE = datetime(2026, 4, 10, 8, 30, 0, tzinfo=UTC)


def ev(
    visitor: str,
    etype: BehaviorEventType,
    *,
    zone: str | None = None,
    dwell: int = 0,
    staff: bool = False,
    queue_depth: int | None = None,
    offset_s: int = 0,
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
        confidence=0.9,
        metadata=EventMetadata(queue_depth=queue_depth),
    )


def txn(order: str, *, offset_s: int) -> Transaction:
    return Transaction(
        transaction_id=order,
        timestamp=BASE + timedelta(seconds=offset_s),
        amount=1000.0,
        brand="Faces Canada",
        line_items=1,
    )


def _of_type(anomalies, type_: str):
    return [a for a in anomalies if a.type == type_]


# ----------------------------------- heatmap -----------------------------------


def test_heatmap_normalises_to_busiest_zone() -> None:
    events = [
        ev("c1", BehaviorEventType.ZONE_EXIT, zone="makeup_aisle", dwell=4000),
        ev("c2", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle"),
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="skincare_aisle"),
    ]
    heat = compute_heatmap(events, low_sample_threshold=20)
    by_zone = {z.zone: z for z in heat.zones}
    assert by_zone["makeup_aisle"].visits == 2  # c1 + c2
    assert by_zone["makeup_aisle"].score == 100.0  # busiest
    assert by_zone["skincare_aisle"].visits == 1
    assert by_zone["skincare_aisle"].score == 50.0  # half of busiest
    assert heat.data_confidence == "low"  # 2 customers < 20


def test_heatmap_excludes_staff() -> None:
    events = [
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle"),
        ev("s1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle", staff=True),
    ]
    heat = compute_heatmap(events)
    assert {z.zone: z.visits for z in heat.zones} == {"makeup_aisle": 1}


# ----------------------------------- feed status -----------------------------------


def test_feed_status_fresh_and_stale() -> None:
    fresh = feed_status(last_event_ms=1_000_000, reference_ms=1_000_000, stale_minutes=10)
    assert fresh.lag_seconds == 0.0 and fresh.stale_feed is False

    stale = feed_status(last_event_ms=0, reference_ms=11 * 60 * 1000, stale_minutes=10)
    assert stale.lag_seconds == 660.0 and stale.stale_feed is True  # 11 min > 10

    none = feed_status(last_event_ms=None, reference_ms=1000, stale_minutes=10)
    assert none.stale_feed is True and none.lag_seconds is None


# ----------------------------------- anomalies -----------------------------------


def test_queue_spike_thresholds() -> None:
    warn = detect_anomalies(
        [ev("c1", BehaviorEventType.BILLING_QUEUE_JOIN, zone="checkout", queue_depth=3)],
        [],
        queue_warn=3,
        queue_critical=5,
    )
    spike = _of_type(warn, ANOMALY_QUEUE_SPIKE)
    assert spike and spike[0].severity == SEV_WARN and spike[0].value == 3.0

    crit = detect_anomalies(
        [ev("c1", BehaviorEventType.BILLING_QUEUE_JOIN, zone="checkout", queue_depth=6)],
        [],
        queue_warn=3,
        queue_critical=5,
    )
    assert _of_type(crit, ANOMALY_QUEUE_SPIKE)[0].severity == SEV_CRITICAL


def test_no_queue_spike_below_threshold() -> None:
    out = detect_anomalies(
        [ev("c1", BehaviorEventType.BILLING_QUEUE_JOIN, zone="checkout", queue_depth=1)],
        [],
        queue_warn=3,
    )
    assert _of_type(out, ANOMALY_QUEUE_SPIKE) == []


def test_conversion_drop_is_info_under_low_sample() -> None:
    # 1 customer (< threshold) → confidence "low" → INFO, never a false WARN/CRITICAL.
    out = detect_anomalies(
        [ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle")],
        [],
        low_sample_threshold=20,
    )
    drop = _of_type(out, ANOMALY_CONVERSION_DROP)
    assert drop and drop[0].severity == SEV_INFO


def test_conversion_drop_critical_when_zero_at_ok_confidence() -> None:
    # 2 customers with low_sample_threshold=2 → "ok"; zero conversions ≤ baseline → CRITICAL.
    events = [
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle"),
        ev("c2", BehaviorEventType.ZONE_ENTER, zone="skincare_aisle"),
    ]
    out = detect_anomalies(
        events, [], low_sample_threshold=2, conversion_baseline=0.15, conversion_drop_pct=0.30
    )
    drop = _of_type(out, ANOMALY_CONVERSION_DROP)
    assert drop and drop[0].severity == SEV_CRITICAL and drop[0].value == 0.0


def test_dead_zone_dormant_on_short_window() -> None:
    events = [
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle", offset_s=0),
        ev("c1", BehaviorEventType.ZONE_EXIT, zone="makeup_aisle", dwell=5000, offset_s=60),
    ]
    dead = _of_type(detect_anomalies(events, []), ANOMALY_DEAD_ZONE)
    assert dead and dead[0].severity == SEV_INFO  # 1-min span < 30-min horizon


def test_dead_zone_fires_for_unvisited_zone_over_long_window() -> None:
    # 40-min span, only makeup visited → skincare_aisle + checkout are dead during open hours.
    events = [
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle", offset_s=0),
        ev("c1", BehaviorEventType.ZONE_DWELL, zone="makeup_aisle", offset_s=40 * 60),
    ]
    dead = _of_type(detect_anomalies(events, [], dead_zone_minutes=30), ANOMALY_DEAD_ZONE)
    dead_zones = {a.zone_id for a in dead}
    assert dead and all(a.severity == SEV_WARN for a in dead)
    assert "skincare_aisle" in dead_zones and "checkout" in dead_zones
    assert "makeup_aisle" not in dead_zones  # visited recently
