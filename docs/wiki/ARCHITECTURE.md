# ARCHITECTURE

> Canonical system design (current, post-ADR-0005). Source for the reviewer-facing `DESIGN.md`.
> Authoritative requirements: [[SPEC]]. Decisions + rationale: [[DECISIONS]]. Data facts: [[GROUND_TRUTH]].

## Design goal
Every component serves one number — the **North Star: conversion rate** (`converted visitors ÷
unique visitors`). Components either make it *more accurate* (detection/tracking/Re-ID) or *more
actionable* (the API + dashboard).

## Two-tier shape (clean seam: seeing vs serving)

```
 Raw CCTV clips (2 stores · ~4 role-named cams each)
      │  OpenCV samples ~5 fps
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ DETECTION PIPELINE  (offline/CV; owns all per-person reasoning)       │
│   YOLOv8 detect → ByteTrack track → Re-ID (visitor_id, cross-cam,     │
│   re-entry) → zone & direction logic → emit BEHAVIOURAL events        │
└─────────────────────────────────────────────────────────────────────┘
      │  events.jsonl  +  HTTP POST (batched, simulated real-time)
      ▼
┌─────────────────────────────────────────────────────────────────────┐
│ INTELLIGENCE API  (FastAPI; owns ingest, storage, metrics)            │
│   POST /events/ingest  → validate, dedup (idempotent), store          │
│   GET /stores/{id}/{metrics,funnel,heatmap,anomalies}, /health        │
│            │ reads/writes                                             │
│            ▼   PostgreSQL (events + derived metrics)                  │
└─────────────────────────────────────────────────────────────────────┘
      │  JSON
      ▼
 Live dashboard (≥1 metric updating as events arrive)   +   Prometheus/Grafana, structured logs
```

The two tiers share exactly one contract — the **event schema** ([[EVENT_SCHEMA]]). Either side can be
reworked independently. The whole stack starts with one `docker compose up`.

## Components & responsibilities
| Component | Responsibility | Key inputs → outputs |
|-----------|----------------|----------------------|
| **Detection pipeline** | Detect people, track them, assign a per-visit `visitor_id` (Re-ID), classify staff, map to zones/direction, compute dwell & queue, **emit behavioural events**. Owns all CV + sessionization. Optionally calls a **VLM (Gemini) offline** for staff + zone classification (ADR-0027) — off by default, heuristic fallback, gate-safe. | CCTV clips → `events.jsonl` + POST to API |
| **Intelligence API** (FastAPI) | Ingest events (idempotent, deduped, partial-success), persist, and compute metrics/funnel/heatmap/anomalies on read. Health + observability. | events → JSON metrics |
| **PostgreSQL** | Durable store for events + derived metrics; the query surface. | — |
| **Dashboard** | Show ≥1 metric live as events flow (Part E). | API → screen |
| **Prometheus + Grafana** | Process metrics + dashboards (observability). | `/metrics` |

