# PROMPT
# Task: A true end-to-end pipeline integration test — ingest the COMMITTED detector output
#   (data/events/behavior.jsonl, the real events the offline pass emitted for both stores) through
#   the live API and assert the analytics that come back are internally consistent and non-trivial.
# Context: this is the "≥1 end-to-end pipeline integration test" the SPEC (Part C) asks for. Unlike
#   test_api.py (synthetic 4-event batch), this replays the actual pipeline artifact, so it guards
#   the whole chain: real emitted events → POST /events/ingest (idempotent) → repository →
#   analytics → /metrics + /funnel. It also proves the committed events stay schema-valid (the
#   default `docker compose up` replayer depends on this exact file).
# Context: hermetic — SQLite via the `client` fixture, no POS CSV (PII, gitignored), so conversion
#   is honestly 0 here; POS-driven conversion is covered by tests/unit/test_conversion.py.
# Constraints: assertions are DERIVED FROM THE DATA (distinct non-staff visitor ids, monotonic
#   funnel, cross-endpoint agreement) — never hardcoded counts — so the test survives data changes.
# Output: pytest tests using the shared `client` fixture (tests/integration/conftest.py).
# CHANGES MADE:
#   - Added this test module to cover the cases listed under Output above; pure
#     assertions (no production behaviour changed by the test itself).

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

EVENTS_FILE = Path(__file__).resolve().parents[2] / "data" / "events" / "behavior.jsonl"
BATCH = 500  # the API's per-request cap

FUNNEL_ORDER = ["entry", "zone_visit", "billing_queue", "purchase"]


def _load_events() -> list[dict]:
    if not EVENTS_FILE.exists():
        pytest.skip(f"committed replay events not found at {EVENTS_FILE}")
    rows = []
    for line in EVENTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    if not rows:
        pytest.skip("behavior.jsonl is empty")
    return rows


def _ingest_all(client, events: list[dict]) -> tuple[int, int]:
    """POST every event in ≤500 batches; return (total_accepted, total_duplicates)."""
    accepted = duplicates = 0
    for i in range(0, len(events), BATCH):
        body = client.post("/events/ingest", json={"events": events[i : i + BATCH]}).json()
        assert body["rejected"] == 0, f"committed events failed schema validation: {body['errors']}"
        accepted += body["accepted"]
        duplicates += body["duplicates"]
    return accepted, duplicates


def _expected_unique_non_staff(events: list[dict]) -> dict[str, int]:
    """Per store: distinct visitor_ids that are NEVER flagged staff (the any-flag rule)."""
    seen: dict[str, set[str]] = defaultdict(set)
    staff: dict[tuple[str, str], bool] = defaultdict(bool)
    for e in events:
        sid, vid = e["store_id"], e["visitor_id"]
        seen[sid].add(vid)
        staff[(sid, vid)] = staff[(sid, vid)] or bool(e.get("is_staff"))
    return {
        sid: len([vid for vid in vids if not staff[(sid, vid)]]) for sid, vids in seen.items()
    }


def test_committed_events_replay_into_consistent_metrics(client) -> None:
    events = _load_events()
    expected_unique = _expected_unique_non_staff(events)
    stores = sorted(expected_unique)

    # The corrected dataset has two stores — both must be present in the committed artifact.
    assert {"ST1008", "ST1009"}.issubset(set(stores)), f"expected both stores, got {stores}"

    accepted, duplicates = _ingest_all(client, events)
    # Every real event is schema-valid; `accepted` == distinct event_ids, and idempotent ingest
    # collapses any repeated event_id within the file (the committed artifact has a few), so
    # accepted + duplicates accounts for every line.
    distinct_ids = len({e["event_id"] for e in events})
    assert accepted == distinct_ids
    assert accepted + duplicates == len(events)

    for sid in stores:
        metrics = client.get(f"/stores/{sid}/metrics").json()
        funnel = client.get(f"/stores/{sid}/funnel").json()

        # unique_visitors == distinct non-staff visitor ids (staff excluded), derived from the data.
        assert metrics["unique_visitors"] == expected_unique[sid], sid
        assert metrics["unique_visitors"] > 0, sid
        assert 0.0 <= metrics["conversion_rate"] <= 1.0, sid
        assert 0.0 <= metrics["abandonment_rate"] <= 1.0, sid

        # Funnel: canonical order, monotonic non-increasing, and agreeing with /metrics.
        counts = {s["stage"]: s["visitors"] for s in funnel["stages"]}
        assert [s["stage"] for s in funnel["stages"]] == FUNNEL_ORDER, sid
        visitors = [s["visitors"] for s in funnel["stages"]]
        assert visitors == sorted(visitors, reverse=True), f"{sid} funnel not monotonic: {visitors}"
        assert counts["entry"] == metrics["unique_visitors"], sid  # same denominator both endpoints
        assert funnel["conversion_rate"] == metrics["conversion_rate"], sid


def test_replay_is_idempotent(client) -> None:
    events = _load_events()
    _ingest_all(client, events)
    before = {
        sid: client.get(f"/stores/{sid}/metrics").json()["unique_visitors"]
        for sid in _expected_unique_non_staff(events)
    }

    # Re-ingest the whole artifact: nothing new is accepted, everything is a duplicate.
    accepted, duplicates = _ingest_all(client, events)
    assert accepted == 0
    assert duplicates == len(events)

    after = {
        sid: client.get(f"/stores/{sid}/metrics").json()["unique_visitors"]
        for sid in before
    }
    assert after == before  # no double counting on replay
