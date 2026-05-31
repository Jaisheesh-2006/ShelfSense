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
- ⬜ **Slice 2.1** — detector: read frames (OpenCV) → YOLO person detection → emit `detection.created`
- ⬜ tracker: ByteTrack associate → emit `track.updated` with zone mapping (entrance line-crossing)
- ⬜ analytics: sessions → footfall + **session-based funnel** + conversion (load POS CSV → `transactions`) → persist
- ⬜ Confirm api `/funnel` + `/metrics` show real, input-varying values once tables populated
- ⬜ frontend: minimal dashboard (footfall, funnel, conversion)

## Phase 3 — Deepen analytics & edge cases
- ⬜ Re-entry, staff exclusion, group entry, occlusion handling ([[EDGE_CASES]])
- ⬜ Journeys, zone engagement, checkout activity, anomalies (rule-based, meaningful)
- ⬜ KPIs incl. basket size + GMV by department from CSV

## Phase 4 — Production polish & submission
- ⬜ Error handling pass; Prometheus metrics + Grafana dashboards; tracing
- ⬜ Pytest: unit + edge-case + one pipeline integration test
- ⬜ Per-service Dockerfiles; verify `docker compose up` clean from scratch
- ⬜ **Generate `DESIGN.md` + `CHOICES.md` at repo root** from [[ARCHITECTURE]]+[[DECISIONS]] (ADR-0003)
- ⬜ Final gate dry-run against [[GROUND_TRUTH]] §3 checklist

> Each task follows CLAUDE.md's approach: understand → fit → tradeoffs → plan → implement → validate.
