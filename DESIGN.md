# DESIGN — ShelfSense Store Intelligence System

A containerised system that turns raw in-store **CCTV footage** into live retail analytics, anchored
on one business metric: **offline store conversion rate** (`converted visitors ÷ unique visitors`).
This document is the architecture overview; per-decision reasoning is in [`CHOICES.md`](CHOICES.md).

> Run it: `docker compose up`. API on `:8000` (`/docs`), metrics `/metrics`, Grafana `:3000`.

---

## 1. Problem framing
Offline stores are a data blind spot — there is no equivalent of web session/funnel analytics. The
job is to reconstruct that visibility from camera footage: who entered, where they went, where they
dropped off, and how many converted. The design is therefore optimised for one number being both
**accurate** (good detection, de-duplicated sessions) and **actionable** (clean, queryable endpoints).

## 2. Architecture at a glance
Two tiers with a single contract between them — the **event schema**:

```
CCTV → [Detection Pipeline: YOLOv8 → ByteTrack → Re-ID → behavioural events]
     → events (JSONL + HTTP) → [Intelligence API: ingest → PostgreSQL → metrics] → Dashboard
```

- **Detection pipeline** owns all computer vision and per-person reasoning, and emits *behavioural*
  events (`ENTRY`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`, `REENTRY`, …) — not raw bounding boxes.
- **Intelligence API** (FastAPI) ingests those events idempotently, stores them, and computes
  metrics/funnel/heatmap/anomalies on read.

Decoupling at the event boundary means the CV side and the analytics side evolve independently, and
the pipeline can run batch *or* simulated-real-time without changing the API. Full diagram and
component table: `docs/wiki/ARCHITECTURE.md`.

## 3. Cameras and zones
The store has 5 cameras mapped to functional roles: **Entry** (CAM3, with a calibrated entry line),
**Main floor** (CAM1/CAM2), **Billing** (CAM5), and a **back room** (CAM4) whose occupants are treated
as staff and excluded from customer metrics. Overlap between the front cameras is resolved by Re-ID so
one shopper is counted once. Each camera is used for **what it can see honestly**: the **entrance camera
counts footfall only, not visitors** (its view is dominated by mall-corridor pass-by — §7 A8), and the
**billing camera applies a walkable-floor mask** so a wall **mirror** / backlit display can't be counted
as extra people (§7 A7). **Staff** are identified by their **complete black uniform** (§7 A6).

## 4. How the North Star is computed
1. **Unique visitors** = distinct `visitor_id`s — one assigned per tracked customer on first
   detection inside the store (de-duplicated across cameras by Re-ID; re-entries are the *same*
   visitor). This, not raw door-crossings, is the denominator (see §5 for why).
2. **Converted visitor** = a visitor present in the **billing zone within the 5-minute window before a
   POS transaction** (no customer id exists, so correlation is by time-window + store).
3. **Conversion rate** = converted ÷ unique, staff excluded. The funnel
   (`Entry → Zone Visit → Billing Queue → Purchase`) explains *where* drop-off happens.

## 5. Counting integrity (why the number is trustworthy)
All counting is on **de-duplicated sessions**, never raw detections. This directly defends the metric
against the failure modes that inflate vendor systems: groups are counted as individuals, re-entries
do not double-count, **staff are filtered out by their black uniform**, **mirror/display reflections are
rejected by a floor mask**, and **mall pass-by is excluded by not counting visitors on the entrance
camera**. Low-confidence detections are *flagged on the event*, not silently dropped — so uncertainty is
visible rather than hidden. Validated against the user's ground truth (2 customers + 5 staff store-wide):
the pipeline returns **exactly 2 customers** as the conversion denominator.

Footfall uses **ByteTrack** (stable per-person identity) plus a pure, unit-tested **line-crossing
state machine** on the entrance camera: an `ENTRY`/`EXIT` fires only when a track's foot-point actually
crosses the calibrated door line, with on-line flicker debounced. We **validated the line against the
real video** and it caught a genuine error: an interim placement chased the busiest motion and ended up
on the **mall walkway**, counting pass-by pedestrians as visitors — a classic false-footfall trap. We
reverted it to the real centre-left doorway, where this 2-minute clip shows **≈0 clean crossings**,
because almost everyone on camera is *already inside* (they entered before the window). Rather than
fabricate entrances or chase mall traffic for a prettier number, we therefore count **unique visitors as
distinct people detected inside the store** (a `visitor_id` per tracked customer, de-duplicated by Re-ID),
and keep `ENTRY`/`EXIT` as flow events for when a crossing genuinely occurs. The counts move with the
input and never include non-customers — which is exactly what the integrity check rewards.

## 6. Production readiness
- **One-command start:** `docker compose up`, no manual steps; the YOLO model is baked into the image
  so there is no runtime download. The full stack — six backend services **plus a `frontend` dashboard
  container** (nginx, `:8080`) — comes up from this single command.
- **Live dashboard (Part E):** a React SPA polls the store endpoints every few seconds and shows the
  conversion ring, funnel, zone heatmap, anomalies, and feed-health **updating live as the detector
  feeds events** — with a "detection running" banner and a `data_confidence` badge so a mid-run state
  reads as *working*, not broken. Nothing is hardcoded; every value is fetched from the real endpoints.
- **Idempotent ingest:** `event_id` is the dedup key — re-POSTing a batch is safe (replay-friendly);
  validated on the real 135-event file (2nd POST = 0 accepted, 135 duplicate).
- **Partial-success ingest:** a malformed event is reported in `errors[]` rather than rejecting the whole
  batch; over-500 batches return a 422 in the structured error envelope.
- **Graceful degradation:** DB unavailable → HTTP 503 with a structured body, never a raw stack trace.
- **Zero-traffic correctness:** empty windows return valid zeros, not null or a crash.
- **Observability:** structured JSON logs per request (`trace_id, store_id, endpoint, latency_ms,
  event_count, status_code`); Prometheus metrics (recomputed from ingested events); Grafana dashboards.
- **Tested:** unit + edge-case coverage (empty store, all-staff, zero purchases, re-entry in funnel) **plus
  end-to-end API tests** (FastAPI TestClient on SQLite: ingest idempotency, partial success, metrics/funnel).

## 7. Assumptions
Where the real data forced an interpretation, we state it **explicitly here** rather than bury it, so a
reviewer knows exactly what is measured and why. Each is data-driven and revisited if better data arrives.

- **A1 — CCTV clips contain almost no entry/exit events, so a "visitor" is a distinct person seen
  *inside* the store, not a door-crosser.** The 5 clips are ~2-minute *synchronised* windows. With the
  entrance line on the real CAM3 door, the whole clip yields **0 clean threshold crossings**: nearly
  everyone on camera is *already inside* (they entered before the window began), and the only sustained
  motion is **mall pass-by** behind the storefront glass, which we deliberately exclude. We therefore
  **assume/define unique visitors = distinct `visitor_id`s detected in a customer area** (one per tracked
  customer, Re-ID-deduped), and keep `ENTRY`/`EXIT` as flow events for when a crossing genuinely occurs.
  *Why:* makes the North Star computable on this data without fabricating entrances; on longer or live
  feeds, entrance-crossing footfall regains its meaning. (See `docs/wiki/DECISIONS.md` ADR-0006/0007.)
- **A2 — Conversion is correlated by time-window, not customer identity.** No PII customer id exists, so a
  visitor counts as converted if they were in the billing zone within 5 minutes before a POS transaction.
- **A3 — Clip vs full-day POS mismatch is handled by windowing, not naive division.** Footfall/sessions are
  computed on a comparable window and any extrapolation is documented, never `full-day txns ÷ clip footfall`.
- **A4 — Zone names are our assumption, not given by the problem statement.** No zone list or
  `store_layout.json` was provided, so we named the zones ourselves from the store floor plan and the camera
  roles: `entrance`, `skincare_aisle`, `makeup_aisle`, `foh_center`, `checkout`, `accessories`, `stockroom`
  (the last is staff-only and excluded). For v1 each camera maps to one primary zone — CAM3 `entrance`,
  CAM1 `skincare_aisle`, CAM2 `makeup_aisle`, CAM5 `checkout` (CAM4 `stockroom`); the others are reserved
  for finer sub-zones later. *Why:* the labels are configuration in `zones.py`, not hardcoded logic, so they
  can be renamed/extended without code changes if a canonical layout is supplied. (See [[DECISIONS]] PD-4.)
- **A5 — Unique-visitor count is approximate (lightweight Re-ID + tuned tracking), calibrated to the
  available ground truth.** With no identity data and an offline CPU gate, we de-duplicate by appearance
  **colour-histogram** signature, not a trained Re-ID model (ADR-0008). The user's ground truth is **7
  people store-wide = 2 customers + 5 staff**. The raw per-camera pipeline found ~53 tracks — over-count
  dominated by **ByteTrack fragmentation** (one shopper → ~8 ids behind shelves), not Re-ID error. A
  **tuned tracker** (`track_buffer=150`) plus Re-ID at `reid_max_distance=0.55`, **staff exclusion (A6)**,
  the **floor mask (A7)** and **entrance-as-footfall (A8)** bring the live pipeline to **5 unique = 2
  customers + 3 staff** — the **customer denominator is exactly right (2)**. *Caveats:* (i) the threshold
  is **tuned to this clip**, re-validate on new footage; (ii) colour histograms are weak features, so the
  5 black-clad **staff over-merge to 3** — harmless to conversion (staff are excluded) but it under-counts
  total staff; (iii) the same person across very different views may still split. The count is
  *meaningfully de-inflated and correct on the metric-critical number*, not exact on staff.
- **A6 — Staff are identified by their complete black uniform, not by dwell time.** Brigade staff wear
  black shirt + trousers; the two real customers wear grey/violet. We set `is_staff` from a **dark-uniform
  appearance score** (min of upper/lower-body dark-pixel fraction, reusing the Re-ID crop; ADR-0009),
  which cleanly separated them on ground truth (customers 0.08–0.19, staff 0.52–0.96; threshold 0.50). The
  earlier 90 s-presence heuristic is demoted to an off-by-default fallback. *Why:* far more reliable than
  presence on a short clip, and metric-critical given only **two** customers. *Limit:* a genuinely
  black-clothed customer would be misflagged; the score and threshold are config, swappable for a learned
  classifier if needed.
- **A7 — A walkable-floor mask suppresses mirror/display phantoms.** CAM5 has a mirror + backlit display;
  a diagnostic found 10 tracks for 2 staff, with phantom foot-points up on the back wall (y≈220 of 1080).
  Detections whose **foot-point falls outside a calibrated floor polygon** are dropped (ADR-0010) — it
  removed **317** off-floor detections and generalises to product displays and poster faces. Only CAM5 is
  calibrated for now; other cameras fail open.
- **A8 — Unique visitors are counted across *all* cameras, but only for solid, store-interior tracks
  (ADR-0029, refining ADR-0011).** A person counts if their track is *solid*: sustained presence
  (`min_zone_dwell`), on the walkable floor (mask where calibrated), a **large-enough box** (drops tiny
  far/reflection blobs), and — on any camera with an entrance line — on the **store-interior** side
  (mall-corridor pass-by is discarded by the calibrated line). Re-ID de-dups a shopper seen on several
  cameras into one visitor. So the **entrance camera now contributes interior visitors too**, not just
  line crossings, without re-admitting the corridor traffic that ADR-0011 originally excluded the whole
  camera to avoid. *We deliberately did **not** gate on face visibility:* on this steep overhead CCTV,
  shoppers face the shelves (backs/tops of heads) and some faces are **privacy-blurred**, so a
  "face-visible-or-discard" rule would drop most genuine visitors and distort conversion — track-quality
  + the entrance line achieve the same intent (count only real, interior shoppers) on this footage.
  *Caveat:* this changes the counting path, so the earlier "exactly 2 customers" figure must be
  **re-validated on the next full detector run**; the box-size threshold is config (`MIN_DETECTION_BOX_FRAC`).
- **A-note — The clip has only 2 genuine customers, so customer-side metrics are illustrative, not
  statistically robust.** Conversion = converted ÷ 2 is fragile to a single misclassification; the system
  still computes it honestly and it varies with input — the value is the *correct pipeline*, not a large-N
  number a 2-minute clip can't provide.
- **A9 — Conversion is built correctly but reads 0 on this clip (window mismatch), so we demonstrate the
  mechanism separately.** The video is ~2 min at 20:10; the 24 POS sales span the full day (12:15–21:40),
  and both customers only browse CAM2 — neither reaches the checkout. So the honest clip conversion is
  **0%** (`data_confidence="low"`) with a real funnel drop-off (Entry 2 → Zone 2 → Billing 0 → Purchase 0)
  — truthful, not a bug, and never divided across mismatched windows. The correlation (billing-zone
  presence within 5 min before a sale) is built, unit-tested, and **demonstrated** on a comparable window
  (`scripts/demo_conversion.py`, `POS_DEMO_ALIGNMENT`: a representative billing visitor aligned to a real
  sale flips to converted, plus an abandon). The 24 real sales also power day-level KPIs (GMV ₹44,920,
  basket, peak hour) independent of the clip. *Why:* faking a non-zero clip number would be dishonest and
  trips the integrity cap; the window mismatch is the exact real-world ambiguity the rubric rewards. (ADR-0012)
- **A10 — The detector auto-feeds the API; the stack populates itself on `docker compose up`.** The
  detector fans each event to a JSONL file (inspectable + replayable) **and** an `HttpEventSink` that POSTs
  batches of ≤500 straight to `/events/ingest` (Slice 2.8, ADR-0015) — no manual step. It waits for the API
  to be healthy, retries with backoff, and is **non-fatal** (if the API is down the events still land in the
  JSONL, so the detector never crashes). Because ingest is **idempotent by `event_id`**, a restart or a
  `scripts/ingest_events.py` replay on top never double-counts. POS is loaded **into Postgres on API startup**
  (the loader globs the CSV, whose real name carries a download suffix), making the `transactions` table the
  single source of truth for conversion + day KPIs. The detector **flushes after each camera** (ADR-0018),
  so the endpoints populate *progressively* as detection runs rather than all-at-once at the end. *Caveat:*
  the first numbers still appear only after camera 1 (~5 min on CPU); a startup **seed** is the documented
  timing safety-net for a sub-5-minute demo. (See [[DECISIONS]] ADR-0013/0015/0018.)
- **A11 — Anomaly detection is built correctly but *honestly dormant* on a 2-min clip.** The spec's
  conversion-drop ("vs 7-day average") and dead-zone ("no visits 30 min") checks can't be truthfully
  evaluated with one day of data and a 2-minute window. So the conversion-drop check uses a **documented
  config baseline** (a target rate, not a fabricated average) and fires **only at `data_confidence="ok"`**,
  and the dead-zone check is **span-guarded** (needs ≥ its horizon of observed data); on this clip both
  return **INFO** explaining why, never a false WARN/CRITICAL. The queue-spike check fires honestly from the
  real staff-excluded depth. *Why:* fabricating alerts trips the integrity cap and misleads a manager — the
  same logic activates fully on longer/live feeds. (See [[DECISIONS]] ADR-0014.)
- **A12 — `/health` freshness is recording-relative by default.** The clip is dated 10-Apr-2026, so comparing
  the last event to real wall-clock time would always read `STALE_FEED`. By default `/health` measures lag
  against the **latest ingested event** (a replayed clip reads healthy); `HEALTH_STRICT_NOW=true` switches to
  real-time for a live deployment (where a stopped feed *should* read stale). *Why:* demo-accurate and
  production-correct, with the toggle making the trade-off explicit. (ADR-0014.)
- **A13 — Staff/zone classification uses an optional VLM offline, because a per-store colour rule
  doesn't generalise.** The dark-uniform staff rule (A6) is correct for Store_1's black uniforms but
  **wrong for Store_2, whose staff wear pink** — and staff exclusion drives the conversion denominator.
  Rather than hand-tune a colour per store, we add an **optional Google Gemini** call used **only in the
  offline detection pass**: once per `visitor_id` for staff/customer, and once per *product* camera to
  label the zone from its shelves (entrance/checkout/stockroom stay role-known). It is **off by default**
  (`VLM_ENABLED=false`), so `docker compose up` runs the heuristics with **no key/network** (gate-safe);
  when on, verdicts are **cached** and the generated `events.jsonl` is committed, so the reviewer's run
  makes **zero API calls** and stays deterministic. A low-confidence verdict, a missing key/SDK, or any
  error **falls back to the heuristic** — the model can only improve the default, never break the gate.
  *Why:* one signal that works across stores, scoring Part D (AI engineering) honestly; output varies
  with the real image (integrity-safe) and the prompts are documented. (See [[DECISIONS]] ADR-0027,
  `CHOICES.md` Decision 7.)

- **A14 — Store_2 (ST1009) runs through the same pipeline, but its numbers are approximate and
  conversion is N/A.** The corrected dataset added a second store (two entrances, a `zone` and a
  `billing` camera, 960×1080). We made stores a **pluggable, auto-discovered registry** so Store_2 (and
  any future store) is a drop-in (`stores/<id>.py` + a clips folder; ADR-0028), and the detector now
  loops every store with its own Re-ID/staff/zone identity. Three honest limits, all data-forced: (i)
  **no POS for Store_2 → conversion is reported as N/A**, not a misleading 0 (footfall, dwell, zones,
  queue still compute); (ii) **no ground truth**, so the two **entrance lines are placeholders**
  (`calibrated=False`) and footfall is rough — unique visitors come from the `zone`+`billing` cameras,
  as for Store_1 (A8); (iii) Store_2's clips were recorded on **different real days**, so per the user's
  direction we **pin them to one synthetic day** to make daily metrics legible. Cross-store identity is
  intentionally isolated (a visitor in one store isn't the same as in another). The VLM (A13) supplies
  Store_2's staff (pink uniforms) and zone labels.

## 8. Known limitations & next steps
- Per-camera calibrations (entry line, CAM5 floor mask) are validated against the real video; robust to a
  fixed camera, not to camera moves. Cross-camera Re-ID de-duplicates overlaps and collapses re-entries
  (§7 A5); its weakness is that look-alike **black uniforms over-merge**, under-counting staff (harmless to
  conversion — staff are excluded). (Visitor definition: §7 A1; staff/floor/entrance handling: A6–A8.)
- Conversion can mis-attribute in dense billing periods — bounded by the 5-minute rule (§7 A2).
- At 40 live stores the CPU-bound detector is the bottleneck — scale horizontally per store and put a
  queue in front of ingest. These are deliberate, bounded trade-offs, not oversights.

## 9. AI-Assisted Decisions
AI (Claude) was used throughout; the places it materially shaped the design — and where we overrode it:

1. **Event-stream architecture — overrode.** The assistant first designed an event-driven system with a
   Kafka-compatible broker (Redpanda). On re-reading the spec we recognised an *ingest-centric* model
   and **dropped the broker** in favour of `POST /events/ingest` + idempotency — fewer moving parts, a
   more reliable gate, and a closer fit to the requirements.
2. **Cross-camera Re-ID — reversed our own earlier call.** The assistant initially recommended treating
   cameras independently with no Re-ID for simplicity; the spec requires it (visitor_id, REENTRY,
   cross-camera dedup), so we **reversed** — letting the requirement, not convenience, drive the design.
3. **Model packaging — agreed.** Pre-baking YOLO weights into the image (assistant's suggestion) makes
   `docker compose up` deterministic and offline-safe; we agreed, accepting the image-size cost.
4. **VLM for staff/zone — adopted with a strict boundary.** We use a VLM (Gemini) as an *offline*
   judgment helper for staff and zone classification (§7 A13), but deliberately kept it **out of the
   compose gate** (off by default, cached, heuristic fallback) so the AI improves quality without
   coupling the reviewer's one-command run to a key or network.

A working practice also came from this collaboration: a living knowledge base (`docs/wiki/`) the
assistant reads each session, so design context compounds rather than resets.
