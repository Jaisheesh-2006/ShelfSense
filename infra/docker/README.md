# infra/docker

Containerization for ShelfSense.

- Per-service Dockerfiles (detector, tracker, analytics, api, frontend).
- `docker-compose.yml` orchestrating the full stack: services + event stream
  (Kafka-compatible) + PostgreSQL + Redis + Prometheus + Grafana.
- Goal: **one-command up** for reviewers — `docker compose up`.

> Scaffold only. See [../../docs/wiki/ARCHITECTURE.md](../../docs/wiki/ARCHITECTURE.md) and [../../docs/wiki/TASKS.md](../../docs/wiki/TASKS.md).
