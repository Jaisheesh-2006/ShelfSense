# api service

**Responsibility:** The Intelligence API (FastAPI). Ingests behavioural events and serves
per-store metrics, computed live from stored events. Serves the frontend and any BI consumer.

- **Reads from:** PostgreSQL.
- **Endpoints:** `POST /events/ingest`, `GET /stores/{id}/{metrics,funnel,heatmap,anomalies}`,
  `/health`, plus `/healthz`, `/readyz`, `/metrics` — see [../../docs/wiki/API_SPEC.md](../../docs/wiki/API_SPEC.md).
- **Tech:** Python, FastAPI, Pydantic v2, SQLAlchemy. Run: `uvicorn shelfsense_api.main:app`.
