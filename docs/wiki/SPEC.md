# SPEC — authoritative requirements (from the Problem Statement)

> Digest of `docs/raw/Purplle_Tech_Challenge_PS3f02573.pdf`. This is the **authoritative spec for WHAT to
> build** (schema, endpoints, scoring). Where this and earlier assumptions disagree, **this wins**. Data
> facts live in [[GROUND_TRUTH]].
>
> ⚠️ **Corrected dataset (2026-06-02). The old "print mistake" theory is RETIRED — it was wrong.** The
> earlier wiki claimed the PDF's "Apex Retail" dataset description was a print error and the single Brigade
> store was final. The team has since delivered a **corrected dataset** ([[GROUND_TRUTH]] §0), confirming the
> Apex framing is real. What's now true:
> - **The PDF is authoritative as written.** Build to its schema/endpoints/scoring/edge-cases/North-Star.
> - **Delivered data still differs from the PDF's *described* dataset**, but far less than before: **2 stores**
>   (not 5), **4 cams each** (role-named), **~2-min clips** (not 20-min), **layout PNGs** (no `store_layout.json`),
>   a **7-column POS sample** (not the documented `transaction_id`/`basket_value_inr` shape), **13 sample events**
>   (not 200), and **no `assertions.py`**. So we still **self-derive zones** (from the PNGs) and **self-validate**.
> - **`sample_events.jsonl` now EXISTS** and uses a **richer schema that conflicts with the PDF's page-5
>   "Required Output Schema"** (the flat schema our code emits). **Decided (ADR-0024 D1): keep the flat
>   page-5 schema; the sample is informational only** — see "REQUIRED event schema" below, [[EVENT_SCHEMA]],
>   and [[DECISIONS]] ADR-0024.
> - **`store_id = "ST1008"`** in the POS (Store_1). Store_2 has no POS and no assigned store_id yet.

## North Star
**Offline Store Conversion Rate = purchasers ÷ unique visitors** (per session window). Every
component either makes this number more *accurate* (detection) or more *actionable* (API).

## Scoring (100 + 10 bonus) — matches the rubric in [[GROUND_TRUTH]] §3
- **Part A Detection — 30**: entry/exit accuracy (10), staff/re-entry/group handling (10), schema compliance & event quality (10).
- **Part B Intelligence API — 35**: endpoint correctness (20), funnel accuracy & session dedup (10), anomaly detection (5).
- **Part C Production — 20**: containerisation+README gate (5), structured logs+health (5), tests & edge cases (10).
- **Part D AI Engineering — 15**: prompt blocks in tests, DESIGN.md "AI-Assisted Decisions", CHOICES.md (3 decisions).
- **Part E Live Dashboard — +10 bonus**: ≥1 metric live (terminal ok, web higher).
- Parts **A & B weigh most**. Follow-up: 5 questions about *your own code* (async video).

## Acceptance gate (fail any → not scored; 12h fix window)
1. `docker compose up` starts the API — no manual steps beyond `git clone`.
2. README explains how to run the detection pipeline against the clips + where output goes.
3. `POST /events/ingest` accepts events without a 5xx.
4. `GET /stores/{store_id}/metrics` returns valid JSON (spec example uses `STORE_BLR_002`; ours is `ST1008`).
5. `DESIGN.md` and `CHOICES.md` exist and are **>250 words each**.

## Pipeline (4 stages — all ours)
`Raw CCTV → Detection Layer (detect, track, direction, visitor_id) → Event Stream (our schema) → Intelligence API (ingest, metrics, anomalies, endpoints) → Live Dashboard`.

## REQUIRED event schema (the detection layer must emit this)
Flat behavioural events (one object per behaviour), not raw bbox detections:
```json
{
  "event_id": "uuid-v4",                 // globally unique (idempotency key)
  "store_id": "ST1008",
  "camera_id": "CAM3",
  "visitor_id": "VIS_c8a2f1",            // Re-ID token, unique per VISIT session
  "event_type": "ZONE_DWELL",
  "timestamp": "2026-04-10T14:22:10Z",   // ISO-8601 UTC (clip + frame offset)
  "zone_id": "makeup_aisle",             // null for ENTRY/EXIT
  "dwell_ms": 8400,                       // 0 for instantaneous events
  "is_staff": false,                      // model/heuristic classifies
  "confidence": 0.91,                     // do NOT suppress low-confidence — flag them
  "metadata": { "queue_depth": null, "sku_zone": "MOISTURISER", "session_seq": 5 }
}
```
**Event types:** `ENTRY` (start session, new visitor_id) · `EXIT` (close session) · `ZONE_ENTER` ·
`ZONE_EXIT` · `ZONE_DWELL` (every 30s of continuous dwell) · `BILLING_QUEUE_JOIN` (set queue_depth) ·
`BILLING_QUEUE_ABANDON` (left billing before a POS txn) · `REENTRY` (same visitor_id after an EXIT).

