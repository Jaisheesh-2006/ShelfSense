# PROMPT
# Task: Unit-test the ADR-0040 superset pieces — (1) the VLM demographics reply parser
#       (gender/age-bucket snapping, confidence clamping, honest nulls) and (2) build_event_metadata
#       (zone descriptors from zone_id, billing queue analytics, zoneless entry, is_face_hidden).
# Context: events now carry the sample_events.jsonl richer fields as a metadata superset; these two
#       pure functions are the seam. Must be deterministic, no network, no model calls.
# Constraints: pytest; pure functions only; cover the unknown/garbage paths (honest nulls).
# Output: this test file.
#
# CHANGES MADE
# - New file (ADR-0040). Covers parse_demographics_reply + build_event_metadata superset.

from __future__ import annotations

import pytest
from app.vlm import DemographicsVerdict, parse_demographics_reply
from shelfsense_common.contracts import BehaviorEventType, build_event_metadata


class TestParseDemographicsReply:
    def test_female_adult(self) -> None:
        v = parse_demographics_reply(
            '{"gender":"female","gender_confidence":0.8,'
            '"age_bucket":"adult","age_confidence":0.6,"reason":"long hair"}'
        )
        assert isinstance(v, DemographicsVerdict)
        assert v.gender == "F"
        assert v.age_bucket == "adult"
        assert v.gender_confidence == 0.8
        assert v.age_confidence == 0.6

    def test_male_maps_to_m(self) -> None:
        assert parse_demographics_reply('{"gender":"male","gender_confidence":0.5}').gender == "M"

    def test_unknown_gender_and_age_become_null(self) -> None:
        v = parse_demographics_reply(
            '{"gender":"unknown","gender_confidence":0.1,"age_bucket":"unknown"}'
        )
        assert v.gender is None
        assert v.age_bucket is None

    def test_unrecognised_age_bucket_is_dropped(self) -> None:
        # A fine-grained band must not leak through — we keep only the coarse set.
        v = parse_demographics_reply('{"gender":"female","age_bucket":"45-50"}')
        assert v.age_bucket is None

    def test_confidence_is_clamped(self) -> None:
        v = parse_demographics_reply(
            '{"gender":"female","gender_confidence":5,"age_confidence":"x"}'
        )
        assert v.gender_confidence == 1.0  # clamped to [0,1]
        assert v.age_confidence == 0.0  # garbage -> 0.0

    def test_tolerates_json_fence(self) -> None:
        v = parse_demographics_reply('```json\n{"gender":"male","gender_confidence":0.7}\n```')
        assert v.gender == "M"


class TestBuildEventMetadataSuperset:
    def test_zone_descriptors_derived(self) -> None:
        m = build_event_metadata(
            event_type=BehaviorEventType.ZONE_ENTER, zone_id="makeup_aisle", session_seq=2
        )
        assert m.zone_name == "Makeup Aisle"
        assert m.zone_type == "SHELF"
        assert m.is_revenue_zone is True
        assert m.session_seq == 2
        assert m.is_face_hidden is True  # our footage is anonymised
        assert m.gender_pred is None and m.age_pred is None  # filled later by the VLM merge

    def test_billing_join_sets_queue_position(self) -> None:
        m = build_event_metadata(
            event_type=BehaviorEventType.BILLING_QUEUE_JOIN, zone_id="checkout", queue_depth=3
        )
        assert m.zone_type == "BILLING"
        assert m.queue_position_at_join == 3
        assert m.abandoned is None

    def test_billing_abandon_flag(self) -> None:
        m = build_event_metadata(
            event_type=BehaviorEventType.BILLING_QUEUE_ABANDON, zone_id="checkout"
        )
        assert m.abandoned is True

    def test_entry_is_zoneless(self) -> None:
        m = build_event_metadata(event_type=BehaviorEventType.ENTRY, zone_id=None)
        assert m.zone_name is None
        assert m.zone_type is None
        assert m.is_revenue_zone is None

    def test_unknown_zone_falls_back_titlecased(self) -> None:
        m = build_event_metadata(event_type=BehaviorEventType.ZONE_ENTER, zone_id="new_aisle_7")
        assert m.zone_name == "New Aisle 7"
        assert m.zone_type == "SHELF"  # safe default so a new store needs no change


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("male", "M"), ("female", "F"), ("MALE", "M"), ("f", "F"), ("nonbinary", None), ("", None)],
)
def test_gender_mapping_table(raw: str, expected: str | None) -> None:
    assert parse_demographics_reply(f'{{"gender":"{raw}"}}').gender == expected
