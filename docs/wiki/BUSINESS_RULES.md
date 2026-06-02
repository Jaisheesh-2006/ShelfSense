# BUSINESS RULES

> Definitions of every business metric — the contract between analytics output and what
> reviewers expect. Headline metric is **conversion rate**. Facts about the data are in
> [[GROUND_TRUTH]]. Update whenever business logic changes. `(TBD)` = pending confirmation.

## Core entities

- **Track** — one tracked person across frames (per camera), a `track_id`.
- **Session** — one customer visit; bounded by entry and exit. The unit for funnel/conversion
  (sessions, **never raw detections**, to avoid double counting — rubric-critical).
- **Zone** — a named store region from the floor plan ([[GROUND_TRUTH]] §4): entrance, skincare_aisle,
  makeup_aisle, foh_center, checkout, accessories, stockroom (staff). Each camera maps to one zone:
  by default the hand-mapped `primary_zone`, or — for **product** cameras with `VLM_ENABLED=true` — a
  **Gemini-labelled** zone read from the shelves (entrance/checkout/stockroom stay role-known; ADR-0027).
- **Visitor** — one visit session, identified by a `visitor_id` (Re-ID). Re-entries keep the same id.
- **Transaction** — one POS order from the CSV (`distinct order_id`). 24 on 10-Apr-2026.

## Headline metric — Conversion rate (North Star)

- **Definition (per [[SPEC]]):** `conversion_rate = converted visitors ÷ unique visitors` over a
  session window. Staff excluded.
- **Converted visitor (POS correlation rule):** a visitor whose session was in the **billing zone
  within the 5-minute window before a POS transaction timestamp** (same store) counts as converted.
  No `customer_id` — correlation is **time-window + store** only.
- **unique visitors:** distinct **non-staff** `visitor_id`s — assigned to every tracked customer on first
  detection in a **shopping-floor area (CAM1/CAM2/CAM5)**, not only to people who cross the entrance line
  (ADR-0007). The **entrance camera (CAM3) contributes footfall only, not visitor counts** — its view is
  dominated by mall-corridor pass-by ([[DECISIONS]] ADR-0011). Re-ID de-duplicates across cameras and keeps
  re-entries the *same* visitor; staff (dark-uniform, ADR-0009) are excluded. This is the conversion
  denominator. (Rationale: on ~2-min clips most shoppers are already inside, so entrance-crossings ≈ 0 —
  ADR-0006/0007. Validated count on the clip: **2 customers** + 3 staff.)
- **POS source (corrected dataset, [[GROUND_TRUTH]] §2):** 7-col `POS - sample transactions.csv` → a
  **transaction = distinct `order_time`** (`order_id` is now per-line-item, not the basket key),
  `timestamp` from `order_date`+`order_time` (local, no tz), `basket_value` = Σ `total_amount` per
  timestamp. **24 transactions**, store **ST1008** only (Store_1; Store_2 has no POS). **⚠ `pos_loader.py`
  parses the OLD 20-col GMV format and must be reworked** before these KPIs are real again.
- **⚠ Window caveat (handled, ADR-0012):** clips (~2 min) vs CSV (full day) differ, and no sale falls in
  the clip window. We **do not** divide mismatched windows: we report the honest clip conversion (**0%**,
  `data_confidence="low"`) and demonstrate the correlation on a comparable window (`demo_conversion.py`).
  The 24 real sales still power day-level KPIs (**total ₹34,331.71** via `total_amount`; basket, peak hour
  12:00/19:00) via `pos_day_metrics`.

## Footfall (entry/exit)

- **Definition:** `ENTRY`/`EXIT` count the *flow* across the entrance threshold in a window.
- **Rule:** an `ENTRY` fires when a track's foot-point crosses the **entrance line** inward on CAM3
  (calibrated, centre-left door); `EXIT` on outward crossing. Debounced for on-line flicker.
- **⚠ On short clips this is ≈0** because most shoppers entered before the window — so the
  **unique-visitor count** (above), not entrance-crossings, is the basis for conversion (ADR-0007).
  ENTRY/EXIT remain valuable as real flow signals and would scale on longer/live feeds.
