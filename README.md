# ShelfSense — Store Intelligence System

> Turn retail **CCTV footage** into business insights — how many people walked in, where they
> went, and what share of them **actually bought something** (conversion rate).
>
> Built for the Purplle Store Intelligence Challenge (2026).

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

### Tips for reviewers

- **Give Docker ~8 CPUs / 10 GB.** Docker Desktop → **Settings → Resources**.
- The **first `--build` is heavy** (YOLO/Torch downloaded once, then cached).
- **Inspect the raw events:** open `data/events/behavior.jsonl` (newline-delimited JSON)
  to see exactly what the pipeline emitted.

---

## Data (not included in this repo)

The raw inputs live in `docs/raw/` and are **kept out of GitHub** on purpose — they contain
customer personal data and large video files. To run with real data, place them locally:

```
docs/raw/
├── Store_CCTV_Clips/
│   ├── Store_1/Store 1/   CAM 1 - zone.mp4, CAM 2 - zone.mp4, CAM 3 - entry.mp4,
│   │                      CAM 5 - billing.mp4, Store 1 - layout.png
│   └── Store_2/Store 2/   entry 1.mp4, entry 2.mp4, zone.mp4,
│                          billing_area.mp4, store 2 - layout.png
├── POS - sample transactions*.csv        # 7-col POS sales (store ST1008 only)
├── Purplle_Tech_Challenge_PS*.pdf        # problem statement
├── Assessment  Evaluation Framework*.pdf  # grading rubric
└── sample_events*.jsonl                   # 13 example events (reference schema)
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

🟢 **All phases complete** — `docker compose up --build` runs the full stack with one command; the
replayer feeds pre-generated events into the API, which serves health, metrics, funnel, heatmap,
and anomaly endpoints (computed from real data, never hardcoded). The **live React dashboard**
(Part E) is up at http://localhost:8080. Two stores supported (ST1008, ST1009). 138 unit tests,
84% code coverage.

---

## Tech stack

Python · FastAPI · YOLO + ByteTrack · PostgreSQL · React · Docker Compose ·
Prometheus + Grafana.
