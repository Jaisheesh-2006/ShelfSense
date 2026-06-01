# STATE — where the build is right now

> Stateful progress for the LLM wiki. Update this at the end of every working session so the
> next session resumes instantly. Keep it short and current; history lives in git, detail in
> [[TASKS]]. This replaces the empty root `CURRENT_STATE.md`.
>
> Last updated: 2026-06-01.

## Current phase

🟢 **Slice 2.5 done — billing queue + POS correlation; the full conversion engine exists.** Phase 1 +
Slices 2.0–2.5 complete. Both halves of the North Star now compute from real input. Slice 2.6 (the API:
`POST /events/ingest` + `/stores/{id}/{metrics,funnel}`, reusing this slice's pure logic) next.

### Slice 2.5 (done) — billing queue + POS correlation (ADR-0012)
- **POS loader** (`common/shelfsense_common/pos_loader.py`) + **`Transaction` contract** (`contracts/pos.py`):
  Brigade CSV → **24 transactions** (one per order_id), `order_date`+`order_time` parsed as **IST → UTC**,
  `amount` = sum of the order's **GMV** (day total **₹44,920**, reconciles with [[GROUND_TRUTH]] §2).
- **Conversion engine** (`common/shelfsense_common/conversion.py`, pure): `correlate_conversions` — a
  billing visitor within the **5-min-before-a-sale** window is converted; no-match = abandon; rate =
  converted ÷ unique customers; `data_confidence="low"` under threshold. `pos_day_metrics` (count, GMV,
  avg basket, peak hour, top dept). **Placed in `common` so the Slice 2.6 API reuses it verbatim.**
- **Billing detection** (`detector/app/billing.py` `BillingTracker`, pure): on CAM5, a **non-staff**
  visitor entering the checkout zone emits **`BILLING_QUEUE_JOIN`** with **`queue_depth`** (driven off
  the existing CAM5 `ZONE_ENTER`/`EXIT`; wired in `main.py`). `BILLING_QUEUE_ABANDON` is **derived** in
  conversion (needs POS). Schema/`queue_depth` already existed — no schema change.
- **Validated (honest clip):** **conversion 0%** (`data_confidence=low`), funnel **Entry 2 → Zone 2 →
  Billing 0 → Purchase 0** — customers browsed CAM2, none reached checkout, no sale in the 2-min window
  (the window mismatch, not a bug). Nuance: **1 raw `BILLING_QUEUE_JOIN`** fired from a CAM5 track that
  dipped below the staff-darkness threshold, but that visitor is **overall staff** (any-flag rule) so
  conversion excludes it → honest billing-customer count = 0. Good end-to-end demo of layered staff handling.
- **Demonstrated:** `scripts/demo_conversion.py` (honest report) + `POS_DEMO_ALIGNMENT=true` (a
  representative billing visitor aligned to a **real** sale → CONVERTED, plus an ABANDON), loudly labelled
  "not a reading of the clip." `scripts/load_pos.py` prints the 24 sales + day-metrics.
- **Sink:** `JsonlEventSink(truncate=...)` (added 2.4b) keeps re-runs clean. **69 unit tests pass** (+17:
  `test_pos_loader`, `test_conversion`, `test_billing`); ruff clean.

### Slice 2.4b (done) — dark-uniform staff, floor mask, entrance=footfall-only

### Refined ground truth (user, 2026-06-01)
The **7 people are store-wide** (all cameras), splitting **2 customers (grey + violet tops) + 5 staff
(complete black uniform)**. CAM4 (stockroom) is **empty** the whole window; CAM5 has a **mirror** that can
double-detect its 2 staff. This reframed the goal: the conversion denominator is *customers* = **2**.

### Slice 2.4b (done) — dark-uniform staff, floor mask, entrance=footfall-only
- **Staff = dark-uniform appearance (ADR-0009):** `detector/app/staff.py` — `uniform_darkness` = min of
  upper/lower-body dark-pixel fraction (HSV V ≤ `staff_dark_v_max=70`, central column), reusing the Re-ID
  crop; `StaffClassifier` flags staff when mean ≥ `staff_darkness_threshold=0.50`. Replaces the vague 90 s
  presence heuristic (now an off-by-default fallback). **Calibrated:** customers score 0.08–0.19, staff
  0.52–0.96 — clean gap.
- **CAM5 mirror suppression (ADR-0010):** new `FloorRegion` (polygon + ray-cast `contains`) on
  `CameraConfig`; detections with foot-point off the walkable floor are dropped. Calibrated via
  `scripts/calibrate_floor.py` (overlay `frames/CAM5_floor_calibration.jpg`). Live pass dropped **317**
  off-floor phantoms (back doorway / mirror / accessories light-box).
- **Entrance = footfall only (ADR-0011, refines ADR-0007):** the ENTRANCE camera (CAM3) emits
  ENTRY/EXIT/REENTRY only — **no zone-visitor events** (its view is dominated by mall-corridor pass-by).
  Unique visitors are counted from shopping-floor cams CAM1/CAM2/CAM5. `ZoneTracker` gated on
  `role is not ENTRANCE` in `main.py`.
- **Sink fix:** `run_once` now **truncates** the JSONL export (a single full pass re-exports, never
  accumulates stale events — also closes a re-run double-count). `JsonlEventSink(path, truncate=...)`.
- **Validated end-to-end (CAM1/2/3/5):** **5 unique = 2 customers + 3 staff.** Customers = **exactly 2**
  (grey + violet on CAM2) ✅ matches ground truth. Staff 3 (the 5 black staff over-merge in colour-hist
  Re-ID — ADR-0008 weakness; harmless to conversion as staff are excluded). 52 unit tests pass; ruff clean.
- **New tooling:** `scripts/diagnose_tracks.py` (per-track foot-point + darkness), `scripts/calibrate_floor.py`,
  `scripts/evidence_visitors.py` (labelled crop montage of every counted visitor → `frames/evidence_visitors.jpg`
  — reproduces the live 2-customers + 3-staff split for visual verification).

### Slice 2.4 (done) — Re-ID, REENTRY, staff, tuned tracking
- **Appearance Re-ID** (`detector/app/reid.py`, ADR-0008, user chose Option 1): HSV colour-histogram
  `appearance_signature` + `signature_distance` + pure `ReIDGallery` (nearest-match within `reid_max_distance`,
  else mint; re-match after a gap ⇒ `REENTRY`). Lightweight, offline-safe — no extra model.

### Slice 2.4 (done) — Re-ID, REENTRY, staff, tuned tracking
- **Appearance Re-ID** (`detector/app/reid.py`, ADR-0008, user chose Option 1): HSV colour-histogram
  `appearance_signature` + `signature_distance` + pure `ReIDGallery` (nearest-match within `reid_max_distance`,
  else mint; re-match after a gap ⇒ `REENTRY`). Lightweight, offline-safe — no extra model.
- **VisitorRegistry → gallery-backed:** resolves each `(camera, track)` to a GLOBAL `visitor_id` via the
  gallery using the track's accumulated signature; this is the cross-camera de-dup.
- **Tuned ByteTrack** (`detector/app/trackers/bytetrack_shelfsense.yaml`): `track_buffer=150` (~15s, bridges
  shelf occlusion) + `new_track_thresh=0.5` — the real fix for fragmentation (root cause of over-count).
  `PersonTracker` loads the local yaml; `enabled_cameras` config restricts which cameras run.
- **is_staff:** presence heuristic — flagged once continuous presence ≥ `staff_min_presence_ms` (90s); API
  treats a visitor as staff if **any** event is flagged. **Groups:** counted as individuals by design
  (per-track). **Confidence:** real value carried on every event, never dropped.
- **Calibration:** `scripts/calibrate_reid.py` runs the tracker once, sweeps thresholds offline vs the
  ground-truth 7 → picked 0.55. Honest caveat: clip-tuned + colour histograms are weak features (DESIGN A5).
- **Verified:** 40 unit tests pass (new `test_reid`, rewritten `test_visits`); ruff clean; clean CAM1/2/3
  artifact = 146 events, **9 unique visitors**.

### Slice 2.3 (done) — visitor registry + zones
- **VisitorRegistry** (`detector/app/visits.py`): one `visitor_id` per `(camera, track)` on first sighting
  + a shared per-visitor `session_seq`. Single source of identity (crossing & zone logic look it up).
- **ZoneTracker** (`detector/app/zone_tracker.py`): pure state machine — `ZONE_ENTER` after `min_zone_dwell`
  (2s, noise filter), `ZONE_DWELL` every 30s (running dwell), `ZONE_EXIT` after `zone_exit_grace` absence
  (total dwell); `flush()` closes tracks at clip end. Camera-level zone (PD-4).
- **CrossingDetector refactored:** dropped its private id minting; the main loop attaches identity from the
  registry — fixes the 2.2 risk of two ids for one person.
- **main.py** now loops ALL customer cameras (CAM1/2/3/5), per-camera `reset()`; reports `zone_visitors`
  (meaningful, =64) vs `tracks_seen` (raw track ids incl. blips, =155 — diagnostic only).
- **Verified:** 36 unit tests pass (incl. new `test_visits`, `test_zone_tracker`); ruff clean; full pipeline
  wrote 163 schema-valid events to `data/events/behavior.jsonl` (70 ENTER / 70 EXIT / 23 DWELL).

### Slice 2.2 (done) — tracking + ENTRY/EXIT in the prescribed schema
- **Prescribed schema:** `BehaviorEvent` (flat, 8 `BehaviorEventType`s, `EventMetadata`) in
  `common/contracts/behavior.py` — UTC ISO-8601 timestamps, `zone_id` null for ENTRY/EXIT, validators
  enforce both. This is now the emitted/ingested contract; the old envelope (`events.py`) is internal.
- **Tracking:** `detector/app/track.py` `PersonTracker` wraps Ultralytics **ByteTrack** (`persist=True`,
  `reset()` between cameras); pure `boxes_to_tracks` split out for tests. Entrance tracked at 10 fps.
- **Footfall core:** `detector/app/crossing.py` `CrossingDetector` — pure per-track line-crossing state
  machine (seed-on-first-sight, on-line ignored, `confirm_frames` flicker debounce). Fully unit-tested.
  (Identity moved to the VisitorRegistry in 2.3.)
- **Emission:** `common/sinks.py` `JsonlEventSink` (append NDJSON). **Redpanda producer dropped** from the
  detector. `run_once()` extracted so `scripts/emit_entrance_events.py` runs a single pass locally.
- **⚠ Entrance line — integrity catch (ADR-0006):** an interim move to the frame's right corridor
  reported "3 ENTRY / 3 EXIT", but **user video review showed that corridor is the MALL walkway** —
  pass-by pedestrians, not visitors. **Reverted to the centre-left door** `(320,490)→(1140,415)`. With
  the correct line this clip yields **0 crossings**, which matches the video (everyone visible is
  already inside; only mall traffic moves). Mechanism is sound (unit-tested); the number is honest.
- **➡ Visitor definition decided (ADR-0007):** because clean door-crossings ≈0 on 2-min clips,
  **unique visitors = distinct people detected in-store** (`visitor_id` per tracked customer on first
  sighting, Re-ID-deduped in 2.4), not door-crossings. `ENTRY`/`EXIT` remain flow events. Implemented
  from Slice 2.3 (visitor registry across customer cameras).
- **Verified:** `validate_entrance.py` over the full clip → **0/0 at the correct door** (matches reality);
  the crossing/schema/sink logic is covered by **26 unit tests (pass); ruff clean**. `emit_entrance_events.py`
  runs the real pipeline path and writes schema-valid JSONL. Config: `detection_confidence` 0.35,
  `tracker_sample_fps` 10, `crossing_confirm_frames` 2, `clip_start_iso` ~20:10 IST.

### Deliverables + wiki reconciliation (2026-05-31)
- **DESIGN.md** (784w) + **CHOICES.md** (640w) at repo root — production-grade, structured, with
  AI-Assisted Decisions / 3 decisions + trade-offs. Prompt blocks in all test files reformatted to
  **Task/Context/Constraints/Output**. 13 tests pass.
- **Wiki reconciled** (not just appended): ARCHITECTURE.md rewritten to the current ingest-centric,
  no-broker, Re-ID design (old diagram/tables removed); PROJECT.md, BUSINESS_RULES.md, EDGE_CASES.md
  de-duplicated and stale content removed (old conversion formula, resolved open questions, duplicate
  dwell sections, stale status table).
- New **`/update-wiki`** slash command (`.claude/commands/update-wiki.md`) — reconciliation pass that
  fixes conflicts and removes superseded content on demand.

### Re-alignment (2026-05-31, after reading the Problem Statement PDF)
- PDF **dataset description was a print mistake** — `raw/` (Brigade, 5 cams) is final. Spec's
  schema/endpoints/scoring/edge-cases/North-Star **are authoritative**.
- New canonical: [[SPEC]]. **Reversed PD-5** → Re-ID required (`visitor_id`, `REENTRY`, cross-cam dedup).
- **Event schema** → prescribed flat behavioural schema + 8 types ([[EVENT_SCHEMA]]).
- **API** → `POST /events/ingest` + `/stores/{id}/{metrics,funnel,heatmap,anomalies}` + `/health` ([[API_SPEC]]).
- **Dropped Redpanda broker** → pipeline emits JSONL + POSTs to `/events/ingest`. Kept Postgres.
- Conversion redefined (POS 5-min billing-window rule). Added queue/abandon/heatmap/anomalies/dwell, the 7 edge cases, Part D AI docs.
- **Code impact (not yet done):** refactor `common.contracts.events` to the new schema; replace api `/api/v1/*` with the prescribed endpoints; reorganize tracker/analytics into the pipeline + API; retire the broker in compose. Slice 2.1's YOLO detection is reused; its emission changes.

### Slice 2.1 (done) — detector sees people & emits events
- `common/stream.py`: `EventProducer` (confluent-kafka, idempotent, keyed, JSON) — lazy import so api stays slim.
- `detector/app/detect.py`: `PersonDetector` (Ultralytics YOLO, lazy) + pure `boxes_to_detections` (person class + conf filter, xyxy→xywh).
- `detector/app/main.py`: loops customer cameras (skips CAM4 stockroom) via `VideoFrameSource` → detect → publish `detection.created` to Redpanda, keyed by camera; idles after one pass (recorded clips). Config: `detector_max_frames`, `detector_reprocess`.
- Detector Dockerfile: libgl1/glib, ultralytics+confluent-kafka, **YOLO weights pre-baked** (no runtime download). compose mounts `docs/raw/CCTV Footage` → `/data/cctv` (ro), `CCTV_DIR` env.
- **Verified:** preview overlays show boxes on real people (`docs/wiki/frames/CAM_*_det_*.jpg`); ran stack and consumed `detection.created` — real structured events (CAM1=20,CAM2=45,CAM3=7,CAM5=11 dets over 10 frames each), frame_id/ts_ms confirm 5 fps. 13 unit tests pass.

### Slice 2.0 (done) — calibration + frame reader
- `services/detector/app/frames.py`: `VideoFrameSource` (context-managed video reader, configurable
  `sample_fps`, yields `Frame(index, ts_ms, image)`) + pure `compute_stride()`. Validated on real
  CAM 3 (1920×1080 @ 29.97 fps, stride=6 at 5 fps).
- **Entrance line calibrated** on CAM 3: `(320,490)→(1140,415)`, `inside_sign=-1`, `calibrated=True`
  in `zones.py`; `EntranceLine.side()/is_inside()` added. Overlay at `docs/wiki/frames/CAM3_entrance_calibration.jpg`.
- `scripts/calibrate_entrance.py` (grid+line overlay tool, re-runnable to refine).
- Tests: `tests/unit/test_frames.py`, `test_zones.py` (7 passing); root `pyproject.toml` pytest config.
- Deps installed in `.venv`: opencv-python-headless, numpy, pytest. `services/detector/requirements.txt` records CV deps.

## Done
- Read & internalized [[GROUND_TRUTH]] from `docs/raw/` (5 cameras, CSV = 24 txns/day, eval rubric, floor plan).
- Directory structure + root files; LLM-wiki (Karpathy) pattern; production-grade CLAUDE.md.
- Frames extracted & inspected → camera→area map; floor plan read ([[GROUND_TRUTH]] §1, §4).
- **All decisions locked** (PD-1..PD-5) in [[DECISIONS]] ADR-0004: Redpanda, ByteTrack, comparable-window conversion, floor-plan zones (camera-level), independent cameras.
- **Phase 1 foundations built & validated:**
  - `services/common/` — shared `shelfsense_common` pkg: Pydantic v2 **event contracts** (`events.py`),
    floor-plan **zone/store config** (`zones.py`, `STORE`), **env settings** (`config.py`), **structured
    JSON logging** (`logging.py`), graceful **worker** runtime (`worker.py`). Smoke-tested locally.
  - `services/api/` — FastAPI: `/healthz`, `/readyz` (DB+Redis), `/metrics` (Prometheus + business
    gauges refreshed from DB), `/api/v1/{conversion,funnel,footfall/summary,sessions,kpis}`. SQLAlchemy
    models (`visit_sessions`, `transactions`, `metrics`); error envelope; request metrics middleware.
  - `services/{detector,tracker,analytics}/` — Phase-1 scaffolds (boot, log, heartbeat) ready for Phase 2 logic.
  - Root **`docker-compose.yml`** (Redpanda, Postgres, Redis, api, 3 workers, Prometheus, Grafana) +
    Dockerfiles + `infra/monitoring/{prometheus.yml,grafana provisioning}` + `.dockerignore`.
  - **VALIDATED:** `docker compose up --build` → all 9 containers up, api healthy, `/metrics` 200,
    `/readyz` 200, endpoints return honest computed zeros, **Prometheus scrapes api = up**. Gate ✅.

## ▶ Next action — Slice 2.6 (Intelligence API: ingest + core metrics)
1. **`POST /events/ingest`** — accept a batch ≤500 `BehaviorEvent`s; **idempotent by `event_id`**,
   partial-success on bad events, structured errors; persist to Postgres ([[API_SPEC]]).
2. **`GET /stores/{id}/metrics`** + **`/funnel`** — compute from stored events, **reusing this slice's
   `conversion.correlate_conversions` + `pos_loader` verbatim** (the reason that logic lives in `common`).
   Funnel is session-based, re-entries don't double-count; exclude `is_staff` (any-flag rule).
3. **Retire the old `/api/v1/*`** endpoints (ADR-0005). Map the loader `Transaction` → the `db.Transaction` ORM.
4. Add the compose mount `docs/raw → /data/pos` so `pos_csv_path` resolves in-container.

See [[TASKS]] Phase 2 for slices 2.6–2.7 (heatmap/anomalies/health in 2.7).

## Notes / env
- Local: `.venv` has pydantic/fastapi/etc.; OpenCV installed for frame work. Real runtime = containers.
- Run the stack: `docker compose up --build` (api :8000, prometheus :9090, grafana :3000). Postgres/Redis/Redpanda internal-only.
