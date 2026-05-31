---
description: Reconcile the ShelfSense wiki with reality — apply only required changes, fix conflicts, remove superseded content
---

You are updating the ShelfSense LLM wiki (`docs/wiki/`). The wiki is the assistant-owned source of
truth; `docs/raw/` is user-owned input. Goal: make the wiki **accurately reflect the current code,
decisions, and the authoritative [[SPEC]]** — concise, non-contradictory, production-grade.

This is a **reconciliation pass, not an append pass.** When you find conflicting or duplicated
content, **keep the single best/most-current version and delete the rest.** Do not pile new info on
top of stale info.

## Steps
1. **Load context.** Read `docs/wiki/README.md`, `STATE.md`, `SPEC.md`, `GROUND_TRUTH.md`, and the
   other wiki files. Skim the actual code in `services/` and the root `DESIGN.md`/`CHOICES.md` so the
   wiki is checked against *reality*, not memory.
2. **Find drift.** For each wiki file, look for: statements contradicted by current code/decisions;
   superseded designs (e.g. anything implying a message broker, old `/api/v1/*` endpoints, or
   `transactions ÷ footfall` conversion); the same fact stated differently in two places; resolved
   "open questions" or "TBDs" that are now answered; stale STATE/TASKS entries.
3. **Reconcile.** Apply only the changes needed:
   - Replace stale content with the current truth; **delete** the outdated version (don't leave both).
   - Merge duplicates into the one canonical location; cross-link with `[[...]]` instead of repeating.
   - Keep `DECISIONS.md` ADR entries as immutable history, but mark superseded ones clearly
     (`Status: superseded by ADR-xxxx`) — history is intentional; active guidance must not conflict.
   - Keep each file tight and skimmable. Don't add filler.
4. **Update STATE.md** to the true current phase / next action, and **TASKS.md** check-marks.
5. **Verify links & consistency:** every `[[name]]` resolves to a file; the North Star, event schema,
   and endpoints are described identically wherever they appear.
6. **Report** a short summary: which files changed and what conflict each change resolved. If the wiki
   was already consistent, say so and change nothing.

## Guardrails
- Do **not** edit `docs/raw/` (user-owned).
- Do **not** invent facts — if something is uncertain, mark it as an open question in `PROJECT.md`/`RISKS.md`.
- Prefer deletion of stale text over hedging. The wiki should read as if written fresh today.
- Keep changes minimal and surgical; this command is for upkeep, not rewrites (unless a file is clearly
  out of date end-to-end).

$ARGUMENTS
