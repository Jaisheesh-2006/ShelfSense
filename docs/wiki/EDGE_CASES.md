# EDGE CASES

> Real-world conditions the system must handle gracefully. [[SPEC]] §3.3 names **7 edge cases** that
> are graded (Parts A & C) and used as a tie-breaker. Handle these well, then the secondary cases.

## The 7 spec edge cases (graded — [[SPEC]] §3.3, Parts A & C)
1. **Group entry** (2–4 together) → count **individuals, not groups** (3 enter ⇒ 3 `ENTRY`).
2. **Staff movement** → classify `is_staff=true` and **exclude from customer metrics** (CAM4 back
   room + heuristic/VLM: uniform, behind-counter, persistent all-day presence).
3. **Re-entry** → same person returning produces `REENTRY` under the **same `visitor_id`**, not a
   new `ENTRY` (avoids re-entry inflation — a known vendor problem). Needs Re-ID.
4. **Partial occlusion** → detection confidence must **degrade gracefully, not fail silently**;
   keep low-confidence events but **flag** them (see confidence calibration below).
5. **Billing queue buildup** → track `queue_depth` and emit `BILLING_QUEUE_JOIN`/`ABANDON`.
6. **Empty store periods** (5–10 min no customers) → API must return **0 / valid JSON, never null/crash**.
7. **Camera angle overlap** (floor overlaps entry) → **cross-camera dedup**: same person not double-counted.

## Confidence calibration (graded)
Do **not** silently drop or falsely elevate low-confidence detections — emit them with their real
`confidence` so downstream can weigh them. Define a threshold for *acting* on a detection, but
keep the event.

## Secondary cases we also handle (extras beyond the graded 7)
- **Lighting variation** (natural/fluorescent/mixed) → confidence drops, handled by confidence calibration above.
- **ID switch / track fragmentation** → tracker tuning + Re-ID re-associates a fragmented identity.
- **Zone-boundary flicker** (foot point oscillates across an edge) → debounce via `min_zone_dwell` before logging a zone.
- **Out-of-order / duplicate events** → ingest is **idempotent by `event_id`**; events ordered by `timestamp`.
- **Replay safety** → reprocessing the same clip must not double-count — guaranteed by idempotent ingest.
- **Stuck/never-ending session** → close it via `session_timeout`.
- **Corrupt/empty frames** → skipped gracefully by the frame reader.
- **Perspective distortion** → we use the **foot point** (bottom-centre), not the box centre, for zone/line tests.

> Definitions and thresholds live in [[BUSINESS_RULES]]; production handling (idempotency, zero-traffic,
> graceful degradation) is in [[ARCHITECTURE]].
