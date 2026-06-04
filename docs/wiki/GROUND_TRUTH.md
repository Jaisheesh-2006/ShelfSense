# GROUND TRUTH — facts distilled from `docs/raw/`

> The assistant's factual understanding of the raw inputs, in its own words. This is the
> foundation the rest of the wiki is built on. **Re-derive this file whenever the user
> changes `docs/raw/`**, then propagate changes outward. Do not put speculation here —
> assumptions live in [[PROJECT]]/[[RISKS]]; this file is observed fact only.
>
> Last derived from raw on: **2026-06-02** (the team replaced the dataset — see §0).

## §0. ⚠️ The dataset changed (2026-06-02) — read this first

The user flagged data flaws in the **original** dataset (a single detailed Brigade store that
didn't match the problem-statement PDF, no `sample_events.jsonl`, etc.). The team responded with a
**corrected dataset**, now in `docs/raw/`; the old files were removed. The headline consequences:

- The PDF's **"Apex Retail / 40 stores" framing is real**, not a print mistake. The earlier theory
  (recorded in the old [[SPEC]]) that the PDF dataset description was an error is **wrong and retired**.
- **`sample_events.jsonl` now exists** — and its schema is **richer than and different from** the PDF's
  page-5 "Required Output Schema" (the flat schema our code emits). This is a genuine tension to resolve
  (see §5 and [[EVENT_SCHEMA]]).
- There are **two stores now** (Store_1, Store_2), not one. **Store_1 is the same physical store as the
  old data** (identical clip durations); **Store_2 is brand new**.
- The **POS file is a different, simpler format** (7 columns) and a different money total.
- `store_layout.json` and `assertions.py` are named by the PDF but **not provided as code/JSON** — we
  derive zones from the **layout PNGs** (provided for both stores) and self-validate with 138 unit tests.

## What is in `docs/raw/` (current)

```
docs/raw/
├── Assessment  Evaluation Frameworkb24a398.pdf      # grading rubric (UNCHANGED — see §3)
├── Purplle_Tech_Challenge_PS3f02573.pdf             # NEW problem statement (12 pp — see §5)
├── POS - sample transactionsb1e826f.csv             # POS sample, 7-col (see §2)
├── sample_eventsbe42122.jsonl                       # 13 example events, richer schema (see §5)
└── Store_CCTV_Clips/
    ├── Store_1/Store 1/   CAM 1 - zone · CAM 2 - zone · CAM 3 - entry · CAM 5 - billing · Store 1 - layout.png
    └── Store_2/Store 2/   entry 1 · entry 2 · zone · billing_area · store 2 - layout.png
```

---

## §1. CCTV footage — TWO stores now

Cameras are now **named by role** in the filenames (no more guessing entrance/checkout/aisle).
Verified specs via OpenCV (`scripts/extract_frames.py`-style probe):

**Store_1** — 1920×1080, **the same physical store as the old single-store data** (clip durations
match the old CAM 1/2/3/5 exactly), now with role labels and **no stockroom camera** (old CAM 4 dropped).
| File | Role | Resolution | FPS | Frames | Duration |
|------|------|-----------|-----|--------|----------|
| CAM 1 - zone | sales floor (skincare wall) | 1920×1080 | 29.97 | 4193 | 139.9 s |
| CAM 2 - zone | sales floor (makeup wall) | 1920×1080 | 29.97 | 3774 | 125.9 s |
| CAM 3 - entry | **entrance** (glass door, mall corridor) | 1920×1080 | 29.97 | 4436 | 148.0 s |
| CAM 5 - billing | **checkout / billing counter** | 1920×1080 | 24.98 | 3465 | 138.7 s |

**Store_2** — **NEW store**, portrait-ish **960×1080**, 25 fps, ~1.5–2-min clips. Different camera
set: **two entry cameras** plus a floor and a billing view.
| File | Role | Resolution | FPS | Frames | Duration |
|------|------|-----------|-----|--------|----------|
| entry 1 | entrance #1 | 960×1080 | 25.00 | 2636 | 105.4 s |
| entry 2 | entrance #2 | 960×1080 | 25.00 | 2129 | 85.2 s |
| zone | main floor | 960×1080 | 25.00 | 2898 | 115.9 s |
| billing_area | checkout / billing | 960×1080 | 25.00 | 3126 | 125.0 s |

- **Clips are still ~2 minutes**, *not* the "20 minutes per clip" the PDF describes (§5). The PDF's
  dataset spec is aspirational/generic; the actual delivered clips are short. **The window mismatch with
  the full-day POS therefore still holds** (§2).
- **Time-synchronized (Store_1):** burnt-in timestamps ~**20:10–20:11 on 10/04/2026** (matches the POS
  date), watermark "CP IP Cam" — a concurrent evening window. (Store_2 sync window not yet read frame-by-frame.)
- **People in Store_1 (verified ground truth — same clips):** across the cameras there are **2 customers
  (grey + violet tops) + 5 staff (complete black uniform) = 7 people**. Staff signal = the VLM-baseline +
  `black` colour-override hybrid ([[DECISIONS]] ADR-0009/0032/0034). **Local detection result:** unique
  people **7 ✓**, ENTRY/EXIT/REENTRY **0 ✓** (nobody crosses the line; REENTRY fixed by ADR-0035). Staff
  split **4/3 vs the true 5/2** — one staffer (violet-ish top, **colour 0.22**, badly under-exposed crop)
  reads as a customer; the VLM was unsure too. A genuine marginal call on overhead CCTV (user-adjudicated).
  CAM 5 has a **mirror / backlit display** that double-detects (walkable-floor mask, ADR-0010); the
  entrance view is dominated by **mall-corridor pass-by**, filtered by the entrance line + quality gate
  (ADR-0029). Store_2 staff instead wear **bright pink** (`staff_heuristic_color="pink"`).
- **People in Store_2 (user-provided ground truth, watching the footage — authoritative):**
  **22 unique customers + 3 staff** across the store (Re-ID-deduped headline). Per-camera observations
  (flows, not unique counts):
    - **billing_area:** 5 people — **2 staff + 3 customers** (2 customers linger at the counter; 1 person
      just passes through).
    - **entry 1:** 1 person inside; flows of customers entering/exiting (≈2 enter, 2 exit, 1 enter,
      2 exit); 1 staff.
    - **entry 2:** ~6 people enter; 1 staff already present; 1 customer exit; 2 customers enter; 1 staff arrives.
    - **zone:** 1 staff; 2 customers come, then 3 customers; 1 staff; 1 person enters the staff room.
  Headline to validate the pipeline against: **22 customers, 3 staff (25 people total)** — a *busy* store
  vs Store_1's 2 customers, which stresses Re-ID de-duplication. Store_2 has **no POS** (no conversion).
  - **Pipeline result (local detection, ADR-0037 motion stitching on; ADR-0030/0034/0035/0036):** the
    detector reaches **22 unique people** (17 customers + 5 staff; per-camera BILLING 7 / ENTRY1 4 /
    ENTRY2 11 / ZONE 6) with **footfall ENTRY 11 · EXIT 5 · REENTRY 2**. Exact counts are run-config-dependent.
  - **⚠ History — user crop-adjudication (2026-06-04) showed the earlier "~23 ≈ 25" was a coincidence.**
    Dumping one labelled crop per visitor revealed three distinct detection errors that roughly cancelled in
    the headline number:
    1. **Re-ID over-split (was dominant):** one moving pink-uniform staffer was split into **4** visitor_ids
       on a single camera (front/back), another into 2 — appearance Re-ID can't match the same person across
       views on overhead CCTV (same-person crops are *farther* apart than different-person crops; **ADR-0036**).
    2. **Group under-detection:** 2 tightly-packed shoppers detected as **1** track — YOLO merges adjacent
       people on overhead views. Deflates the count.
    3. **Under-detection / pass-by:** a few real shoppers never form a solid track; the entrance lines are the
       frame-verified door-threshold calibration (a tried ~30px inward tightening over-excluded near-door
       customers — 23→18 — and was reverted, ADR-0037 notes).
  - **✅ Tracking-based association (ADR-0037) fixed the dominant error.** A per-camera motion tracklet-stitch
    (run *before* the appearance gallery) collapses fragmented ids by spatio-temporal continuity, not pixels.
    Result: the **within-camera over-split is largely resolved** — the ZONE staffer that was **4 ids is now 1**;
    ENTRY2 lands **exactly 8 customers** (GT ~8) and BILLING **exactly 2 staff** (GT 2); and **footfall now
    matches GT** (11 entries / 5 exits). The remaining gap to 25 is two errors *outside* association: **group-
    merge** (customers 17 vs 22, a detection limit) and **cross-camera staff duplication** (staff 5 vs 3 — a
    roaming staffer seen on ENTRY2+ZONE+BILLING is minted per camera; cross-camera dedup still leans on the
    measured-ambiguous appearance Re-ID). Per-camera identity quality is now materially cleaner; the honest
    store-wide output is still a **head-count band + per-camera figures**.
  - **The two residual errors were each addressed on their merits (2026-06-04):**
    - **Group-merge (customers 17 vs 22):** an opt-in **pose splitter** (`GROUP_SPLIT="pose"`, YOLOv8-pose
      splits a wide merged box per skeleton; ADR-0038) was built and **A/B-measured → no net gain** (Store_2
      unique 22→22). A frame probe shows why: overhead groups stand **front-to-back**, so a merged pair is a
      *tall* box (median `w/h` 0.33; only ~5% exceed the width gate), and pose keypoints degrade under
      occlusion — the **same limit** that made imgsz-960 useless. Kept as a tested, off-by-default capability;
      the gap stays a documented overhead-CCTV detection limit.
    - **Cross-camera staff duplication (staff 5 vs 3):** the textbook fix — a floor-plane **homography** so
      motion association spans cameras — is **not feasible on this dataset (ADR-0039):** Store_2's cams are
      non-overlapping AND recorded on different real days (no true time-sync), so a spatio-temporal merge
      would *fabricate* identities (integrity risk). Appearance won't help either (measured-ambiguous,
      ADR-0036). Decided to **skip + document**; its only effect (staff +2) is within the accepted ±1–2.
    Proof images: `docs/wiki/frames/store2_entrance_lines.jpg`, `store2_customers_staff.jpg`,
    `data/crops/montage_*.jpg`.
