# STATE — where the build is right now

> Stateful progress for the LLM wiki. Update this at the end of every working session so the
> next session resumes instantly. Keep it short and current; history lives in git, detail in
> [[TASKS]]. This replaces the empty root `CURRENT_STATE.md`.
>
> Last updated: 2026-05-31.

## Current phase

🟠 **Re-aligned to the authoritative problem statement ([[SPEC]], ADR-0005).** Phase 1 + Slices
2.0/2.1 done; Phase 2 **re-planned**. Slice 2.2 (tracking + ENTRY/EXIT in the new schema) next.

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

## ▶ Next action — Slice 2.2 (tracking + ENTRY/EXIT in the prescribed schema)
1. Define the prescribed event as Pydantic models in `common` ([[EVENT_SCHEMA]]); keep YOLO detection from 2.1.
2. tracker: **ByteTrack** per camera → stable `track_id`; assign a `visitor_id` per visit.
3. On CAM3, use the calibrated `EntranceLine` (`zones.py`): foot-point `OUTSIDE`→`INSIDE` ⇒ `ENTRY`,
   `INSIDE`→`OUTSIDE` ⇒ `EXIT`. Emit prescribed events to a JSONL file (ingest path comes in 2.6).
4. **Validate the entrance line for real** (Slice 2.0 promise): overlay tracks + line on CAM3,
   count entries by eye vs system; nudge coords if needed.

See [[TASKS]] Phase 2 for slices 2.3–2.7. Re-ID/staff/groups land in 2.4; API ingest in 2.6.

## Notes / env
- Local: `.venv` has pydantic/fastapi/etc.; OpenCV installed for frame work. Real runtime = containers.
- Run the stack: `docker compose up --build` (api :8000, prometheus :9090, grafana :3000). Postgres/Redis/Redpanda internal-only.
