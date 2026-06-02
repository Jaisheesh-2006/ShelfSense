# ShelfSense — Store Intelligence System

> Turn retail **CCTV footage** into business insights — how many people walked in, where they
> went, and what share of them **actually bought something** (conversion rate).
>
> Built for the UpGrad / Purplle Store Intelligence Challenge (2026).

---

## What it does

ShelfSense watches a store's camera feeds and produces retail metrics:

- **Footfall** — how many customers entered
- **Conversion rate** — visitors who bought ÷ total visitors
- **Funnel** — the drop-off from *entered → browsed → checkout → purchased*
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

That starts everything. Once it's up:

| What | URL |
|------|-----|
| **Live dashboard** | **http://localhost:8080** |
| API (with interactive docs) | http://localhost:8000/docs |
| Metrics (Prometheus format) | http://localhost:8000/metrics |
| Prometheus | http://localhost:9090 |
| Grafana dashboards | http://localhost:3000 |

To stop it: `docker compose down`

### Run it fast (recommended for reviewers)

The detector runs YOLO on **CPU**, so give Docker some headroom or the first run drags:

- **Give Docker ~8 CPUs / 10 GB.** Docker Desktop → **Settings → Resources** (Hyper-V backend); or on
  the **WSL2 backend** put this in `C:\Users\<you>\.wslconfig`, then run `wsl --shutdown`:
  ```ini
  [wsl2]
  processors=8
  memory=10GB
  ```
- The **first `--build` is heavy** (YOLO/Torch downloaded once, then cached); later runs are quick.
- **No manual steps** — the stack feeds itself. The numbers **appear progressively** as each camera
  is processed (a few minutes on CPU); `/stores/ST1008/metrics` fills in while detection runs.
- **Inspect the raw events:** the detector also writes every event to **`data/events/behavior.jsonl`**
  on the host (newline-delimited JSON), **growing incrementally** as each camera finishes — open it to
  see exactly what the pipeline emitted.

---

## Data (not included in this repo)

The raw inputs live in `docs/raw/` and are **kept out of GitHub** on purpose — they contain
customer personal data and large video files. To run with real data, place them locally:

```
docs/raw/
├── CCTV Footage/CCTV Footage/CAM 1.mp4 … CAM 5.mp4   # camera clips
├── Brigade_Bangalore_*.csv                            # POS sales data
└── Brigade Road - Store layout*.pdf                   # floor plan
```

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

The full design lives in the **wiki** — start at [docs/wiki/README.md](docs/wiki/README.md):

- [GROUND_TRUTH.md](docs/wiki/GROUND_TRUTH.md) — the facts about the data & store
- [ARCHITECTURE.md](docs/wiki/ARCHITECTURE.md) — how the system is built
- [BUSINESS_RULES.md](docs/wiki/BUSINESS_RULES.md) — how each metric is defined
- [DECISIONS.md](docs/wiki/DECISIONS.md) — key choices and why
- [STATE.md](docs/wiki/STATE.md) — current progress & what's next

---

## Status

🟢 **Phases 1 & 2 complete** — `docker compose up` runs the full stack with one command; the
detector counts people from the real clips and **auto-feeds** the API, which serves health, metrics,
funnel, heatmap, and anomaly endpoints (computed from real data, never hardcoded). The **live React
dashboard** (Part E) is up at http://localhost:8080.

🟡 **Phase 3 in progress** — production hardening (structured-logging fields, coverage push).
See [docs/wiki/TASKS.md](docs/wiki/TASKS.md).

---

## Tech stack

Python · FastAPI · YOLO + ByteTrack · PostgreSQL · React · Docker Compose ·
Prometheus + Grafana.