- **Do NOT count mall pass-by:** people walking the mall corridor past the storefront are not
  visitors; the entrance line is placed on the actual door, not the busiest motion (ADR-0006).
- **Must handle (Detection bucket, 30 marks):** re-entry, staff, group entry — see [[EDGE_CASES]].

## Customer session

- **Start:** first detection of the track after entry.
- **End:** track lost > `session_timeout` OR outward exit crossing.
- **Re-entry rule:** a returning visitor (matched by Re-ID) keeps the **same `visitor_id`** and emits
  `REENTRY`, never a second `ENTRY` — so footfall/conversion are not inflated. See [[EDGE_CASES]].

## Staff classification (excluded from customer metrics)
- **Rule (ADR-0009):** Brigade staff wear a **complete black uniform**, so `is_staff` is set from a
  **dark-uniform appearance score** — the min of the upper- and lower-body dark-pixel fraction (HSV Value
  ≤ `staff_dark_v_max`, central column), reusing the Re-ID crop. A track is staff when its mean score ≥
  `staff_darkness_threshold`. (The old Store_1 **stockroom cam (CAM4) was staff-only** and excluded at
  source; it is **no longer in the corrected dataset** — [[GROUND_TRUTH]] §1.)
- **Optional VLM override (ADR-0027):** when `VLM_ENABLED=true`, a **Gemini** call (once per
  `visitor_id`, offline only) decides staff/customer and **overrides the heuristic when it clears
  `vlm_staff_min_confidence`**; otherwise the dark-uniform heuristic stands. This is what makes staff
  detection work for **Store_2 (pink staff)** without per-store colour tuning. Off by default, cached,
  gate-safe — see [[DECISIONS]] ADR-0027.
- **Aggregation:** the API treats a visitor as staff if **any** of their events is flagged.
- **Excluded** from unique visitors, conversion, funnel, heatmap — staff are not customers.
- **Limits:** a genuinely black-clothed customer would be misflagged (ours are grey/violet); bright shelf
  backgrounds dilute the score (so the entrance camera is not used for this). See [[EDGE_CASES]] #2.

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

## Billing queue & abandonment (Slice 2.5, ADR-0012)
- **`BILLING_QUEUE_JOIN`:** emitted when a **non-staff** visitor enters the checkout zone on CAM5
  (`BillingTracker`, driven off the CAM5 `ZONE_ENTER`). **queue_depth** = number of customers in the
  checkout zone *including the joiner* (set in `metadata.queue_depth`). Staff are excluded from the queue.
- **`BILLING_QUEUE_ABANDON`:** **derived** in `conversion.py` (not the detector — it needs POS): a billing
  visitor with **no** POS transaction in the correlation window. **abandonment rate** = abandons ÷
  billing-zone customers.
- **Staff at the per-event vs visitor level:** a CAM5 track that dips below the staff-darkness threshold can
  emit a JOIN with `is_staff=false`, but if the visitor is **overall staff** (any event flagged) the
  conversion step excludes them — so staff never pollute the billing/customer counts.
- **Honest clip result:** customers browse CAM2, none reach checkout → **0 billing customers, conversion 0%**
  with `data_confidence="low"` (the window mismatch). The mechanism is demonstrated on a comparable window
  (`scripts/demo_conversion.py`, `POS_DEMO_ALIGNMENT`).

## Heatmap (Slice 2.7, ADR-0014, `analytics.compute_heatmap`)
- Per-zone **distinct-customer visit frequency + average dwell**, **normalised 0–100** (busiest zone =
  100) for grid rendering. Staff excluded.
- Include a `data_confidence="low"` flag when **< `conversion_low_sample_threshold` (20)** customers.

## Anomalies (severity + suggested action) — Slice 2.7, ADR-0014, `analytics.detect_anomalies`
- **Queue spike:** billing `queue_depth` (staff-excluded) ≥ `anomaly_queue_depth_warn` ⇒ WARN,
  ≥ `anomaly_queue_depth_critical` ⇒ CRITICAL. Suggested action: open another till.
- **Conversion drop:** conversion below `anomaly_conversion_baseline × (1 − anomaly_conversion_drop_pct)`.
  ⚠ We have **one day** of data, not a 7-day average, so the baseline is a **documented config target**.
  The check fires **only at `data_confidence="ok"`**; under low sample it emits **INFO** — it never cries
  wolf on the 2-min clip.
