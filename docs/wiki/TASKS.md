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

- ⬜ **Slice 2.2 — Tracking + ENTRY/EXIT (+ visitor_id).** ByteTrack per camera; CAM3 entrance-line
  crossing → emit `ENTRY`/`EXIT` (prescribed schema) with a `visitor_id`, to JSONL. **Validate the
  entrance line** (Slice 2.0 promise): overlay tracks, count entries by eye vs system.
- ⬜ **Slice 2.3 — Zones + dwell.** Map tracks to zones; emit `ZONE_ENTER`/`ZONE_EXIT`/`ZONE_DWELL` (30s).
- ⬜ **Slice 2.4 — Re-ID + edge cases.** Cross-camera dedup + `REENTRY` (no double-count), `is_staff`
  classification, group-entry (count individuals), confidence calibration (flag low-conf, don't drop).
- ⬜ **Slice 2.5 — Billing queue + POS.** `BILLING_QUEUE_JOIN`/`ABANDON` + `queue_depth`; POS
  correlation (5-min billing-zone window → converted). See [[BUSINESS_RULES]].
- ⬜ **Slice 2.6 — API ingest + core metrics.** `POST /events/ingest` (idempotent/dedup/partial/≤500);
  `GET /stores/{id}/metrics` + `/funnel` (session-based, no double-count). Retire old `/api/v1/*`.
- ⬜ **Slice 2.7 — heatmap + anomalies + health.** `/heatmap` (normalised, data_confidence),
  `/anomalies` (queue spike / conversion drop vs 7-day / dead zone; severity + suggested_action), `/health` (STALE_FEED).

## Phase 3 — Production hardening, AI docs, dashboard
- ⬜ Structured logging fields (trace_id, store_id, endpoint, latency_ms, event_count, status_code);
  idempotency tests; graceful degradation (DB down → 503, no stack traces).
- ⬜ Pytest **>70% coverage** incl. edge cases (empty store, all-staff, zero purchases, re-entry in funnel);
  **prompt blocks** atop test files (`# PROMPT:` / `# CHANGES MADE:`).
- 🔄 **Part D (now LIVE, maintained each slice):** `DESIGN.md` + `CHOICES.md` at repo root (>250 words
  each) created; `# PROMPT`/`# CHANGES MADE` blocks added to all test files. Keep in sync as design moves.
- ⬜ **Part E (bonus):** live dashboard — ≥1 metric updating as the pipeline POSTs events (web > terminal).
- ⬜ Final **acceptance-gate dry-run** against [[SPEC]] §gate on a clean machine.

> Each task follows CLAUDE.md's approach: understand → fit → tradeoffs → plan → implement → validate.
