# EDGE CASES

> Real-world conditions the system must handle gracefully. The rubric ([[GROUND_TRUTH]] §3)
> explicitly names **re-entry, staff movement, occlusion, group entry** in the Detection
> bucket (30 marks) and uses edge-case handling as a tie-breaker. Add cases as discovered.

## Rubric-named cases (prioritize — these are graded by name)
- **Re-entry** — same person leaves and returns. Rule needed: same session within
  `reentry_window` vs. new visit. Affects footfall & conversion. See [[BUSINESS_RULES]].
- **Staff movement** — salespersons present all day (named in the CSV). Must not be counted as
  customer footfall. Heuristics: persistent presence, behind-counter position, uniform.
- **Occlusion** — people hidden by shelves/each other → missed/merged detections.
- **Group entry** — several people entering together → must count each, not one blob.

## Detection
- **Occlusion** — people partially hidden by shelves/each other → missed/merged boxes.
- **Crowding** — dense clusters → overlapping detections, NMS suppression.
- **Lighting** — glare, shadows, low light → confidence drops.
- **Non-customers** — staff, children, reflections, mannequins → false footfall.
- **Partial entries** — person at the doorway who doesn't enter.

## Tracking
- **ID switches** — two tracks swap identity after crossing.
- **Track fragmentation** — one person split into multiple track IDs after occlusion.
- **Re-entry** — same person leaves and returns → one session or two? (rule needed).
- **Loitering / stationary people** — long static presence (staff at till).
- **Multi-camera hand-off** — same person across overlapping/adjacent cameras.

## Zone / spatial
- **Boundary flicker** — position oscillates across a zone edge → noisy dwell.
- **Zones overlap or have gaps** in the floor-plan mapping.
- **Perspective distortion** — bbox foot-point vs. centroid for zone assignment.

## Sessions / analytics
- **Session never ends** (track stuck) → enforce `session_timeout`.
- **Zero-footfall windows** (store closed) → must report 0, not error.
- **Clock/ordering** — out-of-order or duplicate events from the stream → idempotency.
- **Replay** — reprocessing footage must not double-count.

## System / ops
- **Service restart mid-stream** — recover state from stream/DB without corruption.
- **Backpressure** — analytics slower than detector → queue growth handling.
- **Empty / corrupt frames** in the footage.
- **Missing business CSV** — degrade gracefully (see [[RISKS]] R-1).

## Handling status

| Case | Strategy | Status |
|------|----------|--------|
| Zero-footfall window | Return 0 explicitly | ⬜ planned |
| Duplicate/out-of-order events | Idempotent keys + event time ordering | ⬜ planned |
| Session never ends | `session_timeout` sweep | ⬜ planned |
| Non-customer filtering | Confidence + zone heuristics (later) | ⬜ planned |

> Definitions and thresholds referenced here live in [[BUSINESS_RULES]].
