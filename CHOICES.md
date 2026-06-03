# CHOICES — key engineering decisions

Six headline decisions, each with the options weighed, what the AI suggested, what we chose, why,
and **when we would revisit it**. Full decision log: `docs/wiki/DECISIONS.md`.

---

## Decision 1 — Detection model: YOLOv8-nano

**Context.** The detection layer is the foundation; everything downstream inherits its quality. It must
run on a plain CPU under `docker compose up`, and the challenge scores _handling of uncertainty and
edge cases_, not a perfect detection rate.

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

**Context.** The detection layer must emit structured events that the API ingests and is _scored_
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

---

## Decision 4 — Staff identification: dark-uniform appearance, not presence time

**Context.** Staff must be excluded from customer metrics, and they dominate this clip — reviewing the
footage, the store has **5 staff / 2 customers**. With only **two** customers the conversion denominator
is tiny, so a single staff/customer mistake is a ~50 % error. Getting this right matters more than headcount.

**Options considered.**

- (a) **Presence-time heuristic** — flag anyone present beyond a long threshold (our first, Slice 2.4 approach).
- (b) **Dark-uniform appearance** — staff wear a complete black uniform; the customers wear grey/violet.
- (c) **A learned uniform/colour classifier or VLM** — most accurate, heaviest.
- (d) **Stockroom (CAM4) enrolment** — anyone in the back room is staff; re-match them on the floor.

**What the AI suggested.** We first shipped the **presence heuristic (a)**. After we confirmed from the
footage that staff wear a complete black uniform while the two customers wear grey/violet, the AI suggested
pairing **dark-uniform (b)** as the primary signal with **CAM4 enrolment (d)** as a scaling layer. We
validated both against the video before trusting them: CAM4 is **empty the whole clip**, so (d) enrols
nobody here (kept only as a documented scaling idea), and presence (a) risks flagging a long-browsing
customer — which we can't afford with only two.

**Decision.** **Dark-uniform appearance (b)** as the primary signal (`min` of upper/lower-body dark-pixel
fraction, reusing the Re-ID crop); presence (a) demoted to an off-by-default fallback; CAM4 enrolment (d)
kept as a documented scaling mechanism; a learned model (c) deferred.

**Why.** It is cheap (reuses pixels we already sample), offline/CPU-safe, and on the footage it **cleanly
separates** the two groups (customers 0.08–0.19, staff 0.52–0.96; threshold 0.50) — yielding **exactly 2
customers**. It directly protects the metric that matters, unlike presence.

