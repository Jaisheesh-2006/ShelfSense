# TASKS

> Phased roadmap, ordered. ✅ done · 🟡 in progress · ⬜ todo. Live state in [[STATE]].
> Sequencing reflects the rubric ([[GROUND_TRUTH]] §3): protect the acceptance gate, then
> invest in the API/business bucket (35), then detection (30), production (20), thinking (15).

## Phase 0 — Scaffolding & wiki grounding
- ✅ Read CLAUDE.md; create prescribed directory structure
- ✅ Derive [[GROUND_TRUTH]] from `docs/raw/` (5 cameras, CSV=24 txns, eval rubric)
- ✅ Adopt LLM-wiki pattern: [[README]] bootstrap + rewrite all docs grounded in real data
- ✅ Root README, .gitignore, .env.example
- ⬜ Initialize git repository
- ⬜ **Inspect one frame per camera** → identify entrance/checkout/aisle cameras, define zones (PD-4/PD-5)

## Phase 1 — Contracts & foundations ✅ DONE
- ✅ Resolve PD-1..PD-5 in [[DECISIONS]] (ADR-0004)
- ✅ Shared `contracts` Pydantic models from [[EVENT_SCHEMA]] (`services/common`)
- ✅ Env-based config loader (no hardcoded secrets); structured JSON logging; worker runtime
- ✅ docker-compose (Redpanda, Postgres, Redis, Prometheus, Grafana, api + 3 workers) — gate validated
- ✅ api: `/healthz`, `/readyz`, `/metrics`, `/api/v1/{conversion,funnel,footfall/summary,sessions,kpis}`

## Phase 2 — Vertical slice (thin end-to-end, gate-safe)
- ✅ **Slice 2.0** — Calibrated CAM 3 entrance line in `zones.py` (`(320,490)→(1140,415)`, inside_sign=-1)
  + reusable `VideoFrameSource` frame reader (`services/detector/app/frames.py`) + unit tests (7 passing).
- ✅ **Slice 2.1** — detector: reads customer-camera clips (OpenCV) → YOLO person detection → publishes
  real `detection.created` events to Redpanda. Verified: boxes land on real people
  (`docs/wiki/frames/CAM_3_det_*.jpg`) + structured events on the topic (keyed by camera, 5 fps).
  `confluent-kafka` producer in `common/stream.py`; model pre-baked in image. 13 tests passing.
> ⚠️ **Re-planned (ADR-0005 / [[SPEC]]).** Slices now produce the **prescribed behavioural events**
> and the **prescribed API**. The detection *pipeline* (detector+tracker+re-id+emit) owns
> sessionization; the **API ingests events** and computes metrics. Redpanda broker dropped —
> pipeline POSTs to `/events/ingest` (events also written to JSONL; simulated real-time for Part E).
> Slice 2.1's YOLO detection is reused; only its **emission** changes to the new schema.

- ✅ **Slice 2.2 — Tracking + ENTRY/EXIT (+ visitor_id).** ByteTrack (`PersonTracker`) on CAM3 at 10 fps;
  pure `CrossingDetector` line-crossing state machine → `BehaviorEvent` `ENTRY`/`EXIT` (prescribed schema)
  with `visitor_id` + `session_seq`, written to JSONL (`JsonlEventSink`). Redpanda producer dropped from
  detector. **Integrity catch (ADR-0006):** an interim line on the right corridor counted mall pass-by as
  "3/3"; user review caught it → reverted to the real centre-left door → honest **0 crossings** (shoppers
  already inside). Drove **ADR-0007** (unique visitors = distinct in-store people). 26 tests pass; ruff clean.
- ✅ **Slice 2.3 — Visitor registry + zones + dwell.** Tracks all customer cams; `VisitorRegistry` assigns a
  `visitor_id` per customer on first detection (ADR-0007); `ZoneTracker` (pure) emits `ZONE_ENTER` (after
  `min_zone_dwell`) / `ZONE_DWELL` (30s) / `ZONE_EXIT` (total dwell). CrossingDetector refactored to use the
  registry (single id source). **Validated:** 163 events on real clips, **64 zone-visitors** (per-camera,
  pre Re-ID), dwell 2.1–139.6s. 36 tests pass; ruff clean.
