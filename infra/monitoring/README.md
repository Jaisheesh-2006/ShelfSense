# infra/monitoring

Observability stack configuration.

- **Prometheus** — scrape config for each service's `/metrics` endpoint.
- **Grafana** — provisioned dashboards for pipeline health (throughput, latency, queue
  depth, detection/track counts) and business KPIs (footfall, conversion, dwell).

Observability is a first-class concern (CLAUDE.md Principle 7).

> Scaffold only. See [../../docs/wiki/ARCHITECTURE.md](../../docs/wiki/ARCHITECTURE.md).
