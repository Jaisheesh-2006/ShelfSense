# STATE — where the build is right now

> Stateful progress for the LLM wiki. Update this at the end of every working session so the
> next session resumes instantly. Keep it short and current; history lives in git, detail in
> [[TASKS]]. This replaces the empty root `CURRENT_STATE.md`.
>
> Last updated: 2026-06-03.

## ⚠️ Dataset changed (2026-06-02) — re-grounding underway (ADR-0024)
The team delivered a **corrected dataset** (old single-store Brigade data removed); the wiki is
re-derived ([[GROUND_TRUTH]] §0). Decision status:
1. ✅ **Event schema — DECIDED (user): keep the flat PDF page-5 schema** (what the pipeline must emit;
   the richer `sample_events.jsonl` signals are not adopted). We already emit this → **no code change**.
   ([[EVENT_SCHEMA]])
3. ✅ **POS loader — REWORKED (done)** for the new 7-col CSV: basket = distinct `order_time` (24),
   value = Σ `total_amount` (**₹34,331.71**), `invoice_number` dropped. Plus a **brand → department
   taxonomy** (ADR-0025, `departments.py`) so the API now reports **both `top_brand` and
   `top_department`** (real CSV → top brand Faces Canada, top dept makeup; split makeup 14/skincare
   5/bath_and_body 2/…). Validated against the real CSV; ruff + **115 tests** + frontend `tsc` clean.
2. ✅ **Second store — PLUMBING DONE (ADR-0026 + ADR-0028):** the **dashboard switcher + `GET /stores`**
   were already done; now the **detection half** is too. Stores are a **pluggable auto-discovered
   registry** (`shelfsense_common.stores`, one file per store) — the detector loops `all_stores()`,
   each with its own Re-ID/staff/zone/clip-start, tagging events with the right `store_id`. **ST1009
   (Store_2)** added: two entrances + `zone` + `billing` (960×1080), clips pinned to **one synthetic
   day**, entrance lines placeholder-flagged (no ground truth), **no POS → conversion N/A**. The
   corrected dataset's Store_1 filenames/paths were also fixed, and the **CCTV mount repointed** to
   `Store_CCTV_Clips/`. Adding a future store = drop a `stores/<id>.py` + clips folder. **Remaining:**
   the live two-store generation run (pending `GEMINI_API_KEY`) → commit `events.jsonl` + VLM cache.
