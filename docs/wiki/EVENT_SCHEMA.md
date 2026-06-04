# EVENT SCHEMA

> The contract the detection layer **emits** and the API **ingests**. This is the **PDF page-5
> "Required Output Schema"** from [[SPEC]] — schema compliance is graded (Part A). Pydantic models are
> canonical; this doc mirrors them for humans. Definitions of the behaviours live in [[BUSINESS_RULES]].
>
> **Note (ADR-0005):** this replaces the earlier internal `detection.created`/`track.updated`
> envelope design. Low-level detector→tracker data may stay internal, but the **emitted/ingested
> event is the flat behavioural schema below**.
>
> ✅ **DECISION (2026-06-04, user, ADR-0040 — supersedes ADR-0024 D1): keep the flat page-5 top-level
> schema AND carry the delivered `sample_events.jsonl` richer fields as a `metadata` *superset*.** The
> page-5 flat object stays exactly as the PDF prints it (acceptance gate + Part-A schema-compliance safe);
> the sample's extra signals (zone semantics, groups, demographics, queue analytics, hotspots) are added
> under `metadata` — the schema's own extension point — so every event is a strict superset of both
> schemas. Demographics are **VLM-predicted** (gender + a coarse age band) from body/clothing/hair —
> the faces are blurred, so they are *predictions* with confidence, left `null` where the model is unsure
> (`is_face_hidden=true` always; exact `age_pred` stays null). Input-derived, never fabricated. See
> [[DECISIONS]] ADR-0040.

## Event object (flat)

```json
{
  "event_id": "uuid-v4",                 // globally unique — the idempotency/dedup key
  "store_id": "ST1008",
  "camera_id": "CAM3",
  "visitor_id": "VIS_c8a2f1",            // Re-ID token, unique per VISIT session
  "event_type": "ZONE_DWELL",
  "timestamp": "2026-04-10T14:22:10Z",   // ISO-8601 UTC, derived from clip + frame offset
  "zone_id": "makeup_aisle",             // null for ENTRY / EXIT
  "dwell_ms": 8400,                       // duration; 0 for instantaneous events
  "is_staff": false,                      // classified by the pipeline
  "confidence": 0.91,                     // detection confidence — never silently dropped
  "metadata": {
    "queue_depth": null,                  // int; set for BILLING_QUEUE_JOIN
    "sku_zone": "MOISTURISER",            // finer zone/brand label where known
    "session_seq": 5,                     // ordinal of this event within the visitor session
    // --- sample_events.jsonl superset (ADR-0040); derived from real events, never fabricated ---
    "zone_name": "Makeup Aisle",          // human label for zone_id
    "zone_type": "SHELF",                 // SHELF | DISPLAY | BILLING | ENTRANCE | BACK_OF_HOUSE
    "is_revenue_zone": true,              // zone holds sellable product / a till
    "zone_hotspot_x": null,               // pixel coords are not retained in the event stream
    "zone_hotspot_y": null,
    "group_id": null,                     // group entry — null until group detection is enabled
    "group_size": null,
    "gender_pred": "F",                   // VLM prediction from body/clothing (face blurred); null if unsure
    "age_pred": null,                     // exact age not inferable from blurred CCTV -> always null
    "age_bucket": "adult",                // coarse VLM band (child/teen/adult/senior); null if unsure
    "is_face_hidden": true,               // our footage is anonymised (full-face blur)
    "queue_position_at_join": null,       // = queue_depth on BILLING_QUEUE_JOIN
    "wait_seconds": null,                 // derived at analytics time, not carried on the event
    "abandoned": null                     // true on BILLING_QUEUE_ABANDON
  }
}
```

Field rules: `event_id` unique (UUIDv4); `timestamp` UTC ISO-8601; `zone_id` null for ENTRY/EXIT;
`dwell_ms` 0 for instantaneous; **low-confidence events are flagged, not suppressed**.

## Event types (catalogue)

| `event_type` | Emit when | Notes |
|--------------|-----------|-------|
| `ENTRY` | visitor crosses entry threshold inbound | starts a session; assign a new `visitor_id` |
| `EXIT` | crosses entry threshold outbound | closes the session |
| `ZONE_ENTER` | enters a named zone | zone from our zone config |
| `ZONE_EXIT` | leaves a named zone | |
| `ZONE_DWELL` | in a zone continuously ≥30s | re-emit every 30s of continued dwell |
| `BILLING_QUEUE_JOIN` | non-staff visitor enters the checkout zone (CAM5) | `metadata.queue_depth` = customers in zone incl. joiner (Slice 2.5) |
| `BILLING_QUEUE_ABANDON` | billing visitor with no POS sale following | **derived** in conversion.py (needs POS), not emitted by the detector |
| `REENTRY` | same `visitor_id` seen after a prior `EXIT` | Re-ID must catch this (not a 2nd ENTRY) |

## visitor_id (Re-ID)
A token unique **per visit session**, assigned to a tracked customer on **first detection in a customer
area** — not only at `ENTRY`, because on short clips most shoppers are already inside (ADR-0007). It
survives short occlusion (within-camera tracking) and track fragmentation (a per-camera **motion
tracklet-stitch** re-links a person split front/back into one id, ADR-0037), is **deduplicated across
overlapping cameras** (CAM1/CAM2/CAM3, appearance Re-ID as the cross-camera fallback, Slice 2.4), and a
returning shopper produces `REENTRY` under the **same** `visitor_id` —
never a fresh `ENTRY`. **Unique visitors = distinct `visitor_id`s** (the conversion denominator). See
[[EDGE_CASES]], [[BUSINESS_RULES]].

