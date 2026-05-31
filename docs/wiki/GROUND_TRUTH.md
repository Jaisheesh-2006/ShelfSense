# GROUND TRUTH — facts distilled from `docs/raw/`

> The assistant's factual understanding of the raw inputs, in its own words. This is the
> foundation the rest of the wiki is built on. **Re-derive this file whenever the user
> changes `docs/raw/`**, then propagate changes outward. Do not put speculation here —
> assumptions live in [[PROJECT]]/[[RISKS]]; this file is observed fact only.
>
> Last derived from raw on: 2026-05-31.

## What is in `docs/raw/`

```
docs/raw/
├── Assessment  Evaluation Frameworkb24a398.pdf      # the grading rubric (see §3)
├── Brigade Road - Store layoutc5f5d56.pdf            # store floor plan (see §4)
├── Brigade_Bangalore_10_April_26 (1)bc6219c.csv      # POS sales data (see §2)
└── CCTV Footage/CCTV Footage/
    ├── CAM 1.mp4 … CAM 5.mp4                          # 5 camera clips (see §1)
```

---

## §1. CCTV footage

- **5 cameras**: `CAM 1.mp4` … `CAM 5.mp4`. Five fixed viewpoints of one store, all **1920×1080**.
  Verified specs (via `scripts/extract_frames.py`, OpenCV):
  | File | Resolution | FPS | Frames | Duration | Size |
  |------|-----------|-----|--------|----------|------|
  | CAM 1 | 1920×1080 | 29.97 | 4193 | 139.9 s | 172 MB |
  | CAM 2 | 1920×1080 | 29.97 | 3774 | 125.9 s | 155 MB |
  | CAM 3 | 1920×1080 | 29.97 | 4436 | 148.0 s | 182 MB |
  | CAM 4 | 1920×1080 | 24.98 | 3647 | 146.0 s | 70 MB |
  | CAM 5 | 1920×1080 | 24.98 | 3465 | 138.7 s | 70 MB |
- **Time-synchronized:** on-screen timestamps are all ~**20:10–20:11 on 10/04/2026** (matches the
  CSV date). So the clips are a **~2-min concurrent evening window**, watermark "CP IP Cam".
- **Camera → store area** (from inspecting mid-clip frames in `docs/wiki/frames/`):
  | Cam | Area | Pipeline role |
  |-----|------|---------------|
  | CAM 1 | Sales floor — skincare wall + browsing tables | product/browse zone |
  | CAM 2 | Makeup wall (Lakme, Faces Canada, Maybelline); a **group of 3** browsing | product/browse zone; group-entry edge case |
  | **CAM 3** | **Store ENTRANCE** — glass door, Purplle standee, mall corridor outside | **footfall line-crossing (linchpin)** |
  | CAM 4 | **Back room / stockroom** — boxes, water dispenser, stool | **staff-only; exclude from footfall** |
  | CAM 5 | **Checkout / billing counter** — POS desk, laptop, carry bags | checkout activity + funnel end |
- **Funnel maps onto cameras:** Entered (CAM 3) → Browsed (CAM 1/2) → Checkout (CAM 5) → Purchased (POS CSV).
- **No cross-camera re-ID by default:** views are different areas (little overlap), so a single
  shopper is not followed entrance→checkout without re-ID. v1 funnel = **aggregate per-zone
  session counts**, not per-person linking. Documented tradeoff (see [[DECISIONS]] PD-5).
- **Implication:** footfall = entry/exit counting on **CAM 3**. CAM 4 detections are staff.
  Reference frames saved at `docs/wiki/frames/CAM_*_{10,50,90}pct.jpg`.
- **Entrance line (calibrated, Slice 2.0):** on CAM 3 the counting line runs along the **front
  edge of the retail wood floor**: `(320,490) → (1140,415)`, `inside_sign=-1` (upper-left wood =
  inside, lower-right dark threshold/mall = outside). Crossing onto the wood = entering the
  shopping area. Defined in `shelfsense_common.contracts.zones` (`STORE`); overlay saved at
  `docs/wiki/frames/CAM3_entrance_calibration.jpg`. **Refine in Slice 2.2** by overlaying real tracks.

## §2. Business CSV — POS sales transactions

- **Store:** `store_id = ST1008`, `store_name = Brigade_Bangalore`, `city = Bangalore`.
  A **Purplle** beauty retail store.
- **Date:** all rows `10-04-2026`. **Time span 12:15:05 → 21:39:55** (≈ store open window that day).
- **Grain:** one row = **one product line item**. Rows sharing an `order_id` / `invoice_number`
  = one **transaction/basket**.
- **Aggregates (observed):**
  - 101 line items
  - **24 unique orders = 24 unique invoices = 24 transactions**
  - **21 unique customer numbers** (caveat: "Guest" rows use placeholder numbers like
    `1000000000` and repeated guest numbers — so unique-customer ≠ unique-transaction exactly)
  - Total GMV ₹44,920
  - Department mix: makeup (54), skin (27), bath-and-body (9), hair (6), personal-care (4), fragrance (1)