5. ✅ **VLM staff/zone classification — LOGIC DONE (ADR-0027):** optional **Gemini Flash** used **only in
   the offline detection pass** to classify **staff vs customer** (per visitor, replaces the dark-uniform
   heuristic that breaks on Store_2's pink staff) and **product-camera zones** (per camera). `VLM_ENABLED`
   is **off by default** (gate-safe: no key/network for `docker compose up`); cached + heuristic fallback.
   Code/tests landed (`detector/app/vlm.py`, `staff_decider.py`, `zone_resolver.py`; **138 tests**). The
   actual two-store generation run is **pending the user's `GEMINI_API_KEY`**.
4. ⏳ **Demographics/groups — PENDING (deferred):** default per D1 is **no** (full-face-blurred footage).
6. ✅ **Counting approach changed — ALL cameras, quality-gated (ADR-0029, refines ADR-0011):** unique
   visitors are now counted from **every camera** (Re-ID-deduped), but only for **solid tracks** —
   sustained + on-floor + large-enough box + **store-interior side of the entrance line** (mall pass-by
   discarded by the line). The entrance cam now contributes interior visitors, not just crossings. A
   literal "face-visible" gate was **rejected** (overhead CCTV + privacy-blurred faces ⇒ would
   undercount). ⚠ **The Store_1 "2 customers" figure must be re-validated on the next full run** — this
   changed the counting path and can't be re-checked without running YOLO.
See [[RISKS]] R-12..R-16, [[DECISIONS]] ADR-0024/0029.

7. ✅ **Store_2 pipeline RUN against ground truth (ADR-0030):** full chain executed — calibrated both
   entrance lines, per-store density tuning (`reid_max_distance=0.30`, `min_zone_dwell_ms=800`, baked in
   ST1009; Store_1 unchanged). Result: **23 unique people vs 25 ground truth** (per-camera BILLING=6,
   ENTRY1=5, ENTRY2=8, ZONE=7 — consistent with the flows). Re-ID over-merge was the bottleneck (sweep:
   0.55→6, 0.35→20, 0.30→23, 0.25→37). ⚠ **VLM staff-ID blocked:** model works (`gemini-2.5-flash-lite`)
   but free tier = **20 req/day** < 23 visitors → all calls 429'd → staff split is heuristic (3/20), not
   VLM. Events at `data/events/store2.jsonl`.

8. ✅ **VLM staff/zone for Store_2 — DONE via Groq (ADR-0031):** added a pluggable **Groq** provider
   (`meta-llama/llama-4-scout-17b-16e-instruct`) alongside Gemini, since Gemini's free tier (20/day) <
   23 visitors. Full run: **23 staff calls + 1 zone call, 0 failures**. VLM result **4 staff / 19
   customers** (vs 3/22); zone relabelled `makeup_aisle → skincare_aisle`. Proof images in
   `docs/wiki/frames/` (`store2_entrance_lines.jpg`, `store2_customers_staff.jpg`).

**Single next action:** **re-validate Store_1's count** under the new all-cameras counting (ADR-0029)
on a full run (Store_1 can use the Groq VLM too now), then a clean-machine gate dry-run
(`docker compose up`) covering the mount/multi-store/counting changes.

## Current phase

> **Snapshot below is PRE-2026-06-02 (the old dataset).** It remains true *as logic/architecture* but the
> POS figures (₹44,920) and "validated" data numbers are from the old data — see the ⚠ banner above and
> [[GROUND_TRUTH]] §0 for what the corrected dataset changes.

🟢 **Gate dry-run PASSED on the real stack; the auto-feed populates the API progressively; the full
stack (incl. the React dashboard) builds and runs from one command.** Phase 1 + Slices 2.0–2.10 +
the Part-E dashboard + deterministic ids + the build/runtime hardening are all done. `docker compose
up --build` from clean brings up **six services** — five load-bearing backend (api, detector,
postgres, prometheus, grafana) **plus `frontend`** (nginx, :8080) — the detector processes all
4 cameras and auto-POSTs its events, and **every endpoint returns real, internally-consistent data**
(unique 2, funnel 2→2→0→0, heatmap makeup=100, POS 24/₹44,920, anomalies 2× honest-INFO) with zero
manual steps.

Recent work, newest first:
- **Redis removed entirely (ADR-0023).** It was vestigial — only the `/readyz` probe pinged it, with no
  caching job. Dropped the `redis` compose service, the `redis` Python dep, the `redis_client.py` module,
  the `REDIS_*` config/env, and the readiness check (now Postgres-only). Resolves the long-standing
  "decide Redis's fate" open item. Fewer moving parts on the gate path; nothing else referenced it.
- **Detector image actually imports `cv2` (ADR-0022).** Dropping `libgl1` to slim the image broke
  `import cv2` because `ultralytics` pulls the FULL `opencv-python` (needs libGL + X11/`libxcb`) →
  `ImportError: libxcb.so.1` at the YOLO pre-bake. Fixed by **replacing opencv with the headless
  build** after `pip install -r requirements.txt`. Validated by reproducing the conflict →
  `CV2_HEADLESS_OK` (cv2 4.13.0). Build is now slim, GL/X-free, and runnable.
- **Deterministic event/visitor ids (ADR-0021)** so re-runs and restarts are **idempotent** — no more
  DB accumulation (the `events_total 237 = 131+106` / inflated-unique foot-gun is gone).
- **Live React dashboard (ADR-0020, :8080)** — flat custom design system, polls all five endpoints,
  numbers climb live as detection runs.
- **CPU-only torch + pip cache (ADR-0017)** + **detector throughput tuning** (sample_fps 10→5,
  imgsz 640→480, ADR-0019) for a fast build and a ~10-min-budget run.
- **2.10 per-camera incremental flush (ADR-0018)** so endpoints fill in *as detection runs*;
  **2.9 compose cleanup (ADR-0016)**.

**⚠ The one pending check:** re-validate `unique_visitors`=2 / funnel 2→2→0→0 on a clean
`docker compose down -v` + `up --build` run — the fps5/imgsz480 tuning hasn't been confirmed against
the accuracy target on a from-scratch run yet (if it drifts, step back toward 7 fps / 560 px).

Remaining beyond that: **Phase 3 polish** (coverage push to >70%, structured-logging field pass) — plus
the optional startup **seed** (set aside) for an instant-on demo. (**Redis's fate is now decided —
removed, ADR-0023.**)

### Dashboard (done) — live React UI + ShelfSense design system (ADR-0020)
- **`frontend/`** Vite + React + TS SPA polling all five store endpoints every 4 s: conversion ring,
  funnel, zone heatmap, anomalies, feed-health — live numbers climb as detection runs. **Custom flat
  design system** (CSS tokens, no UI lib, **no gradients**, white-forward, one blue + one teal accent,
  tabular numbers). Served by **nginx** (multi-stage Docker build) as the `frontend` service on
  **:8080**; the API gained **CORS** (`CORS_ALLOW_ORIGINS`). Honest states: `data_confidence` badge +
  a "detection running" banner so a mid-run reviewer reads it as working, not broken.
- **Validated:** `tsc --noEmit` clean, `vite build` ok (151 kB JS / 7 kB CSS, 49 kB gz); ruff + 105
  tests green; compose parses — the stack is now **seven** services (added `frontend`).

### Slice 2.10 (done) — per-camera incremental flush (ADR-0018)
- **Problem the real run exposed:** the auto-feed POSTed only at `batch_size` (500) or final exit, and
  a full pass is ~131 events, so the *single* POST landed at the end of a ~24-min CPU run — endpoints
  read zero for ~24 min, then jumped. A 10-min reviewer would see zeros and bail.
- **Fix:** `flush()` is now on the `EventSink` Protocol + `JsonlEventSink` + `FanOutSink` (it already
  existed on `HttpEventSink`); the detector's `run_once` calls `sink.flush()` **after each camera** and
  logs `camera_posted`. Events now POST as each camera finishes (~4 update points) — the endpoints
  climb while detection is still running. Idempotent ingest makes the extra POSTs safe; JSONL still
  gets all; `batch_size` stays as a within-camera cap. **Validated:** ruff clean + **105 tests** (+3
  in `test_http_sink`: on-demand flush posts a partial buffer, empty flush is a no-op, FanOut fans
  flush). Narrows but doesn't erase the timing gap (first numbers after camera 1, ~5 min) — the seed
  is still the instant-on net.

### Slice 2.9 (done) — compose cleanup (ADR-0016)
- Removed the **`redpanda`**, **`tracker`**, and **`analytics`** services from `docker-compose.yml`
  (legacy: broker dropped in ADR-0005; tracker/analytics were Phase-1 heartbeat stubs whose work now
  lives in `detector` + `api`). Deleted the orphaned `services/tracker/` and `services/analytics/`
  dirs; dropped the unused `STREAM_BOOTSTRAP_SERVERS` compose env.
- **Final stack (at the time) = `api`, `detector`, `postgres`, `redis`, `prometheus`, `grafana`** — all
  load-bearing. Kept Redis (`/readyz` dependency) and the old `stream.py`/`events.py` envelope (out of the
  run path but still unit-tested; removing them is separate code-cleanup). **(Redis later removed — ADR-0023.)**
- **Validated:** `docker compose config` parses; final service list is the six above; **ruff clean +
  102 tests pass**. The clean-machine `docker compose up --build` dry-run is the user's next step.

### Slice 2.8 (done) — detector → API auto-feed (ADR-0015)
- **`HttpEventSink`** (`common/sinks.py`): buffers `BehaviorEvent`s and POSTs batches of ≤500 to
  `{API_BASE_URL}/events/ingest` (stdlib `urllib`, no new dep). Bounded wait-for-ready on enter, per-batch
  retry+backoff, **non-fatal** on failure (logs + drops; JSONL still has it → no crash). Idempotent ingest
  makes restarts/replays safe. **`FanOutSink`** writes each event to JSONL **and** the API at once.
- **Detector `run_once`** now fans to `[JsonlEventSink, HttpEventSink]` (HTTP gated on `detector_post_to_api`)
  and logs `posted_to_api`. **Compose:** `detector` depends on `api` (`service_healthy`), gets `API_BASE_URL`,
  and bind-mounts `./data/events` so the JSONL is inspectable on the host.
- **Validated:** 102 tests pass (+7 `test_http_sink`); ruff clean. End-to-end (sink → real API → metrics, no
  replay): **135/135 events posted**, `/metrics` unique_visitors 2 / conversion 0%, funnel 2→2→0→0, 24 POS
  txns. `scripts/ingest_events.py` demoted to a dev/replay fallback. New knobs in `.env.example`.

### Slice 2.7 (done) — heatmap + anomalies + health (ADR-0014)
- **Pure logic in `common/analytics.py`:** `compute_heatmap` (per-zone distinct-customer visits + avg
  dwell, **normalised 0–100** to the busiest zone; `data_confidence` flag), `detect_anomalies`
  (QUEUE_SPIKE / CONVERSION_DROP / DEAD_ZONE with severity + `suggested_action`), `feed_status` (lag +
  stale). Reuses `customer_visitor_ids` / `_avg_dwell_by_zone` / `compute_store_metrics`. Routers thin.
- **Honest anomalies (the headline judgment):** conversion-drop uses a **documented config baseline**
  (no 7-day history) and only fires at `data_confidence="ok"` — INFO under low sample; dead-zone is
  **span-guarded** (needs ≥ `dead_zone_minutes` of data) — INFO on the 2-min clip. So **no fabricated
  WARN/CRITICAL** on this dataset; queue spike still fires from real staff-excluded depth.
- **`/health` recording-relative (user choice):** freshness vs the latest ingested event by default (a
  replayed clip reads healthy); `HEALTH_STRICT_NOW=true` → real wall-clock. `status=degraded` if DB down
  or any feed stale. New repo helper `latest_event_ms_by_store`.
- **Validated (real data, TestClient):** heatmap `makeup_aisle`=100 (data_confidence low); anomalies =
  2× INFO (conversion low-sample, dead-zone window-too-short) — no false alerts; `/health` default →
  `ok`/not-stale, strict → `degraded`/stale (lag ≈ 52 days). **95 tests pass** (+13: `test_anomalies`,
  +5 API); ruff clean. New config knobs (anomaly thresholds, open hours, health) in `.env.example`.

### Slice 2.6 (done) — API ingest + core metrics (ADR-0013)
- **Renamed API package `app` → `shelfsense_api`** (both detector + api had a top-level `app` that
  collided on the test path, blocking API tests). Dockerfile now runs `uvicorn shelfsense_api.main:app`;
  `services/api` added to pytest `pythonpath`. Old `/api/v1/*` (`business.py`) **retired** (ADR-0005).
- **Pure analytics** (`common/analytics.py`): `compute_funnel` + `compute_store_metrics` over
  `BehaviorEvent`s, reusing `correlate_conversions`/`pos_day_metrics`. Session-based, staff-excluded
  (any-flag), funnel stages forced monotonic (purchase ⊆ billing ⊆ zone ⊆ entry). DB-free + unit-tested.
- **`POST /events/ingest`** (`routers/events.py`): ≤500 events, **idempotent by `event_id`**
  (`repository.insert_events_dedup`, within-batch + DB dedup + IntegrityError fallback), **partial
  success** (each event validated individually; bad ones go to `errors[]`, not a whole-batch 422).
  Over-500 → 422 wrapped in the `{"error":{...}}` envelope.
- **`GET /stores/{id}/metrics` + `/funnel`** (`routers/stores.py`): thin adapters that load events +
  POS from the DB and call the pure analytics — computed live per request, never cached/hardcoded.
- **POS into Postgres at startup** (`pos_ingest.py`): globs `*.csv` (the real file is
  `Brigade_Bangalore_10_April_26 (1)bc6219c.csv`) → `load_transactions` → upsert; graceful if absent.
  New `behavior_events` ORM table + `department` on `transactions`; engine is **lazy** so importing the
  app needs no Postgres driver (hermetic SQLite TestClient tests via `db.configure_engine`).
- **Validated end-to-end (real data, TestClient on SQLite):** 135 events ingest; re-POST → **0 accepted /
  135 duplicate** (idempotency); POS 24 txns / GMV ₹44,920 / peak hour 19; **unique_visitors 2,
  conversion 0%** (`data_confidence=low`), **funnel Entry 2 → Zone 2 → Billing 0 → Purchase 0**. Prometheus
  gauges recomputed from `behavior_events`. **82 unit+integration tests pass** (+13: `test_analytics`,
  `test_api`); ruff clean. `scripts/ingest_events.py` replays the JSONL to a running API.

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

## ▶ Next action
**D1 (schema = flat page-5) and D3 (POS loader rework) are DONE.** Remaining ADR-0024 items, to discuss
with the user next:
- **D2 — Store_2:** decide whether to process it (repoint the detector to `Store_CCTV_Clips/Store_1` +
  add `Store_2`; calibrate its two entrances + zones; tag a distinct `store_id`) or document out-of-scope.
- **D4 — Demographics/groups:** default **no** (full-face-blurred footage); confirm or revisit.

After D2 lands: re-run the clean-machine **gate dry-run** end-to-end (detector → API → endpoints) on the
corrected clips, then resume the Phase-3 polish below.

— Prior status (still true *as logic* on Store_1): every prescribed endpoint exists, the stack feeds
itself (2.8), compose is clean (2.9 / no-Redis 0023), ids are deterministic, and the clean-machine gate
dry-run PASSED on the **old** data. ⚠ The detector's compose mount still points at the old
`./docs/raw/CCTV Footage/...` path, which no longer exists — fixing that is part of D2.

Then Phase 3 **polish + packaging** ([[TASKS]] Phase 3):
1. ✅ **Redis's fate decided — removed** (ADR-0023). It was vestigial (only `/readyz` pinged it); rather
   than invent a caching job we dropped it to keep the gate path lean. `/readyz` is now Postgres-only.
2. **Structured-logging field pass** — `trace_id, store_id, endpoint, latency_ms, status_code` per
   request; confirm graceful degradation (DB down → 503, no stack trace).
3. **Coverage to >70%** incl. edge cases (empty store, all-staff, zero purchases, re-entry in funnel).
4. ✅ **Live dashboard (Part E)** — done (ADR-0020); `frontend` on :8080 polling live.
5. **(Optional) startup seed** — instant-on numbers for a sub-5-min demo (set aside).
6. Keep `DESIGN.md`/`CHOICES.md` + [[INTERVIEW_QA]] in sync (ongoing).

## Notes / env
- Local: `.venv` has pydantic/fastapi/etc.; OpenCV installed for frame work. Real runtime = containers.
- Run the stack: `docker compose up --build` (api :8000, prometheus :9090, grafana :3000). Postgres internal-only.
- **Detector build (ADR-0017):** CPU-only torch (PyTorch CPU index) + BuildKit pip cache — the detector
  image pulls a ~200 MB CPU wheel, not the ~2 GB CUDA build. After the first successful build, use
  `docker compose up` (no `--build`) to skip the re-install entirely.
