# STATE — where the build is right now

> Stateful progress for the LLM wiki. Update at the end of every working session. Keep it **short and
> current**; deep history lives in git + [[DECISIONS]] (ADRs) + [[TASKS]] (checkmarks).
>
> Last updated: 2026-06-03.

## Snapshot — what exists today

🟢 **End-to-end system, two stores, one command.** `docker compose up --build` brings up postgres ·
api · **replayer** · prometheus · grafana · **frontend** (:8080); the detector is opt-in behind a
`detect` profile. Every prescribed endpoint returns real, internally-consistent, store-aware data.

- **Detection pipeline** (`services/detector`): YOLOv8n + ByteTrack → **per-camera motion tracklet-stitch
  (ADR-0037)** → colour-histogram Re-ID gallery, **multi-store** via the registry. Counting spans **all
  cameras**, gated to solid store-interior tracks (entrance line + box-size + floor mask; ADR-0029). The
  stitcher (`association.py`) collapses fragmented ByteTrack ids into one local id by spatio-temporal
  continuity *before* the gallery, fixing the within-camera over-split; the appearance gallery still does
  cross-camera dedup (pluggable: `TRACK_ASSOCIATION=appearance` reverts to gallery-only). Per-store
  overrides: `reid_max_distance`, `min_zone_dwell_ms`, `staff_heuristic_color`, `staff_uniform_hint`.
- **Staff** = per-store uniform-colour heuristic (`black`/`pink`; ADR-0009/0032) with an optional **VLM**
  (Gemini **or** Groq; ADR-0027/0031) that overrides when confident. VLM is **off by default**, cached,
  gate-safe.
- **Zones** = static `primary_zone`, or VLM-labelled for product cams when enabled (Store_2 `zone` →
  `skincare_aisle`).
- **Two run modes (ADR-0033):** default `docker compose up` = **replayer** POSTs the committed
  `data/events/behavior.jsonl` (seconds, no YOLO/keys — the gate path); `--profile detect` (or
  `DETECTOR_MODE=detect`) runs the full pipeline and regenerates events. The replay artifact is now
  **git-tracked** (`.gitignore` negations) so the gate works on a fresh clone.
- **API** (`services/api`): idempotent `POST /events/ingest`; per-store `GET /stores/{id}/{metrics,funnel,
  heatmap,anomalies}`, `GET /stores`, `/health`, Prometheus `/metrics`. Staff excluded (any-flag);
  honest zeros + dormant anomalies; POS for **ST1008 only**. Per-request structured log carries
  `trace_id · store_id · endpoint · event_count · latency_ms · status_code`; DB-down degrades to a
  structured **503** (not a 500).
- **Tests:** 164 pytest (unit + 2 integration suites incl. a **pipeline-replay E2E** over the committed
  events; `test_association.py` covers the stitcher 100%), coverage **84.5%** gated at **70%** (`pytest`
  enforces; `requirements-dev.txt`).
- **Frontend**: store switcher (polls only the visible store, 4 s); conversion ring, funnel, heatmap,
  anomalies, health, POS (top_brand/top_department/peak_hour).
- **Stores:** **ST1008** Brigade (POS, ~2 customers GT) · **ST1009** Store_2 (no POS; busy, 22 cust + 3
  staff GT). Adding a store = drop `stores/<id>.py` + a clips folder (ADR-0028).

## Headline results (honest — motion-stitched local re-run, ADR-0037, 2026-06-04)

- **Store_1 (ST1008):** **7 people ✓** (GT 7), ENTRY/EXIT/REENTRY **0 ✓**. Staff split **4/3 vs true 5/2** —
  one under-exposed staffer (colour 0.22) reads as customer; a marginal overhead call (unchanged — Store_1
  was never the over-split problem). Conversion **0%** on the 2-min clip (`data_confidence=low`). POS day
  KPIs: **24 txns, ₹34,331.71**, top brand Faces Canada.
- **Store_2 (ST1009):** **22 unique vs 25 GT** (17 cust + 5 staff), footfall **ENTRY 11 · EXIT 5 · REENTRY
  2**. **ADR-0037 motion stitching fixed the dominant error:** the ZONE staffer that was **4 ids → 1**;
  ENTRY2 customers **exactly 8 ✓ (GT ~8)**; BILLING staff **exactly 2 ✓**; **footfall now matches GT
  (~11/~5)**. Residual gap to 25 is *outside* association: **group-merge** (customers 17 vs 22, a detection
  limit) + **cross-camera staff duplication** (5 vs 3 — appearance-bound, ADR-0036).