## The provided `sample_events.jsonl` (richer — adopted as a `metadata` superset, ADR-0040)

The corrected dataset ships 13 example events ([[GROUND_TRUTH]] §5) from a sample store (`store_1076`,
Mumbai) "to help you validate your detection layer." Its schema **differs from the flat one above** and is
**internally inconsistent** across event types. Three shapes:

| Group | Key id fields | Time field | Extra fields beyond ours |
|-------|---------------|-----------|--------------------------|
| `entry` / `exit` (lowercase) | `id_token`, `store_code` | `event_timestamp` | **`gender_pred`, `age_pred`, `age_bucket`, `is_face_hidden`, `group_id`, `group_size`** |
| `zone_entered` / `zone_exited` | `track_id`, `store_id` | `event_time` | **`zone_name`, `zone_type` (SHELF/DISPLAY/BILLING), `is_revenue_zone`, `zone_hotspot_x/y`**, `gender`, `age` |
| `queue_completed` / `queue_abandoned` | `queue_event_id`, `track_id` | `queue_join_ts`/`served_ts`/`exit_ts` | **`wait_seconds`, `queue_position_at_join`, `abandoned`**, hotspot, demographics |

**Conflicts with our schema:** lowercase vs UPPERCASE `event_type`; `id_token`/`track_id` vs `visitor_id`;
`event_timestamp`/`event_time` vs `timestamp`; `store_code` vs `store_id`; no `event_id`/`confidence`/
`dwell_ms`/`metadata` on several; queue modelled as one completed/abandoned record (with join/serve/exit
timestamps) rather than our `BILLING_QUEUE_JOIN` + derived-`ABANDON` pair.

**New signals it implies we don't yet produce:** demographics (gender/age/bucket), face-hidden flag,
explicit groups (`group_id`/`group_size`), zone semantics (`zone_type`/`is_revenue_zone`), spatial
hotspots, and richer queue analytics (wait time, queue position).

**The decision — ✅ ADR-0040 (2026-06-04, user): option (c), enrich ours into a superset** (supersedes the
earlier ADR-0024 D1, which had chosen (a)). We **keep the flat page-5 top-level** and add the sample's
richer fields under `metadata`:
- (a) *Keep the flat page-5 schema only* — was the prior choice; superseded. The top-level is still page-5
  (gate + schema-compliance safe), but `metadata` now carries the sample's signals.
- (b) *Replace with the sample's exact shapes* — **rejected:** the sample is internally inconsistent (3
  shapes), drops `ZONE_DWELL`/`REENTRY`/`BILLING_QUEUE_JOIN`, and risks the gate/schema-compliance points.
- (c) **Enrich ours into a superset** — **chosen.** `zone_name`/`zone_type`/`is_revenue_zone`/hotspots,
  `group_id`/`group_size`, demographics, and queue analytics are added under `metadata`. How each is filled
  HONESTLY (no fabrication):
  - **Zone descriptors** — derived deterministically from `zone_id` (`zone_descriptor`, `contracts/zones.py`).
  - **`wait_seconds`** — the visitor's real checkout-zone dwell; **`queue_position_at_join`** = `queue_depth`.
  - **`group_id`/`group_size`** — co-entry heuristic (ENTRY crossings within 4 s ⇒ one arriving group).
  - **`zone_hotspot_x/y`** — the visitor's representative foot-point (pixel coords) on a zone event.
  - **`gender_pred` + `age_bucket`** — a **VLM prediction** (Groq Llama-4 Scout) from body/clothing/hair,
    with confidence, `null` where unsure; exact `age_pred` stays null (not inferable from blurred faces),
    `is_face_hidden=true`. Harvested per visitor and **merged by `visitor_id`** into the committed events
    (`scripts/enrich_events_schema.py` + a sidecar) so the validated counts never change.
  One helper (`build_event_metadata`) gives the detector and the offline transform identical metadata.

## Status
Prescribed schema adopted (ADR-0005) and **implemented** as `BehaviorEvent` in
`shelfsense_common/contracts/behavior.py`. Emitted from real footage to JSONL by the detector:
`ENTRY`/`EXIT` on the entrance door; `ZONE_ENTER`/`DWELL`/`EXIT` on **all** customer cameras (entrance
contributes interior visitors too since ADR-0029); `REENTRY` + `is_staff` (per-store uniform colour /
optional VLM, ADR-0009/0032/0027) + `visitor_id` made stable within a camera by **motion tracklet-stitching**
(ADR-0037) and **cross-camera de-duplicated** via appearance Re-ID as the fallback (2.4, ADR-0008/0036); **`BILLING_QUEUE_JOIN` with
`queue_depth`** on CAM5 (2.5, ADR-0012; `BILLING_QUEUE_ABANDON` derived in conversion). Validators
enforce a tz-aware UTC timestamp and `zone_id=None` for ENTRY/EXIT.

**Ingested + persisted (Slice 2.6, ADR-0013):** `POST /events/ingest` validates each event against this
model (including the ADR-0040 superset `metadata`) and stores it in the `behavior_events` table keyed by
`event_id` (idempotent dedup). `metadata` is flattened on persistence to the columns the metrics need
(`queue_depth`); the superset fields travel on the **emitted event + ingest contract** (what reviewers
inspect in `data/events/behavior.jsonl`) — they are not promoted to columns because no read endpoint needs
them and the metrics compute from the persisted columns. The other flat fields map 1:1. Metrics/funnel are
recomputed from these rows on read (`shelfsense_common/analytics.py`).
