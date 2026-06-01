# STATE — where the build is right now

> Stateful progress for the LLM wiki. Update this at the end of every working session so the
> next session resumes instantly. Keep it short and current; history lives in git, detail in
> [[TASKS]]. This replaces the empty root `CURRENT_STATE.md`.
>
> Last updated: 2026-06-01.

## Current phase

🟢 **Slice 2.4 done — Re-ID + edge cases; validated against ground truth.** Phase 1 + Slices 2.0–2.4
complete. Appearance Re-ID (colour histogram) de-duplicates visitors across cameras + re-entries; a tuned
ByteTrack cuts fragmentation; staff are flagged by presence. **Ground-truth check (user: ~7 people on
CAM1/2/3):** per-camera over-count was **53 tracks → tuned tracker 44 → Re-ID 9 unique** (live pipeline,
`reid_max_distance=0.55`; 2 cross-camera merges, 3 staff). Honest, close to 7. Slice 2.5 (billing queue +
POS correlation → the "converted" half of conversion) next.

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

## ▶ Next action — Slice 2.5 (billing queue + POS correlation)
1. On the **checkout camera (CAM5)**, track the billing zone: emit `BILLING_QUEUE_JOIN` with
   `metadata.queue_depth` and `BILLING_QUEUE_ABANDON` when a visitor leaves without a purchase
   ([[EVENT_SCHEMA]], [[BUSINESS_RULES]]).
2. **POS correlation:** load the Brigade CSV; a visitor in the billing zone within the **5-min window
   before a transaction** counts as **converted** (time-window + store, no customer id). [[BUSINESS_RULES]].
3. This completes the **"converted" half** of the North Star (`converted ÷ unique visitors`) — pair it
   with the unique-visitor count from 2.3/2.4.
4. Mind the clip-vs-full-day window mismatch (PD-3 / DESIGN A3); demonstrate on a comparable window.

See [[TASKS]] Phase 2 for slices 2.5–2.7. API ingest + funnel/heatmap/anomalies in 2.6.

## Notes / env
- Local: `.venv` has pydantic/fastapi/etc.; OpenCV installed for frame work. Real runtime = containers.
- Run the stack: `docker compose up --build` (api :8000, prometheus :9090, grafana :3000). Postgres/Redis/Redpanda internal-only.
