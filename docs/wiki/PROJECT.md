# PROJECT

> Scope, goals, success criteria, assumptions. Requirements: [[SPEC]]. Data facts: [[GROUND_TRUTH]].
> This file adds interpretation and scope; it does not duplicate the schema/endpoints (see [[SPEC]]).

## One-liner
ShelfSense converts a store's CCTV footage into retail intelligence — North Star **conversion rate** —
via a two-tier pipeline: a detection layer that emits behavioural events, and an API that ingests them
and serves metrics.

## Problem statement
Purplle Store Intelligence Challenge. Start from **raw CCTV footage** + a **POS CSV**
and build a complete, containerised system that produces meaningful, queryable store metrics. Graded
as an **end-to-end systems & engineering** problem ([[SPEC]] scoring), not on detection accuracy.

## Inputs (full detail in [[GROUND_TRUTH]]; corrected dataset 2026-06-02)
- **2 stores** of CCTV, cameras **named by role**:
  - **Store_1** (= the old single store, ST1008): `CAM 1/2 - zone` (floor), `CAM 3 - entry`, `CAM 5 - billing`;
    1920×1080, ~2-min, time-synced (~20:10). **No stockroom cam** anymore (old CAM 4 dropped).
  - **Store_2** (NEW): `entry 1`, `entry 2`, `zone`, `billing_area`; 960×1080, 25 fps, ~1.5–2-min.
- **POS sample CSV** — 7-col, store **ST1008** only (Store_1), 10-Apr-2026, **24 transactions** (₹34,331.71)
  — the conversion source. Different format from the old CSV (`pos_loader.py` needs rework).
- **`sample_events.jsonl`** — 13 example events in a **richer schema** than the PDF's page-5 one;
  **informational only — we keep the flat page-5 schema** (ADR-0024 D1, [[EVENT_SCHEMA]]).

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
- **A1 (resolved):** Store_1's clips are concurrent, time-synced views; `CAM 3 - entry` is the entrance
  ([[GROUND_TRUTH]] §1). Store_2's sync window is not yet frame-verified.
- **A2:** footfall is counted on the entrance cam via line crossing (Store_1 line calibrated, Slice 2.0;
  Store_2 has **two** entrances — uncalibrated).
- **A3:** clips (~2 min) vs POS (full day) windows differ → conversion demonstrated on a comparable/
  representative window, documented — not a naive full-day-txns ÷ clip-footfall divide. (Unchanged: the
  delivered clips are still ~2 min, not the PDF's 20 min.)
- **A4:** staff are classified (`is_staff`) and excluded (Store_1: black-uniform signal, ADR-0009). The
  stockroom cam no longer exists in the data.

## Resolved decisions (post-dataset-change, ADR-0024)
- **Event schema — DECIDED:** keep the flat PDF page-5 schema (what we emit); `sample_events.jsonl`'s richer
  signals are **informational only, not adopted** (ADR-0024 D1, [[EVENT_SCHEMA]]).
- **Second store — DONE:** Store_2 is processed as **ST1009** via the pluggable store registry (ADR-0028).
- **POS loader — DONE:** reworked for the 7-col CSV (transaction = distinct `order_time`; ADR-0024 D3).
- **Demographics from blurred faces — DEFERRED:** full-face blur makes gender/age low-integrity; default is
  **not to emit** (ADR-0024 D4). Revisit only if a defensible signal exists.

See [[DECISIONS]] for the decision log and [[RISKS]] for tracked unknowns.