> ✅ **Schema tension — DECIDED (ADR-0024 D1).** The above is the PDF's page-5 *Required Output Schema* and the
> gate example uses it — **our code emits exactly this**. But the delivered **`sample_events.jsonl`** uses a
> **different, richer schema** (lowercase event types; `id_token`/`track_id` instead of `visitor_id`;
> `event_timestamp`/`event_time` instead of `timestamp`; plus **demographics** `gender_pred`/`age_pred`/
> `age_bucket`, **`is_face_hidden`**, **groups** `group_id`/`group_size`, **zone metadata** `zone_name`/
> `zone_type`/`is_revenue_zone`/`zone_hotspot_x,y`, and **queue analytics** `queue_join_ts`/`served_ts`/
> `exit_ts`/`wait_seconds`/`queue_position_at_join`/`abandoned`). **We keep the flat page-5 schema** (the
> authoritative, gate-referenced contract) and treat the sample as **informational only** — it is internally
> inconsistent and from a different sample store (`store_1076`), so adopting it is a refactor for no scoring
> gain. See [[EVENT_SCHEMA]], [[GROUND_TRUTH]] §5.

## REQUIRED API endpoints
| Endpoint | Returns | Key requirements |
|---|---|---|
| `POST /events/ingest` | accept batch ≤500; validate, dedup, store | **idempotent by event_id**; partial success on bad events; structured errors |
| `GET /stores/{id}/metrics` | unique visitors, conversion rate, avg dwell/zone, queue depth, abandonment rate | exclude `is_staff`; handle zero-purchase; real-time |
| `GET /stores/{id}/funnel` | Entry→Zone Visit→Billing Queue→Purchase + counts + drop-off% | **session is the unit**; re-entries don't double-count |
| `GET /stores/{id}/heatmap` | zone visit freq + avg dwell, normalised 0–100 | `data_confidence` flag if <20 sessions in window |
| `GET /stores/{id}/anomalies` | queue spike, conversion drop vs 7-day, dead zone (no visits 30 min) | severity INFO/WARN/CRITICAL + `suggested_action` |
| `GET /health` | status, last event ts per store, `STALE_FEED` if >10 min lag | must be accurate (on-call first check) |

## POS correlation rule (conversion)
No customer_id. Correlate by **time window + store**: a visitor present in the **billing zone in
the 5-minute window before a transaction timestamp** counts as a **converted** visitor for that
session. Conversion = converted visitors ÷ unique visitors. (Delivered CSV is 7-col → a **transaction =
distinct `order_time`** (24 of them), `timestamp` from `order_date`+`order_time` (local, no tz),
`basket_value` from summing `total_amount` per timestamp; see [[GROUND_TRUTH]] §2. `pos_loader.py`
has been reworked for this format — ADR-0024/D3.)

## The 7 edge cases (graded under Part A & C)
Group entry (count individuals, not groups) · Staff movement (`is_staff`, exclude) · Re-entry
(REENTRY, not new ENTRY) · Partial occlusion (degrade gracefully; flag low confidence) · Billing
queue buildup (queue depth + abandonment) · Empty store periods (zero-traffic must not crash/null) ·
Camera angle overlap (cross-camera dedup — same person not double-counted).

## Production (Part C)
`docker compose up` only; structured logs per request (`trace_id, store_id, endpoint,
latency_ms, event_count, status_code`); ingest **idempotent** (tested); graceful degradation
(DB down → 503 structured, no stack traces); **test coverage >70%** incl. edge cases; README 5 commands.

## AI Engineering (Part D)
Prompt blocks atop each test file (`# PROMPT:` / `# CHANGES MADE:`); `DESIGN.md` with an
"AI-Assisted Decisions" section (2–3 places an LLM shaped design + agree/override); `CHOICES.md`
with 3 decisions (detection model, event-schema design, one API choice) — options, what AI
suggested, what we chose, why. **Defendable in follow-up questions.**

## FAQ highlights
Python/FastAPI recommended (harness coverage best). Any model. **VLM allowed** (document use).
**SQLite fine**, Postgres fine. Imperfect detection expected — handle uncertainty/edge cases.
Batch **or** streaming (real-time only for Part E bonus).
