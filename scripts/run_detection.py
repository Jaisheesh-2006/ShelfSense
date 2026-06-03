"""Full Pipeline Mode — run the real detector once over the local CCTV clips and write events.

This is the offline generation entrypoint (vs Evaluation Mode, which replays committed events). It
calls the exact service code path (`app.main.run_once`: YOLO + ByteTrack -> Re-ID + zone/crossing +
staff + optional VLM -> BehaviorEvent -> JSONL), as a single pass without the container's idle loop,
so it exits when done. Honours every service env var (CCTV_DIR, EVENTS_JSONL_PATH, VLM_*, ...).

Usage:
    python scripts/run_detection.py                 # all registered stores, all cameras
    python scripts/run_detection.py --store ST1009   # only Store_2 (sets ENABLED_STORES)
    python scripts/run_detection.py --store ST1009 --cameras ZONE,BILLING
Notes:
  - Defaults CCTV_DIR to the corrected dataset (docs/raw/Store_CCTV_Clips) and writes to a
    repo-local JSONL unless overridden. API posting is OFF by default (no stack needed); set
    DETECTOR_POST_TO_API=true to also feed a running API.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))
sys.path.insert(0, str(REPO / "services" / "detector"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the ShelfSense detector once (offline).")
    parser.add_argument("--store", default="", help="store_id filter, e.g. ST1009 (default: all)")
    parser.add_argument("--cameras", default="", help="CSV camera_id filter (default: all)")
    parser.add_argument("--events", default="", help="output JSONL path (default: data/events/...)")
    args = parser.parse_args()

    os.environ.setdefault("CCTV_DIR", str(REPO / "docs" / "raw" / "Store_CCTV_Clips"))
    os.environ.setdefault("EVENTS_JSONL_PATH", str(REPO / "data" / "events" / "behavior.jsonl"))
    os.environ.setdefault("DETECTOR_POST_TO_API", "false")  # offline by default; no API required
    if args.store:
        os.environ["ENABLED_STORES"] = args.store
    if args.cameras:
        os.environ["ENABLED_CAMERAS"] = args.cameras
    if args.events:
        os.environ["EVENTS_JSONL_PATH"] = args.events

    from app.main import run_once
    from shelfsense_common.config import get_settings
    from shelfsense_common.logging import configure_logging, get_logger

    settings = get_settings()
    configure_logging("detector", settings.log_level)
    log = get_logger("detector")
    totals = run_once(settings, log)
    print(
        f"\nprocessed {totals['frames']} frames -> "
        f"unique_visitors={totals['unique_visitors']} (Re-ID deduped), "
        f"zone_events={totals['zone']} entries={totals['entries']} exits={totals['exits']} "
        f"reentry={totals['reentry']} too_small={totals.get('too_small', 0)} "
        f"off_floor={totals.get('off_floor', 0)}"
    )
    print(f"events written to {settings.events_jsonl_path}")


if __name__ == "__main__":
    main()
