# EVENT SCHEMA

> The contract the detection layer **emits** and the API **ingests**. This is the prescribed
> schema from [[SPEC]] — schema compliance is graded (Part A). Pydantic models are canonical;
> this doc mirrors them for humans. Definitions of the behaviours live in [[BUSINESS_RULES]].
>
> **Note (ADR-0005):** this replaces the earlier internal `detection.created`/`track.updated`
> envelope design. Low-level detector→tracker data may stay internal, but the **emitted/ingested
> event is the flat behavioural schema below**.

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
    "session_seq": 5                      // ordinal of this event within the visitor session
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
survives short occlusion (within-camera tracking), is **deduplicated across overlapping cameras**
(CAM1/CAM2/CAM3, Slice 2.4), and a returning shopper produces `REENTRY` under the **same** `visitor_id` —
never a fresh `ENTRY`. **Unique visitors = distinct `visitor_id`s** (the conversion denominator). See
[[EDGE_CASES]], [[BUSINESS_RULES]].

## Status
Prescribed schema adopted (ADR-0005) and **implemented** as `BehaviorEvent` in
`shelfsense_common/contracts/behavior.py`. Emitted from real footage to JSONL by the detector:
`ENTRY`/`EXIT` on the CAM3 door (2.2, footfall-only since 2.4b/ADR-0011); `ZONE_ENTER`/`DWELL`/`EXIT`
on the shopping-floor cameras (2.3); `REENTRY` + `is_staff` (dark-uniform, ADR-0009) + **cross-camera
de-duplicated** `visitor_id` via appearance Re-ID (2.4, ADR-0008); **`BILLING_QUEUE_JOIN` with
`queue_depth`** on CAM5 (2.5, ADR-0012; `BILLING_QUEUE_ABANDON` derived in conversion). Validators
enforce a tz-aware UTC timestamp and `zone_id=None` for ENTRY/EXIT.

**Ingested + persisted (Slice 2.6, ADR-0013):** `POST /events/ingest` validates each event against this
model and stores it in the `behavior_events` table keyed by `event_id` (idempotent dedup). `metadata`
is flattened on persistence to the columns the metrics need (`queue_depth`); the other flat fields map
1:1. Metrics/funnel are recomputed from these rows on read (`shelfsense_common/analytics.py`).
