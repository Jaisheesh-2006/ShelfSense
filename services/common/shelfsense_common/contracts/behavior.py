"""Prescribed behavioural event contract — the flat schema the detection layer EMITS and the
Intelligence API INGESTS.

This is the canonical, schema-graded contract from docs/wiki/EVENT_SCHEMA.md (SPEC, Part A).
It deliberately replaces the internal `detection.created`/`track.updated` envelope (events.py)
as the *emitted* event (ADR-0005): low-level detector->tracker data may stay internal, but every
event that leaves the pipeline and enters the API is a `BehaviorEvent`.

Design notes:
- Flat (not envelope/payload) because the SPEC prescribes a flat object and reviewers grade against
  it. `event_id` is the idempotency/dedup key (ingest is idempotent by it).
- Timestamps are timezone-aware UTC ISO-8601, derived from clip start + frame offset (so events are
  meaningful independent of processing wall-clock — important for replay and integrity).
- `zone_id` is null for ENTRY/EXIT (the threshold has no zone); `dwell_ms` is 0 for instantaneous
  events. Low-confidence detections are flagged via `confidence`, never silently dropped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Fixed namespace so event_ids are a deterministic function of the event's stable identity.
_EVENT_ID_NAMESPACE = uuid.UUID("a3f5c8e2-1b4d-4e6f-8a9c-0d1e2f3a4b5c")


def deterministic_event_id(
    store_id: str,
    camera_id: str,
    visitor_id: str,
    event_type: object,
    zone_id: str | None,
    timestamp: datetime,
) -> str:
    """A stable UUIDv5 derived from the event's identifying fields (ADR-0021).

    The timestamp is recording-relative (clip start + frame offset) and detection is reproducible
    for a given clip+config, so the same event always hashes to the same id — making a re-POST (a
    detector restart / identical re-run) idempotent instead of accumulating duplicates. Volatile
    fields (confidence, dwell) are intentionally excluded so float jitter can't change the id.
    """
    key = "|".join(
        [
            store_id,
            camera_id,
            visitor_id,
            str(event_type),
            zone_id or "",
            timestamp.astimezone(UTC).isoformat(),
        ]
    )
    return str(uuid.uuid5(_EVENT_ID_NAMESPACE, key))


class BehaviorEventType(StrEnum):
    """The 8 prescribed behavioural event types (SPEC §3 / EVENT_SCHEMA catalogue)."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


#: Event types that occur at the entrance threshold and therefore carry no zone.
_ZONELESS_TYPES = {BehaviorEventType.ENTRY, BehaviorEventType.EXIT}


class EventMetadata(BaseModel):
    """Optional, event-type-specific detail. Kept small and explicit rather than a free dict."""

    model_config = ConfigDict(extra="forbid")

    queue_depth: int | None = None  # set for BILLING_QUEUE_JOIN
    sku_zone: str | None = None  # finer brand/zone label where known
    session_seq: int | None = None  # ordinal of this event within the visitor session


class BehaviorEvent(BaseModel):
    """One behavioural event in the prescribed flat schema (EVENT_SCHEMA.md)."""

    model_config = ConfigDict(use_enum_values=False)

    event_id: str = Field(default="")  # blank -> filled deterministically (see validator below)
    store_id: str
    camera_id: str
    visitor_id: str
    event_type: BehaviorEventType
    timestamp: datetime  # tz-aware UTC; derived from clip start + frame offset
    zone_id: str | None = None  # null for ENTRY/EXIT
    dwell_ms: int = Field(default=0, ge=0)  # 0 for instantaneous events
    is_staff: bool = False  # classified by the pipeline (Slice 2.4)
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_utc(cls, v: datetime) -> datetime:
        """Reject naive datetimes and normalise to UTC so emitted timestamps are unambiguous."""
        if v.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware (UTC)")
        return v.astimezone(UTC)

    @field_validator("zone_id")
    @classmethod
    def _entry_exit_have_no_zone(cls, v: str | None, info) -> str | None:
        """ENTRY/EXIT happen at the threshold and must not carry a zone (schema rule)."""
        event_type = info.data.get("event_type")
        if event_type in _ZONELESS_TYPES and v is not None:
            raise ValueError(f"{event_type.value} must have zone_id=None")
        return v

    @model_validator(mode="after")
    def _ensure_event_id(self) -> BehaviorEvent:
        """Fill a deterministic event_id when one wasn't supplied (the detector path). An id given
        upstream (e.g. on ingest of an already-emitted event) is preserved, so the dedup key stays
        stable end to end and a re-POST is idempotent (ADR-0021)."""
        if not self.event_id:
            self.event_id = deterministic_event_id(
                self.store_id,
                self.camera_id,
                self.visitor_id,
                self.event_type,
                self.zone_id,
                self.timestamp,
            )
        return self
