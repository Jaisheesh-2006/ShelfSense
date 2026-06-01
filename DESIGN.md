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
1. **Unique visitors** = distinct `visitor_id`s — one assigned per tracked customer on first
   detection inside the store (de-duplicated across cameras by Re-ID; re-entries are the *same*
   visitor). This, not raw door-crossings, is the denominator (see §5 for why).
2. **Converted visitor** = a visitor present in the **billing zone within the 5-minute window before a
   POS transaction** (no customer id exists, so correlation is by time-window + store).
3. **Conversion rate** = converted ÷ unique, staff excluded. The funnel
   (`Entry → Zone Visit → Billing Queue → Purchase`) explains *where* drop-off happens.

## 5. Counting integrity (why the number is trustworthy)
All counting is on **de-duplicated sessions**, never raw detections. This directly defends the metric
against the failure modes that inflate vendor systems: groups are counted as individuals, re-entries
do not double-count, and staff are filtered out. Low-confidence detections are *flagged on the event*,
not silently dropped — so uncertainty is visible rather than hidden.

Footfall uses **ByteTrack** (stable per-person identity) plus a pure, unit-tested **line-crossing
state machine** on the entrance camera: an `ENTRY`/`EXIT` fires only when a track's foot-point actually
crosses the calibrated door line, with on-line flicker debounced. We **validated the line against the
real video** and it caught a genuine error: an interim placement chased the busiest motion and ended up
on the **mall walkway**, counting pass-by pedestrians as visitors — a classic false-footfall trap. We
reverted it to the real centre-left doorway, where this 2-minute clip shows **≈0 clean crossings**,
because almost everyone on camera is *already inside* (they entered before the window). Rather than
fabricate entrances or chase mall traffic for a prettier number, we therefore count **unique visitors as
distinct people detected inside the store** (a `visitor_id` per tracked customer, de-duplicated by Re-ID),
and keep `ENTRY`/`EXIT` as flow events for when a crossing genuinely occurs. The counts move with the
input and never include non-customers — which is exactly what the integrity check rewards.

## 6. Production readiness
- **One-command start:** `docker compose up`, no manual steps; the YOLO model is baked into the image
  so there is no runtime download.
- **Idempotent ingest:** `event_id` is the dedup key — re-POSTing a batch is safe (replay-friendly).
- **Graceful degradation:** DB unavailable → HTTP 503 with a structured body, never a raw stack trace.
- **Zero-traffic correctness:** empty windows return valid zeros, not null or a crash.
- **Observability:** structured JSON logs per request (`trace_id, store_id, endpoint, latency_ms,
  event_count, status_code`); Prometheus metrics; Grafana dashboards.
- **Tested:** unit + edge-case coverage (empty store, all-staff, zero purchases, re-entry in funnel).

## 7. Assumptions
Where the real data forced an interpretation, we state it **explicitly here** rather than bury it, so a
reviewer knows exactly what is measured and why. Each is data-driven and revisited if better data arrives.

- **A1 — CCTV clips contain almost no entry/exit events, so a "visitor" is a distinct person seen
  *inside* the store, not a door-crosser.** The 5 clips are ~2-minute *synchronised* windows. With the
  entrance line on the real CAM3 door, the whole clip yields **0 clean threshold crossings**: nearly
  everyone on camera is *already inside* (they entered before the window began), and the only sustained
  motion is **mall pass-by** behind the storefront glass, which we deliberately exclude. We therefore
  **assume/define unique visitors = distinct `visitor_id`s detected in a customer area** (one per tracked
  customer, Re-ID-deduped), and keep `ENTRY`/`EXIT` as flow events for when a crossing genuinely occurs.
  *Why:* makes the North Star computable on this data without fabricating entrances; on longer or live
  feeds, entrance-crossing footfall regains its meaning. (See `docs/wiki/DECISIONS.md` ADR-0006/0007.)
- **A2 — Conversion is correlated by time-window, not customer identity.** No PII customer id exists, so a
  visitor counts as converted if they were in the billing zone within 5 minutes before a POS transaction.
- **A3 — Clip vs full-day POS mismatch is handled by windowing, not naive division.** Footfall/sessions are
  computed on a comparable window and any extrapolation is documented, never `full-day txns ÷ clip footfall`.
- **A4 — Zone names are our assumption, not given by the problem statement.** No zone list or
  `store_layout.json` was provided, so we named the zones ourselves from the store floor plan and the camera
  roles: `entrance`, `skincare_aisle`, `makeup_aisle`, `foh_center`, `checkout`, `accessories`, `stockroom`
  (the last is staff-only and excluded). For v1 each camera maps to one primary zone — CAM3 `entrance`,
  CAM1 `skincare_aisle`, CAM2 `makeup_aisle`, CAM5 `checkout` (CAM4 `stockroom`); the others are reserved
  for finer sub-zones later. *Why:* the labels are configuration in `zones.py`, not hardcoded logic, so they
  can be renamed/extended without code changes if a canonical layout is supplied. (See [[DECISIONS]] PD-4.)
- **A5 — Unique-visitor count is approximate (lightweight Re-ID + tuned tracking), calibrated to the one
  available ground truth.** With no identity data and an offline CPU gate, we de-duplicate by appearance
  **colour-histogram** signature, not a trained Re-ID model (ADR-0008). Validated against a user count of
  **~7 people on CAM1/2/3**: the raw per-camera pipeline found **53** tracks — over-count dominated by
  **ByteTrack fragmentation** (one shopper → ~8 ids behind shelves), not Re-ID error. A **tuned tracker**
  (`track_buffer=150`) cut that to 44, and Re-ID at the calibrated `reid_max_distance=0.55` brings the live
  pipeline to **9 unique** (close to 7). *Caveats:* (i) the threshold is **tuned to this clip** and should
  be re-validated on new footage; (ii) colour histograms are weak features (dark clothing, varied angles),
  so look-alikes can still merge and the same person across very different views may not — the count is
  *meaningfully de-inflated, not exact*; (iii) `is_staff` is a **presence heuristic** (continuous presence
  ≥ threshold ⇒ staff), not uniform recognition. The signature and threshold are swappable config/one
  function if higher accuracy is later required.

## 8. Known limitations & next steps
- The entry line is a per-camera calibration validated against the real video; robust to a fixed camera,
  not to camera moves. Until Re-ID (next slice), visitor counts are **per-camera and over-count** people
  in overlapping views; cross-camera dedup and re-entry collapsing fix this. (Visitor definition: §7 A1.)
- Conversion can mis-attribute in dense billing periods — bounded by the 5-minute rule (§7 A2).
- At 40 live stores the CPU-bound detector is the bottleneck — scale horizontally per store and put a
  queue in front of ingest. These are deliberate, bounded trade-offs, not oversights.

## 9. AI-Assisted Decisions
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