- ✅ **Slice 2.4 — Re-ID + edge cases.** Appearance Re-ID (HSV histogram + `ReIDGallery`, ADR-0008) gives
  cross-camera-deduped global `visitor_id` + `REENTRY`; tuned ByteTrack (`track_buffer=150`) cuts
  fragmentation; `is_staff` by presence heuristic; groups counted as individuals; confidence carried.
  **Validated vs ground truth (7 on CAM1/2/3):** 53 per-camera → tuned 44 → **9 unique** (live, 0.55).
  `scripts/calibrate_reid.py` for threshold tuning. 40 tests pass; ruff clean. (Approximate — DESIGN A5.)
- ✅ **Slice 2.4b — Staff by uniform + mirror mask + entrance-as-footfall.** Refined ground truth (7
  store-wide = **2 customers + 5 staff**). `is_staff` now from a **dark-uniform appearance score**
  (`detector/app/staff.py`, ADR-0009), replacing the presence heuristic; **`FloorRegion`** mask drops
  off-floor mirror/display phantoms on CAM5 (ADR-0010, **317 dropped**); the **entrance camera counts
  footfall only**, visitors from CAM1/2/5 (ADR-0011). JSONL export now truncates per pass.
  **Validated: 5 unique = 2 customers + 3 staff** (customers exact). 52 tests pass; ruff clean.
- ✅ **Slice 2.5 — Billing queue + POS correlation (ADR-0012).** `BillingTracker` emits
  `BILLING_QUEUE_JOIN`+`queue_depth` on CAM5; pure POS loader (CSV→**24 txns**, IST→UTC, GMV ₹44,920) +
  `correlate_conversions` (5-min rule, converted/abandon, `data_confidence`) + `pos_day_metrics` — all in
  `common` so 2.6's API reuses them. **Honest clip: conversion 0%** (browsers only, window mismatch);
  `demo_conversion.py` shows the flip against a real sale. 69 tests pass; ruff clean.
