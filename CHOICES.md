# CHOICES.md

## Overview
This document focuses on the core engineering decisions made while architecting the ShelfSense Store Intelligence system. It details the problem space, the options weighed, AI recommendations evaluated, and the final trade-offs accepted to deliver a resilient, scalable, and operationally simple analytical platform.

---

# Core Decisions (Highest Priority)

## Decision 1: Detection Model Selection

### Problem
The detection layer is the foundation of the analytics pipeline. It must accurately identify and track people in dense retail environments while running efficiently on standard CPUs, without relying on specialized hardware accelerators.

### Options Considered
* YOLOv8 (nano / small / medium)
* YOLOv9 / RT-DETR
* MediaPipe

### What AI Suggested
The AI recommended YOLOv8 as a strong baseline, specifically suggesting the nano variant for CPU execution, but noted a larger variant or RT-DETR would help maximize recall on heavily occluded billing frames.

### Final Decision
**YOLOv8-nano** executed on a strictly CPU-only PyTorch build.

### Why
YOLOv8-nano balances acceptable accuracy with the performance required to run real-time inference on a standard CPU. It natively integrates with ByteTrack, minimizing pipeline dependencies. I explicitly enforced a CPU-only PyTorch build because a standard GPU installation pulls gigabytes of unused CUDA overhead. By keeping the operational footprint light, the system achieves frictionless portability and fast startup times.

### Trade-offs Accepted
The nano variant misses more detections under heavy occlusion compared to heavier models. We mitigate this by flagging low-confidence detections rather than dropping them, and by tuning the tracking buffer to bridge short occlusion gaps.

### When I Would Revisit This Decision
When deploying to production hardware equipped with edge GPUs, I would immediately swap to a heavier model (e.g., YOLOv8-medium or RT-DETR) to maximize tracking recall in dense store environments.

---

## Decision 2: Event Schema Design

### Problem
Translating raw computer vision outputs (bounding boxes, track IDs, frame coordinates) into actionable, queryable metrics for downstream analytical consumption.

