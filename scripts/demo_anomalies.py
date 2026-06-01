"""Anomalies: a clearly-labelled mechanism demo (Slice 2.7).

The real 2-minute clip can't trigger the spec's anomalies — nobody reaches the till (no queue),
there's no 7-day history (no conversion baseline), and 2 minutes is too short to assert a 30-min
dead zone. So the live `/anomalies` correctly returns only INFO ("insufficient data") on the clip.

This script proves the detector FIRES real alerts by feeding it three **clearly-synthetic** cases
through the SAME pure function the API calls (`shelfsense_common.analytics.detect_anomalies`). The
data here is fabricated for demonstration and is loudly labelled as such — it never touches the
honest clip reading.

Usage:
    python scripts/demo_anomalies.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))

from shelfsense_common.analytics import detect_anomalies  # noqa: E402
from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.contracts import (  # noqa: E402
    BehaviorEvent,
    BehaviorEventType,
    EventMetadata,
    Transaction,
)

# 08:30 UTC == 14:00 Asia/Kolkata — inside the 12–22 trading window (so dead-zone is in open hours).
BASE = datetime(2026, 4, 10, 8, 30, 0, tzinfo=UTC)


def ev(
    visitor: str,
    etype: BehaviorEventType,
    *,
    zone: str | None = None,
    dwell: int = 0,
    queue_depth: int | None = None,
    offset_s: int = 0,
) -> BehaviorEvent:
    return BehaviorEvent(
        store_id="ST1008",
        camera_id="CAM5" if zone == "checkout" else "CAM2",
        visitor_id=visitor,
        event_type=etype,
        timestamp=BASE + timedelta(seconds=offset_s),
        zone_id=zone,
        dwell_ms=dwell,
        is_staff=False,
        confidence=0.9,
        metadata=EventMetadata(queue_depth=queue_depth),
    )


def queue_spike_events() -> list[BehaviorEvent]:
    """Six customers pile into the checkout zone, depth climbing 1 -> 6."""
    events: list[BehaviorEvent] = []
    for i in range(1, 7):
        events.append(
            ev(
                f"c{i}",
                BehaviorEventType.BILLING_QUEUE_JOIN,
                zone="checkout",
                queue_depth=i,
                offset_s=i * 5,
            )
        )
    return events


def conversion_drop_events() -> list[BehaviorEvent]:
    """25 customers browse (>= the low-sample threshold, so confidence is 'ok'); none convert."""
    return [
        ev(f"c{i}", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle", offset_s=i)
        for i in range(25)
    ]


def dead_zone_events() -> list[BehaviorEvent]:
    """40-minute window with customers only ever in makeup_aisle — skincare + checkout go dead."""
    return [
        ev("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle", offset_s=0),
        ev("c2", BehaviorEventType.ZONE_DWELL, zone="makeup_aisle", offset_s=40 * 60),
    ]


def run(title: str, events: list[BehaviorEvent], txns: list[Transaction]) -> None:
    s = get_settings()
    anomalies = detect_anomalies(
        events,
        txns,
        store_tz=s.store_timezone,
        window_ms=s.pos_correlation_window_ms,
        low_sample_threshold=s.conversion_low_sample_threshold,
        queue_warn=s.anomaly_queue_depth_warn,
        queue_critical=s.anomaly_queue_depth_critical,
        conversion_baseline=s.anomaly_conversion_baseline,
        conversion_drop_pct=s.anomaly_conversion_drop_pct,
        dead_zone_minutes=s.anomaly_dead_zone_minutes,
        open_hour=s.store_open_hour,
        close_hour=s.store_close_hour,
    )
    print(f"\n=== {title} ===")
    for a in anomalies:
        zone = f" [{a.zone_id}]" if a.zone_id else ""
        value = f" (value={a.value})" if a.value is not None else ""
        print(f"  {a.severity:8} {a.type}{zone}{value}")
        print(f"           {a.message}")
        print(f"           -> {a.suggested_action}")


def main() -> None:
    print("*" * 90)
    print("SYNTHETIC ANOMALY DEMO — fabricated scenarios, NOT a reading of the real clip.")
    print("Same detector the /anomalies endpoint uses; thresholds come from config.")
    print("*" * 90)
    run("Scenario 1 - checkout rush (expect QUEUE_SPIKE CRITICAL)", queue_spike_events(), [])
    run("Scenario 2 - 25 browsers, zero sales (expect CONVERSION_DROP CRITICAL)",
        conversion_drop_events(), [])
    run("Scenario 3 - 40-min window, skincare+checkout never visited (expect DEAD_ZONE WARN)",
        dead_zone_events(), [])


if __name__ == "__main__":
    main()
