# BUSINESS RULES

> Definitions of every business metric — the contract between analytics output and what
> reviewers expect. Headline metric is **conversion rate**. Facts about the data are in
> [[GROUND_TRUTH]]. Update whenever business logic changes. `(TBD)` = pending confirmation.

## Core entities

- **Track** — one tracked person across frames (per camera), a `track_id`.
- **Session** — one customer visit; bounded by entry and exit. The unit for funnel/conversion
  (sessions, **never raw detections**, to avoid double counting — rubric-critical).
- **Zone** — a named store region defined per camera from the footage (e.g. entrance, aisle,
  checkout). To be defined after frame inspection ([[STATE]]).
- **Transaction** — one POS order from the CSV (`distinct order_id`). 24 on 10-Apr-2026.

## Headline metric — Conversion rate

- **Definition:** `conversion_rate = transactions ÷ footfall` over a comparable window.
- **transactions:** `count(distinct order_id)` from the CSV (see [[GROUND_TRUTH]] §2).
- **footfall:** unique customer sessions entering the store, counted from CCTV.
- **⚠ Window rule:** video (~2 min) and CSV (full day) windows differ. Do **not** divide
  full-day transactions by clip footfall. Demonstrate on a comparable/representative basis and
  state the assumption (A3 in [[PROJECT]], PD-3 in [[DECISIONS]]). Reviewers reward this honesty.

## Footfall (entry/exit)

- **Definition:** count of sessions entering the store in a window.
- **Rule:** a session counts when its track crosses the **entrance line** inward (line-crossing
  on the entrance camera). Exits counted on outward crossing.
- **Must handle (Detection bucket, 30 marks):** re-entry, staff, group entry — see [[EDGE_CASES]].

## Customer session

- **Start:** first detection of the track after entry.
- **End:** track lost > `session_timeout` OR outward exit crossing.
- **Re-entry rule `(TBD)`:** same person returning within `reentry_window` → same session vs new
  visit. Decision affects footfall; document choice. See [[EDGE_CASES]].

## Customer journey
- Ordered sequence of zones a session visits with timestamps. Append a zone only when dwell
  ≥ `min_zone_dwell` to filter pass-through noise.

## Zone engagement & dwell time
- **Dwell:** total contiguous time a session's mapped position is inside a zone polygon.
- **Engagement:** session counted as engaging a zone when dwell ≥ `min_engagement_dwell`.
- Report per-zone session counts and avg/total dwell.

## Conversion funnel (35-mark bucket — get this right)
- **Stages (default):** `Entered → Browsed (≥1 product zone) → Approached checkout → Purchased`.
- **Session-based, NO double counting:** each session contributes at most once per stage.
- **Drop-off:** `rate(stage_n) = sessions reaching stage_n ÷ sessions reaching stage_(n-1)`.
  `/funnel` must show monotonic drop-off (reviewers check this).
- **Purchased:** tie to POS transactions where possible; otherwise infer from checkout-zone
  engagement and clearly label the inference `(TBD)`.

## Checkout activity
- Sessions present at the **checkout** zone; queue/dwell stats there. Engagement ≥ `min_engagement_dwell`.

## Anomaly detection (must be "logical and meaningful")
- Rule-based first, each rule documented here with its threshold. Candidates: abnormal dwell,
  crowd spike, entrance with no subsequent zone activity, checkout idle during peak,
  after-hours presence. `(TBD: thresholds)` — must compute from input (integrity cap).

## Store KPIs
- Total footfall, conversion rate, avg session duration, avg dwell per zone, top zones,
  peak-hour footfall, basket size (from CSV: line-items ÷ transactions), GMV by department.

## Configurable thresholds (env-driven, surfaced here — single source)

| Param | Meaning | Default `(TBD)` |
|-------|---------|-----------------|
| `min_zone_dwell` | min dwell to record a zone in a journey | 2 s |
| `min_engagement_dwell` | min dwell to count zone engagement | 3 s |
| `session_timeout` | track-lost duration that ends a session | 30 s |
| `reentry_window` | gap within which a re-entry is the same visit | 120 s |

All thresholds via environment variables (no hardcoding). See [[EVENT_SCHEMA]] for how these
become events and [[API_SPEC]] for how they surface.
