# System Overview

**Business Problem:** Offline retail lacks the session and funnel analytics native to e-commerce. Retailers need visibility into customer behavior—such as entry, zone visits, billing queues, and conversions—to optimize store layout and staffing.
**North-Star Metric:** Offline store conversion rate (`converted visitors / unique visitors`).
**High-Level Approach:** A containerized system that ingests CCTV footage, processes it via a computer vision pipeline to extract tracking and behavioral events, and stores these events in a relational database for querying. The architecture explicitly decouples heavy CV processing from the intelligence API via a strict event contract. This enables offline batching, robust replayability, and independent scaling of the analytical backend.

# Architecture

**End-to-End Architecture Diagram:**
```text
CCTV Clips → [Detection Pipeline (YOLO + Re-ID + VLM Staff Logic)]
                  ↓
             (behavioral events: JSONL / HTTP POST)
                  ↓
             [Intelligence API] → PostgreSQL
                  ↓
             [Dashboard] (Live React SPA & Grafana)
```

**Data Flow:**
1. The **Detection Pipeline** ingests raw video, detects and tracks people, and de-duplicates identities across overlapping cameras.
2. A **Vision-Language Model (VLM)** classifies staff versus customers based on uniform appearance, filtering staff out of the customer metrics.
3. The pipeline emits behavioral events, flushing them via HTTP POST to the **Intelligence API** while logging to an append-only JSONL file.
4. The API validates events against a strict schema and persists them to **PostgreSQL**.
5. Endpoints compute funnel metrics and conversion rates dynamically on read, serving a React dashboard and Prometheus/Grafana.

**Boundaries & Responsibilities:**
The pipeline owns all computer vision, sessionization, and spatial reasoning. The API owns data ingestion, validation, persistence, and metric computation. The event schema acts as the strict boundary between the two. The API has no knowledge of pixels or tracking logic, and the pipeline has no knowledge of business metric aggregations.

### Key Architectural Assumptions
1. **Visitor Definition:** A unique visitor is defined by cross-camera Re-ID association. All cameras contribute to this count to accurately capture shoppers.
2. **Conversion Correlation:** Since POS records lack customer identifiers, conversion is inferred by associating a customer's presence in the billing zone with a POS transaction within a 5-minute time window.
3. **Staff Exclusion:** Staff must be excluded from the conversion denominator. This requires uniform-based classification rather than relying purely on dwell time.
4. **Zone Mapping:** Camera fields of view map to semantic zones (e.g., checkout, skincare aisle) derived directly from the physical floor plans.
5. **Eventual Consistency:** The analytical backend assumes that metrics are computed at query time over the latest available data, tolerating minor ingestion delays from the CV pipeline.

# Detection Layer

*   **Detection:** YOLOv8n handles base detection on CPU to meet strict resource constraints without requiring hardware accelerators.
*   **Tracking:** ByteTrack associates frame-by-frame detections into stable, occlusion-resistant trajectories.
*   **Re-ID:** A lightweight HSV color-histogram signature, matched via cosine distance, de-duplicates customers across overlapping cameras.
*   **Staff Identification:** A Vision-Language Model (Groq/Llama) classifies staff versus customers based on uniform appearance. A color-based heuristic serves as the offline fallback.
*   **Event Generation:** The pipeline translates pixel coordinates into business events (`ENTRY`, `ZONE_DWELL`, `BILLING_QUEUE_JOIN`, `EXIT`) using calibrated zone maps and walkable-floor polygons to suppress reflections and phantoms.

**Key Trade-Offs:**
*   **CPU Inference vs. GPU:** Chose CPU-only inference to ensure the system is highly portable and runs smoothly without CUDA setup. *Limitation accepted:* Lower processing throughput (5 FPS) and smaller input resolution (480px).
*   **Color-Histogram Re-ID vs. Learned Embeddings:** Chose simple color histograms to minimize dependencies and compute overhead. *Limitation accepted:* Look-alike uniforms can over-merge, reducing cross-camera precision compared to deep Re-ID models.

# Event Model

**Why Behavioral Events?**
Instead of emitting raw bounding boxes or tracking points, the CV layer emits semantic events (e.g., `ZONE_DWELL`). This compresses the data stream by orders of magnitude, prevents PII (raw video frames) from entering the storage layer, and drastically simplifies downstream analytics.

**Scalability & Replay:**
Events are written to an append-only JSONL file and POSTed to the API. This enables the API to be tested, developed, and deployed independently using pre-generated events without re-running heavy CV models. In a production environment, this event-driven design easily extends to message brokers (like Kafka) to buffer high-throughput writes.

# Intelligence Layer

