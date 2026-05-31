# STATE — where the build is right now

> Stateful progress for the LLM wiki. Update this at the end of every working session so the
> next session resumes instantly. Keep it short and current; history lives in git, detail in
> [[TASKS]]. This replaces the empty root `CURRENT_STATE.md`.
>
> Last updated: 2026-05-31.

## Current phase

🟢 **Phase 1 DONE (gate met). Phase 2 in progress — Slice 2.0 DONE, Slice 2.1 next.**

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

## ▶ Next action — Slice 2.1 (detector: real detections)
Make the detector actually see people:
1. Add `ultralytics` to `services/detector/requirements.txt`; wire CV deps into `services/detector/Dockerfile`
   (opencv-headless needs `libgl1`/`libglib2.0-0` on slim) + bind-mount `docs/raw/CCTV Footage` → `/data/cctv`.
2. In `detector/app`, use `VideoFrameSource` to read CAM frames → run YOLO (person class) → build
   `DetectionCreated` events → publish to Redpanda topic `detection.created` (add a small Kafka producer).
3. Verify: consume the topic and see structured events; overlay boxes on sample frames to confirm
   they sit on real people. This also satisfies the gate's "pipeline produces structured events" for real.

Then Slice 2.2 (tracker + footfall), 2.3 (conversion), 2.4 (funnel), 2.5 (dashboard).

## Notes / env
- Local: `.venv` has pydantic/fastapi/etc.; OpenCV installed for frame work. Real runtime = containers.
- Run the stack: `docker compose up --build` (api :8000, prometheus :9090, grafana :3000). Postgres/Redis/Redpanda internal-only.