- **Dead zone:** a monitored customer zone (from `STORE` config) with **no visit for
  `anomaly_dead_zone_minutes`** during open hours (`store_open_hour`–`store_close_hour`). **Span-guarded:**
  only evaluated when the observed window is at least that long; otherwise **INFO** ("window too short").
- Each: `severity` INFO/WARN/CRITICAL + a human `suggested_action`. **All compute from input** (no
  hardcoding); honest dormancy over fabricated alerts is deliberate (integrity cap + reviewer trust).

## Health / feed freshness (Slice 2.7, ADR-0014)
- **`/health`** reports per-store `last_event_at`, `lag_seconds`, `stale_feed`. Freshness is
  **recording-relative** by default (lag vs the latest ingested event, so a replayed clip reads healthy);
  `health_strict_now=true` compares to real wall-clock for live ops. `STALE_FEED` when lag >
  `health_stale_feed_minutes`. `status=degraded` if the DB is unreachable or any feed is stale.

## POS day-level KPIs (from the sales CSV, independent of the clip window)
- `transaction_count` (distinct `order_time` baskets), `total_gmv` (Σ `total_amount`), `avg_basket`,
  `peak_hour`, **`top_brand`** (busiest `brand_name`), and **`top_department`** (busiest category).
- **`top_department`** rolls brands up via a curated **brand → department** taxonomy
  (`shelfsense_common/departments.py`, ADR-0025): makeup · skincare · haircare · bath_and_body ·
  personal_care · fragrance · accessories · **other** (unmapped/own-label). A basket's department follows
  its dominant brand; the rollup excludes `other` so a meaningful category wins. Reference data — the
  output still varies with real sales (no hardcoding). On the real file: **top brand Faces Canada, top
  department makeup**.

## Store KPIs
- Unique visitors, conversion rate, avg session duration, avg dwell per zone, top zones,
  basket value (from POS), top brand + top department, abandonment rate, queue depth.

## Configurable thresholds (env-driven, surfaced here — single source)

| Param | Meaning | Default `(TBD)` |
|-------|---------|-----------------|
| `min_zone_dwell` | min dwell to record a zone in a journey | 2 s |
| `min_engagement_dwell` | min dwell to count zone engagement | 3 s |
| `session_timeout` | track-lost duration that ends a session | 30 s |
| `reentry_window` | gap within which a re-entry is the same visit | 120 s |
| `staff_darkness_threshold` | mean dark-uniform score ≥ ⇒ `is_staff` (ADR-0009) | 0.50 |
| `staff_dark_v_max` | HSV Value (0–255) ≤ ⇒ a pixel is "dark"/near-black | 70 |
| `staff_presence_fallback` | also flag long-present tracks as staff (off by default) | false |
| `pos_correlation_window_ms` | billing-zone-before-a-sale window for "converted" (ADR-0012) | 300000 (5 min) |
| `conversion_low_sample_threshold` | < N unique customers ⇒ `data_confidence="low"` | 20 |
| `store_timezone` | tz for POS `order_date`+`order_time` → UTC | Asia/Kolkata |
| `anomaly_queue_depth_warn` / `_critical` | checkout-customer depth ⇒ WARN / CRITICAL queue spike (2.7) | 3 / 5 |
| `anomaly_conversion_baseline` | documented target conversion rate (no 7-day history) — drop baseline | 0.15 |
| `anomaly_conversion_drop_pct` | fire conversion-drop when rate ≤ baseline·(1−this), at ok confidence only | 0.30 |
| `anomaly_dead_zone_minutes` | zone silent this long during open hours ⇒ dead zone (span-guarded) | 30 min |
| `store_open_hour` / `store_close_hour` | store-local trading window for dead-zone | 12 / 22 |
| `health_stale_feed_minutes` | feed lag beyond which a store is `STALE_FEED` | 10 min |
| `health_strict_now` | false ⇒ freshness vs latest event (recording-relative); true ⇒ vs real now | false |

All thresholds via environment variables (no hardcoding). See [[EVENT_SCHEMA]] for how these
become events and [[API_SPEC]] for how they surface.