*   **Ingestion:** An idempotent `POST /events/ingest` endpoint accepts batched events. The system dedups on `event_id`, ensuring safe replays and preventing double-counting during network retries.
*   **Storage:** PostgreSQL serves as the durable source of truth, providing robust transactional guarantees. SQLite is utilized for hermetic unit testing.
*   **Metrics Computation:** Metrics (footfall, dwell time, conversion) are computed at query time rather than materialized incrementally. This approach simplifies the backend architecture and remains highly performant at current data volumes.
*   **Funnel Generation:** The funnel (`Entry → Zone Visit → Billing Queue → Purchase`) enforces a monotonic subset constraint to represent drop-off accurately while aggressively filtering out staff sessions.
*   **Anomaly Detection:** Heuristic-based alerts (e.g., queue spikes, conversion drops) run dynamically. For metrics requiring historical baselines, synthetic baselines are configurable to bootstrap the system.
*   **Health Monitoring:** Feed freshness is monitored relative to the latest ingested event, ensuring accurate health states even when replaying historical data batches.

# Production Readiness

*   **Docker Strategy:** `docker compose up --build` brings up the API, DB, and dashboard. The heavy CV pipeline is isolated behind a `--profile detect` flag, respecting reviewer time by defaulting to a fast data replay.
*   **Idempotency:** Unique UUIDs (`event_id`) prevent duplicate records across network retries or manual event replays.
*   **Structured Logging:** All API requests emit JSON logs containing `trace_id`, endpoint, latency, and status codes for immediate observability.
*   **Error Handling:** The API uses partial-success ingest. A single malformed event in a batch is flagged in the response payload rather than rejecting the entire batch. Database unavailability results in a graceful HTTP 503 instead of a stack trace.
*   **Testing:** 138 unit and integration tests cover edge cases (re-entries, missing data) and end-to-end API flows using a test SQLite database.
*   **Dashboard:** A React SPA polls the API to display the live conversion ring, funnel, and heatmaps without hardcoded dependencies.

# AI-Assisted Decisions

### 1. Detection Model Selection
1.  **Problem:** Required a fast, accurate person detector that runs efficiently without specialized hardware.
2.  **Options considered:** YOLOv8 (nano / small / medium), YOLOv9 / RT-DETR, MediaPipe.
3.  **What AI suggested:** YOLOv8 as a strong baseline; nano for CPU; noted a larger variant or RT-DETR would help on heavily occluded billing frames.
4.  **What I chose:** YOLOv8-nano (with a strictly CPU-only PyTorch build).
5.  **Why I agreed/disagreed:** I agreed with the YOLOv8-nano choice. It is fast on CPU, accurate enough to count people, and integrates directly with ByteTrack. I also enforced the CPU-only PyTorch dependency, as a standard GPU build pulls gigabytes of unused CUDA libraries, violating the fast setup requirement.

### 2. Re-ID Approach
1.  **Problem:** De-duplicating the same shopper across multiple cameras to compute a precise unique visitor denominator.
2.  **Options considered:** Treat cameras independently (no Re-ID), OSNet embeddings, Color Histograms.
3.  **What AI suggested:** Treat cameras independently to simplify the pipeline.
4.  **What I chose:** Color-histogram Re-ID mapped via cosine distance.
5.  **Why I agreed/disagreed:** I disagreed with the AI. The core business requirement demands an accurate unique visitor count, which fundamentally requires cross-camera association. However, I chose color histograms over deep embeddings (OSNet) to keep the CPU compute budget strictly bounded.

### 3. API Architecture Design
1.  **Problem:** Reliably transmitting events from the CV pipeline to the database.
2.  **Options considered:** A Kafka-compatible broker (Redpanda) streaming to a consumer vs. direct HTTP POST batched ingest.
3.  **What AI suggested:** Initially suggested the Kafka-compatible broker design for scalability, and later the simpler ingest path based on requirements.
4.  **What I chose:** Direct HTTP POST to an idempotent API endpoint (broker dropped).
5.  **Why I agreed/disagreed:** I disagreed with the initial broker suggestion. Introducing a message broker for a single producer-consumer pair adds unnecessary infrastructure overhead and failure modes. An idempotent HTTP ingest provides the necessary reliability with significantly less operational complexity. As the problem statement says that e2e reliability >> more services and addition of more services introduces more chaces of failure

# Limitations and Future Work

1.  **CPU Bottleneck at Scale:** The computer vision pipeline is currently CPU-bound. Deploying to 40+ stores will require replacing the CPU PyTorch base with a CUDA-enabled image and migrating inference to edge GPUs.
2.  **Re-ID Under Dense Occlusion:** The color histogram Re-ID struggles with look-alike uniforms and lighting shifts, occasionally over-merging subjects. Upgrading to a lightweight learned embedding model (e.g., OSNet) is the immediate next step for improving cross-camera identity tracking accuracy.
3.  **Synchronous Ingestion:** The current API processes ingest POSTs synchronously. For high-throughput live deployments across multiple stores, decoupling ingestion via an in-memory queue or message broker will prevent slow database writes from blocking the upstream CV pipeline.
