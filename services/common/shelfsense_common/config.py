"""Centralised, environment-driven configuration (12-factor).

All services import `get_settings()`. No hardcoded hosts/secrets/thresholds — everything is an
env var, documented in `.env.example`. Business thresholds live here and are mirrored in
docs/wiki/BUSINESS_RULES.md.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration loaded from the environment.

    Field names map to UPPER_SNAKE env vars (case-insensitive).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- General ---
    environment: str = "development"
    log_level: str = "INFO"
    service_name: str = "shelfsense"

    # --- Event stream (Redpanda / Kafka-compatible) ---
    stream_bootstrap_servers: str = "redpanda:9092"
    topic_detections: str = "detection.created"
    topic_tracks: str = "track.updated"
    topic_sessions: str = "session.events"
    topic_metrics: str = "metric.computed"

    # --- PostgreSQL ---
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "shelfsense"
    postgres_user: str = "shelfsense"
    postgres_password: str = "shelfsense"

    # --- Detector ---
    yolo_model: str = "yolov8n.pt"
    detection_confidence: float = 0.35  # validated on CAM3 corridor traffic (Slice 2.2)
    person_class_id: int = 0  # COCO 'person'
    cctv_dir: str = "/data/cctv"  # where CCTV clips are mounted in the container
    enabled_cameras: str = ""  # CSV of camera_ids to process (empty = all customer cameras)
    detector_sample_fps: float = 5.0  # frames sampled per second (see frames.py)
    detector_max_frames: int = 0  # cap sampled frames per clip (0 = whole clip); for quick runs
    detector_reprocess: bool = False  # if False, process each clip once then idle (no duplicates)

    # --- Tracking / behavioural events (Slice 2.2) ---
    # Frames sampled per second of video for tracking. Lowered 10->5 (ADR-0019) to roughly halve the
    # detector's CPU wall-time so a full pass fits the reviewer's window; the tuned track_buffer
    # bridges the wider inter-frame gaps. Speed/accuracy trade — re-validate the unique-customer
    # count (=2 on this clip) after changing it.
    tracker_sample_fps: float = 5.0
    # YOLO inference image size, longest side (ADR-0019). Lowered 640->480: ~1.6x faster per frame
    # on CPU for a small accuracy cost; must be a multiple of 32 (stride). Re-validate detections.
    detector_imgsz: int = 480
    tracker_cfg: str = "bytetrack_shelfsense.yaml"  # tuned ByteTrack (less fragmentation)
    crossing_confirm_frames: int = 2  # frames a side flip must persist (flicker debounce)
    events_jsonl_path: str = "/data/events/behavior.jsonl"  # where the pipeline writes events
    # Detector -> API auto-feed (Slice 2.8, ADR-0015): the detector POSTs its events straight to the
    # API so `docker compose up` populates the endpoints with no manual replay. Idempotent ingest
    # makes re-runs safe. Non-fatal: if the API is down the events still land in the JSONL above.
    api_base_url: str = "http://api:8000"  # in-container API base the detector POSTs to
    detector_post_to_api: bool = True  # auto-POST emitted events to /events/ingest
    ingest_batch_size: int = 500  # <= the API's per-request cap (API_SPEC)
    ingest_wait_s: float = 60.0  # max seconds to wait for the API to be ready before posting
    ingest_max_retries: int = 5  # per-batch POST retries (backoff) before dropping to JSONL-only
    # Clip wall-clock start (store-local), approx from the burnt-in CCTV overlay (~20:10 IST,
    # 10-Apr-2026). Used to turn per-frame media time into an absolute UTC event timestamp.
    clip_start_iso: str = "2026-04-10T20:10:00+05:30"

    # --- Business-rule thresholds (see BUSINESS_RULES.md) ---
    min_zone_dwell_ms: int = 2000  # min continuous presence before a zone visit is recorded
    min_engagement_dwell_ms: int = 3000
    session_timeout_ms: int = 30000
    reentry_window_ms: int = 120000
    zone_dwell_interval_ms: int = 30000  # re-emit ZONE_DWELL every N ms of continuous presence
    zone_exit_grace_ms: int = 2000  # absence beyond this ends a zone visit (ZONE_EXIT)

    # --- Re-ID + staff (Slice 2.4) ---
    # Max appearance (cosine) distance to call two tracks the same person. Calibrated against the
    # ground-truth of 7 people on CAM1/2/3 (scripts/calibrate_reid.py): with the tuned tracker,
    # 0.55 collapses 44 fragmented tracks to ~7 unique. Clip-tuned + approximate (see DESIGN A5).
    reid_max_distance: float = 0.55
    reid_reentry_min_gap_ms: int = 5000  # absence before a re-matched visitor counts as REENTRY
    # Staff classification (Slice 2.4b, ADR-0009): Brigade staff wear a complete BLACK uniform; the
    # two real customers wear grey/violet. Primary signal = dark-uniform appearance. A track is
    # staff if its mean dark-uniform score (min of upper/lower body dark fraction) >= threshold.
    staff_darkness_threshold: float = 0.50  # calibrated vs ground truth (5 staff / 2 customers)
    staff_dark_v_max: int = 70  # HSV Value (0-255) at/below which a pixel is "dark"/near-black
    # Optional fallback: also flag very-long-present tracks even if not dark (off by default — on a
    # 2-min clip a browsing customer can dwell long too, and we only have two customers to protect).
    staff_presence_fallback: bool = False
    staff_min_presence_ms: int = 90000  # presence-fallback threshold (used only if enabled above)

    # --- POS correlation / conversion (Slice 2.5) ---
    # Mounted sales CSV. The real file carries a download suffix (e.g. "POS - sample transactions
    # b1e826f.csv"); if this exact path is absent, pos_ingest.resolve_pos_csv globs the directory.
    pos_csv_path: str = "/data/pos/pos_transactions.csv"
    store_timezone: str = "Asia/Kolkata"  # store-local tz for order_date+order_time -> UTC
    pos_correlation_window_ms: int = 300000  # 5-min billing-zone-before-transaction window
    conversion_low_sample_threshold: int = 20  # < N unique visitors => data_confidence "low"
    # Demo only: align a representative billing visitor to a real sale so the flip to "converted" is
    # visible. NEVER changes the honest clip number; honoured only by scripts/demo_conversion.py.
    pos_demo_alignment: bool = False

    # --- Vision-Language Model (Slice 2.9, ADR-0027) ---
    # An optional VLM (Google Gemini) used ONLY in the offline detection pass to (a) classify each
    # tracked person as staff/customer and (b) label each camera's zone from the shelves it shows —
    # replacing brittle per-store heuristics (dark-uniform staff, hand-mapped zones) with one signal
    # that generalises across stores. OFF by default so `docker compose up` needs no key/network and
    # runs the heuristics (acceptance-gate safe). Verdicts are cached + the events are committed, so
    # the reviewer's run makes ZERO API calls. When enabled but the SDK/key is missing or a call
    # fails, the pipeline logs and falls back to the heuristic — the VLM never breaks the gate.
    vlm_enabled: bool = False  # master switch; True only for the offline pre-generation run
    vlm_provider: str = "gemini"  # only "gemini" implemented today
    gemini_api_key: str = ""  # SECRET — supplied via env/.env, never committed
    vlm_model: str = "gemini-2.0-flash"  # any fast multimodal Gemini model; override via VLM_MODEL
    vlm_classify_staff: bool = True  # use the VLM for staff/customer (else heuristic only)
    vlm_classify_zone: bool = True  # use the VLM to label camera zones (else static primary_zone)
    # Confidence floors: below these the VLM verdict is ignored and we keep the heuristic / static
    # zone. Keeps a hesitant model from overriding a known-good default.
    vlm_staff_min_confidence: float = 0.55
    vlm_zone_min_confidence: float = 0.55
    # Persistent verdict cache: re-runs reuse it, and it can be committed for repeatable replay.
    vlm_cache_path: str = "/data/vlm/vlm_cache.json"
    vlm_zone_frame_fraction: float = 0.4  # where in the clip to grab the representative zone frame
    vlm_timeout_s: float = 30.0  # per-call timeout
    vlm_max_retries: int = 2  # per-call retries before giving up and falling back

    # --- Anomalies (Slice 2.7) ---
    # Queue-spike severities (customers in the checkout zone, staff excluded).
    anomaly_queue_depth_warn: int = 3
    anomaly_queue_depth_critical: int = 5
    # Conversion-drop baseline. We have ONE day of data, not the spec's 7-day average, so this is a
    # documented *target* rate; the anomaly fires only at data_confidence="ok" (never on the
    # low-sample 2-min clip). Fire when conversion <= baseline * (1 - drop_pct).
    anomaly_conversion_baseline: float = 0.15
    anomaly_conversion_drop_pct: float = 0.30
    # Dead-zone: a customer zone with no visit for this many minutes during open hours. Evaluated
    # only when the observed span is at least this long (a 2-min clip can't assert 30-min silence).
    anomaly_dead_zone_minutes: int = 30
    store_open_hour: int = 12  # store-local trading window (POS spans ~12:15-21:40); for dead-zone
    store_close_hour: int = 22

    # --- Health / feed freshness (Slice 2.7) ---
    health_stale_feed_minutes: int = 10  # lag beyond which a store's feed is STALE_FEED
    # Recording-relative by default: freshness is measured against the latest ingested event, so a
    # replayed clip reads healthy. Set true to compare against real wall-clock time (live ops).
    health_strict_now: bool = False

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Store registry the dashboard switcher lists ("id:name" pairs, comma-separated). ST1008 is the
    # store the POS covers (Brigade); ST1009 is our assigned id for the corrected dataset's Store_2,
    # which had no id of its own (ADR-0026). Override via STORES.
    stores: str = "ST1008:Brigade Bangalore,ST1009:Store 2"
    # CORS: browser origins allowed to call the API (the React dashboard). Comma-separated; "*"
    # allows any — safe here since the API is read-only metrics. Override via CORS_ALLOW_ORIGINS.
    cors_allow_origins: str = "*"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def store_list(self) -> list[tuple[str, str]]:
        """Parse `stores` ("id:name,...") into (store_id, display_name) pairs for the switcher."""
        out: list[tuple[str, str]] = []
        for item in self.stores.split(","):
            item = item.strip()
            if not item:
                continue
            sid, _, name = item.partition(":")
            sid = sid.strip()
            if sid:
                out.append((sid, name.strip() or sid))
        return out

    @property
    def clip_start_dt(self) -> datetime:
        """Clip wall-clock start as a timezone-aware datetime (for absolute event timestamps)."""
        return datetime.fromisoformat(self.clip_start_iso)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
