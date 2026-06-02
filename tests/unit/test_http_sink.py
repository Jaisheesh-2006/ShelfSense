# PROMPT
# Task: Unit-test the Slice 2.8 auto-feed sinks — HttpEventSink (batched POST to /events/ingest with
#   retry + non-fatal failure) and FanOutSink (write to several sinks at once) — with no network.
# Context: the detector fans events to JSONL + HTTP so `docker compose up` feeds the API itself. The
#   HTTP transport + readiness check are injectable so batching/flush/retry are tested offline.
# Constraints: pure/deterministic, no real sockets; cover <=500 batching, final flush on exit,
#   idempotent re-send shape, give-up-after-retries (non-fatal), and FanOut fanning to all children.
# Output: pytest tests using a fake transport that records the POSTed bodies.

from __future__ import annotations

import json
from datetime import UTC, datetime

from shelfsense_common.contracts import BehaviorEvent, BehaviorEventType
from shelfsense_common.sinks import FanOutSink, HttpEventSink

BASE = datetime(2026, 4, 10, 14, 0, 0, tzinfo=UTC)


def ev(visitor: str, n: int = 0) -> BehaviorEvent:
    return BehaviorEvent(
        store_id="ST1008",
        camera_id="CAM2",
        visitor_id=visitor,
        event_type=BehaviorEventType.ZONE_ENTER,
        timestamp=BASE,
        zone_id="makeup_aisle",
        confidence=0.9,
    )


class _Recorder:
    """A fake transport that records each POSTed (url, parsed-body)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, body: bytes) -> None:
        self.calls.append((url, json.loads(body.decode("utf-8"))))


def _sink(transport, **kw) -> HttpEventSink:
    # ready_check returns True instantly so __enter__ never waits/polls the network.
    return HttpEventSink(
        "http://api:8000", transport=transport, ready_check=lambda: True, **kw
    )


def test_posts_to_events_ingest_url() -> None:
    rec = _Recorder()
    with _sink(rec) as sink:
        sink.write(ev("c1"))
    assert len(rec.calls) == 1
    url, payload = rec.calls[0]
    assert url == "http://api:8000/events/ingest"
    assert [e["visitor_id"] for e in payload["events"]] == ["c1"]
    assert sink.posted == 1


def test_batches_at_size_then_final_flush() -> None:
    rec = _Recorder()
    with _sink(rec, batch_size=2) as sink:
        sink.write(ev("a"))
        sink.write(ev("b"))  # hits batch_size=2 -> first POST
        sink.write(ev("c"))  # remainder -> flushed on exit
    sizes = [len(payload["events"]) for _, payload in rec.calls]
    assert sizes == [2, 1]
    assert sink.posted == 3


def test_no_events_no_post() -> None:
    rec = _Recorder()
    with _sink(rec):
        pass
    assert rec.calls == []


def test_body_is_valid_ingest_envelope() -> None:
    rec = _Recorder()
    with _sink(rec) as sink:
        sink.write(ev("c1"))
        sink.write(ev("c2"))
    _, payload = rec.calls[0]
    assert set(payload) == {"events"}
    assert len(payload["events"]) == 2
    # Each serialised event round-trips back into the contract (so the API will accept it).
    for raw in payload["events"]:
        BehaviorEvent.model_validate(raw)


def test_failure_is_non_fatal_and_gives_up() -> None:
    attempts = {"n": 0}

    def always_fails(url: str, body: bytes) -> None:
        attempts["n"] += 1
        raise OSError("connection refused")

    # backoff_s=0 so the retry loop doesn't sleep during the test.
    with _sink(always_fails, max_retries=3, backoff_s=0.0) as sink:
        sink.write(ev("c1"))  # never raises out of the sink
    assert attempts["n"] == 3  # retried up to the cap
    assert sink.posted == 0  # nothing counted as accepted


def test_recovers_on_a_later_attempt() -> None:
    calls = {"n": 0}

    def flaky(url: str, body: bytes) -> None:
        calls["n"] += 1
        if calls["n"] < 2:
            raise OSError("temporary")

    with _sink(flaky, max_retries=3, backoff_s=0.0) as sink:
        sink.write(ev("c1"))
    assert sink.posted == 1  # second attempt succeeded


class _Spy:
    def __init__(self) -> None:
        self.entered = self.exited = False
        self.events: list[str] = []

    def __enter__(self) -> _Spy:
        self.entered = True
        return self

    def __exit__(self, *exc: object) -> None:
        self.exited = True

    def write(self, event: BehaviorEvent) -> None:
        self.events.append(event.visitor_id)


def test_fanout_writes_to_all_and_manages_lifecycle() -> None:
    a, b = _Spy(), _Spy()
    with FanOutSink([a, b]) as fan:
        fan.write(ev("c1"))
        fan.write(ev("c2"))
    assert a.events == ["c1", "c2"] == b.events
    assert a.entered and a.exited and b.entered and b.exited
