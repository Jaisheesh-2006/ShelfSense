# PROJECT

> Scope, goals, success criteria, assumptions, open questions. Facts come from
> [[GROUND_TRUTH]]; this file adds interpretation, scope, and assumptions.

## One-liner

ShelfSense converts the store's CCTV footage into retail business intelligence —
headline metric **store conversion rate** — via an event-driven, service-separated pipeline.

## Problem statement

UpGrad/Purplle Store Intelligence Challenge (April 2026). Start from **raw CCTV footage**
of a Purplle store + a **POS sales CSV**, and build a complete, runnable pipeline that
produces meaningful business metrics. Graded as an **end-to-end systems & engineering**
problem (see the rubric in [[GROUND_TRUTH]] §3), not on detection accuracy.

## Inputs (see [[GROUND_TRUTH]] for full detail)

- **5 CCTV cameras**, ~2-min clips each — the visual signal for footfall, journeys, dwell, funnel.
- **POS CSV** — Brigade_Bangalore (ST1008), 10-Apr-2026, **24 transactions** / day — the
  conversion numerator and source of basket/department/peak-hour metrics.

## Target outputs

- **Store conversion rate** (headline) — transactions ÷ footfall.
- Footfall (entry/exit counts), customer sessions, customer journeys, zone engagement,
  dwell time, conversion funnel (with drop-off), checkout activity, anomaly detection,
  store KPIs. Definitions in [[BUSINESS_RULES]].

## Goals (aligned to the rubric)

- A **one-command, non-crashing, observable** end-to-end system (`docker compose up`).
- Correct, consistent APIs — especially `/metrics` and a **session-based `/funnel`** (35-mark bucket).
- **Structured events** flowing between services.
- Strong **DESIGN.md** + **CHOICES.md** (generated from [[ARCHITECTURE]] + [[DECISIONS]]).
- Honest handling of edge cases: re-entry, staff, group entry, occlusion ([[EDGE_CASES]]).

## Non-goals

- SOTA detection/tracking accuracy. "Close to actual counts" is enough.
- Heavy ML experimentation. Real computation that varies with input matters more (integrity cap).
- Unnecessary architectural complexity.

## Success criteria (reviewer lens, from rubric)

1. `docker compose up` works with zero manual steps; nothing crashes.
2. `/metrics` returns logically consistent values; `/funnel` shows expected drop-off.
3. Events are structured and consistent.
4. DESIGN.md & CHOICES.md are present and non-trivial.
5. Outputs visibly **vary with input** (no hardcoding — avoid the 50-cap).

## Working assumptions (challenge them; track in [[RISKS]])

- **A1.** The 5 clips are concurrent views of one store; at least one shows the entrance.
  *(Unverified — needs frame inspection; see [[STATE]] next action.)*
- **A2.** Footfall is counted primarily from the entrance camera via line-crossing.
- **A3.** Because video (~2 min) and CSV (full day) windows differ, conversion is demonstrated
  on a comparable/representative basis and the mismatch is documented (see [[GROUND_TRUTH]]
  §window-mismatch, [[DECISIONS]] PD-3). Not a naive full-day-txns ÷ 2-min-footfall divide.
- **A4.** Staff (e.g. salespersons in the CSV) should be excluded from footfall where detectable.

## Open questions

- Which camera is the entrance? Checkout? Do views overlap (→ cross-camera re-ID needed)?
- Video resolution/fps/codec? (ffprobe pending — [[STATE]] blocker.)
- Are the 5 clips time-synchronized?
- Intended conversion window semantics for the demo (PD-3).

See [[DECISIONS]] for resolved/pending decisions and [[RISKS]] for tracked unknowns.
