# ShelfSense — Project Context & Engineering Guide

> Operating guide for any AI/engineer working in this repo. Read it fully, then follow the
> **Session Bootstrap** protocol below. Optimize for **engineering quality and reviewer
> outcomes**, not code volume.

---

## 1. What this project is

**ShelfSense** is a **Store Intelligence System** that turns raw retail **CCTV footage** into
business metrics — headline metric: **store conversion rate**. It is the submission for the
**Purplle Store Intelligence Challenge**, graded as an **end-to-end
systems & engineering problem**, not an ML-accuracy problem.

- **Store:** Purplle "Brigade_Bangalore" (store_id `ST1008`), data from **10-Apr-2026**.
- **Raw inputs (in `docs/raw/`, user-owned):** 5 CCTV cameras (~2-min clips), a POS sales CSV
  (24 transactions/day), and the evaluation rubric PDF.
- **Full, current facts:** see `docs/wiki/GROUND_TRUTH.md`. **Never restate data facts from
  memory — read the wiki.**

---

## 2. Role

You are a Staff+ AI/Backend/Systems/MLOps engineer **and** a critical reviewer. Your job is not
to emit code on demand — it is to build a production-quality system that scores highly under the
rubric in `docs/wiki/GROUND_TRUTH.md` §3. Think first. Challenge assumptions, name risks and
tradeoffs, propose better approaches, and own your decisions. Prioritize maintainability,
reliability, observability, simplicity, and **business value**.

---

## 3. Session Bootstrap (context engineering — do this first, every session)

This project uses the **Karpathy LLM-wiki** pattern. The wiki is the stateful, compounding
source of truth. At the start of every session, before acting:

1. Read `docs/wiki/README.md` (the index/bootstrap).
2. Read `docs/wiki/STATE.md` (current phase + the single next action).
3. Read `docs/wiki/GROUND_TRUTH.md` (hard facts from raw — never contradict it).
4. Pull the specific wiki file(s) for the task (they are densely `[[cross-linked]]`).

At the **end** of meaningful work, **write understanding back**: update `STATE.md`, and the
relevant wiki docs, so the next session resumes with full context. Knowledge must compound.

### Ownership contract (do not violate)
- **`docs/raw/`** — user-owned source material. **Read-only**; only add to it if explicitly asked.
- **`docs/wiki/`** — assistant-owned. You read and write it; the user does not edit it. It is
  *your synthesized understanding in your own words*, not a dump of raw.
- When `docs/raw/` changes → re-derive `GROUND_TRUTH.md`, then propagate to the other wiki docs.

### Wiki maintenance rules
- Update `DECISIONS.md` (with alternatives + tradeoffs) whenever a major decision is made.
- Update `ARCHITECTURE.md` on architecture changes; `BUSINESS_RULES.md` on business-logic changes.
- Keep files atomic, dense, and cross-linked. Treat the wiki as the source of truth.

---

## 4. What is being evaluated (drive every decision by this)

Authoritative rubric: `docs/wiki/GROUND_TRUTH.md` §3. Summary:

- **Acceptance gate (fail any → rejected before scoring):** `docker compose up` runs with **zero
  manual steps**; `/metrics` returns a valid response; the pipeline emits **structured events**;
  **`DESIGN.md` and `CHOICES.md`** exist and are non-trivial; no crash.
- **Score weights (100):** Detection 30 · **API & Business Logic 35** · Production Readiness 20 ·
  Engineering Thinking 15. Invest most in the API/business bucket and a runnable, observable demo.
- **`/funnel` must be session-based with no double counting.** `/metrics` must be logically consistent.
- **Integrity cap:** hardcoded or input-invariant outputs → **score capped at 50**. Everything
  must compute from real input and visibly vary with it.
- **Reviewer time ≈ 10 minutes.** Be instantly runnable and legible.

### Graded deliverables vs. wiki
The rubric requires **`DESIGN.md`** and **`CHOICES.md`** (exact names) at repo root. These are
**generated from** the wiki (DESIGN ← `ARCHITECTURE.md`, CHOICES ← `DECISIONS.md`) before
submission. Keep the wiki rich internally; produce these two for reviewers. See ADR-0003.

---

## 5. Architecture (overview — full detail in `docs/wiki/ARCHITECTURE.md`)

Event-driven, service-separated pipeline:

```
CCTV (5 cams) → detector (YOLO) → tracker (MOT + zone map) → analytics (sessions, funnel,
conversion via POS CSV join, anomalies) → api (FastAPI) → frontend (React)
            └──────────── structured events (Kafka-compatible) ────────────┘
            storage: PostgreSQL (events + metrics) · observability: Prometheus + Grafana
```

Each service has one clear responsibility and communicates via versioned events
(`docs/wiki/EVENT_SCHEMA.md`). The entrance camera drives footfall; conversion joins CCTV
footfall with POS transactions (mind the video/CSV window mismatch — `BUSINESS_RULES.md`).

---

## 6. Tech stack

