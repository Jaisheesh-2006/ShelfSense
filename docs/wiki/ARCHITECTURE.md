# ARCHITECTURE

> Update whenever the architecture changes. See [[DECISIONS]] for rationale. This file is
> the source for the graded **`DESIGN.md`** deliverable (ADR-0003) — keep it clear enough to
> distill. Grounded in [[GROUND_TRUTH]]: **5 cameras** (entrance camera drives footfall) and a
> **POS CSV** joined in analytics for **conversion rate**.

## Guiding principles

- A working end-to-end system beats isolated sophisticated components.
- Each service has one clear responsibility.
- Communicate via structured events over a streaming backbone.
- Observability is first-class. Avoid unnecessary complexity.

## System overview

```
                ┌──────────────────────────── Event Stream (Kafka-compatible) ────────────────────────────┐
                │                                                                                           │
   CCTV / video │        frame.captured          detection.created        track.updated        session.*   │
   ─────────────▼──────┐   ─────────────►   ┌──────────────┐  ───────►  ┌──────────────┐  ──────►  ┌────────▼────────┐
   │   detector        │                    │   tracker    │            │  analytics   │           │      api        │
   │  (YOLO person     │───detections──────►│ (MOT + re-id │───tracks──►│ sessions,    │──metrics─►│   (FastAPI)     │
   │   detection)      │                    │  + zone map) │            │ dwell, zones │           │  REST endpoints │
   └───────────────────┘                    └──────────────┘            │ funnels,     │           └────────┬────────┘
                                                                         │ anomalies    │                    │
                                                                         └──────┬───────┘                    │
                                                                                │                            ▼
                                                            ┌───────────────────▼──────────┐         ┌──────────────┐
                                                            │   PostgreSQL (metrics store)  │◄────────│   Frontend   │
                                                            │   Redis (cache / hot state)   │         │   (React)    │
                                                            └───────────────────────────────┘         └──────────────┘

   Cross-cutting: Prometheus metrics + Grafana dashboards, structured logging on every service.
```

## Services

| Service | Responsibility | Consumes | Produces |
|---------|----------------|----------|----------|
| **detector** | Detect persons in frames using YOLO. Stateless per frame. | video frames | `detection.created` events |
| **tracker** | Assign stable IDs across frames (multi-object tracking), map detections to store zones via the floor plan. | `detection.created` | `track.updated` events |
| **analytics** | Build sessions, compute dwell/zone engagement, **session-based funnel**, anomalies, KPIs; **join POS CSV for conversion rate**. Persist metrics. | `track.updated` + POS CSV | `session.*`, `metric.*` events + DB writes |
| **api** | Expose business insights over REST (FastAPI). Read from DB/Redis. | DB / Redis | HTTP/JSON responses |
| **frontend** | Dashboard visualizing footfall, journeys, funnels, KPIs. | api | — |

## Data flow

1. **Ingestion** — frames are read from CCTV footage and emitted/handled by the detector.
2. **Detection** — YOLO produces bounding boxes for persons per frame.
3. **Tracking** — detections are associated over time into tracks; each track point is mapped to a store zone using the floor-plan homography/zone polygons.
4. **Analytics** — tracks are aggregated into sessions; dwell time, zone engagement, journeys, funnel stages, and anomalies are computed and persisted.
5. **Serving** — the API reads computed metrics; the frontend renders them.

## Communication

- **Event stream:** Kafka-compatible streaming as the backbone between services (decoupling, replayability, scale). A lightweight in-process/queue shim may back early development; the contract stays event-shaped. See [[DECISIONS]].
- **Contracts:** All events conform to schemas in [[EVENT_SCHEMA]]. Pydantic models are the single definition shared via a common contracts module.

## Storage

- **PostgreSQL** — durable store for sessions, metrics, aggregates (query surface for the API).
- **Redis** — hot state / caching (e.g. active tracks, last-known positions, rate-limited reads).

## Observability

- **Structured logging** in every service (JSON logs, correlation/trace IDs per frame & track).
- **Prometheus** metrics endpoints per service (throughput, latency, queue depth, detection counts).
- **Grafana** dashboards for pipeline health + business KPIs.

## Deployment

- Each service is independently **Dockerized**.
- **docker-compose** orchestrates the full stack (services + Kafka + Postgres + Redis + Prometheus + Grafana) for local/reviewer runs.

## Open architectural questions

- Streaming backbone concrete choice (Kafka vs. Redpanda vs. in-proc shim for the demo) — see [[DECISIONS]].
- Re-identification across multiple cameras (if multi-camera).
- Where zone-mapping (homography) lives: tracker vs. a dedicated mapping step.

> Status: design seeded during scaffolding. Implementation pending plan approval.
