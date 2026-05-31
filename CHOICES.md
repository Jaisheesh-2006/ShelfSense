# CHOICES — key engineering decisions

Three headline decisions, each with the options weighed, what the AI suggested, what we chose, why,
and **when we would revisit it**. Full decision log: `docs/wiki/DECISIONS.md`.

---

## Decision 1 — Detection model: YOLOv8-nano

**Context.** The detection layer is the foundation; everything downstream inherits its quality. It must
run on a plain CPU under `docker compose up`, and the challenge scores *handling of uncertainty and
edge cases*, not a perfect detection rate.

**Options considered.**
- YOLOv8 (nano / small / medium) — mature, CPU-friendly, ships with tracking.
- YOLOv9 / RT-DETR — higher accuracy, heavier, more setup.
- MediaPipe — light but weaker for crowded retail scenes.

**What the AI suggested.** YOLOv8 as a strong baseline; nano for CPU; noted a larger variant or RT-DETR
would help on heavily occluded billing frames.

**Decision.** **YOLOv8-nano**, with the model path as a config value.

**Why.** Fast on CPU, accurate enough to count people in our footage, and integrates directly with
ByteTrack (one dependency, not two). Occlusion misses are mitigated by keeping low-confidence
detections (flagged, not dropped) and letting the tracker bridge short gaps — the rubric rewards
graceful degradation over a perfect detector.

**Trade-off / when we'd revisit.** Nano misses more under heavy occlusion. If entry/exit accuracy fell
short on validation, the config swap to `yolov8s/m` or RT-DETR is one line — at a latency cost we'd
only pay if accuracy demanded it.

---

## Decision 2 — Event schema: adopt the prescribed flat behavioural schema

**Context.** The detection layer must emit structured events that the API ingests and is *scored*
against. Schema compliance is a graded criterion.

**Options considered.**
- (a) Our own envelope+payload design with low-level `detection.created` / `track.updated` events
  (rich for internal tracing).
- (b) The flat behavioural schema prescribed by the problem statement (`ENTRY`, `ZONE_DWELL`,
  `BILLING_QUEUE_JOIN`, … each with `visitor_id`, `is_staff`, `confidence`, `metadata`).

**What the AI suggested.** It initially built the richer envelope design, then — on re-reading the spec
— recommended adopting the prescribed schema verbatim as the wire contract.

**Decision.** **The prescribed behavioural schema** is the emitted/ingested contract; any low-level
representation stays internal to the pipeline.

**Why.** It is exactly what the API is validated against, so it removes a translation layer and a whole
class of mismatch bugs. `event_id` doubles as the idempotency/dedup key. Behavioural events (not boxes)
are also the right altitude for the API — it computes every metric from them directly.

**Trade-off / when we'd revisit.** Less internal richness on the wire; we don't need it downstream. If
we later needed frame-level forensics we'd add an internal debug stream without touching this contract.

---

## Decision 3 — Ingestion architecture: direct POST ingest, no message broker

**Context.** Events must get from the pipeline into the API reliably, and the acceptance gate hinges on
`POST /events/ingest` plus a clean one-command start.

**Options considered.**
- (a) A Kafka-compatible broker (Redpanda) streaming events to a consumer that writes to the DB.
- (b) The pipeline writes `events.jsonl` and **POSTs batches to `/events/ingest`**, which validates,
  de-duplicates (idempotent by `event_id`), and stores.

**What the AI suggested.** The broker design first (replayable, scalable); after the spec, the simpler
ingest path.

**Decision.** **Direct POST ingest; broker dropped.**

**Why.** The spec's model is ingest-centric, and a broker is a heavy moving part that adds risk to the
gate. Idempotent ingest gives us safe retry/replay — the durability a broker would have provided — with
far less operational surface. For the live dashboard (Part E) we simulate real time by POSTing as
frames are processed.

**Trade-off / when we'd revisit.** We give up built-in stream replay and back-pressure. That is fine for
recorded clips and a single store; at 40 live stores we would reintroduce a queue in front of ingest —
a bounded, well-understood step (and the exact scaling question the follow-up interview probes).
