# EVENT SCHEMA

> The contract for every event flowing through the pipeline. Events are the backbone
> of the system — keep them consistent and versioned. Pydantic models are the canonical
> definition; this doc mirrors them for humans.
>
> **✅ Implemented in code:** `services/common/shelfsense_common/contracts/events.py`
> (`Event[...]` envelope + `EventType`, `DetectionCreated`, `TrackUpdated`, `Session*`,
> `MetricComputed`, `AnomalyDetected`, `make_event()`). Import from `shelfsense_common.contracts`;
> never redefine. `SCHEMA_VERSION = "1.0"`. Payloads carry `ts_ms` (source media time) for
> replay/idempotency; envelope carries `correlation_id` for tracing.

## Conventions

- **Envelope:** every event shares a common envelope.
- **Naming:** `noun.verb` past tense (e.g. `detection.created`).
- **Versioning:** `schema_version` on the envelope; additive changes bump minor.
- **IDs:** `event_id` (uuid), `correlation_id` (propagated from frame → detection → track → session).
- **Time:** all timestamps UTC, ISO-8601 / epoch millis.

## Envelope

```json
{
  "event_id": "uuid",
  "event_type": "detection.created",
  "schema_version": "1.0",
  "occurred_at": "2026-05-31T10:00:00.000Z",
  "correlation_id": "uuid",
  "source": "detector",
  "payload": { }
}
```

## Event types (initial draft)

### `frame.captured`
Emitted when a frame is read from the source.
```json
{ "camera_id": "cam-01", "frame_id": 12345, "ts": 1730000000000, "width": 1920, "height": 1080 }
```

### `detection.created`
A person detected in a frame (one event per detection or batched per frame — TBD).
```json
{
  "camera_id": "cam-01",
  "frame_id": 12345,
  "ts": 1730000000000,
  "detections": [
    { "bbox": [x, y, w, h], "confidence": 0.91, "class": "person" }
  ]
}
```

### `track.updated`
A tracked person's state after association, mapped to a store zone.
```json
{
  "camera_id": "cam-01",
  "track_id": "t-0007",
  "frame_id": 12345,
  "ts": 1730000000000,
  "bbox": [x, y, w, h],
  "position": { "x": 0.0, "y": 0.0 },
  "zone": "aisle-1",
  "confidence": 0.88
}
```

### `session.started`
```json
{ "session_id": "s-0007", "track_id": "t-0007", "started_at": 1730000000000, "entry_zone": "entrance" }
```

### `session.updated`
```json
{ "session_id": "s-0007", "zones_visited": ["entrance", "aisle-1"], "journey": [ {"zone":"entrance","enter":...,"dwell_ms":...} ] }
```

### `session.ended`
```json
{
  "session_id": "s-0007",
  "ended_at": 1730000030000,
  "duration_ms": 30000,
  "zones_visited": ["entrance", "aisle-1", "checkout"],
  "funnel_stage": "checkout",
  "total_dwell_ms": 28000
}
```

### `metric.computed`
Aggregated business metric emitted/persisted by analytics.
```json
{ "metric": "footfall", "window": "2026-05-31T10:00/PT1H", "value": 42, "dimensions": {"camera_id":"cam-01"} }
```

### `anomaly.detected`
```json
{ "rule": "abnormal_dwell", "severity": "warn", "ts": 1730000000000, "context": { "zone": "checkout", "value": 600 } }
```

## Status

Draft seeded during scaffolding. Finalize alongside the shared `contracts` Pydantic
models when implementation begins. See [[ARCHITECTURE]] and [[BUSINESS_RULES]].
