# PROMPT
# Task: End-to-end test the Slice 2.6 API (POST /events/ingest, GET /stores/{id}/metrics + /funnel)
#   against a real SQLite-backed app via FastAPI TestClient.
# Context: ingest is idempotent by event_id and partial-success on bad events; metrics/funnel are
#   computed live (session-based, staff-excluded). The old /api/v1/* endpoints are retired.
# Constraints: hermetic (SQLite tmp DB, no Postgres/POS); deterministic; assert the response
#   contracts (counts, error envelope) and the no-double-count guarantee on re-POST.
# Output: pytest tests using the `client` fixture (tests/integration/conftest.py).

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shelfsense_common.contracts import BehaviorEvent, BehaviorEventType, EventMetadata

BASE = datetime(2026, 4, 10, 14, 0, 0, tzinfo=UTC)


def _event(visitor: str, etype: BehaviorEventType, **kw) -> dict:
    event = BehaviorEvent(
        store_id="ST1008",
        camera_id="CAM2",
        visitor_id=visitor,
        event_type=etype,
        timestamp=BASE + timedelta(seconds=kw.get("offset_s", 0)),
        zone_id=kw.get("zone"),
        dwell_ms=kw.get("dwell", 0),
        is_staff=kw.get("staff", False),
        confidence=kw.get("conf", 0.9),
        metadata=EventMetadata(queue_depth=kw.get("queue_depth")),
    )
    return event.model_dump(mode="json")


def _batch() -> list[dict]:
    return [
        _event("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle"),
        _event("c1", BehaviorEventType.ZONE_EXIT, zone="makeup_aisle", dwell=8000, offset_s=30),
        _event(
            "c1", BehaviorEventType.BILLING_QUEUE_JOIN, zone="checkout", queue_depth=1, offset_s=60
        ),
        _event("c2", BehaviorEventType.ZONE_ENTER, zone="skincare_aisle"),
    ]


def test_healthz_ok(client) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_list_stores(client) -> None:
    stores = client.get("/stores").json()
    by_id = {s["store_id"]: s["name"] for s in stores}
    assert by_id.get("ST1008") == "Brigade Bangalore"  # POS store
    assert "ST1009" in by_id  # the corrected dataset's Store_2 (assigned id, ADR-0026)
    assert all(s["store_id"] and s["name"] for s in stores)


def test_ingest_then_metrics_and_funnel(client) -> None:
    resp = client.post("/events/ingest", json={"events": _batch()})
    assert resp.status_code == 200
    assert resp.json() == {"accepted": 4, "duplicates": 0, "rejected": 0, "errors": []}

    metrics = client.get("/stores/ST1008/metrics").json()
    assert metrics["unique_visitors"] == 2
    assert metrics["converted"] == 0  # no POS in this hermetic test
    assert metrics["max_queue_depth"] == 1
    assert metrics["avg_dwell_ms_by_zone"]["makeup_aisle"] == 8000.0

    funnel = client.get("/stores/ST1008/funnel").json()
    counts = {s["stage"]: s["visitors"] for s in funnel["stages"]}
    assert counts == {"entry": 2, "zone_visit": 2, "billing_queue": 1, "purchase": 0}
    assert funnel["conversion_rate"] == 0.0


def test_ingest_is_idempotent(client) -> None:
    batch = _batch()
    first = client.post("/events/ingest", json={"events": batch}).json()
    assert first["accepted"] == 4

    second = client.post("/events/ingest", json={"events": batch}).json()
    assert second == {"accepted": 0, "duplicates": 4, "rejected": 0, "errors": []}

    # Metrics unchanged after the duplicate POST (no double counting).
    assert client.get("/stores/ST1008/metrics").json()["unique_visitors"] == 2


def test_partial_success_on_malformed_event(client) -> None:
    good = _event("c1", BehaviorEventType.ZONE_ENTER, zone="makeup_aisle")
    bad = {**good, "event_id": "bad-1", "event_type": "NOT_A_REAL_TYPE"}

    body = client.post("/events/ingest", json={"events": [good, bad]}).json()
    assert body["accepted"] == 1
    assert body["rejected"] == 1
    assert body["errors"][0]["index"] == 1


def test_batch_over_500_rejected_with_envelope(client) -> None:
    resp = client.post("/events/ingest", json={"events": [{} for _ in range(501)]})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_retired_api_v1_is_gone(client) -> None:
    assert client.get("/api/v1/conversion").status_code == 404


def test_heatmap_endpoint(client) -> None:
    client.post("/events/ingest", json={"events": _batch()})
    heat = client.get("/stores/ST1008/heatmap").json()
    by_zone = {z["zone"]: z for z in heat["zones"]}
    # c1 in makeup, c2 in skincare → both 1 visitor → both at the (tied) busiest score.
    assert by_zone["makeup_aisle"]["score"] == 100.0
    assert by_zone["makeup_aisle"]["avg_dwell_ms"] == 8000.0
    assert heat["data_confidence"] == "low"


def test_anomalies_are_honest_not_fabricated(client) -> None:
    client.post("/events/ingest", json={"events": _batch()})
    body = client.get("/stores/ST1008/anomalies").json()
    severities = {a["type"]: a["severity"] for a in body["anomalies"]}
    # No real alert on the tiny clip: depth 1 (< warn), low-sample conversion, short window.
    assert all(a["severity"] == "INFO" for a in body["anomalies"])
    assert severities.get("CONVERSION_DROP") == "INFO"
    assert severities.get("DEAD_ZONE") == "INFO"
    assert "QUEUE_SPIKE" not in severities


def test_health_recording_relative_is_ok(client) -> None:
    client.post("/events/ingest", json={"events": _batch()})
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["strict_now"] is False
    assert health["stores"][0]["store_id"] == "ST1008"
    assert health["stores"][0]["stale_feed"] is False  # fresh vs the latest ingested event


def test_health_strict_now_flags_stale(client, monkeypatch) -> None:
    client.post("/events/ingest", json={"events": _batch()})
    # The clip is from 2026-04-10; against real wall-clock time the feed is legitimately stale.
    from shelfsense_common.config import get_settings

    monkeypatch.setenv("HEALTH_STRICT_NOW", "true")
    get_settings.cache_clear()
    health = client.get("/health").json()
    assert health["strict_now"] is True
    assert health["stores"][0]["stale_feed"] is True
    assert health["status"] == "degraded"
