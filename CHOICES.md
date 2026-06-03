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
A very large buffer increases memory usage and can cause "ghost tracks" to teleport if the Re-ID signature falsely matches a different person emerging far away. We accepted this risk by tuning the buffer to cover only short (1-3 second) occlusions typical of retail aisles.

### When I Would Revisit This Decision
If the store introduces massive obstructions (e.g., full floor-to-ceiling promotional displays) that exceed our tuned buffer duration, we would need to implement explicit cross-zone merging logic using a global state tracker.
