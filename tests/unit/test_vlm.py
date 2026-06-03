# PROMPT
# Task:
#   - Unit-test the offline VLM layer (ADR-0027): reply parsing, the persistent verdict cache, the
#     staff decider's VLM-vs-heuristic policy, and the zone resolver's scope/cache behaviour.
# Context:
#   - The detector can ask Google Gemini "staff or customer?" (per person) and "which zone?" (per
#     product camera). The model is optional: missing key/SDK/low-confidence/errors fall back to
#     the dark-uniform heuristic / static primary_zone, and verdicts are cached so re-runs are free.
# Constraints:
#   - No network and no real SDK. Use a FakeVLM client and synthetic images; never construct the
#     Gemini client. Pure/deterministic; cache I/O uses tmp_path.
# Output:
#   - Tests: extract_json (plain/fenced/prose); parse_staff_reply + parse_zone_reply (label snap,
#     confidence clamp); build_zone_prompt lists candidates; JsonFileCache round-trips + reloads;
#     StaffDecider overrides when confident, falls back on low-confidence / no-crop / visitor=None /
#     VLM error (and doesn't retry a failed visitor); build_vlm_client returns None when off/no-key;
#     resolve_zones is empty without a VLM, only labels product cameras, honours a cached verdict.
"""Unit tests for the optional VLM staff/zone classification layer."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from app.staff import StaffClassifier
from app.staff_decider import StaffDecider
from app.vlm import (
    JsonFileCache,
    StaffVerdict,
    ZoneVerdict,
    build_staff_prompt,
    build_vlm_client,
    build_zone_prompt,
    extract_json,
    parse_staff_reply,
    parse_zone_reply,
)
from app.zone_resolver import product_zone_candidates, resolve_zones
from shelfsense_common.contracts import CameraConfig, CameraRole, ZoneName


class _NullLog:
    """A logger stub that swallows structured calls."""

    def info(self, *args, **kwargs) -> None: ...
    def warning(self, *args, **kwargs) -> None: ...


class FakeVLM:
    """In-memory VLMClient: returns canned verdicts, counts calls, can raise for the error path."""

    def __init__(self, staff=None, zone=None, raise_on_staff=False) -> None:
        self._staff = staff
        self._zone = zone
        self._raise = raise_on_staff
        self.staff_calls = 0
        self.zone_calls = 0

    def classify_staff(self, image_bgr, staff_hint=None):
        self.staff_calls += 1
        if self._raise:
            raise RuntimeError("boom")
        return self._staff

    def classify_zone(self, image_bgr, candidate_zones, floor_plan_bgr=None):
        self.zone_calls += 1
        return self._zone


def _img() -> np.ndarray:
    return np.zeros((40, 40, 3), dtype=np.uint8)


def _bbox(x=0, y=0, w=10, h=20) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y, w=w, h=h)


# --- reply parsing --------------------------------------------------------------------------


def test_extract_json_plain_fenced_and_prose():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('here is the answer: {"a": 3} thanks') == {"a": 3}


def test_extract_json_raises_without_object():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_parse_staff_reply_labels_and_confidence_clamp():
    staff = parse_staff_reply('{"label": "staff", "confidence": 1.4, "reason": "lanyard"}')
    assert staff.is_staff is True
    assert staff.confidence == 1.0  # clamped to [0,1]
    customer = parse_staff_reply('{"label": "customer", "confidence": -0.2}')
    assert customer.is_staff is False
    assert customer.confidence == 0.0


def test_parse_zone_reply_snaps_to_candidate_else_zero_confidence():
    cands = ["skincare_aisle", "makeup_aisle"]
    ok = parse_zone_reply('{"zone": "Makeup_Aisle", "confidence": 0.8}', cands)
    assert ok.zone == "makeup_aisle"  # snapped to the canonical candidate (case-insensitive)
    assert ok.confidence == 0.8
    bad = parse_zone_reply('{"zone": "garden_centre", "confidence": 0.9}', cands)
    assert bad.confidence == 0.0  # unknown label -> no confidence so the caller keeps its default


def test_build_zone_prompt_lists_candidates():
    prompt = build_zone_prompt(["skincare_aisle", "makeup_aisle"])
    assert "skincare_aisle" in prompt and "makeup_aisle" in prompt
    assert "JSON" in prompt


def test_build_staff_prompt_includes_optional_hint():
    base = build_staff_prompt(None)
    hinted = build_staff_prompt("Staff wear pink shirts.")
    assert "pink shirts" in hinted
    assert base != hinted


# --- persistent cache -----------------------------------------------------------------------


def test_json_file_cache_roundtrip_and_reload(tmp_path):
    path = tmp_path / "vlm_cache.json"
    cache = JsonFileCache(path)
    assert cache.get("missing") is None
    cache.set("k", {"v": 1})
    assert cache.get("k") == {"v": 1}
    assert path.exists()
    # A fresh instance loads the persisted value (re-runs reuse verdicts).
    assert JsonFileCache(path).get("k") == {"v": 1}


def test_json_file_cache_tolerates_missing_file(tmp_path):
    assert JsonFileCache(tmp_path / "nope.json").get("k") is None


# --- staff decider --------------------------------------------------------------------------


def _decider(heuristic, vlm, cache, min_confidence=0.55):
    return StaffDecider(
        heuristic,
        vlm,
        cache,
        "ST1008",
        staff_hint=None,
        min_confidence=min_confidence,
        classify_staff=True,
        log=_NullLog(),
    )


def test_decider_uses_heuristic_when_no_vlm():
    heuristic = StaffClassifier(threshold=0.5)
    heuristic.observe("CAM1", 1, 0.9)  # dark -> heuristic says staff
    decider = _decider(heuristic, None, None)
    assert decider.is_staff("CAM1", 1, "V1") is True


def test_decider_vlm_overrides_heuristic_when_confident(tmp_path):
    heuristic = StaffClassifier(threshold=0.5)
    heuristic.observe("CAM1", 1, 0.0)  # bright -> heuristic says NOT staff
    vlm = FakeVLM(staff=StaffVerdict(is_staff=True, confidence=0.9, reason="apron"))
    decider = _decider(heuristic, vlm, JsonFileCache(tmp_path / "c.json"))
    decider.observe_crop("CAM1", 1, _img(), _bbox())
    assert decider.is_staff("CAM1", 1, "V1") is True  # VLM wins
    assert vlm.staff_calls == 1


def test_decider_low_confidence_falls_back_to_heuristic(tmp_path):
    heuristic = StaffClassifier(threshold=0.5)
    heuristic.observe("CAM1", 1, 0.9)  # heuristic -> staff
    vlm = FakeVLM(staff=StaffVerdict(is_staff=False, confidence=0.1, reason="unsure"))
    decider = _decider(heuristic, vlm, JsonFileCache(tmp_path / "c.json"))
    decider.observe_crop("CAM1", 1, _img(), _bbox())
    assert decider.is_staff("CAM1", 1, "V1") is True  # low-confidence verdict ignored


def test_decider_no_crop_uses_heuristic(tmp_path):
    heuristic = StaffClassifier(threshold=0.5)
    heuristic.observe("CAM1", 1, 0.0)  # not staff
    vlm = FakeVLM(staff=StaffVerdict(is_staff=True, confidence=0.9, reason="x"))
    decider = _decider(heuristic, vlm, JsonFileCache(tmp_path / "c.json"))
    # No observe_crop -> nothing to send -> heuristic, no VLM call.
    assert decider.is_staff("CAM1", 1, "V1") is False
    assert vlm.staff_calls == 0


def test_decider_visitor_none_forces_heuristic(tmp_path):
    heuristic = StaffClassifier(threshold=0.5)
    heuristic.observe("CAM1", 1, 0.0)
    vlm = FakeVLM(staff=StaffVerdict(is_staff=True, confidence=0.9, reason="x"))
    decider = _decider(heuristic, vlm, JsonFileCache(tmp_path / "c.json"))
    decider.observe_crop("CAM1", 1, _img(), _bbox())
    assert decider.is_staff("CAM1", 1, None) is False  # internal-gate path skips the VLM
    assert vlm.staff_calls == 0


def test_decider_uses_cached_verdict_without_recall(tmp_path):
    cache = JsonFileCache(tmp_path / "c.json")
    cache.set("staff:ST1008:none:V1", {"is_staff": True, "confidence": 0.9, "reason": "seen"})
    heuristic = StaffClassifier(threshold=0.5)  # would say NOT staff (no observations)
    vlm = FakeVLM(raise_on_staff=True)  # must NOT be called on a cache hit
    decider = _decider(heuristic, vlm, cache)
    assert decider.is_staff("CAM1", 1, "V1") is True
    assert vlm.staff_calls == 0


def test_decider_error_falls_back_and_does_not_retry(tmp_path):
    heuristic = StaffClassifier(threshold=0.5)
    heuristic.observe("CAM1", 1, 0.0)
    vlm = FakeVLM(raise_on_staff=True)
    decider = _decider(heuristic, vlm, JsonFileCache(tmp_path / "c.json"))
    decider.observe_crop("CAM1", 1, _img(), _bbox())
    assert decider.is_staff("CAM1", 1, "V1") is False
    assert decider.is_staff("CAM1", 1, "V1") is False  # same visitor again
    assert vlm.staff_calls == 1  # failed visitor not retried this run


# --- factory --------------------------------------------------------------------------------


def _vlm_settings(**over):
    base = {
        "vlm_enabled": True,
        "vlm_provider": "gemini",
        "gemini_api_key": "k",
        "vlm_model": "gemini-2.5-flash-lite",
        "vlm_timeout_s": 30.0,
        "vlm_max_retries": 2,
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_build_vlm_client_none_when_disabled():
    assert build_vlm_client(_vlm_settings(vlm_enabled=False), _NullLog()) is None


def test_build_vlm_client_none_without_key():
    assert build_vlm_client(_vlm_settings(gemini_api_key=""), _NullLog()) is None


def test_build_vlm_client_none_for_unknown_provider():
    assert build_vlm_client(_vlm_settings(vlm_provider="acme"), _NullLog()) is None


# --- zone resolver --------------------------------------------------------------------------


def _zone_settings(**over):
    base = {
        "vlm_classify_zone": True,
        "vlm_zone_min_confidence": 0.55,
        "tracker_sample_fps": 5.0,
        "vlm_zone_frame_fraction": 0.4,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _cam(camera_id, role, zone):
    return CameraConfig(
        camera_id=camera_id, file=f"{camera_id}.mp4", role=role, primary_zone=zone, fps=30.0
    )


def test_product_zone_candidates_excludes_role_known_zones():
    cands = product_zone_candidates()
    assert ZoneName.SKINCARE_AISLE.value in cands
    assert ZoneName.ENTRANCE.value not in cands
    assert ZoneName.CHECKOUT.value not in cands
    assert ZoneName.STOCKROOM.value not in cands


def test_resolve_zones_empty_without_vlm(tmp_path):
    cams = [_cam("CAM1", CameraRole.PRODUCT, ZoneName.SKINCARE_AISLE)]
    out = resolve_zones(cams, tmp_path, None, None, _zone_settings(), "ST1008", _NullLog())
    assert out == {}


def test_resolve_zones_uses_cache_and_skips_non_product(tmp_path):
    cache = JsonFileCache(tmp_path / "c.json")
    cache.set("zone:ST1008:CAM1", {"zone": "makeup_aisle", "confidence": 0.9, "reason": "lipstick"})
    cache.set("zone:ST1008:CAM3", {"zone": "makeup_aisle", "confidence": 0.9, "reason": "x"})
    cams = [
        _cam("CAM1", CameraRole.PRODUCT, ZoneName.SKINCARE_AISLE),
        _cam("CAM3", CameraRole.ENTRANCE, ZoneName.ENTRANCE),  # role-known -> never relabelled
    ]
    vlm = FakeVLM(zone=ZoneVerdict(zone="x", confidence=0.0, reason=""))  # cache hit -> not called
    out = resolve_zones(cams, tmp_path, vlm, cache, _zone_settings(), "ST1008", _NullLog())
    assert out == {"CAM1": "makeup_aisle"}  # product cam overridden; entrance skipped
    assert vlm.zone_calls == 0


def test_resolve_zones_ignores_low_confidence_cache(tmp_path):
    cache = JsonFileCache(tmp_path / "c.json")
    cache.set("zone:ST1008:CAM1", {"zone": "makeup_aisle", "confidence": 0.2, "reason": "guess"})
    cams = [_cam("CAM1", CameraRole.PRODUCT, ZoneName.SKINCARE_AISLE)]
    vlm = FakeVLM(zone=ZoneVerdict(zone="x", confidence=0.0, reason=""))
    out = resolve_zones(cams, tmp_path, vlm, cache, _zone_settings(), "ST1008", _NullLog())
    assert out == {}  # below the confidence floor -> keep the static zone


def test_encode_jpeg_returns_bytes():
    pytest.importorskip("cv2")
    from app.vlm import encode_jpeg

    data = encode_jpeg(_img())
    assert isinstance(data, bytes) and len(data) > 0
