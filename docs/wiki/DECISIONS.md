# DECISIONS (ADR log)

> Architecture Decision Records. Every major decision: context, decision, alternatives,
> tradeoffs, rationale. **This file is the source for the graded `CHOICES.md`** (see ADR-0003).

---

## ADR-0001 — Event-driven, service-separated architecture
- **Date:** 2026-05-31 · **Status:** Accepted
- **Context:** Rubric rewards end-to-end system thinking and structured events over ML.
  Pipeline decomposes into detect → track → analyze → serve.
- **Decision:** Four services (detector, tracker, analytics, api) over a Kafka-compatible
  event stream; Postgres + Redis; React frontend; Docker Compose; Prometheus/Grafana.
- **Alternatives:** Monolith (simpler, but hides service-separation & event thinking the rubric
  wants); heavy microservice mesh (unnecessary complexity for the timeframe).
- **Tradeoffs:** More moving parts/contracts vs. clear responsibilities, replayable events,
  demonstrable design. Mitigate setup risk via one-command compose (gate requirement).
- **Rationale:** Matches rubric + CLAUDE.md principles.

---

## ADR-0002 — LLM wiki as the source of truth (Karpathy pattern)
- **Date:** 2026-05-31 · **Status:** Accepted
- **Context:** User wants complete context restored every session via a knowledge base the
  assistant owns, derived from raw inputs the user owns. This is context engineering.
- **Decision:** `docs/wiki/` is the assistant's synthesized understanding (plain markdown,
  cross-linked, stateful), bootstrapped by [[README]] and grounded by [[GROUND_TRUTH]];
  `docs/raw/` stays user-owned source material.
- **Alternatives:** RAG/vector DB (stateless, re-derives each query, heavier infra);
  ad-hoc notes (don't compound).
- **Tradeoffs:** Small upkeep cost (write understanding back each session) for compounding,
  instantly-loadable context.
- **Rationale:** Directly serves the user's session-bootstrap goal; 70x lighter than RAG infra.

---

## ADR-0003 — DESIGN.md & CHOICES.md are generated deliverables, distinct from the wiki
- **Date:** 2026-05-31 · **Status:** Accepted
- **Context:** The rubric's acceptance gate **requires `DESIGN.md` and `CHOICES.md`** (exact
  names) and grades them (Engineering Thinking, 15). CLAUDE.md prescribes a wiki using
  `ARCHITECTURE.md`/`DECISIONS.md`. These are different artifacts for different readers.
- **Decision:** Keep the internal wiki as-is (assistant's working knowledge). Generate the two
  **submission deliverables at repo root**: `DESIGN.md` ← distilled from [[ARCHITECTURE]];
  `CHOICES.md` ← distilled from this file. Generate/refresh them before submission.
- **Alternatives:** Rename wiki files to DESIGN/CHOICES (loses the richer wiki structure CLAUDE.md
  wants); maintain both by hand independently (drift risk).
- **Tradeoffs:** One generation step before submission vs. clean separation of internal vs.
  reviewer-facing docs.
- **Rationale:** Satisfies the gate exactly while preserving the LLM-wiki workflow.

---

## ADR-0004 — Tech & approach decisions (PD-1…PD-5), accepted

- **Date:** 2026-05-31 · **Status:** Accepted (user approved all recommendations)

| PD | Decision | Alternatives rejected | Rationale |
|----|----------|----------------------|-----------|
| **PD-1** Streaming backbone | **Redpanda** (Kafka-API compatible, single binary, KRaft) | Apache Kafka (heavier startup), Redis Streams shim (weaker semantics) | Kafka-compatible + low setup friction for one-command `docker compose up` (gate) |
| **PD-2** Tracker | **ByteTrack via Ultralytics** | OC-SORT, DeepSORT/BoT-SORT (heavier, appearance models) | Ships with YOLO, fast, CPU-runnable, strong enough for crowd/occlusion at our scale |
| **PD-3** Conversion window | Compute footfall on the **clip window** (cams synced ~20:10 evening); report conversion vs a **comparable transaction window**; document full-day extrapolation | Naive full-day txns ÷ clip footfall | Honest, non-misleading; rewards the "real-world ambiguity" the rubric values |
| **PD-4** Zones | **Use the floor plan** ([[GROUND_TRUTH]] §4) as the canonical zone map. v1 = **camera-level** zone assignment (each camera ≈ one primary zone) — **no hand-drawn polygons**. Brand bays available as finer sub-zones later. | Hand-drawn arbitrary polygons (rejected — user provided the real layout); full homography per camera (deferred — heavier calibration) | Floor plan removes guesswork; camera-level assignment is simple, robust, and fits PD-5 |
| **PD-5** Multi-camera | **Independent cameras** for v1; footfall from CAM 3; funnel = **aggregate per-zone session counts** (no cross-camera re-ID) | Cross-camera re-ID (heavier; needed only for per-person journeys) | Views are distinct areas; avoids premature complexity |

- **Tradeoffs:** v1 funnel counts sessions per zone-camera rather than following one shopper
  end-to-end (no re-ID). Acceptable and documented; re-ID is a clear future extension.
- All reflected in CHOICES.md at submission (ADR-0003).
