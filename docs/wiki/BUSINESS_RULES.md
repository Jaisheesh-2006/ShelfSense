# BUSINESS RULES

> Definitions of every business metric — the contract between analytics output and what
> reviewers expect. Headline metric is **conversion rate**. Facts about the data are in
> [[GROUND_TRUTH]]. Update whenever business logic changes. `(TBD)` = pending confirmation.

## Core entities

- **Track** — one tracked person across frames (per camera), a `track_id`.
- **Session** — one customer visit; bounded by entry and exit. The unit for funnel/conversion
  (sessions, **never raw detections**, to avoid double counting — rubric-critical).
- **Zone** — a named store region from the floor plan ([[GROUND_TRUTH]] §4): entrance, skincare_aisle,
  makeup_aisle, foh_center, checkout, accessories, stockroom (staff).
- **Visitor** — one visit session, identified by a `visitor_id` (Re-ID). Re-entries keep the same id.
- **Transaction** — one POS order from the CSV (`distinct order_id`). 24 on 10-Apr-2026.

## Headline metric — Conversion rate (North Star)

- **Definition (per [[SPEC]]):** `conversion_rate = converted visitors ÷ unique visitors` over a
  session window. Staff excluded.
- **Converted visitor (POS correlation rule):** a visitor whose session was in the **billing zone
  within the 5-minute window before a POS transaction timestamp** (same store) counts as converted.
  No `customer_id` — correlation is **time-window + store** only.
- **unique visitors:** distinct `visitor_id`s (Re-ID; re-entries are the *same* visitor, not new).
- **POS source:** Brigade CSV → `transaction_id` (invoice/order), `timestamp` (order_date+order_time),
  `basket_value` (order total). 24 transactions on 10-Apr ([[GROUND_TRUTH]] §2).
- **⚠ Window caveat:** clips (~2 min) vs CSV (full day) differ — compute on a comparable/representative
  window and document it (PD-3 in [[DECISIONS]]). Don't divide mismatched windows.

## Footfall (entry/exit)

- **Definition:** count of sessions entering the store in a window.
- **Rule:** a session counts when its track crosses the **entrance line** inward (line-crossing
  on the entrance camera). Exits counted on outward crossing.
- **Must handle (Detection bucket, 30 marks):** re-entry, staff, group entry — see [[EDGE_CASES]].

## Customer session

- **Start:** first detection of the track after entry.
- **End:** track lost > `session_timeout` OR outward exit crossing.
- **Re-entry rule:** a returning visitor (matched by Re-ID) keeps the **same `visitor_id`** and emits
  `REENTRY`, never a second `ENTRY` — so footfall/conversion are not inflated. See [[EDGE_CASES]].

## Customer journey
- Ordered sequence of zones a visitor passes through with timestamps. Append a zone only when dwell
  ≥ `min_zone_dwell` to filter pass-through noise.

## Conversion funnel (spec stages — Part B, get this right)
- **Stages (per [[SPEC]]):** `Entry → Zone Visit → Billing Queue → Purchase`, with counts + drop-off %.
- **Session is the unit; NO double counting:** each `visitor_id` counts at most once per stage;
  **re-entries do not double-count** a visitor.
- **Drop-off:** `drop_off(stage_n) = 1 − visitors(stage_n) ÷ visitors(stage_{n-1})`.
- **Purchase:** visitor satisfies the POS correlation rule above.

## Zone dwell & engagement
- **Dwell:** total contiguous time a visitor's mapped position (foot point) is inside a zone.
- **Engagement:** a visitor is counted as engaging a zone when dwell ≥ `min_engagement_dwell`.
- A `ZONE_DWELL` event is emitted **every 30s** of continuous presence in a zone (see [[EVENT_SCHEMA]]).
- Report per-zone visitor counts and avg/total dwell (feeds the heatmap).

## Billing queue & abandonment
- **queue_depth:** number of visitors in the billing zone at the moment a visitor joins
  (set in `metadata.queue_depth` on `BILLING_QUEUE_JOIN`).
- **Abandonment:** `BILLING_QUEUE_ABANDON` when a visitor leaves the billing zone **without** a
  POS transaction following (per the correlation rule). **abandonment rate** = abandons ÷ billing-zone sessions.

## Heatmap
- Per-zone **visit frequency + average dwell**, **normalised 0–100** for grid rendering.
- Include a `data_confidence` flag when **< 20 sessions** in the window (low-sample warning).

## Anomalies (severity + suggested action)
- **Queue spike:** billing `queue_depth` exceeds a threshold/trend.
- **Conversion drop:** conversion rate materially below the **7-day average**.
- **Dead zone:** a zone with **no visits for 30 minutes** (during open hours).
- Each: `severity` INFO/WARN/CRITICAL + a human `suggested_action`. Compute from input (no hardcoding).

## Store KPIs
- Unique visitors, conversion rate, avg session duration, avg dwell per zone, top zones,
  basket value (from POS), abandonment rate, queue depth.

## Configurable thresholds (env-driven, surfaced here — single source)

| Param | Meaning | Default `(TBD)` |
|-------|---------|-----------------|
| `min_zone_dwell` | min dwell to record a zone in a journey | 2 s |
| `min_engagement_dwell` | min dwell to count zone engagement | 3 s |
| `session_timeout` | track-lost duration that ends a session | 30 s |
| `reentry_window` | gap within which a re-entry is the same visit | 120 s |

All thresholds via environment variables (no hardcoding). See [[EVENT_SCHEMA]] for how these
become events and [[API_SPEC]] for how they surface.
