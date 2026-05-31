# PROJECT

> Scope, goals, success criteria, assumptions. Requirements: [[SPEC]]. Data facts: [[GROUND_TRUTH]].
> This file adds interpretation and scope; it does not duplicate the schema/endpoints (see [[SPEC]]).

## One-liner
ShelfSense converts a store's CCTV footage into retail intelligence — North Star **conversion rate** —
via a two-tier pipeline: a detection layer that emits behavioural events, and an API that ingests them
and serves metrics.

## Problem statement
Purplle / UpGrad Store Intelligence Challenge (2026). Start from **raw CCTV footage** + a **POS CSV**
and build a complete, containerised system that produces meaningful, queryable store metrics. Graded
as an **end-to-end systems & engineering** problem ([[SPEC]] scoring), not on detection accuracy.

## Inputs (full detail in [[GROUND_TRUTH]])
- **5 CCTV cameras**, ~2-min clips, 1920×1080, time-synced (~20:10) — roles: Entry=CAM3, Floor=CAM1/2,
  Billing=CAM5, Back room (staff)=CAM4.
- **POS CSV** — Brigade_Bangalore (ST1008), 10-Apr-2026, **24 transactions** — the conversion source.

## Target outputs
- **Conversion rate** (North Star) = `converted visitors ÷ unique visitors` (POS 5-min billing-window
  rule; staff excluded). See [[BUSINESS_RULES]].
- Footfall (entry/exit), sessions, zone dwell/engagement, the funnel (drop-off), billing queue +
  abandonment, heatmap, anomalies, health. Endpoints in [[API_SPEC]]; behaviours in [[EVENT_SCHEMA]].

## Goals (aligned to the rubric)
- **One-command, non-crashing, observable** stack (`docker compose up`).
- Correct, consistent endpoints — especially `POST /events/ingest` (idempotent) and a session-based
  `/stores/{id}/funnel` (the 35-mark bucket).
- **Schema-compliant behavioural events** from the detection layer.
- Strong **DESIGN.md** + **CHOICES.md** (repo root) and prompt blocks in tests (Part D).
- Honest handling of the 7 edge cases ([[EDGE_CASES]]); Re-ID so counting is on de-duplicated sessions.

## Non-goals
- SOTA detection/tracking accuracy — "close to actual counts" is enough.
- Heavy ML experimentation. Real computation that varies with input matters more (integrity cap).
- Unnecessary architectural complexity.

## Success criteria (gate + reviewer lens — [[SPEC]] §gate)
1. `docker compose up` works with zero manual steps; nothing crashes.
2. `POST /events/ingest` accepts events (no 5xx); `GET /stores/{id}/metrics` returns valid JSON.
3. Events are structured and schema-compliant.
4. DESIGN.md & CHOICES.md exist, >250 words each.
5. Outputs visibly **vary with input** (no hardcoding — avoid the 50-cap / integrity check).

## Working assumptions (challenge them; track in [[RISKS]])
- **A1 (resolved):** the 5 clips are concurrent, time-synced views; CAM3 shows the entrance ([[GROUND_TRUTH]] §1).
- **A2:** footfall is counted on CAM3 via entrance-line crossing (line calibrated, Slice 2.0).
- **A3:** video (~2 min) vs CSV (full day) windows differ → conversion demonstrated on a comparable/
  representative window, documented — not a naive full-day-txns ÷ clip-footfall divide.
- **A4:** staff are classified (`is_staff`) and excluded; CAM4 (back room) is treated as staff space.

## Open questions
- Conversion window semantics for the demo (the A3 trade-off — finalise when conversion lands, Slice 2.5).
- Re-ID approach (embedding vs trajectory/appearance-distance) — decide in Slice 2.4.

See [[DECISIONS]] for the decision log and [[RISKS]] for tracked unknowns.
