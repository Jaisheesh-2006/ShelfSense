# detector service

**Responsibility:** Detect persons in video frames using YOLO. Stateless per frame.

- **Consumes:** video frames (from CCTV footage / ingestion).
- **Produces:** `detection.created` events (see [../../docs/wiki/EVENT_SCHEMA.md](../../docs/wiki/EVENT_SCHEMA.md)).
- **Tech:** Python, YOLO. Exposes `/healthz` and Prometheus `/metrics`.

> Scaffold only. Implementation pending plan approval — see [../../docs/wiki/TASKS.md](../../docs/wiki/TASKS.md).