- **Anonymisation (PDF §3.2):** full-face blur on every frame, store branding masked, no audio. Faces are
  unusable → Re-ID must be appearance/trajectory-based (which ours is), and any gender/age signal in
  `sample_events.jsonl` (§5) cannot come from clear faces.

## §2. POS sales — new simpler format

File: `POS - sample transactionsb1e826f.csv`. **7 columns** (much simpler than the old 20-column
Purplle export):
`order_id, order_date, order_time, store_id, product_id, brand_name, total_amount`.

- **Store:** `store_id = ST1008` for **every** row (so the POS covers **one** store — presumably Store_1;
  **Store_2 has no POS data**).
- **Date:** all `10-04-2026`. **Time span 12:15:05 → 21:39:55** (full trading day).
- **Grain:** one row = **one product line item**. `order_id` is now **unique per row (1…101)** — it is
  *not* the basket key anymore. **Rows sharing an `order_time` = one basket/transaction.**
- **Aggregates (computed):**
  - **101 line items**
  - **24 distinct `order_time` values = 24 transactions/baskets** (matches the prior "24 transactions")
  - **Total `total_amount` = ₹34,331.71** (≠ the old GMV ₹44,920 — different column/figure; this file has
    no GMV/NMV split). **10 line items are ≤ ₹1** (mostly `Purplle`-branded freebies/promos).
  - Brand mix (line items): Faces Canada 32 · Good Vibes 14 · Purplle 10 · NY Bae 10 · DERMDOC 6 · GUBB 3 · …
  - Peak hours by line items: **12:00 and 19:00 (tied, 27 each)**.
  - **Department rollup** (brands → categories, ADR-0025): by basket — makeup 14 · skincare 5 ·
    bath_and_body 2 · personal_care 1 · haircare 1 · other 1. **top brand Faces Canada · top dept makeup.**
    No `dep_name` column exists anymore — we derive departments from `brand_name` via a curated taxonomy
    grounded in the store's old `dep_name` values + the layout (see [[DECISIONS]] ADR-0025, `departments.py`).
