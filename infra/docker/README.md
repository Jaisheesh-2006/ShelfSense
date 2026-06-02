# infra/docker

Containerization for ShelfSense.

- Per-service Dockerfiles (detector, api, frontend).
- Root `docker-compose.yml` orchestrates the full stack: **api, detector, postgres, prometheus,
  grafana, frontend** — every service load-bearing (no message broker; the detector POSTs events
  straight to the API, see ARCHITECTURE).
- Goal: **one-command up** for reviewers — `docker compose up`.

> See [../../docs/wiki/ARCHITECTURE.md](../../docs/wiki/ARCHITECTURE.md) and [../../docs/wiki/TASKS.md](../../docs/wiki/TASKS.md).