**Trade-off / when we'd revisit.** A genuinely black-clothed customer would be misflagged, and bright
backgrounds dilute the score (so we don't use it on the entrance camera). The score and threshold are
config and the measure is one function — we'd swap to a learned classifier (c) if a future store's uniform
weren't a clean colour signal.

---

## Decision 5 — Event ingest: resilient by design, and a thin, testable API over reusable logic

**Context.** `POST /events/ingest` is the acceptance-gate endpoint and the entry to the largest scoring
bucket. Real pipelines re-send (retries, replays) and occasionally emit a bad record, so ingest has to be
both **strict** (validate every event) and **forgiving** (one bad event mustn't sink a 500-event batch).

**Options considered.**

- (a) Type the request body as `list[BehaviorEvent]` and let Pydantic validate the batch.
- (b) Accept the batch as **raw dicts** and validate each event individually, collecting per-event errors.
- For dedup: (c) Postgres `ON CONFLICT` upsert vs (d) a portable "query-existing + insert-new + retry"
  that also works on SQLite.

**What the AI suggested.** It flagged that (a) is cleaner but makes the whole batch 422 on a single bad
event — breaking the spec's _partial success_ — and recommended (b) with idempotent dedup keyed on
`event_id`. It also caught that our two services both had a top-level package named `app`, which collided
on the test path and made the API **untestable**; it proposed renaming the API package to `shelfsense_api`.

**Decision.** **(b) raw-dict per-event validation** (≤500, partial success → `errors[]`; idempotent by
`event_id`) with **(d) portable dedup**; metrics/funnel are **thin adapters over pure
`shelfsense_common/analytics.py`** (reusing the 2.5 conversion engine); and we **renamed the API package**
so the whole surface is covered by FastAPI TestClient integration tests on SQLite.

**Why.** Resilience and idempotency are what a reviewer actually tests; keeping the logic pure and the
handlers thin means the same functions power the API, the Prometheus gauges, and the unit tests — numbers
can't diverge. The rename fixed a real latent bug and unblocked testing the highest-weighted bucket.

**Trade-off / when we'd revisit.** Raw-dict validation is slightly more code than a typed body, and the
portable dedup does an extra read vs a native upsert — both cheap at this scale. At very high ingest
volumes we'd switch to a batched `ON CONFLICT` upsert behind the same idempotent contract.

---

## Decision 6 — Anomalies & health: honest dormancy over fabricated alerts

**Context.** The spec asks for anomaly detection (queue spike, **conversion drop vs a 7-day average**,
**dead zone with no visits for 30 min**) and a `/health` feed-freshness check. But our data is a single
**2-minute clip** from **10-Apr-2026**: there is no 7-day history, no 30-minute window, and the recording
is two months old. A naive implementation would either fabricate baselines or always read "stale".

**Options considered.**

- (a) Fire the alerts anyway against invented baselines / wall-clock time — looks feature-complete.
- (b) Omit the checks we can't fully evaluate — honest but loses graded features.
- (c) Build every check correctly, but have the ones the data can't support **stand down with an INFO
  reason**, and make `/health` freshness **recording-relative** (vs the latest event) with a strict toggle.

**What the AI suggested.** It flagged that (a) trips the integrity cap (outputs not computing from real
input) and misleads a manager, and that an always-red `/health` hurts the demo. It recommended (c): a
documented config baseline for conversion-drop that only fires at trustworthy sample size, a span-guarded
dead-zone check, and recording-relative health with a `HEALTH_STRICT_NOW` switch for live use.

**Decision.** **(c)** — build all three anomalies + `/health`, but let the conversion-drop and dead-zone
checks emit **INFO ("insufficient data / window too short")** on the clip instead of false WARN/CRITICAL;
`/health` measures lag against the latest ingested event by default, real wall-clock when toggled.

**Why.** It keeps every output **computed from real input** and trustworthy, which is exactly what the
integrity check and an on-call engineer both need. The same code fires real alerts the moment a longer or
live feed is connected — we lose nothing by being honest about a 2-minute sample.

**Trade-off / when we'd revisit.** Recording-relative health can hide a genuinely stopped live feed — hence
the strict toggle for production. The conversion baseline is a config target until real multi-day history
lets us compute a rolling 7-day average (then it's a one-line swap, same rule).

## Decision 7 — VLM (Gemini) for staff + zone classification, offline and gate-safe

**Context.** Staff exclusion drives the conversion denominator, and our staff rule was "dark uniform"
(Decision 4) — correct for Store_1's black uniforms but **wrong for Store_2, whose staff wear pink**.
Zones were likewise a hand-mapped label per camera, which doesn't scale to a new store's shelves. The
Problem Statement explicitly invites _"LLMs/VLMs for zone classification, staff detection, or anything
useful"_ (the Part D / AI-engineering bucket).

**Options considered.**

- (a) Per-store colour rules (add a pink rule for Store_2) — quick, but brittle and re-tuned per store.
- (b) Train a staff/zone classifier — no labels exist; over-engineered for ~7 people.
- (c) Use a **VLM (Gemini Flash)** as an occasional judgment helper — once per person for staff, once
  per product camera for zone — run **only in the offline detection pass**, cached, with the heuristic
  as fallback.

**What the AI suggested.** It recommended (c) but stressed the boundary: the VLM must never touch the
`docker compose up` gate (no key/network at review time), output must compute from the real image
(integrity), and verdicts must be cached + the events committed so the reviewer's run is deterministic.

**Decision.** **(c).** A lazy-imported Gemini client (`detector/app/vlm.py`) classifies **staff vs
customer per `visitor_id`** and **zone per product camera** (entrance/checkout/stockroom stay
role-known), feeding only the existing `is_staff` / `zone_id` fields (schema unchanged). It is **off by
default** (`VLM_ENABLED=false`); when on, ~18 calls cover both stores, all cached. The staff prompt
can include a **store-specific uniform hint** (e.g., "pink shirts"), and the cache key includes that
hint so updated guidance **invalidates stale verdicts**. Missing key/SDK, low confidence, or any
error **falls back to the heuristic**.

The prompts (documented, deterministic at temperature 0):

- _Staff:_ "…Decide whether this person is a STORE EMPLOYEE (staff) or a CUSTOMER… consider uniforms,
  lanyards, aprons, standing behind a counter… reply JSON `{label, confidence, reason}`."
- _Zone:_ "…Identify the PRIMARY retail zone this camera covers from the shelves/products/signage…
  choose one of `[skincare_aisle, makeup_aisle, foh_center, accessories]`… reply JSON `{zone,
confidence, reason}`."

**Why.** One signal that generalises across stores (solves Store_2's pink staff) and auto-labels a new
store's zones, while the gate stays a heuristic-only, network-free one-command run. We keep the
heuristic as both fallback and a baseline to compare the VLM against.

**Trade-off / when we'd revisit.** VLM replies are non-deterministic — mitigated by temperature 0 +
caching + committed events. It adds `google-genai` to the detector image (lazy-used). If volume grew,
we'd batch crops per call or distil the verdicts into a small local classifier.

## Decision 8 — Multi-store: a pluggable, auto-discovered store registry

**Context.** The corrected dataset added a second store and renamed/moved the first store's clips. The
detector was hardwired to a single `STORE` constant. The brief: support Store_2 **and** make adding any
future store hassle-free ("drop in footage + details").

**Options considered.**

- (a) Keep one `STORE` and branch on `store_id` throughout — fastest, but scatters store logic and
  isn't pluggable.
- (b) **JSON/YAML store config files** loaded from a directory — very config-driven, but risks the
  acceptance gate (Python packaging must ship the data files; a missed `package-data` stanza → the
  reviewer's `pip install`/`docker compose up` crashes).
- (c) **A Python registry**: one module per store exposing `STORE_CONFIG`, **auto-discovered** at
  import; the detector loops `all_stores()`.

**What the AI suggested.** It flagged that the gate is paramount (option b's packaging risk could fail
the whole submission), and that a `.py` drop-in is _as easy_ as JSON here while shipping automatically
with the package and being Pydantic-validated. It recommended (c), with a `README` recipe and a single
CCTV mount where each store declares its own `clips_dir`.

**Decision.** **(c).** `shelfsense_common.stores` auto-discovers one module per store. `StoreConfig`
gained `clips_dir` (subfolder under one mount) and `clip_start_iso` (per-store synthetic day). The
detector loops every store with its own Re-ID/staff/zone/clip-start; analytics + API are per-store.
**Adding a store = drop `stores/<id>.py` + a clips folder** — no edits to the loop, analytics, API, or
compose. Store_2 (ST1009) is the first store onboarded this way.

**Why.** It makes "a new store arrives" a config drop-in (open/closed), keeps the gate robust (pure
Python ships automatically), and preserves the calibration rationale inline. The registry is a pure,
deterministic function of the files present — trivially testable.

**Trade-off / when we'd revisit.** Store_2's calibration is approximate (no ground truth) and it has no
POS (conversion N/A) — surfaced as assumptions, not hidden. If non-engineers ever need to add stores,
we'd add an optional JSON-config loader on top (env-pointed dir), keeping the bundled Python defaults as
the gate-safe fallback.
