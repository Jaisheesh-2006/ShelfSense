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

    # --- Redis ---
    redis_host: str = "redis"
    redis_port: int = 6379

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
    tracker_sample_fps: float = 10.0  # higher than detection fps: ByteTrack needs denser frames
    tracker_cfg: str = "bytetrack_shelfsense.yaml"  # tuned ByteTrack (less fragmentation)
    crossing_confirm_frames: int = 2  # frames a side flip must persist (flicker debounce)
    events_jsonl_path: str = "/data/events/behavior.jsonl"  # where the pipeline writes events
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
    pos_csv_path: str = "/data/pos/Brigade_Bangalore_10_April_26.csv"  # mounted sales CSV
    store_timezone: str = "Asia/Kolkata"  # store-local tz for order_date+order_time -> UTC
    pos_correlation_window_ms: int = 300000  # 5-min billing-zone-before-transaction window
    conversion_low_sample_threshold: int = 20  # < N unique visitors => data_confidence "low"
    # Demo only: align a representative billing visitor to a real sale so the flip to "converted" is
    # visible. NEVER changes the honest clip number; honoured only by scripts/demo_conversion.py.
    pos_demo_alignment: bool = False

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def clip_start_dt(self) -> datetime:
        """Clip wall-clock start as a timezone-aware datetime (for absolute event timestamps)."""
        return datetime.fromisoformat(self.clip_start_iso)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