- **Key columns:** `order_id`, `invoice_number`, `invoice_type` (all `sales` here; `return_id`
  column exists for returns), `order_date`, `order_time`, `store_id`, `store_name`, `city`,
  `customer_name`, `customer_number`, `sku`, `product_id`, `product_name`, `brand_name`,
  `dep_name`, `sub_category`, `qty`, `GMV`, `NMV`, `total_amount`, `salesperson_name`, …
- **Why it matters:** this is the **conversion numerator source**. `transactions = count(distinct order_id)`.
  Conversion rate = transactions ÷ footfall (footfall comes from CCTV). Also enables
  basket size, peak-hour sales, salesperson/department breakdowns.

### ⚠️ The window-mismatch fact
The video is **~2 minutes per camera**; the CSV covers a **full ~9.5-hour trading day**.
They are **not the same time window**, so conversion cannot be computed by naively dividing
full-day transactions by 2-min footfall. This is the central real-world ambiguity. Handling
options (decision pending, see [[DECISIONS]] PD-3): treat the clip as a representative sample
window; or compute footfall-rate and conversion-rate per comparable window; or demonstrate the
pipeline on the clip while documenting how it would run over full-day footage. **Must be stated
explicitly** — silently dividing mismatched windows would be wrong and looks naive to reviewers.

---

## §3. Evaluation rubric (the PDF) — authoritative grading

**Philosophy:** end-to-end system problem, not model building. Rewards functional correctness,
engineering judgment, clarity of reasoning. "A strong candidate builds a system that works,
makes reasonable trade-offs, and can explain them."

**Acceptance Gate (mandatory — fail any → rejected before scoring):**
- `docker compose up` runs **without manual intervention**
- `/metrics` endpoint returns a valid response
- Detection pipeline produces **structured events**
- **`DESIGN.md` and `CHOICES.md`** present and non-trivial
- System does not crash during basic execution

**Reviewer time budget (~10 min):** 2m run+verify API · 2m inspect events · 3m validate API
outputs · 2m read DESIGN/CHOICES · 1m score.

**Scoring (100 marks):**
| Bucket | Marks | Strong = |
|--------|-------|----------|
| Detection Pipeline | 30 | entry/exit close to actual; handles re-entry, staff, group entry; structured/consistent events |
| **API & Business Logic** | **35** | all endpoints correct & consistent; **funnel session-based, no double counting**; anomaly detection logical & meaningful |
| Production Readiness | 20 | `docker compose up` seamless; observability (logs, metrics, tracing); testing covers key scenarios + edge cases |
| Engineering Thinking | 15 | CHOICES.md clear trade-offs; DESIGN.md clear architecture; independent reasoning |

**Validation reviewers run:** sample clip entry-count vs system output · inspect event schema ·
`/metrics` logically consistent · `/funnel` shows expected drop-off.

**Integrity check:** hardcoded outputs / outputs not varying with input / lack of real
computation → **score capped at 50**.

**Shortlisting:** 85+ strong, 70–85 interview, 60–70 above average. Top 30 selected.
**Tie-breakers:** edge-case handling, cleaner/maintainable design, stronger grasp of the
business metric, clear reasoning.

---

## §4. Store layout (floor plan)

Source: `docs/raw/Brigade Road - Store layout….pdf`. Top-down 2D plan with dimensions in mm.
Two variants: **"Current"** (matches the 10-Apr-2026 footage — use this) and **"Revised"**
(future re-merchandising — ignore for now). The plan is the **canonical source of zones** — we
no longer invent/hand-draw zones; we use the store's actual zones.

- **Shape:** long narrow store, ~6.4 m × ~4 m. Glass door **entrance on the left**; cash counter
  on the **right**.
- **Top wall — skincare gondola (→ CAM 1):** `EB · TFS · GV · DermDoc · Minimalist · Aqualogica · Pilgrim · D&K`.
- **Bottom wall — makeup gondola (→ CAM 2):** `Maybelline · Faces · Lakme · Swiss+Renee · Mars+Nybae · Alps · L'Oréal · Beauty Essentials`.
- **Center F.O.H (Front of House):** Fragrance/Nail unit + two **Makeup Unit** tables (browsing tables seen in CAM 1/2).
- **Right end (→ CAM 5):** **Cash Counter** (checkout) + **Accessories** bay.
- **Stockroom (CAM 4):** not on the plan — separate back room, staff-only.

**Canonical zones (v1):** `entrance` (CAM 3) · `skincare_aisle` (CAM 1) · `makeup_aisle` (CAM 2) ·
`foh_center` (makeup-unit/fragrance tables) · `checkout` (CAM 5) · `accessories` (CAM 5) ·
`stockroom` (CAM 4, excluded). Brand bays above are available as finer sub-zones later.

## What this implies for us (carried into the rest of the wiki)

- Footfall counting (entry/exit) on the **entrance camera** is the linchpin of both Detection
  (30) and conversion. Identify that camera first.
- The funnel and `/metrics` correctness is the **largest scored bucket (35)** — invest there.
- Everything must **compute from input** (integrity cap). No hardcoded numbers anywhere.
- Ship a **one-command, non-crashing, observable** demo; write strong DESIGN.md + CHOICES.md.
- Document the window-mismatch assumption prominently — it's exactly the "real-world ambiguity"
  the rubric rewards.
