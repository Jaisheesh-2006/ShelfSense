"""Event contracts — the structured events that flow between services.

A single envelope `Event[PayloadT]` wraps every message with shared metadata (id, type,
timestamp, correlation id, source). Payloads are typed Pydantic models. This is the canonical
definition referenced by docs/wiki/EVENT_SCHEMA.md — services import these, never redefine them.

Design notes:
- `correlation_id` propagates frame -> detection -> track -> session for tracing.
- Timestamps are UTC. `ts_ms` on payloads is the source media time (epoch millis) so events
  remain meaningful independent of wall-clock processing time (important for replay/idempotency).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class EventType(StrEnum):
    """Canonical event type names (noun.verb, past tense)."""

    FRAME_CAPTURED = "frame.captured"
    DETECTION_CREATED = "detection.created"
    TRACK_UPDATED = "track.updated"
    SESSION_STARTED = "session.started"
    SESSION_UPDATED = "session.updated"
    SESSION_ENDED = "session.ended"
    METRIC_COMPUTED = "metric.computed"
    ANOMALY_DETECTED = "anomaly.detected"


# --- Payloads ---------------------------------------------------------------


class BBox(BaseModel):
    """Axis-aligned bounding box in pixel coordinates."""

    model_config = ConfigDict(frozen=True)
    x: float
    y: float
    w: float
    h: float

    @property
    def foot_point(self) -> tuple[float, float]:
        """Bottom-centre point — used for zone/floor mapping (where the person stands)."""
        return (self.x + self.w / 2.0, self.y + self.h)


class Detection(BaseModel):
    """A single person detection within a frame."""

    bbox: BBox
    confidence: float = Field(ge=0.0, le=1.0)
    class_id: int = 0


class DetectionCreated(BaseModel):
    """Persons detected in one frame (emitted by detector)."""

    camera_id: str
    frame_id: int
    ts_ms: int
    detections: list[Detection] = Field(default_factory=list)


class TrackUpdated(BaseModel):
    """A tracked person's state after association + zone mapping (emitted by tracker)."""

    camera_id: str
    track_id: str
    frame_id: int
    ts_ms: int
    bbox: BBox
    zone: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    is_staff: bool = False


class SessionStarted(BaseModel):
    session_id: str
    track_id: str
    camera_id: str
    started_ms: int
    entry_zone: str


class ZoneDwell(BaseModel):
    zone: str
    enter_ms: int
    dwell_ms: int


class SessionUpdated(BaseModel):
    session_id: str
    zones_visited: list[str] = Field(default_factory=list)
    journey: list[ZoneDwell] = Field(default_factory=list)


class SessionEnded(BaseModel):
    session_id: str
    ended_ms: int
    duration_ms: int
    zones_visited: list[str] = Field(default_factory=list)
    funnel_stage: str
    total_dwell_ms: int


class MetricComputed(BaseModel):
    """An aggregated business metric (emitted/persisted by analytics)."""

    metric: str
    window_start_ms: int
    window_end_ms: int
    value: float
    dimensions: dict[str, str] = Field(default_factory=dict)


class AnomalyDetected(BaseModel):
    rule: str
    severity: str = "warn"
    ts_ms: int
    context: dict[str, str | float | int] = Field(default_factory=dict)


# --- Envelope ---------------------------------------------------------------

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class Event(BaseModel, Generic[PayloadT]):
    """Common envelope wrapping every event on the stream."""

    event_id: str = Field(default_factory=_new_id)
    event_type: EventType
    schema_version: str = SCHEMA_VERSION
    occurred_at: datetime = Field(default_factory=_utcnow)
    correlation_id: str = Field(default_factory=_new_id)
    source: str
    payload: PayloadT


def make_event(
    event_type: EventType,
    payload: PayloadT,
    source: str,
    correlation_id: str | None = None,
) -> Event[PayloadT]:
    """Convenience constructor that fills envelope metadata."""
    kwargs: dict[str, object] = {"event_type": event_type, "payload": payload, "source": source}
    if correlation_id is not None:
        kwargs["correlation_id"] = correlation_id
    return Event(**kwargs)  # type: ignore[arg-type]
