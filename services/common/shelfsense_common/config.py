"""Centralised, environment-driven configuration (12-factor).

All services import `get_settings()`. No hardcoded hosts/secrets/thresholds — everything is an
env var, documented in `.env.example`. Business thresholds live here and are mirrored in
docs/wiki/BUSINESS_RULES.md.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
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
    detection_confidence: float = 0.4
    person_class_id: int = 0  # COCO 'person'

    # --- Business-rule thresholds (see BUSINESS_RULES.md) ---
    min_zone_dwell_ms: int = 2000
    min_engagement_dwell_ms: int = 3000
    session_timeout_ms: int = 30000
    reentry_window_ms: int = 120000

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


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
