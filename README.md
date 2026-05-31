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
CCTV → detector (find people) → tracker (follow them) → analytics (turn into metrics) → API → dashboard
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
| API (with interactive docs) | http://localhost:8000/docs |
| Metrics (Prometheus format) | http://localhost:8000/metrics |
| Prometheus | http://localhost:9090 |
| Grafana dashboards | http://localhost:3000 |

To stop it: `docker compose down`

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
  detector/       # finds people in frames (YOLO)
  tracker/        # follows each person across frames (ByteTrack)
  analytics/      # turns movement into business metrics
  api/            # serves the metrics (FastAPI)
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

🟢 **Phase 1 complete** — the full stack runs with one command; the API serves health,
metrics, and business endpoints (computed from real data, never hardcoded).

🟡 **Phase 2 in progress** — making the cameras actually count people and produce live metrics.
See [docs/wiki/TASKS.md](docs/wiki/TASKS.md).

---

## Tech stack

Python · FastAPI · YOLO + ByteTrack · Redpanda (Kafka-compatible) · PostgreSQL · Redis ·
React · Docker Compose · Prometheus + Grafana.
