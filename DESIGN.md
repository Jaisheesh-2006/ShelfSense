# ShelfSense — System Design

## Overview

- **Problem:** physical retail lacks the funnel analytics e-commerce takes for granted — who enters, where they dwell, where they drop off, whether they buy.
- **North-star metric:** offline conversion rate = `converted visitors / unique visitors`.
- **Approach:** an event-driven system — a CV pipeline turns CCTV into behavioral events; an API ingests, stores, and computes metrics on read. A strict event schema decouples the two, enabling offline batching, replay, and independent scaling.

## Architecture

```text
CCTV clips
   │  YOLO + ByteTrack + motion stitch + Re-ID + staff classification
   ▼
behavioral events ──(JSONL + HTTP POST)──► Intelligence API ──► PostgreSQL
                                                  │
                                                  ▼
                                  React dashboard + Prometheus / Grafana
```

- **Detection pipeline** owns all pixels: detection, tracking, identity, sessionization, spatial reasoning.
- **Intelligence API** owns ingest, validation, persistence, and metric computation — it never sees a pixel.
- **The event schema is the only contract between them**, so either tier can be rebuilt independently.

## Assumptions (forced by the data)

- **Unique visitor** = one cross-camera Re-ID identity; all cameras contribute, gated to solid in-store tracks.
- **Conversion** has no `customer_id`, so it correlates billing-zone presence to a POS transaction within a 5-minute window.
- **Staff** are excluded from the denominator via uniform-based classification, not dwell time.
- **Zones** map each camera view to a floor-plan region (checkout, skincare aisle, …).
- **Metrics are read-time** over the latest events; minor ingest lag is tolerated.

## Detection Layer

- **Detect:** YOLOv8n, CPU-only — portable, no CUDA setup.
- **Track:** ByteTrack for stable, occlusion-resistant trajectories.
- **Stitch (primary identity fix):** a motion associator re-links fragmented tracks (a person turning or briefly occluded) by spatio-temporal continuity, *before* appearance Re-ID.
- **Re-ID:** HSV color-histogram, cosine-matched, for cross-camera de-duplication — the fallback where motion can't apply.
- **Group split (optional):** `GROUP_SPLIT=pose` splits a merged-group box into one sub-track per skeleton; off by default, gate-safe.
- **Staff:** a VLM (Groq/Llama) classifies staff vs customer; a per-store color heuristic is the offline fallback.
- **Events:** zone maps + walkable-floor polygons turn coordinates into `ENTRY` / `ZONE_DWELL` / `BILLING_QUEUE_JOIN` / `EXIT`, suppressing reflections and phantoms.

**Key trade-offs**
- **CPU over GPU** — portable, at the cost of throughput and input resolution.
- **Motion over appearance for identity** — measured that appearance can't separate identities on overhead views (same-person crops land *farther* apart than different-person crops), so motion is primary and appearance is the cross-camera fallback.
- **Color histogram over a learned embedding** — fewer dependencies; acceptable because motion, not a heavier appearance model, is the real fix.

## Event Model

- **Semantic events, not raw boxes:** emitting `ZONE_DWELL` and friends shrinks the data stream by orders of magnitude, keeps video PII out of storage, and simplifies analytics.
- **Replay-friendly:** events are appended to JSONL and POSTed, so the API runs on pre-generated events with no CV. Extends cleanly to a broker (Kafka) under high write throughput.

## Intelligence Layer

- **Ingest:** idempotent `POST /events/ingest`, deduped on `event_id` — safe replays, no double-counting.
- **Storage:** PostgreSQL as source of truth; SQLite for hermetic tests.
- **Metrics:** computed at query time — simpler, and fast at current volumes.
- **Funnel:** `Entry → Zone → Billing → Purchase`, monotonic, staff-excluded.
- **Anomalies:** queue spikes and conversion drops, with configurable baselines where history is absent.
- **Health:** feed freshness measured against the latest ingested event, so replays read healthy.

## Production Readiness

- **One command:** `docker compose up --build` runs API + DB + dashboard; heavy CV is behind `--profile detect`, defaulting to fast replay to respect reviewer time.
- **Idempotency:** deterministic `event_id` survives network retries and re-runs.
- **Observability:** JSON request logs (`trace_id`, endpoint, latency, status).
- **Resilience:** partial-success ingest (one bad event doesn't fail the batch); DB down → structured 503, never a stack trace.
- **Testing:** 164 unit + integration tests (re-entry, missing data, tracklet stitching, end-to-end replay); coverage gated at 70%.
- **Dashboard:** a React SPA polling the live conversion ring, funnel, and heatmaps.

## AI-Assisted Decisions

**1. Detection model**
- *Options:* YOLOv8 (n/s/m), YOLOv9 / RT-DETR, MediaPipe.
- *AI suggested:* YOLOv8 baseline, nano on CPU; a larger model for occluded billing frames.
- *Chosen:* YOLOv8-nano, CPU-only PyTorch. **Agreed** — fast and accurate enough to count people, integrates with ByteTrack; I enforced the CPU-only build to avoid pulling gigabytes of unused CUDA.

**2. Visitor identity (Re-ID)**
- *Options:* independent cameras; histogram Re-ID; learned embedding (OSNet); motion stitching.
- *AI suggested:* start with independent cameras, then strengthen *appearance* with a learned embedding.
- *Chosen:* histogram Re-ID for cross-camera de-dup + a motion stitcher (default-on) as the primary within-camera fix. **Disagreed twice** — independent cameras can't give an accurate count; and I measured that on overhead CCTV appearance can't separate identities (same `0.66` vs different `0.61`), so I moved the fix to a motion layer — collapsing a roaming staffer from 4 ids to 1 and aligning Store 2 footfall with ground truth.

**3. Pipeline → API transport**
- *Options:* a Kafka-compatible broker (Redpanda) vs. batched HTTP POST.
- *AI suggested:* a broker for scalability, then the simpler path.
- *Chosen:* idempotent HTTP POST, broker dropped. **Disagreed** with the broker — for a single producer/consumer it adds infrastructure and failure modes; idempotent ingest gives the same reliability with far less operational risk.

## Limitations & Future Work

- **CPU-bound at scale:** 40+ stores need a CUDA image and edge GPUs.
- **Cross-camera identity:** within-camera over-split is fixed by motion, but cross-camera de-dup still leans on appearance (a roaming staffer is counted per camera). A homography fix is infeasible *here* — Store_2's cameras don't overlap and were recorded on different days, so a merge would fabricate identities. Documented, not forced; impact stays within the accepted ±1–2.
- **Tightly-packed groups:** YOLO merges front-to-back groups into one box (Store_2 ~17–18 vs 22). The pose splitter gave no net gain on this footage (groups are *tall*, not *wide*; pose degrades under occlusion) — kept as an honest, off-by-default negative result. Closing it needs a top-view-tuned detector or a better angle.
- **Synchronous ingest:** a queue or broker would stop slow DB writes from blocking the pipeline under live multi-store load.
