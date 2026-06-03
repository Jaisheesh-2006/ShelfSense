# STATE — where the build is right now

> Stateful progress for the LLM wiki. Update at the end of every working session. Keep it **short and
> current**; deep history lives in git + [[DECISIONS]] (ADRs) + [[TASKS]] (checkmarks).
>
> Last updated: 2026-06-03.

## Snapshot — what exists today

🟢 **End-to-end system, two stores, one command.** `docker compose up --build` brings up postgres ·
api · **replayer** · prometheus · grafana · **frontend** (:8080); the detector is opt-in behind a
`detect` profile. Every prescribed endpoint returns real, internally-consistent, store-aware data.

- **Detection pipeline** (`services/detector`): YOLOv8n + ByteTrack + colour-histogram Re-ID, **multi-store**
  via the registry. Counting spans **all cameras**, gated to solid store-interior tracks (entrance line +
  box-size + floor mask; ADR-0029). Per-store overrides: `reid_max_distance`, `min_zone_dwell_ms`,
  `detector_imgsz`, `staff_heuristic_color`, `staff_uniform_hint`.
- **Staff** = per-store uniform-colour heuristic (`black`/`pink`; ADR-0009/0032) with an optional **VLM**
  (Gemini **or** Groq; ADR-0027/0031) that overrides when confident. VLM is **off by default**, cached,
  gate-safe.
- **Zones** = static `primary_zone`, or VLM-labelled for product cams when enabled (Store_2 `zone` →
  `skincare_aisle`).
- **Two run modes (ADR-0033):** default `docker compose up` = **replayer** POSTs the committed
  `data/events/behavior.jsonl` (seconds, no YOLO/keys — the gate path); `--profile detect` (or
  `DETECTOR_MODE=detect`) runs the full pipeline and regenerates events.
- **API** (`services/api`): idempotent `POST /events/ingest`; per-store `GET /stores/{id}/{metrics,funnel,
  heatmap,anomalies}`, `GET /stores`, `/health`, Prometheus `/metrics`. Staff excluded (any-flag);
  honest zeros + dormant anomalies; POS for **ST1008 only**.
- **Frontend**: store switcher (polls only the visible store, 4 s); conversion ring, funnel, heatmap,
  anomalies, health, POS (top_brand/top_department/peak_hour).
- **Stores:** **ST1008** Brigade (POS, ~2 customers GT) · **ST1009** Store_2 (no POS; busy, 22 cust + 3
  staff GT). Adding a store = drop `stores/<id>.py` + a clips folder (ADR-0028).

## Headline results (honest)

- **Store_1 (ST1008):** unique customers = **2** (grey + violet on CAM2), funnel 2→2→0→0, conversion **0%**
  on the 2-min clip (`data_confidence=low`; no sale in the window — demonstrated separately via
  `demo_conversion.py`). POS day KPIs: **24 txns, ₹34,331.71**, top brand Faces Canada, top dept makeup.
  ⚠ **Must re-validate** under the new global detector defaults (imgsz 768 / fps 10) on a full `detect` run.
- **Store_2 (ST1009):** **~23 unique vs 25 ground truth** (per-camera BILLING=6/ENTRY1=5/ENTRY2=8/ZONE=7).
  Staff/customer split via VLM is **approximate** (overhead CCTV hides uniforms → crop-sensitive). Proof
  images: `docs/wiki/frames/store2_entrance_lines.jpg`, `store2_customers_staff.jpg`.

## Recent decisions (newest first → see [[DECISIONS]])

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

**Single next action:** run the full **`--profile detect`** pipeline on **both stores** with the current
defaults (imgsz 768 / fps 10) to (a) **re-validate Store_1's 2-customer baseline**, (b) regenerate the
committed `events.jsonl` + VLM cache for replay, then do a clean-machine `docker compose down -v && up
--build` gate dry-run.

Known limits (documented, not bugs): staff/customer split is camera-angle-limited on overhead CCTV;
Store_2 count is ~8% under (weak colour-histogram Re-ID on a crowd — a learned embedding would close it);
Store_2 has no POS → conversion N/A. Deferred: demographics/groups (full-face-blurred footage, D4).
