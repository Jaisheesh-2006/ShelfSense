# RISKS

> Known risks, unknowns, mitigations. Surfacing risks is part of the engineering judgment
> graded by the rubric. Facts in [[GROUND_TRUTH]]; pending decisions (PD-*) in [[DECISIONS]].

| ID | Risk | Impact | Likelihood | Mitigation |
|----|------|--------|------------|------------|
| R-1 | **Acceptance-gate failure** (`docker compose up` needs manual steps, `/metrics` missing, no DESIGN.md/CHOICES.md, crash) | **Rejected before scoring** | Med | Treat gate as P0: one-command compose, healthchecks, `/metrics` early, generate DESIGN/CHOICES (ADR-0003). |
| R-2 | **Integrity cap** — outputs hardcoded or invariant to input | **Score capped at 50** | Med | Everything computes from input; vary visibly with clip; no magic constants. |
| R-3 | **Window mismatch** (2-min video vs full-day CSV) handled naively | Misleading conversion; looks naive | High | Document assumption (A3); comparable-window or representative-sample approach (PD-3). |
| R-4 | Unknown which camera is entrance/checkout; views may not overlap | Wrong footfall & zones | High | Inspect one frame per camera first ([[STATE]] next action); define zones from that. |
| R-5 | Occlusion / crowding / group entry break tracking → ID switches | Bad footfall & sessions (Detection 30) | High | Robust tracker (PD-2); tune association; handle group entry; document limits in [[EDGE_CASES]]. |
| R-6 | Staff counted as customers (salespersons present all day) | Inflated footfall, wrong conversion | Med | Exclude staff where detectable (dwell/position heuristics); document. |
| R-7 | Funnel double-counts (per-detection not per-session) | Loses the 35-mark bucket | Med | Session-based funnel, each session once per stage ([[BUSINESS_RULES]]). |
| R-8 | Streaming backbone setup friction for reviewers | Gate risk (R-1) | Med | **Resolved (ADR-0005):** no broker — the detector POSTs events to `/events/ingest` (idempotent); one-command compose. |
| R-9 | ffprobe/ffmpeg unavailable locally → unknown video specs | Slows zone/entry work | Low | Use OpenCV inside detector container; record specs in [[GROUND_TRUTH]]. |
| R-10 | No floor plan in `raw/` | Homography zone mapping harder | Med | Define zones manually per camera frame (PD-4). |
| R-11 | Over-engineering vs. timeframe | Incomplete end-to-end system | Med | Ship thin vertical slice first (CLAUDE.md Principle 1), then deepen ([[TASKS]]). |
