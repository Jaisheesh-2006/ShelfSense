# DESIGN — ShelfSense Store Intelligence System

A containerised system that turns raw in-store **CCTV footage** into live retail analytics, anchored
on one business metric: **offline store conversion rate** (`converted visitors ÷ unique visitors`).
This document is the architecture overview; per-decision reasoning is in [`CHOICES.md`](CHOICES.md).

> Run it: `docker compose up`. API on `:8000` (`/docs`), metrics `/metrics`, Grafana `:3000`.

---

## 1. Problem framing
Offline stores are a data blind spot — there is no equivalent of web session/funnel analytics. The
job is to reconstruct that visibility from camera footage: who entered, where they went, where they
dropped off, and how many converted. The design is therefore optimised for one number being both
**accurate** (good detection, de-duplicated sessions) and **actionable** (clean, queryable endpoints).

## 2. Architecture at a glance
Two tiers with a single contract between them — the **event schema**:

```
CCTV → [Detection Pipeline: YOLOv8 → ByteTrack → Re-ID → behavioural events]
     → events (JSONL + HTTP) → [Intelligence API: ingest → PostgreSQL → metrics] → Dashboard
```

- **Detection pipeline** owns all computer vision and per-person reasoning, and emits *behavioural*
  events (`ENTRY`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`, `REENTRY`, …) — not raw bounding boxes.
- **Intelligence API** (FastAPI) ingests those events idempotently, stores them, and computes
  metrics/funnel/heatmap/anomalies on read.

Decoupling at the event boundary means the CV side and the analytics side evolve independently, and
the pipeline can run batch *or* simulated-real-time without changing the API. Full diagram and
component table: `docs/wiki/ARCHITECTURE.md`.

## 3. Cameras and zones
The store has 5 cameras mapped to functional roles: **Entry** (CAM3, with a calibrated entry line),
**Main floor** (CAM1/CAM2), **Billing** (CAM5), and a **back room** (CAM4) whose occupants are treated
as staff and excluded from customer metrics. Overlap between the front cameras is resolved by Re-ID so
one shopper is counted once.

## 4. How the North Star is computed
1. **Unique visitors** = distinct `visitor_id`s (Re-ID; re-entries are the *same* visitor).
2. **Converted visitor** = a visitor present in the **billing zone within the 5-minute window before a
   POS transaction** (no customer id exists, so correlation is by time-window + store).
3. **Conversion rate** = converted ÷ unique, staff excluded. The funnel
   (`Entry → Zone Visit → Billing Queue → Purchase`) explains *where* drop-off happens.

## 5. Counting integrity (why the number is trustworthy)
All counting is on **de-duplicated sessions**, never raw detections. This directly defends the metric
against the failure modes that inflate vendor systems: groups are counted as individuals, re-entries
do not double-count, and staff are filtered out. Low-confidence detections are *flagged on the event*,
not silently dropped — so uncertainty is visible rather than hidden.

## 6. Production readiness
- **One-command start:** `docker compose up`, no manual steps; the YOLO model is baked into the image
  so there is no runtime download.
- **Idempotent ingest:** `event_id` is the dedup key — re-POSTing a batch is safe (replay-friendly).
- **Graceful degradation:** DB unavailable → HTTP 503 with a structured body, never a raw stack trace.
- **Zero-traffic correctness:** empty windows return valid zeros, not null or a crash.
- **Observability:** structured JSON logs per request (`trace_id, store_id, endpoint, latency_ms,
  event_count, status_code`); Prometheus metrics; Grafana dashboards.
- **Tested:** unit + edge-case coverage (empty store, all-staff, zero purchases, re-entry in funnel).

## 7. Known limitations & next steps
- Conversion is window-correlated, not identity-linked (no PII) — it can mis-attribute in dense
  billing periods; documented and bounded by the 5-minute rule.
- The entry line is a per-camera manual calibration; robust to a fixed camera, not to camera moves.
- At 40 live stores the CPU-bound detector is the bottleneck — scale horizontally per store and put a
  queue in front of ingest. These are deliberate, bounded trade-offs, not oversights.

## 8. AI-Assisted Decisions
AI (Claude) was used throughout; the places it materially shaped the design — and where we overrode it:

1. **Event-stream architecture — overrode.** The assistant first designed an event-driven system with a
   Kafka-compatible broker (Redpanda). On re-reading the spec we recognised an *ingest-centric* model
   and **dropped the broker** in favour of `POST /events/ingest` + idempotency — fewer moving parts, a
   more reliable gate, and a closer fit to the requirements.
2. **Cross-camera Re-ID — reversed our own earlier call.** The assistant initially recommended treating
   cameras independently with no Re-ID for simplicity; the spec requires it (visitor_id, REENTRY,
   cross-camera dedup), so we **reversed** — letting the requirement, not convenience, drive the design.
3. **Model packaging — agreed.** Pre-baking YOLO weights into the image (assistant's suggestion) makes
   `docker compose up` deterministic and offline-safe; we agreed, accepting the image-size cost.

A working practice also came from this collaboration: a living knowledge base (`docs/wiki/`) the
assistant reads each session, so design context compounds rather than resets.