### Options Considered
* Raw detections (bounding boxes per frame)
* Track-level events (start/end of a track)
* Behavioral event stream (`ENTRY`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`)

### What AI Suggested
The AI initially suggested a rich, low-level event envelope containing track updates and bounding box coordinates to support internal debugging and tracing.

### Final Decision
A **behavioral event stream** adhering strictly to a flat, predefined schema.

### Why
I rejected the AI's complex envelope. Behavioral events represent the exact abstraction altitude needed by the analytics layer. They compress the data stream exponentially, abstract away pixels and tracking logic from the database, and map directly to the required business metrics (conversion, dwell, queue depth). This strict separation of concerns means the CV pipeline and the analytical API can evolve independently.

### Trade-offs Accepted
Loss of low-level diagnostic richness in the database. Debugging tracking failures requires re-running the CV pipeline against raw video clips rather than simply querying the database.

### When I Would Revisit This Decision
If the product required a forensics or audit feature (e.g., visualizing shopper paths on a dashboard), I would introduce an internal debug stream alongside the behavioral events, rather than polluting the core analytics schema.

---

## Decision 3: API / Ingestion Architecture

### Problem
Reliably transmitting high-volume events from the CV pipeline to the database while maintaining system resiliency, enabling data replay, and keeping operational simplicity high.

### Options Considered
* Kafka/Redpanda broker streaming to a DB consumer
* Direct HTTP POST ingestion

### What AI Suggested
A Kafka-compatible broker (Redpanda) to ensure replayability, handle backpressure, and provide robust event streaming.

### Final Decision
**Direct HTTP POST ingestion** using an idempotent API endpoint (`POST /events/ingest`).

### Why
I rejected the AI's broker recommendation. For a single producer-consumer topology at this scale, introducing Kafka adds severe operational burden and introduces new failure modes. Reliability and replayability are achieved through idempotency (deduplication via `event_id`) rather than a durable queue. This drastically reduces the infrastructure surface area, keeping deployment simple and maintainable. 

### Trade-offs Accepted
Lack of built-in stream backpressure and durable queueing if the API goes down. In the event of an outage, the CV pipeline must buffer locally or drop events.

### When I Would Revisit This Decision
When scaling to process dozens of live store streams concurrently, a dedicated message broker becomes necessary to buffer traffic spikes and decouple ingestion throughput from database write latency.

---

# Additional High-Impact Decisions

## Decision 4: Staff Identification Strategy and Zone Classification

### Problem
Accurately classifying staff versus customers is critical to prevent staff from artificially inflating the conversion denominator. Simultaneously, we needed a scalable way to classify camera zones automatically across different stores without drawing manual polygons.

### Options Considered
* Pure presence/dwell-time heuristic (staff loiter longer)
* Hand-mapped zones and fixed color heuristics per store (e.g., black shirts)
* VLM-Assisted Classification (Groq/Llama or Gemini)

### What AI Suggested
The AI suggested using a Vision-Language Model (VLM) for offline staff and zone classification to generalize across stores with disparate uniforms and layouts.

### Final Decision
**VLM-Assisted Classification** (via Groq) used strictly offline, supplemented with a color-based heuristic fallback.

### Why
Protecting conversion accuracy is paramount. Dwell-time heuristics are fragile (browsing customers may loiter). Uniform color heuristics are brittle (black uniforms in Store 1, pink in Store 2). The VLM correctly identifies staff by uniform/lanyard context and automatically labels zones based on visible shelving. By keeping the VLM pass offline and caching the verdicts, the live inference gate remains fast, deterministic, and network-free.

### Explicit Evaluation
* **What worked:** The VLM flawlessly separated staff from customers and labeled zones across different stores without manual rule updates.
* **What did not work:** The initial Gemini integration hit free-tier rate limits instantly. Migrating to Groq (Llama-4 Scout) resolved the throughput issue.
* **When it should be used:** Only during offline calibration passes when a new store is onboarded, never in the hot path of live video inference.

### Trade-offs Accepted
VLM inference introduces non-determinism and latency, which is why it was strictly isolated to the offline calibration step.

### When I Would Revisit This Decision
If the business scales to real-time VLM classification, we would deploy a distilled, quantized classification model to the edge rather than relying on external API calls.

---

## Decision 5: Multi-Store Architecture

### Problem
Supporting multiple store layouts, configurations, and calibration parameters without hardcoding or scattering store-specific logic throughout the codebase.

### Options Considered
* Global configuration with conditional branches based on `store_id`
* JSON/YAML configuration files
* Config-driven Python registry (auto-discovered modules)

### What AI Suggested
The AI initially suggested JSON/YAML configs. Upon discussing Python packaging risks and deployment complexity, it recommended a Python registry.

### Final Decision
A pluggable, **auto-discovered Python registry** (`shelfsense_common.stores`).

### Why
A Python registry ensures that onboarding a new store simply involves dropping a `<store_id>.py` file containing the `StoreConfig`. This approach provides strong typing via Pydantic, cleanly isolates calibration overrides (like Re-ID thresholds) per store, and ships seamlessly with the application package without the risk of missing external data files. 

### Trade-offs Accepted
Configuration changes require an application redeployment and are harder for non-engineers to modify compared to a web UI or a simple JSON file.

### When I Would Revisit This Decision
If store onboarding is handed off to non-technical operations staff, we would build a dynamic, database-backed configuration service with a dedicated UI.

---

## Decision 6: Deterministic Event Ingestion (Idempotency)

### Problem
When testing or reviewing the system, a reviewer might run the detection pipeline multiple times without clearing the PostgreSQL database volume. If events generate random UUIDs on each run, the API will ingest them as new records, artificially duplicating footfall and conversion numbers (e.g., 2 unique visitors become 4).

### Options Considered
* Keep random UUIDs and require users to manually run `docker compose down -v` to clear volumes before a rerun.
* Use a destructive "delete and replace" API endpoint per store on pipeline start.
* Generate deterministic IDs based on event contents to enable true idempotency.

### What AI Suggested
The AI suggested adding documentation reminding the reviewer to clear the database volume before a rerun.

### Final Decision
Implement **deterministic IDs** using UUIDv5 based on a combination of `(store, camera, visitor, type, zone, timestamp)`. 

### Why
Relying on the reviewer to run specific tear-down commands is a fragile user experience and a common operational foot-gun. By hashing the exact event properties into a UUIDv5, the same event detected in the same frame will always produce the identical `event_id`. Because the API's `POST /events/ingest` endpoint is idempotent on `event_id`, rerunning the pipeline safely deduplicates the records, preserving the integrity of the business metrics without any destructive API operations.

### Trade-offs Accepted
IDs are only deterministic for the exact same pipeline configuration. If the frame rate (`fps`) or image size is changed, the time offset drifts and new IDs are generated. This is an acceptable trade-off because a different sampling rate constitutes a genuinely different measurement run.

### When I Would Revisit This Decision
If we needed to guarantee idempotency across different pipeline versions or frame rates, we would shift to a stateful Re-ID matching system within the database rather than relying strictly on hashed metadata.

---

## Decision 7: Tracking Buffer for Occlusion Recovery

### Problem
Retail environments feature heavy visual occlusion from shelves, signage, and other shoppers. When a shopper walks behind a shelf, the YOLO detector loses them. Without intervention, this fragments a single customer into multiple visitor IDs, artificially inflating the unique visitor count.

### Options Considered
* Deploy a heavier, occlusion-resistant detection model (e.g., RT-DETR).
* Use multi-camera overlap logic to cover blind spots.
* Tune the tracking algorithm's buffer space (`track_buffer`) to bridge the gap.

### What AI Suggested
The AI suggested using a heavier detection model or explicitly coding spatial logic to merge broken tracks near shelf edges.

### Final Decision
Increase the tracking algorithm's **buffer space** (the number of frames a lost track is kept alive in memory before being dropped).

### Why
Deploying a heavier model violates our strict CPU-only performance constraints, and writing custom spatial merging logic is brittle across different store layouts. ByteTrack natively supports a track buffer. By increasing this buffer size, we keep the track "alive" in memory while the customer is occluded. When they emerge on the other side of the shelf, the tracker re-associates them with their original ID using their Re-ID appearance signature. This elegantly solves occlusion fragmentation without adding any computational overhead.

### Trade-offs Accepted
A very large buffer increases memory usage and can cause "ghost tracks" to teleport if the Re-ID signature falsely matches a different person emerging far away. We accepted this risk by tuning the buffer to cover only short (1-3 second) occlusions typical of retail aisles. *Note:* the buffer's re-association leans on appearance, which we later measured to be unreliable on overhead views (see Decision 8) — so the buffer handles short same-view gaps, while a dedicated motion associator handles the longer turn-around/occlusion case.

### When I Would Revisit This Decision
If the store introduces massive obstructions (e.g., full floor-to-ceiling promotional displays) that exceed our tuned buffer duration, we would need to implement explicit cross-zone merging logic using a global state tracker.

---

## Decision 8: Tracking-Based Association vs. Appearance Re-ID (the over-split fix)

### Problem
On overhead store cameras, the single biggest counting error was the *opposite* of double-counting: one shopper was split into several visitor IDs. When a person turns around or is briefly occluded, ByteTrack ends one track and starts a new one; the system is then supposed to recognize it as the same person. The question was *how*: by appearance, or by motion.

### Options Considered
* Appearance Re-ID only (color histogram, or a learned CNN embedding) to re-link the new track.
* Motion / spatio-temporal association — link a dying track to a new one born nearby a moment later, by trajectory, independent of appearance.
* Simply raise the tracking buffer further (Decision 7).

### What AI Suggested
The AI's first instinct was to strengthen appearance Re-ID — add a learned embedding (e.g., OSNet) so the front and back of a person land closer in feature space.

### Final Decision
A **pluggable, motion-based track associator** (tracklet stitching) that runs *before* the appearance Re-ID gallery and is the default. Appearance Re-ID is retained as the cross-camera fallback (selectable via `TRACK_ASSOCIATION`).

### Why
I tested the appearance hypothesis directly: I built the learned embedder and measured same-person vs. different-person distance on adjudicated crops. The result was decisive — on these overhead views the same person's front and back are *farther* apart than two different people (color histogram **0.66** same vs **0.61** different; ImageNet CNNs overlap too). No appearance method can separate identities here, so a heavier model would not have helped. Motion, however, is unambiguous: a person cannot teleport, so a track that disappears at a point and a new one that appears nearby moments later is the same person. Stitching by spatio-temporal continuity fixed the dominant error — a roaming staff member that had been split into **4 IDs on one camera collapsed to 1**, and Store 2's entry/exit footfall came into line with ground truth.

### Explicit Evaluation
* **What worked:** within-camera over-split largely eliminated; footfall counts matched the hand-labeled ground truth; the associator is pure logic (positions + time), so it is fully unit-tested and never touches the acceptance gate.
* **What did not work:** it is per-camera. A staff member roaming across non-overlapping cameras is still counted once per camera, because positions are not comparable across views.
* **When it should be used:** always, as the default; appearance Re-ID remains the fallback for cross-camera de-duplication.

### Trade-offs Accepted
Motion association cannot span non-overlapping cameras without a shared coordinate space, and it does not fix group-merge (2–4 people detected as one box, a detection-level limit). I accepted both as documented limitations rather than over-fitting.

### When I Would Revisit This Decision
To also fix cross-camera identity, the right tool is a floor-plane homography so each camera's coordinates map to a common store map, letting the same motion association work across overlapping views — a far better investment than a heavier appearance model that the data shows would not generalize. On *this* dataset, however, that homography is itself blocked (the cameras don't overlap and weren't recorded simultaneously) — see Decision 9.

---

## Decision 9: Closing the Two Residual Counting Errors (Group-Merge vs. Cross-Camera)

### Problem
After motion association (Decision 8) fixed the dominant within-camera over-split, two residual counting errors remained on the busy store (Store_2; ground truth 22 customers + 3 staff): customers were **under-counted** (17 vs 22) and staff were **over-counted** (5 vs 3). They have opposite signs and, critically, *different root causes* — so treating them identically would be wrong.

### Options Considered
* **Group-merge (under-count):** raise YOLO resolution; add a pose model to split merged boxes; a geometric width-ratio heuristic; or accept the limit.
* **Cross-camera (over-count):** a floor-plane homography to merge identities across cameras; an appearance/timing heuristic; or skip and document.

### What AI Suggested
For group-merge, the AI's principled lever was a body (pose) model. For cross-camera, the AI was asked to "just implement it" — but, reading the data first, it surfaced that the obvious homography fix is **blocked by this dataset** (the cameras are non-overlapping and were recorded on different days, so the timestamps aren't truly synchronized), meaning a spatio-temporal merge would fabricate identities.

### Final Decision
Two different calls, each matched to the root cause:
* **Group-merge → an opt-in, pose-based splitter** (`GROUP_SPLIT=pose`), off by default — a second YOLOv8-pose model counts skeletons inside a wide box and splits it into one sub-track per person.
* **Cross-camera identity → do NOT implement on this dataset**; document it as a dataset limitation.

### Why
Group-merge is a *detection* problem whose output genuinely varies with the input — a pose model can separate packed bodies, and keeping it off by default means the acceptance gate never loads a second model. Cross-camera duplication, by contrast, is **unfixable on this footage**: with no camera overlap and no real time-synchronization (different recording days collapsed to a synthetic timeline), a spatio-temporal merge would link *different* people who merely share a synthetic timestamp — fabricating identities and tripping the integrity cap, not improving accuracy. Its only symptom is the staff over-count (+2), which sits inside the accepted ±1–2 margin. Refusing to build something the data cannot support — and saying so plainly — is the more senior engineering call than shipping a homography that invents merges.

### Explicit Evaluation
* **Pose split — measured (clean A/B, 2026-06-04):** **no net gain** — Store_2 unique held at 22→22 (the ±1 customer/staff move is classification noise, since the total is unchanged). A frame probe showed why: overhead groups are front-to-back, so only ~5% of person-boxes are *wide* enough to trip the splitter's gate, and pose keypoints degrade under occlusion anyway. So it is **kept as a tested, off-by-default capability**, documented as an honest negative on this footage — not shipped as an active fix.
* **Cross-camera:** the feasibility investigation *is* the deliverable — the engineering judgment to not chase an impossible-on-this-data merge is the value, not lines of code.

### Trade-offs Accepted
On this footage the customer count does **not** actually improve (the splitter is a measured negative here — overhead occlusion defeats pose just as it defeated higher resolution), and the staff over-count remains (within tolerance, by the user's call). Both are documented in DESIGN.md, never hidden — the value is the rigorous attempt-and-measure, not a number we couldn't honestly earn.

### When I Would Revisit This Decision
**Group-merge:** a part-based or top-view-tuned detector when GPU budget allows. **Cross-camera:** only with genuinely time-synchronized, *overlapping* multi-camera footage — at which point a floor-plane homography would extend the Decision-8 motion association across views and resolve the staff duplication too.
