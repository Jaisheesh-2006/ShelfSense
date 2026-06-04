# EDGE CASES

> Real-world conditions the system must handle gracefully. [[SPEC]] §3.3 names **7 edge cases** that
> are graded (Parts A & C) and used as a tie-breaker. Handle these well, then the secondary cases.

## The 7 spec edge cases (graded — [[SPEC]] §3.3, Parts A & C)
1. **Group entry** (2–4 together) → count **individuals, not groups** (3 enter ⇒ 3 `ENTRY`).
   ✅ *Handled by design:* counting is per-tracked-person (per `visitor_id`), never per blob — a group
   yields one track/visitor each. No grouping logic needed.
   ⓘ *New (corrected dataset):* `sample_events.jsonl` carries explicit **`group_id` / `group_size`** on
   entry/exit ([[EVENT_SCHEMA]]). We could *populate* those (group attribution) as an enrichment, but
   **ADR-0024 D1 keeps the flat schema (the sample is informational only)** and counting individuals already
   satisfies the requirement — so it stays out of scope.
2. **Staff movement** → classify `is_staff=true` and **exclude from customer metrics**.
   ✅ *(ADR-0009/0032):* `is_staff` from a **per-store uniform-colour score** — a `COLOR_HEURISTICS`
   registry in `detector/app/staff.py` (Store_1 = **black**, both upper+lower body; Store_2 = **pink**,
   upper body), reusing the Re-ID crop; staff when the mean score ≥ `staff_uniform_threshold`. When
   `VLM_ENABLED=true` an optional **VLM (Gemini/Groq)** overrides it when confident, with a per-store
   `staff_uniform_hint` (ADR-0027/0031). Store_1 calibration (5 staff / 2 customers): customers 0.08–0.19,
   staff 0.52–0.96. CAM4 back room excluded at source (and empty in-clip). The API treats a visitor as
   staff if **any** event is flagged; the old 90 s presence heuristic is an off-by-default fallback.
   *Limit:* on steep overhead CCTV the split is hard regardless (uniforms/lanyards not visible), so a
   same-colour customer can be misflagged and the VLM verdict is crop-sensitive — the **total head-count
   is the more reliable output** ([[GROUND_TRUTH]] §1).
3. **Re-entry** → same person returning produces `REENTRY` under the **same `visitor_id`**, not a
   new `ENTRY`. ✅ *Slice 2.4:* the Re-ID gallery re-matches a returning visitor; a re-match after an
   absence gap emits `REENTRY`. (Rare on these "already inside" clips, like `ENTRY` — honest.)
4. **Partial occlusion** → detection confidence must **degrade gracefully, not fail silently**;
   keep low-confidence events but **flag** them. ✅ real `confidence` carried on every event; the
   tracker bridges short gaps. (See confidence calibration below.)
5. **Billing queue buildup** → track `queue_depth` and emit `BILLING_QUEUE_JOIN`/`ABANDON`.
   ✅ *Slice 2.5:* `BillingTracker` emits `BILLING_QUEUE_JOIN` with `queue_depth` on CAM5; abandon derived
   in conversion. ✅ *Slice 2.7:* `/anomalies` raises a `QUEUE_SPIKE` (WARN/CRITICAL) off the staff-excluded
   depth (ADR-0014).
6. **Empty store periods** (5–10 min no customers) → API must return **0 / valid JSON, never null/crash**.
   ✅ *Slice 2.6/2.7:* every endpoint handles zero-traffic (honest zeros, `data_confidence="low"`); unit +
   integration tests cover the empty/low-sample paths. The dead-zone anomaly is the explicit "quiet zone" signal.
7. **Camera angle overlap** (floor overlaps entry) → **cross-camera dedup**: same person not double-counted.
   ✅ *Slice 2.4:* appearance Re-ID merges the same shopper across cameras into one `visitor_id`
   (approximate — ADR-0008/A5). ✅ *Slice 2.4b:* the **entrance camera no longer counts visitors** (footfall
   only, ADR-0011), removing CAM3↔CAM1/2 overlap double-counting and mall pass-by at source.
   ⚠ **Measured limit (ADR-0036):** on **overhead** CCTV the *opposite* error dominates on a busy store —
   **over-splitting**: the same person seen front vs back fails to match (same-person crops are *farther*
   apart than different-person crops; appearance Re-ID — histogram, MobileNet, ResNet50 — all fail to
   separate identities), so one moving staffer splits into several ids.
   ✅ **Fixed *within* a camera (ADR-0037):** a per-camera **motion tracklet-stitch** runs before the
   appearance gallery and collapses fragmented ids by spatio-temporal continuity (last position + velocity,
   not pixels). Store_2's ZONE staffer went from **4 ids → 1**; footfall now matches GT. **Cross-camera**
   dedup still leans on appearance (positions aren't comparable across cameras), so a roaming staffer seen on
   several cameras is still over-counted. The textbook fix — a floor-plane homography — is **not feasible on
   this dataset (decided, ADR-0039):** Store_2's cameras are non-overlapping *and* were recorded on different
   real days (synthetic timeline), so a spatio-temporal cross-camera merge would *fabricate* identities. It is
   documented as a data limitation; its only effect (staff +2) is within the accepted ±1–2. Honest crowd
   output = head-count band + per-camera figures ([[GROUND_TRUTH]] §1).

9. **Tightly-packed groups** (2+ people standing together) → should count as individuals.
   ⚠ *Partial — a detection limit, not a logic/association one:* per-tracked-person counting handles a
   *resolvable* group, but on overhead views YOLO sometimes merges adjacent people into **one box → one
   track → one visitor** (under-counts; e.g. Store_2 customers read 17 vs GT 22). A higher NMS IoU keeps
   nearby boxes, and motion stitching (ADR-0037) does **not** worsen it (it links fragments, never merges
   coexisting tracks). A tried inference-size bump (`detector_imgsz=960` on ST1009) did **not** separate
   tight groups (count didn't rise, just slower) and was **reverted** — the merge happens at the box level,
   before tracking. ⚠ **Optional pose splitter (ADR-0038) — measured no gain:** `GROUP_SPLIT=pose` runs
   YOLOv8-pose on frames with a *wide* box and splits the merged box into one sub-track per skeleton (off by
   default, gate-safe — the replay/default path never loads a second model). Clean A/B: **Store_2 unique
   22→22, no net gain** — overhead groups stand front-to-back, so a merged pair is a *tall* box (only ~5% of
   boxes hit the width gate) and pose keypoints degrade under occlusion. Kept as a tested, opt-in capability;
   the group-merge gap stays a documented overhead-CCTV detection limit ([[GROUND_TRUTH]] §1).

8. **Mirror / reflective-surface phantoms** (CAM5 mirror, backlit displays, wall posters) → a reflection
   is not a person. ✅ *Slice 2.4b (ADR-0010):* a calibrated **walkable-floor mask** drops detections whose
   foot-point lands off the floor (up on a wall/mirror). Dropped **317** off-floor detections on CAM5.
   General — also rejects product displays and poster faces. (Beyond the spec's 7; surfaced from the data.)

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
