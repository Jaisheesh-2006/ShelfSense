# ShelfSense Wiki — START HERE (session bootstrap)

> **Purpose of this file:** This is the entry point to the project's living knowledge base.
> Read this file first at the start of every session — it gives complete orientation and
> links to everything else. This wiki is an **LLM wiki** (Karpathy pattern): it is *my*
> (the assistant's) synthesized understanding of the raw inputs, kept as plain markdown.
>
> **Ownership contract:**
> - `docs/raw/` — owned by the user. Source material. The assistant only reads it (and may
>   only add to it if explicitly asked).
> - `docs/wiki/` — owned by the assistant. The assistant reads & writes this; the user does
>   not edit it. It is the assistant's understanding distilled from `raw/`, in its own words.
> - When `raw/` changes, re-derive [[GROUND_TRUTH]] from it, then propagate to the rest.

---

## How to use this wiki (for future me)

1. Read this README fully.
2. Read [[GROUND_TRUTH]] — the hard facts about the raw inputs. Never contradict it.
3. Read [[STATE]] — where the build currently is and the next action.
4. Pull the specific file(s) for the task (map below). Files are densely cross-linked
   with `[[name]]`.
5. As understanding changes, **write it back** here. Knowledge must compound, not reset.

---

## TL;DR — what this project is

Build a **Store Intelligence System** that turns raw retail **CCTV footage** into business
metrics — headline metric: **store conversion rate**. It's the UpGrad/Purplle Store
Intelligence Challenge (April 2026). Evaluated as an **end-to-end systems problem**, not an
ML accuracy problem. Store: **Purplle "Brigade_Bangalore" (ST1008)**, data from **10-Apr-2026**.

Pipeline: `CCTV → detector (YOLO) → tracker (MOT) → analytics (sessions, funnel, anomalies) → api (FastAPI) → frontend`, glued by structured events, with Postgres + Redis, Dockerized, observable. See [[ARCHITECTURE]].

---

## ⛔ Never-forget facts (these drive every decision)

1. **Headline metric:** conversion rate = `transactions (CSV) ÷ footfall (CCTV)`. See [[BUSINESS_RULES]].
2. **Raw inputs:** **5 cameras**, each a **~2-min clip**; CSV is **24 transactions** over a **full day** (12:15–21:40). The **video window ≠ CSV window** — a core ambiguity to handle, not ignore. See [[GROUND_TRUTH]].
3. **Acceptance gate (fail any → rejected before scoring):** `docker compose up` works with **zero manual steps**; `/metrics` returns a valid response; pipeline emits **structured events**; **`DESIGN.md` + `CHOICES.md`** exist and are non-trivial; no crash. See [[GROUND_TRUTH]] §Eval.
4. **Score weights (100):** Detection 30 · **API & Business Logic 35** · Production 20 · Thinking 15. Optimize for the API/business bucket and a runnable demo.
5. **Integrity:** hardcoded or input-invariant outputs → **score capped at 50**. Everything must compute from real input.
6. **`DESIGN.md` & `CHOICES.md`** are the graded submission deliverables (repo root). They are *generated from* this wiki: DESIGN ← [[ARCHITECTURE]], CHOICES ← [[DECISIONS]]. See [[DECISIONS]] ADR-0003.
7. **Reviewer time ≈ 10 min.** Must be instantly runnable and legible.

---

## Wiki map

| File | What it holds |
|------|---------------|
| [[GROUND_TRUTH]] | Hard facts distilled from `raw/`: the 5 videos, CSV schema & aggregates, the evaluation rubric. The source-of-truth synthesis. |
| [[STATE]] | Current build phase, what's done, the single next action. Update every session. |
| [[PROJECT]] | Scope, goals, non-goals, success criteria, open questions. |
| [[ARCHITECTURE]] | System design, services, data flow, storage, observability, deployment. → DESIGN.md |
| [[BUSINESS_RULES]] | Definitions of every metric (footfall, sessions, dwell, funnel, conversion, anomalies) + thresholds. |
| [[EVENT_SCHEMA]] | Event envelope + contracts between services (the structured events the gate checks). |
| [[API_SPEC]] | API surface, incl. mandatory `/metrics` and `/funnel`. |
| [[DECISIONS]] | ADR log — every major decision with alternatives + tradeoffs. → CHOICES.md |
| [[RISKS]] | Known risks, unknowns, mitigations. |
| [[EDGE_CASES]] | Real-world conditions (re-entry, staff, occlusion, group entry) + handling. |
| [[TASKS]] | Phased roadmap, ordered. |

---

## Current state (snapshot — full detail in [[STATE]])

🟡 **Phase 0 — Scaffolding + wiki grounding.** Structure created; wiki rewritten against the
real raw inputs and evaluation rubric. **No application code yet.** Next action lives in [[STATE]].
