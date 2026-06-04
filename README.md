# ShelfSense — Store Intelligence System

> Turn retail **CCTV footage** into business insights — how many people walked in, where they
> went, and what share of them **actually bought something** (conversion rate).
>
> Built for the Purplle Store Intelligence Challenge (2026).

---

## 🚀 Live demo

|               | URL                                                                                                                                                |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Dashboard** | **https://shelfsense-fronted.onrender.com**                                                                                                        |
| **API**       | https://shelfsense-3ujc.onrender.com — [/health](https://shelfsense-3ujc.onrender.com/health) · [/docs](https://shelfsense-3ujc.onrender.com/docs) |

> Hosted free on Render. The API **sleeps after ~15 min idle** — if the dashboard shows "Reconnecting",
> open the [API `/health`](https://shelfsense-3ujc.onrender.com/health) once to wake it (~30–60 s), then refresh.
> View the dashboard **without an ad blocker** (or in an incognito window) — blockers can stop the metric polls.

---

## What it does

ShelfSense watches a store's camera feeds and produces retail metrics:

- **Footfall** — how many customers entered
- **Conversion rate** — visitors who bought ÷ total visitors
- **Funnel** — the drop-off from _entered → browsed → checkout → purchased_
- **Zone engagement & dwell** — which areas attract people, and for how long
- **Anomalies** — unusual patterns worth a look

It does this with an event-driven pipeline:

```
CCTV → detector (find + track + Re-ID people → events) → API (ingest + compute metrics) → dashboard
```

---

## Run it (one command)

You need **Docker Desktop** installed. Then:

```bash
docker compose up --build
```

That starts everything. The detector **replays pre-generated events** from
`data/events/behavior.jsonl` into the API — data appears on the dashboard within seconds, no
YOLO model, CCTV clips, or VLM keys required. This is done to make it easy for reviewers to run and test the system without heavy dependencies or datal setup. To run the full detection pipeline on real CCTV clips, see the next section.

> **Running from the source zip (no Docker)?** The submission ships **source only** — no virtual
> environment, `node_modules`, or model weights are included. The Docker path above needs nothing
> pre-installed. But to run anything **directly** from the source (the tests or the detection
> pipeline outside Docker), first install the Python requirements:
>
> ```bash
> pip install ./services/common -r services/api/requirements.txt \
>             -r services/detector/requirements.txt -r requirements-dev.txt
> ```
>
> (Python 3.11+. The frontend, if run outside Docker, needs `npm install` in `frontend/`.)

| What                        | URL                           |
| --------------------------- | ----------------------------- |
| **Live dashboard**          | **http://localhost:8080**     |
| API (with interactive docs) | http://localhost:8000/docs    |
| Metrics (Prometheus format) | http://localhost:8000/metrics |
| Prometheus                  | http://localhost:9090         |
| Grafana dashboards          | http://localhost:3000         |

### API Endpoints (as required by the spec)

All endpoints conform to the challenge specification and are testable via the Swagger UI (`/docs`).

| Endpoint                                          | Purpose                                               |
| ------------------------------------------------- | ----------------------------------------------------- |
| `POST http://localhost:8000/events/ingest`        | Idempotent event ingestion (batch up to 500)          |
| `GET http://localhost:8000/health`                | System status and feed freshness (STALE_FEED check)   |
| `GET http://localhost:8000/stores/{id}/metrics`   | Core conversion rate, dwell times, and queue depths   |
| `GET http://localhost:8000/stores/{id}/funnel`    | Drop-off counts from Entry → Browsed → Queue → Bought |
| `GET http://localhost:8000/stores/{id}/heatmap`   | Zone engagement and relative dwell times              |
| `GET http://localhost:8000/stores/{id}/anomalies` | Queue spikes, conversion drops, and dead zones        |

To stop it: `docker compose down` (add `-v` to also clear the database)

### Run the detection pipeline (re-generate events)

To re-run the full YOLO + ByteTrack detection over CCTV clips:

1. **Place CCTV clips** in `docs/raw/Store_CCTV_Clips/` (gitignored).
2. Run with detect mode:
   ```bash
   docker compose --profile detect up --build
   ```
3. Events are written to **`data/events/behavior.jsonl`** and auto-POSTed to the API.
4. To enable VLM staff/zone classification, set `VLM_ENABLED=true` and a provider key in a `.env`
   file. The **default provider is Groq** (multimodal Llama-4 Scout — what we ran), so just set
   `GROQ_API_KEY=...`. The VLM layer is **pluggable**: to use a different model/provider, set
   `VLM_PROVIDER` and `VLM_MODEL` (e.g. `VLM_PROVIDER=gemini`, `VLM_MODEL=gemini-2.5-flash-lite`,
   `GEMINI_API_KEY=...`). The VLM is **optional** — with it off the pipeline uses the per-store
   uniform-colour staff heuristic, so `docker compose up` never needs a key or network.

### Run the tests

```bash
pip install ./services/common -r services/api/requirements.txt \
            -r services/detector/requirements.txt -r requirements-dev.txt
pytest          # 188 tests; enforces ≥70% coverage (SPEC Part C) — currently 83%
```

The unit + integration suites (edge cases, ingest idempotency, end-to-end event replay) run
**hermetically** — no Docker, Postgres, or network required (the API tests use SQLite via FastAPI's
`TestClient`). CI runs the same `ruff` + `pytest` gates on every push (`.github/workflows/ci.yml`).

### Tips for reviewers

- **The default `docker compose up` is light** — it replays committed events (no YOLO/Torch, no
  detector build), so the dashboard fills in ~20 s on a normal laptop.
- **The heavy build is opt-in:** only `docker compose --profile detect up --build` pulls YOLO/Torch
  and runs detection over the clips — for that, give Docker ~8 CPUs / 10 GB and expect a longer first build.
- **Inspect the events:** open `data/events/behavior.jsonl` (newline-delimited JSON) — the committed
  replay artifact the API ingests (ST1008: 106 events · ST1009: 183), i.e. exactly what the detector emitted.

---

## Project layout

```
docs/
  raw/            # source inputs (local only — videos, sales CSV, floor plan)
  wiki/           # living project knowledge base (design, decisions, rules)
services/
  common/         # shared code: event contracts, config, logging
  detector/       # finds, tracks & Re-IDs people, emits behavioural events (YOLO + ByteTrack)
  api/            # ingests events, computes metrics, serves them (FastAPI)
frontend/         # dashboard (React)
infra/            # Docker, Prometheus, Grafana config
tests/            # automated tests
scripts/          # helper scripts
docker-compose.yml
```

---

## Documentation

### How this was built — context engineering with an "LLM wiki"

The project was developed with an AI pair-engineer using a deliberate **context-engineering**
discipline: a self-maintained **LLM wiki** (the Karpathy pattern). Instead of an assistant
re-deriving context every session, `docs/wiki/` is a **stateful, densely `[[cross-linked]]`
knowledge base** that is the single source of truth — and the two graded deliverables are
_generated from it_, not written once and left to rot:

- **`GROUND_TRUTH.md`** — observed facts from the raw data; nothing else may contradict it.
- **`DECISIONS.md`** — an ADR log (every choice with alternatives + trade-offs) → distilled into **`CHOICES.md`**.
- **`ARCHITECTURE.md`** → **`DESIGN.md`**; **`STATE.md`** tracks the live build state; **`INTERVIEW_QA.md`** defends each slice.

Every session **reads the wiki first and writes understanding back at the end**, so knowledge
_compounds_ instead of resetting. The payoff: every decision is traceable, the reasoning behind each
trade-off is recorded, and the reviewer-facing docs reflect a living source rather than a one-off.

The full design lives in the **wiki** — start at [docs/wiki/README.md](docs/wiki/README.md):

- [GROUND_TRUTH.md](docs/wiki/GROUND_TRUTH.md) — the facts about the data & store
- [ARCHITECTURE.md](docs/wiki/ARCHITECTURE.md) — how the system is built
- [BUSINESS_RULES.md](docs/wiki/BUSINESS_RULES.md) — how each metric is defined
- [DECISIONS.md](docs/wiki/DECISIONS.md) — key choices and why
- [STATE.md](docs/wiki/STATE.md) — current progress & what's next

---

## Engineering practices

Production-readiness and code quality were first-class, not afterthoughts:

- **CI on every push** — [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs four jobs: **ruff**
  lint, **pytest** with the ≥70% coverage gate, the **frontend build** (`tsc` + `vite`), and a
  **`docker compose config`** check that guards the one-command acceptance gate.
- **Linting & types** — `ruff` across the whole repo (rules E/F/I/UP/B/C4/SIM); full type hints with
  **Pydantic v2** models for every event / API / config contract; `mypy` configured (strict on the
  shared `common` package).
- **Tested** — 188 unit + integration tests at **83% coverage** (gate 70%): edge cases (re-entry, staff,
  empty store, occlusion), ingest **idempotency**, and an end-to-end replay test. Every test file carries
  a `# PROMPT` / `# CHANGES MADE` block (AI-engineering trace).
- **12-factor config** — every setting via environment variables (`pydantic-settings`), all documented in
  [`.env.example`](.env.example); no hardcoded secrets, hosts, or thresholds.
- **Observability** — structured JSON request logs (`trace_id`, endpoint, latency, status, event count),
  a Prometheus `/metrics` endpoint, and Grafana dashboards.
- **Resilient API** — idempotent ingest (safe replays), partial-success batches, and graceful DB-down →
  structured **503** (no leaked stack traces).
- **One-command stack** — `docker compose up` builds every service from scratch with healthchecks and
  startup ordering; CPU-only images, pinned dependencies.

---

## Status

🟢 **All phases complete** — `docker compose up --build` runs the full stack with one command; the
replayer feeds pre-generated events into the API, which serves health, metrics, funnel, heatmap,
and anomaly endpoints (computed from real data, never hardcoded). The **live React dashboard**
(Part E) is up at http://localhost:8080. Two stores supported (ST1008, ST1009). 188 unit + integration tests,
83% code coverage.

---

## Tech stack

Python · FastAPI · YOLO + ByteTrack · PostgreSQL · React · Docker Compose ·
Prometheus + Grafana.
