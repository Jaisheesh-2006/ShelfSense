"""Versioned data contracts shared across services (events + zone/store config)."""

from shelfsense_common.contracts.events import (
    SCHEMA_VERSION,
    AnomalyDetected,
    BBox,
    Detection,
    DetectionCreated,
    Event,
    EventType,
    MetricComputed,
    SessionEnded,
    SessionStarted,
    SessionUpdated,
    TrackUpdated,
    make_event,
)
from shelfsense_common.contracts.zones import (
    STORE,
    CameraConfig,
    CameraRole,
    EntranceLine,
    StoreConfig,
    ZoneName,
)

__all__ = [
    "SCHEMA_VERSION",
    "Event",
    "EventType",
    "make_event",
    "BBox",
    "Detection",
    "DetectionCreated",
    "TrackUpdated",
    "SessionStarted",
    "SessionUpdated",
    "SessionEnded",
    "MetricComputed",
    "AnomalyDetected",
    "ZoneName",
    "CameraRole",
    "EntranceLine",
    "CameraConfig",
    "StoreConfig",
    "STORE",
]
