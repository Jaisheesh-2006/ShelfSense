"""Run the detector's entrance pass once over the local raw CAM3 clip and write behavioural events.

A dev/demo helper that calls the *real* service code path (PersonTracker -> CrossingDetector ->
BehaviorEvent -> JsonlEventSink), but as a single pass without the container's idle loop. Use it to
regenerate the JSONL locally and eyeball the emitted schema.

Usage:
    python scripts/emit_entrance_events.py            # writes data/events/behavior.jsonl
Honours the same env vars as the service (CCTV_DIR, EVENTS_JSONL_PATH, DETECTION_CONFIDENCE, ...).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))
sys.path.insert(0, str(REPO / "services" / "detector"))

# Default to the local raw clips + a repo-local events file unless the caller overrides via env.
os.environ.setdefault("CCTV_DIR", str(REPO / "docs" / "raw" / "CCTV Footage" / "CCTV Footage"))
os.environ.setdefault("EVENTS_JSONL_PATH", str(REPO / "data" / "events" / "behavior.jsonl"))

from app.main import run_once  # noqa: E402
from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.logging import configure_logging, get_logger  # noqa: E402


def main() -> None:
    settings = get_settings()
    configure_logging("detector", settings.log_level)
    log = get_logger("detector")
    frames, entries, exits = run_once(settings, log)
    print(f"\nprocessed {frames} frames -> entries={entries} exits={exits}")
    print(f"events written to {settings.events_jsonl_path}")


if __name__ == "__main__":
    main()