- **Key findings:** appearance Re-ID **cannot** fix the over-split (ADR-0036: same-person front/back is
  *farther* than different people — histogram 0.66 vs 0.61; ImageNet CNNs also overlap); **motion can** and
  does (ADR-0037), per-camera. Store-wide honest output on a crowd = **head-count band + per-camera figures**.

## Recent decisions (newest first → see [[DECISIONS]])

- **ADR-0039** cross-camera identity — **not feasible on this dataset**, skip + document (user, 2026-06-04):
  Store_2 cams are non-overlapping AND recorded on different real days (no true time-sync), so a homography/
  spatio-temporal merge would *fabricate* identities. Its only payoff (staff +2) is within the accepted
  ±1–2. Supersedes ADR-0037 alt-c ("deferred homography").
- **ADR-0038** pose group-split (opt-in `GROUP_SPLIT="pose"`, off by default): pluggable YOLOv8-pose splitter
  for merged-group boxes. **Measured no net gain** (Store_2 22→22) — overhead groups are front-to-back (tall
  boxes, only ~5% trip the width gate) + pose occlusion-limited; same root cause as imgsz-960. Kept as a
  tested, gate-safe capability; committed events reverted to baseline. An honest negative, not a fix.
- **ADR-0037** tracking-based association (motion tracklet-stitch, default on): fixes the within-camera
  over-split ADR-0036 deferred — Store_2 ZONE staffer 4 ids → 1, footfall now matches GT. Pluggable
  (`TRACK_ASSOCIATION`), pure/gate-safe; appearance gallery kept as cross-camera fallback.
- **ADR-0036** Re-ID over-split: learned embedder built (gate-safe, off by default) but appearance proven
  non-discriminative on overhead CCTV → keep histogram, document the limit (superseded as the *fix* by
  ADR-0037's motion association; the appearance finding stands).
- **ADR-0035** REENTRY requires a prior EXIT (kills track-fragmentation false positives: 27→0, 19→2).
- **ADR-0034** staff = VLM cross-store baseline + per-store colour **high-confidence override** (hybrid).
- **ADR-0033** two run modes (replay default + opt-in detect profile).
- **ADR-0032** per-store staff uniform colour (`COLOR_HEURISTICS` registry: black/pink) + VLM hint.
- **ADR-0031** multi-provider VLM — added **Groq** (multimodal Llama-4 Scout); cleared what Gemini's
  20/day free tier couldn't.
- **ADR-0030** per-store density tuning (ST1009 `reid 0.35` / `dwell 800`); offline detector raised for
  accuracy (imgsz 768, fps 10, IoU 0.85) — this **largely reverses ADR-0019**'s speed tuning, now that
  replay (not live YOLO) is the gate path.
- **ADR-0029** count unique visitors across **all** cameras, quality- + entrance-line-gated (refines ADR-0011).
- **ADR-0027/0028** VLM staff/zone (offline, gate-safe) · pluggable per-store registry.

## Open items / next action

**Single next action:** committed `data/events/behavior.jsonl` is **regenerated** with the validated config
(motion stitching ADR-0037 + histogram Re-ID + ADR-0034/0035, frame-verified ENTRY lines, global imgsz 768)
— ST1008 106 events / ST1009 183 events, replay E2E green. Next: a clean-machine `docker compose down -v &&
up --build` gate dry-run.

Known limits (documented, not bugs — [[GROUND_TRUTH]] §1, [[EDGE_CASES]], ADR-0036/0037/0038/0039): the
within-camera **over-split is fixed** by motion association (ADR-0037); what remains is **cross-camera**
identity (a roaming staffer counted per camera — **not feasible on this dataset**: the cams don't overlap
and aren't time-synced, so a homography would fabricate identities; appearance is measured-unfixable —
ADR-0039/0036), and **tight groups merge** at the box level (a detection limit — imgsz 960 *and* the
opt-in pose splitter both measured **no gain**, ADR-0038). The **staff split is ±1–2** at the margin (user
accepts this). Store_2 has no POS → conversion N/A. Deferred: demographics (full-face-blurred footage). The
learned-embedder (`reid_backend=cnn`) and pose splitter (`GROUP_SPLIT=pose`) remain as parked, gate-safe
capabilities.