- **PDF's documented POS schema differs again:** the PDF (§5) shows `store_id, transaction_id, timestamp,
  basket_value_inr` with ISO-8601-Z timestamps. The **actual CSV** uses `order_id` + split `order_date`/
  `order_time` (local, no tz) + `total_amount`. So three POS shapes have existed; **build to the real CSV.**
- **Why it matters:** conversion **numerator source**. `transactions = count(distinct order_time)`.
  Conversion correlates a billing-zone visitor to a transaction by the **time-window + store** rule (§5).
- **✅ Code updated:** `pos_loader.py` has been reworked for the 7-col CSV (basket = distinct
  `order_time`, value = Σ `total_amount`; ADR-0024/D3). The `department` field is derived from
  `brand_name` via a curated taxonomy in `departments.py` (ADR-0025).

### ⚠️ The window-mismatch fact (still true)
Clips are **~2 minutes**; the CSV covers a **full ~9.5-hour day**. They are **not the same window**, so
conversion can't be a naive full-day-txns ÷ clip-footfall divide. We report the honest clip conversion and
demonstrate the correlation on a comparable window ([[DECISIONS]] ADR-0012, [[BUSINESS_RULES]]). The PDF's
"20-min clips" would narrow this gap; the **delivered ~2-min clips do not**.

---

## §3. Evaluation rubric (`Assessment … Frameworkb24a398.pdf`) — UNCHANGED

This file is byte-identical to the prior dataset's rubric. Re-confirmed contents:

**Philosophy:** end-to-end system problem, not model building. Rewards functional correctness,
engineering judgment, clear reasoning.

**Acceptance Gate (fail any → rejected before scoring):** `docker compose up` runs without manual
intervention · `/metrics` returns a valid response · pipeline produces **structured events** ·
**`DESIGN.md` and `CHOICES.md`** present and non-trivial · system does not crash.

**Reviewer time budget (~10 min):** 2m run+verify · 2m inspect events · 3m validate API · 2m read
DESIGN/CHOICES · 1m score. Two reviewers per submission.

**Scoring (100):** Detection 30 · **API & Business Logic 35** · Production 20 · Engineering Thinking 15.

**Integrity check:** hardcoded outputs / outputs not varying with input / lack of real computation →
**score capped at 50**.

**Shortlisting:** 85+ strong · 70–85 interview · 60–70 above average · **top 30** selected. Tie-breakers:
edge-case handling, cleaner design, stronger grasp of the business metric, clear reasoning.

> The full *problem statement* (parts A–E breakdown, schema, endpoints, edge cases, North Star) is the
> separate `Purplle_Tech_Challenge_PS` PDF — digested in [[SPEC]] (§5 below summarises the data-relevant bits).

---

## §4. Store layouts (per-store PNGs)

Source: `Store 1 - layout.png` and `store 2 - layout.png` (top-down plans; the old layout *PDF* is gone).
These are the **canonical zone source** — we use the store's real zones, not hand-drawn ones.

- **Store_1** (same as the old Brigade plan): long narrow store, glass **entrance on the left**, **cash
  counter on the right**. Top wall = **skincare gondola** (Salm/TFS/…/Minimalist/Aqualogica/Foxtale/JC →
  CAM 1). Bottom wall = **makeup gondola** (Faces/Mars+NYBae/Mens/L'Oréal/Beauty → CAM 2). Centre = **F.O.H**
  (Fragrance/Nail unit + two **Makeup Unit** tables). Right end = **Cash Counter** + **Accessories** (CAM 5).
- **Store_2** (new, larger): **entrance at the bottom-centre** (storefront glazing), **B.O.H (back of house)
  top-right**, perimeter **wall units (1–13)**, two angled centre gondolas, a **central cash counter**, and
  an **F.O.H** makeup area on the right. More zones than Store_1.

**Canonical zones (v1, Store_1):** `entrance` (CAM 3) · `skincare_aisle` (CAM 1) ·
`makeup_aisle` (CAM 2) · `foh_center` · `checkout` + `accessories` (CAM 5). **Store_2 zones:** defaults
assigned by camera role, with the VLM (ADR-0027) auto-relabelling from visible shelves/signage when
enabled (e.g., `makeup_aisle → skincare_aisle` for the zone cam).

## §5. New problem statement PDF + `sample_events.jsonl` (the schema tension)

**`Purplle_Tech_Challenge_PS` PDF (authoritative for WHAT to build — digested in [[SPEC]]):**
- Business framing: **Apex Retail, 40 stores / 8 cities**; offline stores are a data blind spot.
- Dataset *as described*: 5 stores × 3 cams × **20 min**, + `store_layout.json` + `pos_transactions.csv`
  + `sample_events.jsonl` (200 events) + `assertions.py` (10 example tests). **Delivered reality differs**
  (2 stores, 4 cams, ~2-min clips, layout PNGs, a 7-col POS, 13 sample events, no JSON layout, no assertions).
- **Page-5 "Required Output Schema" = the flat event** `{event_id, store_id, camera_id, visitor_id,
  event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, metadata{queue_depth, sku_zone,
  session_seq}}` with **8 event types** (ENTRY, EXIT, ZONE_ENTER, ZONE_EXIT, ZONE_DWELL,
  BILLING_QUEUE_JOIN, BILLING_QUEUE_ABANDON, REENTRY). **This is exactly what our code emits.**
- 6 endpoints, the 7 edge cases, the 5-min billing-window conversion rule, Parts A–E + bonus — all in [[SPEC]].

**`sample_events.jsonl` (13 events; "to help you validate your detection layer") — a DIFFERENT, richer
schema** from a sample store (`store_1076` / `ST1076`, Mumbai, 2026-03-08; just illustrating the format).
It is **internally inconsistent** (field names differ across event types) and **does not match the page-5
schema**. Three observed shapes:
- **entry / exit:** `event_type`(lowercase), `id_token`, `store_code`, `camera_id`, `event_timestamp`,
  `is_staff`, **`gender_pred`, `age_pred`, `age_bucket`, `is_face_hidden`, `group_id`, `group_size`**.
- **zone_entered / zone_exited:** `track_id`, `store_id`, `camera_id`, `zone_id`, **`zone_name`,
  `zone_type`(SHELF/DISPLAY/BILLING), `is_revenue_zone`**, `event_time`, **`zone_hotspot_x/y`**, `gender`, `age`.
- **queue_completed / queue_abandoned:** `queue_event_id`, `track_id`, …, **`queue_join_ts`,
  `queue_served_ts`(null if abandoned), `queue_exit_ts`, `wait_seconds`, `queue_position_at_join`,
  `abandoned`**, hotspot, demographics.

→ **Decided (ADR-0024 D1 — keep the flat schema):** the PDF's page-5 schema (what we built and what the
*gate example* uses) is the emitted/ingested contract; the provided sample (richer: demographics, groups,
zone metadata, queue analytics, hotspots) is **informational only** — it is internally inconsistent and from
a different sample store, so we document it but do not adopt it. See [[EVENT_SCHEMA]] and [[DECISIONS]] ADR-0024.

## What this implies for us (carried into the rest of the wiki)

- Our emitted schema already matches the PDF's **page-5 Required Output Schema** — the authoritative,
  gate-referenced one. The richer `sample_events.jsonl` is informational; we kept the flat schema (ADR-0024/D1).
- **Two stores processed**: the API is per-store; the **detection pipeline processes both stores**
  (Store_1 ST1008 + Store_2 ST1009) via a pluggable store registry (ADR-0028).
- **POS loader reworked** for the new 7-col CSV — conversion KPIs are live for ST1008; ST1009 has no POS
  (→ conversion N/A). Transactions are filtered per-store in the repository layer.
- The big scored bucket is still **API & Business Logic (35)**; integrity cap still applies (compute from
  input). Ship a **one-command, non-crashing, observable** demo with strong DESIGN.md + CHOICES.md.
- Document the window mismatch and the schema tension prominently — they are exactly the "real-world
  ambiguity" the rubric rewards.
