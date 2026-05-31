# analytics service

**Responsibility:** Turn tracks into business insights — build customer sessions, compute
dwell time, zone engagement, customer journeys, conversion funnels, checkout activity,
anomalies, and KPIs. Persist results.

- **Consumes:** `track.updated` events.
- **Produces:** `session.*` and `metric.computed` events + writes to PostgreSQL.
- **Metric definitions:** [../../docs/wiki/BUSINESS_RULES.md](../../docs/wiki/BUSINESS_RULES.md).

> Scaffold only. Implementation pending plan approval — see [../../docs/wiki/TASKS.md](../../docs/wiki/TASKS.md).
