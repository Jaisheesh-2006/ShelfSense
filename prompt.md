Before submitting, I'd do a final pass using the challenge acceptance gate and scoring rubric, not your local checklist.

# 🚨 Acceptance Gate (Must Pass)

These are non-negotiable. If any fail, scoring may not happen.

### Startup

- [ ] Fresh clone works
- [ ] `docker compose up` works on clean machine
- [ ] No manual setup steps
- [ ] No missing environment variables required for default run

### API

- [ ] `POST /events/ingest` works
- [ ] `GET /stores/STORE_BLR_002/metrics` returns valid JSON
- [ ] `/health` works

### Documentation

- [ ] README exists
- [ ] DESIGN.md >250 words
- [ ] CHOICES.md >250 words

---

# 🎯 Detection Layer

### Event Schema

- [ ] All required fields emitted
- [ ] `event_id` globally unique
- [ ] ISO timestamps
- [ ] confidence always populated
- [ ] is_staff populated

### Event Types

- [ ] ENTRY
- [ ] EXIT
- [ ] ZONE_ENTER
- [ ] ZONE_EXIT
- [ ] ZONE_DWELL
- [ ] BILLING_QUEUE_JOIN
- [ ] BILLING_QUEUE_ABANDON
- [ ] REENTRY

Even if some are rare, verify code paths exist.

### Edge Cases

- [ ] Group entry handled
- [ ] Staff excluded
- [ ] Re-entry logic documented
- [ ] Partial occlusion handled gracefully
- [ ] Empty store doesn't break metrics
- [ ] Camera overlap doesn't obviously double count

---

# 🎯 API Endpoints

### Ingest

- [ ] Idempotent by event_id
- [ ] Duplicate replay safe
- [ ] Batch >500 rejected correctly
- [ ] Partial success works

### Metrics

- [ ] Unique visitors
- [ ] Conversion rate
- [ ] Avg dwell
- [ ] Queue depth
- [ ] Abandonment rate

### Funnel

- [ ] Entry → Zone → Billing → Purchase
- [ ] Re-entries don't double count visitors

### Heatmap

- [ ] Visit frequency
- [ ] Avg dwell
- [ ] data_confidence flag

### Anomalies

- [ ] Queue spike
- [ ] Conversion drop
- [ ] Dead zone

### Health

- [ ] Last event timestamp
- [ ] Feed status

---

# 🎯 Production Readiness

### Logging

- [ ] trace_id
- [ ] endpoint
- [ ] latency_ms
- [ ] status_code
- [ ] event_count on ingest

### Error Handling

- [ ] DB unavailable → 503
- [ ] No stack traces exposed

### Tests

- [ ] > 70% coverage
- [ ] Empty store test
- [ ] All staff test
- [ ] Zero purchase test
- [ ] Re-entry test
- [ ] Ingest idempotency test

---

# 🎯 AI Engineering (Easy Points)

### Test Files

- [ ] Every test file has

```python
# PROMPT:
# CHANGES MADE:
```

header.

### DESIGN.md

- [ ] AI-Assisted Decisions section exists

### CHOICES.md

Strongly highlight:

- [ ] Detection model choice
- [ ] Event schema choice
- [ ] API architecture choice

For each:

- [ ] Options considered
- [ ] AI suggestion
- [ ] Final choice
- [ ] Why

Exactly what rubric asks.

---

# 🎯 Reviewer Experience (Most Important)

### Startup

Ideal:

```bash
docker compose up
```

within 30–60 seconds:

- [ ] API running
- [ ] Dashboard visible
- [ ] Metrics populated
- [ ] No waiting 20–30 minutes

### Dashboard

- [ ] Looks alive immediately
- [ ] Metrics update
- [ ] Not empty
- [ ] No broken charts

### README

Reviewer should be able to understand:

- [ ] How to run
- [ ] How to test
- [ ] How to run full detector
- [ ] How replay mode works

within 2 minutes.

---

# Final Question

Before submission, ask yourself:

> If a reviewer gives my project exactly 5 minutes, will they see something impressive?

If the answer is:

- dashboard loads immediately,
- metrics appear,
- API works,
- docs are clear,

then you're in a much stronger position than a technically perfect solution that requires 30 minutes before showing any output.