## API internals (Slice 2.6, ADR-0013)
Package `shelfsense_api` (renamed from `app` to un-collide with the detector's `app`; run
`uvicorn shelfsense_api.main:app`). Strict layering, no business logic in handlers:
- **routers/** (`events.py`, `stores.py`, `health.py`) — HTTP shape + validation only.
- **`shelfsense_common/analytics.py`** — pure `compute_funnel`/`compute_store_metrics` (reuse 2.5's
  `conversion.py`); the same functions feed the Prometheus business gauges, so numbers never diverge.
- **`repository.py`** — the only DB-touching layer; maps `BehaviorEvent`/`Transaction` ↔ ORM rows,
  does idempotent dedup insert. Tables: `behavior_events` (new, `event_id` PK), `transactions`
  (POS, loaded at startup by `pos_ingest.py`). The engine is built lazily so the app imports without a
  Postgres driver (hermetic SQLite TestClient tests). Retired the placeholder `/api/v1/*`.

## Camera → role mapping (now explicit in the corrected dataset)
The corrected dataset **names cameras by role** ([[GROUND_TRUTH]] §1), so the mapping is no longer inferred:

- **Store_1** (= the old single store, ST1008): Entry = **CAM 3 - entry** (calibrated footfall line —
  **footfall only, does not count visitors**: its view is dominated by mall-corridor pass-by; ADR-0011) ·
  Main floor = **CAM 1 - zone + CAM 2 - zone** · Billing = **CAM 5 - billing** (with a calibrated
  **walkable-floor mask** so a wall mirror / backlit display can't be counted as people; ADR-0010). The old
  **CAM 4 stockroom is gone** from the dataset (it was staff-only and empty in-clip — no loss).
  **Unique visitors are counted from the shopping-floor cams (CAM1/CAM2/CAM5)**; cross-camera overlap is
  handled by Re-ID de-duplication so one shopper is counted once, and **staff are excluded by their black
  uniform** (ADR-0009).
- **Store_2** (NEW, not yet processed): cams **entry 1 / entry 2 / zone / billing_area** (two entrances).
  Mapping the same roles is mechanical, but the pipeline currently runs **one store**; **multi-store
  processing + per-store `store_id` tagging is pending** (ADR-0024, [[STATE]]). The API is already per-store
  (`/stores/{id}/...`), so the serving tier needs no change for a second store.

## Data flow (one visitor)
1. **Detect** — YOLO finds people on sampled frames (CAM3 etc.).
2. **Track** — ByteTrack links boxes into a stable track; a `visitor_id` is assigned at `ENTRY`.
3. **Re-ID** — the same person across overlapping cameras / on return maps to the same `visitor_id`
   (→ `REENTRY`, never a second `ENTRY`).
4. **Behavioural events** — crossing the entrance line → `ENTRY`/`EXIT`; zone presence →
   `ZONE_ENTER`/`ZONE_EXIT`/`ZONE_DWELL` (30 s); billing → `BILLING_QUEUE_JOIN`/`ABANDON`.
5. **Ingest** — events POSTed in batches to `/events/ingest`; deduped by `event_id` (idempotent).
   **Implemented (Slice 2.8, ADR-0015):** the detector's `HttpEventSink` auto-POSTs as part of its run
   (a `FanOutSink` also writes the JSONL), so `docker compose up` feeds the API with no manual replay.
6. **Serve** — metrics/funnel/heatmap/anomalies computed from stored events at query time; conversion
   joins POS via the 5-minute billing-window rule ([[BUSINESS_RULES]]).

## Production concerns (first-class)
- **Idempotency:** `event_id` is the dedup key; re-POSTing a batch is safe (covers the durability a
  broker would have given).
- **Graceful degradation:** DB unavailable → HTTP 503 with a structured body, never a raw stack trace.
- **Zero-traffic:** empty windows return valid zeros, never null/crash.
- **Observability:** structured JSON logs per request (`trace_id, store_id, endpoint, latency_ms,
  event_count, status_code`); Prometheus `/metrics`; Grafana.
- **Confidence calibration:** low-confidence detections are flagged on the event, never silently dropped.

## Storage
**PostgreSQL** — makes the DB-down→503 path realistic and reads scale cleanly. SQLite is the documented
simpler alternative (single-file, fewer containers). See [[DECISIONS]] ADR-0005.

## Why no message broker
The spec is ingest-centric, and the gate hinges on a clean one-command start. The pipeline writes
`events.jsonl` and POSTs batches to `/events/ingest`; idempotent ingest makes replay safe. This removes
a heavy moving part (Redpanda) that added gate risk. At 40 live stores we would reintroduce a queue in
front of ingest — a known, bounded scaling step (see [[DECISIONS]] ADR-0005 and the scale Q in [[INTERVIEW_QA]]).

## Scaling notes (40 stores, real-time)
Detection is the CPU bottleneck; each store's feeds are independent, so scale **horizontally** (a
detector worker per store/camera), optionally GPU or fewer fps. The API/ingest is lighter and scales
separately behind a queue. Conversion/funnel are per-store and parallelisable.

## Repo layout (deviation from the spec's suggestion is noted here)
We use `services/` (detector, api, common) rather than the spec's `pipeline/` + `app/`, because the
shared `common` package (event contracts, config, logging) is imported by both tiers. Functionally
equivalent; the spec permits deviation when explained.
