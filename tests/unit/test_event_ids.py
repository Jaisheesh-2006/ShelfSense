# PROMPT
# Task: Verify deterministic ids (ADR-0021) — a BehaviorEvent derives a stable event_id from its
#   identity (so a re-POST / detector restart dedups instead of accumulating), an id supplied
#   upstream is preserved, and the ReIDGallery numbers visitors in discovery order by default.
# Context: event_id was random uuid4 and visitor_id random hex, so re-running the detector on top of
#   an existing DB inflated the counts. Both are now reproducible for a given clip+config.
# Constraints: pure/deterministic, no network; cover same-identity-same-id, different-identity-
#   different-id, supplied-id-preserved, and sequential visitor ids.
# Output: pytest tests.

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from app.reid import SIGNATURE_LEN, ReIDGallery
from shelfsense_common.contracts import BehaviorEvent, BehaviorEventType
from shelfsense_common.contracts.behavior import deterministic_event_id

TS = datetime(2026, 4, 10, 14, 0, 0, tzinfo=UTC)


def _event(**overrides: object) -> BehaviorEvent:
    fields: dict[str, object] = {
        "store_id": "ST1008",
        "camera_id": "CAM2",
        "visitor_id": "VIS_0001",
        "event_type": BehaviorEventType.ZONE_ENTER,
        "timestamp": TS,
        "zone_id": "makeup_aisle",
        "confidence": 0.9,
    }
    fields.update(overrides)
    return BehaviorEvent(**fields)  # type: ignore[arg-type]


def test_same_identity_yields_same_event_id() -> None:
    assert _event().event_id == _event().event_id  # re-emitting the same event -> same id


def test_event_id_matches_the_pure_hash() -> None:
    assert _event().event_id == deterministic_event_id(
        "ST1008", "CAM2", "VIS_0001", BehaviorEventType.ZONE_ENTER, "makeup_aisle", TS
    )


def test_different_identity_yields_different_event_id() -> None:
    base = _event().event_id
    assert base != _event(visitor_id="VIS_0002").event_id
    assert base != _event(event_type=BehaviorEventType.ZONE_DWELL).event_id
    assert base != _event(timestamp=datetime(2026, 4, 10, 14, 0, 1, tzinfo=UTC)).event_id


def test_supplied_event_id_is_preserved() -> None:
    # On ingest an event already carries its id — the validator must not overwrite it.
    assert _event(event_id="upstream-abc").event_id == "upstream-abc"


def test_gallery_numbers_visitors_in_discovery_order() -> None:
    gallery = ReIDGallery(max_distance=0.1)
    a = np.zeros(SIGNATURE_LEN, dtype=np.float32)
    a[0] = 1.0
    b = np.zeros(SIGNATURE_LEN, dtype=np.float32)
    b[1] = 1.0  # orthogonal to a -> a distinct visitor
    assert gallery.resolve(a, 0).visitor_id == "VIS_0001"
    assert gallery.resolve(b, 0).visitor_id == "VIS_0002"
    assert gallery.resolve(a, 50).visitor_id == "VIS_0001"  # re-match, not a new mint
