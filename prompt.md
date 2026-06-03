You are a Principal Architect and Staff+ Software Engineer who has reviewed hundreds of system design documents and engineering hiring submissions.

I have already written a CHOICES.md document for a retail CCTV analytics system. The document contains good technical content, but it is too long, too detailed in places, and does not sufficiently emphasize the exact decisions that the challenge rubric scores.

Your task is to rewrite and improve the CHOICES.md.

Important context:

The challenge explicitly asks for:

1. Detection Model Choice
2. Event Schema Design Rationale
3. One API Architecture Choice

For each decision they expect:

* Options considered
* What AI suggested
* What I chose
* Why I chose it

The challenge also rewards:

* Demonstrating engineering judgment
* Showing where AI recommendations were accepted or rejected
* Clear trade-off analysis
* Production thinking
* Ability to defend the decision during follow-up interviews

Goals:

* Make the document read like it was written by a strong engineer who built the system.
* Reduce unnecessary storytelling and dataset-specific details.
* Keep only details that support engineering decisions.
* Highlight business impact, operational simplicity, scalability, and correctness.
* Make the document easy for a reviewer to skim.
* Preserve technical depth.
* Every decision should be defensible in a follow-up interview.

Required structure:

# CHOICES.md

## Overview

One short paragraph explaining that the document focuses on the most important engineering decisions and the trade-offs behind them.

---

# Core Decisions (Highest Priority)

These must appear first because they directly map to the challenge rubric.

## Decision 1: Detection Model Selection

Include:

### Problem

What challenge the detector must solve.

### Options Considered

YOLOv8, RT-DETR, YOLOv11 (or actual models considered).

### What AI Suggested

### Final Decision

### Why

### Trade-offs Accepted

### When I Would Revisit This Decision

Include a concise comparison table if possible.

---

## Decision 2: Event Schema Design

Include:

### Problem

### Options Considered

* Raw detections
* Track-level events
* Behavioral event stream

### What AI Suggested

### Final Decision

### Why

### Trade-offs Accepted

### When I Would Revisit This Decision

Emphasize:

* Replayability
* Decoupling
* Metrics computation
* Funnel generation
* Future scalability

---

## Decision 3: API / Ingestion Architecture

Include:

### Problem

### Options Considered

* Kafka/Redpanda
* Direct HTTP ingestion

### What AI Suggested

### Final Decision

### Why

### Trade-offs Accepted

### When I Would Revisit This Decision

Emphasize:

* Simplicity
* Reviewer experience
* Idempotency
* Operational burden
* Scaling path

---

# Additional High-Impact Decisions

Only include the strongest decisions from the original document.

Recommended:

## Decision 4: Staff Identification Strategy and Zone classification *(VLM-Assisted Classification)

Focus on:

* Presence heuristic vs appearance-based classification
* Why protecting conversion accuracy mattered

* Why a VLM was introduced
* Benefits observed
* Limitations observed
* Why it is disabled by default
* Why it remains valuable

Must include explicit evaluation:

* What worked
* What did not work
* When it should be used

---

## Decision 6: Multi-Store Architecture

Focus on:

* Extensibility
* Config-driven onboarding
* Why store-specific logic was isolated

---

Rewriting Rules:

1. Remove excessive dataset-specific observations.
   Do not spend paragraphs discussing:

* exact clip lengths
* exact customer counts
* exact staff counts
* specific videos

Only keep such details if they directly justify a design decision.

2. Every decision must fit this pattern:

Problem
Options
AI Suggestion
Decision
Why
Trade-off
Future Revisit

3. Eliminate defensive explanations.

Avoid:
"We did this because the reviewer..."
"We didn't want to fail the gate..."

Instead explain:
Operational simplicity
Reliability
Maintainability
Scalability

4. Highlight disagreement with AI.

Reviewers want evidence that I used AI as an advisor rather than blindly following it.

5. Strengthen engineering reasoning.

Explain:

* What alternative existed
* Why it was rejected
* What limitation was accepted

6. Write in the style of:

* Amazon Principal Engineer
* Staff Engineer architecture review
* Engineering RFC

Avoid:

* marketing language
* AI-generated filler
* buzzwords without justification

Target length:
1200–1800 words.

Output:
Return only the rewritten CHOICES.md in markdown.
Do not explain your edits.
Do not provide commentary.