- ✅ **Slice 2.6 — API ingest + core metrics (ADR-0013).** Renamed api pkg `app`→`shelfsense_api` (un-collided
  the two `app` packages, unblocking API tests); retired `/api/v1/*`. `POST /events/ingest` — ≤500,
  **idempotent by `event_id`** (within-batch + DB dedup + IntegrityError fallback), **partial success**
  (per-event validation; bad → `errors[]`), over-500 → 422 in the error envelope. `GET /stores/{id}/{metrics,
  funnel}` — thin adapters over **pure `common/analytics.py`** (`compute_funnel`/`compute_store_metrics`,
  reusing 2.5's `correlate_conversions`/`pos_day_metrics`); session-based, staff-excluded, monotonic funnel.
  POS loaded into Postgres at startup (glob fallback). **Validated (real data):** 135 events, re-POST = 0/135
  dup, **unique 2 / conversion 0% / funnel 2→2→0→0**. 82 tests pass (+13); ruff clean.
- ✅ **Slice 2.7 — heatmap + anomalies + health (ADR-0014).** `/stores/{id}/heatmap` (per-zone visits + avg
  dwell, **normalised 0–100**, data_confidence), `/stores/{id}/anomalies` (QUEUE_SPIKE / CONVERSION_DROP /
  DEAD_ZONE; severity + suggested_action), `/health` (per-store freshness, **recording-relative** by default
  + `HEALTH_STRICT_NOW` toggle, STALE_FEED). Pure logic in `common/analytics.py` (`compute_heatmap`,
  `detect_anomalies`, `feed_status`). **Honest:** conversion-drop uses a documented baseline + fires only at
  ok confidence; dead-zone is span-guarded → both INFO (no false alerts) on the 2-min clip. **Validated:**
  heatmap makeup=100; `/health` ok→stale under strict. 95 tests pass (+18); ruff clean.
  **→ Phase 2 complete: every prescribed endpoint exists.**
- ✅ **Slice 2.8 — detector → API auto-feed (ADR-0015).** Closed the loop: `HttpEventSink` (batched ≤500 POST
  to `/events/ingest`, stdlib urllib, wait-for-ready + retry, **non-fatal**) + `FanOutSink` in `common/sinks.py`;
  detector `run_once` fans events to JSONL **and** the API (gated on `detector_post_to_api`). Compose: `detector`
  depends on `api` healthy, `API_BASE_URL`, events bind-mounted for host inspection. `scripts/ingest_events.py`
  demoted to a dev/replay fallback. **Validated:** 102 tests (+7 `test_http_sink`); end-to-end 135/135 posted
  sink→API→`/metrics` (unique 2, funnel 2→2→0→0) **with no replay**. → `docker compose up` now self-feeds.
- ✅ **Slice 2.9 — compose cleanup (ADR-0016).** Dropped the legacy **redpanda** broker + the dead
  **tracker**/**analytics** Phase-1 scaffolds from `docker-compose.yml`; deleted their `services/` dirs;
  removed the unused `STREAM_BOOTSTRAP_SERVERS` env. **Final stack = api, detector, postgres, redis,
  prometheus, grafana** (all load-bearing; Redis kept for `/readyz`). **Validated:** `docker compose
  config` parses, six services, ruff clean + 102 tests pass. **(Redis later removed — ADR-0023.)**
- ✅ **Slice 2.10 — per-camera incremental flush (ADR-0018).** First real on-stack `docker compose up`
  run surfaced a demo-killer: the auto-feed POSTed only at the final exit, so endpoints read zero for
  the whole ~24-min CPU detection pass, then jumped. Added `flush()` to the `EventSink` Protocol +
  `JsonlEventSink` + `FanOutSink`; `run_once` flushes **after each camera** (logs `camera_posted`), so
  the endpoints climb as detection runs (~4 update points). Idempotent ingest makes the extra POSTs
  safe; JSONL still gets all. **Validated:** ruff clean + **105 tests** (+3 incremental-flush cases).
  **🎯 Clean-machine gate dry-run PASSED:** `docker compose up --build` → all 4 cameras processed,
  131/131 posted, every endpoint real + consistent (unique 2, funnel 2→2→0→0, heatmap makeup=100, POS
  24/₹44,920, anomalies 2× honest-INFO), zero manual steps, no crash.
- 🟡 **Perf tuning (ADR-0019)** — detector `sample_fps` 10→5 + YOLO `imgsz` 640→480 (~3–4× faster, the
  ~24-min run targets ~6–8 min) + README `.wslconfig` note to give Docker more cores. **Pending:**
  re-validate `unique_visitors`=2 / funnel 2→2→0→0 on the next full run; if it drifts, step back toward
  7 fps / 560 px.
- ✅ **Deterministic ids (ADR-0021)** — `visitor_id` numbered in discovery order (`VIS_0001…`) +
  `event_id` = UUIDv5 of `(store,camera,visitor,type,zone,timestamp)`, filled when blank, preserved on
  ingest. Re-runs/restarts at the same config now **dedup** instead of accumulating (fixed the
  `events_total 237 = 131+106` inflation). ruff clean; **110 tests** (+5 `test_event_ids`).
- ✅ **Detector image imports `cv2` (ADR-0022)** — slimming the image by dropping `libgl1` broke
  `import cv2` because `ultralytics` pulls the FULL `opencv-python` (needs libGL + X11/`libxcb`) →
  `ImportError: libxcb.so.1` at the YOLO pre-bake. Fixed by **replacing opencv with the headless build**
  after `pip install -r requirements.txt`; apt installs only `libglib2.0-0`. Validated by reproducing the
  conflict in a standalone build → `CV2_HEADLESS_OK` (cv2 4.13.0). Slim, GL/X-free, runnable.

## Phase 3 — Production hardening, AI docs, dashboard
- ⬜ Structured logging fields (trace_id, store_id, endpoint, latency_ms, event_count, status_code);
  idempotency tests; graceful degradation (DB down → 503, no stack traces).
- ⬜ Pytest **>70% coverage** incl. edge cases (empty store, all-staff, zero purchases, re-entry in funnel);
  **prompt blocks** atop test files (`# PROMPT:` / `# CHANGES MADE:`).
- 🔄 **Part D (now LIVE, maintained each slice):** `DESIGN.md` + `CHOICES.md` at repo root (>250 words
  each) created; `# PROMPT`/`# CHANGES MADE` blocks added to all test files. Keep in sync as design moves.
- ✅ **Part E (bonus) — live React dashboard (ADR-0020).** `frontend/` Vite + React + TS SPA polling all
  five store endpoints every 4 s (conversion ring, funnel, heatmap, anomalies, feed-health); numbers
  climb live as detection runs. Custom **flat token-based design system** (no UI lib, no gradients,
  white-forward, blue + teal accents). nginx-served `frontend` service on **:8080**; API got CORS.
  **Validated:** `tsc` clean, `vite build` ok (151 kB JS / 7 kB CSS), ruff + 105 tests green.
- ⬜ Final **acceptance-gate dry-run** against [[SPEC]] §gate on a clean machine.

## Phase 4 — Dataset re-grounding (corrected dataset, 2026-06-02, ADR-0024)
> The team replaced `docs/raw/` with a corrected dataset ([[GROUND_TRUTH]] §0). Wiki re-derived; **code
> unchanged pending the user's decisions.** These tasks start once D1–D4 are settled.
- ✅ **Re-derive the wiki** from the new raw (GROUND_TRUTH + propagate).
- ✅ **D1 — Event schema decision (user): keep the flat PDF page-5 schema** — the pipeline "must emit
  this." The richer `sample_events.jsonl` signals (demographics, groups, zone metadata, queue analytics)
  are **not adopted**. We already emit page-5, so no code change. ([[EVENT_SCHEMA]], ADR-0024)
- ✅ **D3 — Reworked `pos_loader.py`** for the 7-col CSV: basket = distinct `order_time` (24), value = Σ
  `total_amount` (**₹34,331.71**), `invoice_number` dropped. Touched contract/ORM/repository/analytics/API/
  frontend/tests/scripts; validated on the real CSV.
- ✅ **Brand → department rollup (ADR-0025, user request):** curated `brand → department` taxonomy
  (`departments.py`, grounded in the store's old `dep_name` + layout) so the API reports **both `top_brand`
  and `top_department`** (real CSV → top brand Faces Canada, top dept makeup). ruff + **115 tests** + `tsc` green.
- ✅ **D2 — Store_2 (done — ADR-0028):**
  - ✅ **Dashboard store switcher + `GET /stores` registry (ADR-0026):** top-bar switcher; **only the
    visible store polls** (`usePolling` resetKey); Store_2 assigned **`ST1009`**; config-driven (`STORES`).
  - ✅ **VLM staff/zone signal (D5 below)** — cross-store staff classifier (pink-staff fix) + auto zone
    labelling that the detection half consumes.
  - ✅ **Pluggable multi-store registry + detection half (ADR-0028):** stores are now **auto-discovered**
    (`shelfsense_common.stores`, one file per store); the detector loops `all_stores()` with per-store
    Re-ID/staff/zone/clip-start. **ST1009** added (two entrances + `zone` + `billing`, 960×1080; clips
    pinned to one synthetic day; placeholder entrance lines — no ground truth; **no POS → conversion
    N/A**). Corrected-dataset Store_1 filenames fixed; **CCTV mount repointed** to `Store_CCTV_Clips/`.
    Adding a future store = drop `stores/<id>.py` + a clips folder. ruff + **144 tests** green.
  - ✅ **Store_2 pipeline run vs ground truth (ADR-0030):** calibrated entrance lines + per-store
    density tuning (reid 0.30 / dwell 800, baked in ST1009). **23 unique vs 25 ground truth**;
    `scripts/run_detection.py --store ST1009`; events at `data/events/store2.jsonl`.
  - ✅ **VLM staff-ID for Store_2 via Groq (ADR-0031):** added a pluggable Groq provider
    (`llama-4-scout`) since Gemini free tier (20/day) < 23 visitors. Full run 23+1 calls, 0 failures →
    **4 staff / 19 customers**; zone relabelled `makeup_aisle→skincare_aisle`. Proof images in
    `docs/wiki/frames/`.
- ✅ **D5 — Optional VLM (Gemini) for staff + zone classification (ADR-0027):** offline-only, off by default
  (gate-safe, no key/network for compose), cached, heuristic fallback. `detector/app/vlm.py` +
  `staff_decider.py` + `zone_resolver.py`; staff per `visitor_id`, zone per product camera; schema unchanged.
  ruff + `ruff format` clean, **138 tests** (+22 `test_vlm.py`, fake client). **Live two-store run pending the
  user's `GEMINI_API_KEY`**, then commit `events.jsonl` + the VLM cache for replay.
- ⬜ **D4 — Demographics/groups (deferred):** default **no** (full-face-blurred footage); revisit only if needed.
- ✅ **D6 — Counting approach: all cameras, quality-gated (ADR-0029, refines ADR-0011):** unique
  visitors now counted from **every camera** (Re-ID-deduped) for **solid tracks** only — sustained +
  on-floor + large-enough box (`MIN_DETECTION_BOX_FRAC`, `app/gating.py`) + **store-interior side of the
  entrance line** (mall pass-by discarded by the line). Entrance cam contributes interior visitors, not
  just crossings. Face-visibility gate **rejected** (overhead/blurred faces → undercount). ruff +
  **148 tests** (+4 `test_gating.py`). ⚠ **Re-validate the Store_1 customer count on the next full run.**
- ⬜ **Re-run the acceptance-gate dry-run** after the Store_2 / detector clip-path changes land.

> Each task follows CLAUDE.md's approach: understand → fit → tradeoffs → plan → implement → validate.
