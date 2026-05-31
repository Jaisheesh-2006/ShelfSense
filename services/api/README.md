# api service

**Responsibility:** Expose business insights over a REST API (FastAPI). Read-optimized;
serves the frontend and any BI consumer.

- **Reads from:** PostgreSQL + Redis.
- **Endpoints:** see [../../docs/wiki/API_SPEC.md](../../docs/wiki/API_SPEC.md).
- **Tech:** Python, FastAPI, Pydantic. Exposes `/healthz`, `/readyz`, `/metrics`.

> Scaffold only. Implementation pending plan approval — see [../../docs/wiki/TASKS.md](../../docs/wiki/TASKS.md).