- **Backend:** Python 3.11+, FastAPI, Pydantic v2.
- **Computer vision:** YOLO (Ultralytics), a modern tracker (ByteTrack/OC-SORT/DeepSORT — PD-2), OpenCV.
- **Messaging:** Kafka-compatible event streaming (concrete choice PD-1).
- **Storage:** PostgreSQL.
- **Frontend:** React.
- **Containerization:** Docker + Docker Compose (one-command up).
- **Testing:** Pytest. **Monitoring:** Prometheus + Grafana. **Logging:** structured (JSON).

Prefer these unless a significantly better, justified alternative exists (record it in `DECISIONS.md`).

---

## 7. Repository structure (do not create random directories)

```
docs/
  raw/            # user-owned source material (CCTV, CSV, rubric) — read-only
  wiki/           # assistant-owned living knowledge base (source of truth)
services/
  detector/ tracker/ analytics/ api/    # one responsibility each
frontend/         # React dashboard
tests/            # pytest (unit, edge-case, one integration)
infra/
  docker/         # Dockerfiles + docker-compose.yml
  monitoring/     # Prometheus + Grafana config
scripts/          # ops/dev/demo scripts
DESIGN.md CHOICES.md   # generated submission deliverables (repo root)
```

Shared code (event contracts, config, logging) lives in a common package imported by services —
define event models once (Pydantic) and reuse; do not duplicate contracts.

---

## 8. Coding standards (production-grade)

**Language & types**
- Python 3.11+, **full type hints**; code passes `mypy`. Lint/format with `ruff` (+ `ruff format`).
- **Pydantic v2** models for all external/data contracts (events, API request/response, config).

**Structure & design**
- SOLID where it earns its keep; small, focused, single-responsibility modules.
- Clear, intention-revealing names. Separation of concerns across services and layers.
- No business logic in API route handlers — keep it in service/domain modules (testable).
- Define data contracts once in a shared module; services import them.

**Configuration & secrets (12-factor)**
- All config via **environment variables** (Pydantic `BaseSettings`). No hardcoded secrets,
  hosts, paths, or thresholds. `.env.example` documents every variable. Never commit `.env`.
- Business thresholds (dwell, timeouts) are config, surfaced in `BUSINESS_RULES.md`.

**Errors & resilience**
- Consistent error handling; typed/domain exceptions; a single API error envelope.
- Validate inputs at boundaries. Fail loudly in dev, degrade gracefully in prod.
- Event consumers are **idempotent** (events may duplicate/reorder); reprocessing must not
  double-count (rubric-critical for the funnel).

**Observability (first-class)**
- **Structured JSON logging** in every service, with correlation/trace IDs propagated
  frame → detection → track → session.
- Prometheus `/metrics` per service (throughput, latency, queue depth, counts). Grafana dashboards.

**Testing**
- Pytest: unit tests for business logic; **edge-case tests** (re-entry, staff, group entry,
  occlusion); at least one **end-to-end pipeline integration test**. Deterministic, no network in unit tests.

**Integrity (avoid the score-50 cap)**
- No hardcoded outputs. Every metric computes from input and varies with it. No fabricated numbers
  in code, fixtures-as-results, or stubbed endpoints returning constants.

**Containerization**
- Each service has a Dockerfile; `docker compose up` brings up the full stack from scratch with
  healthchecks and sane startup ordering, **no manual steps**. Pin dependency versions.

---

## 9. Engineering principles

1. A working end-to-end system beats isolated sophisticated components.
2. Clarity over cleverness. 3. Maintainable architecture over short-term hacks.
4. Generate business insights, not raw detections. 5. One clear responsibility per component.
6. Design for future scale; keep the implementation lightweight. 7. Observability is first-class.
8. Avoid unnecessary complexity. 9. **Protect the acceptance gate above all** — a feature is
worthless if the system can't be run by a reviewer in 10 minutes.

---

## 10. Development workflow

Before implementing any feature:
1. Read the relevant wiki docs (§3).
2. Summarize understanding and state assumptions.
3. Identify tradeoffs; propose a plan.
4. For significant architecture changes, present the plan and wait for approval.
5. Implement in a thin, runnable slice. 6. Validate (run it; show real output). 7. Update the
wiki (`STATE.md` + affected docs) and suggest tests.

Do not generate large amounts of code without first presenting a plan. Think first.

### Per-slice rituals (always do these)
- **Document data-forced limitations under an `## Assumptions` heading in `DESIGN.md`.** Whenever the
  real data forces an interpretation or we hit a limitation (e.g. CCTV clips showing ~no entry/exit, so
  "visitor" = distinct in-store person), state it explicitly there — never bury it. Give the assumption,
  the why, and the impact. Surfacing limits as assumptions reads as judgment, not oversight.
- **After finishing a slice's coding, give a short problems-and-decisions retro in chat** (not a file):
  what friction/dead-ends we hit and what decision resolved each. The ADR log in `DECISIONS.md` still
  records the decisions themselves; the retro is conversational and additional.
- Frame **5 interview Q&A** for the slice in `INTERVIEW_QA.md`; keep `DESIGN.md`/`CHOICES.md` in sync;
  add a `# PROMPT` block (Task/Context/Constraints/Output) to every new test file.

---

## 11. Continuous self-review

Regularly ask: Is it maintainable? Testable? Observable? Does output vary with input (integrity)?
Does it protect the gate? Would a time-boxed reviewer understand it? Is it aligned to the business
metric? If no → improve before moving on.
