"""Run the detector once over the local raw clips (all customer cameras) and write events.

A dev/demo helper that calls the *real* service code path (PersonTracker -> VisitorRegistry +
ZoneTracker + CrossingDetector -> BehaviorEvent -> JsonlEventSink), as a single pass without the
container's idle loop. Use it to regenerate the JSONL locally and eyeball the emitted schema.

Usage:
    python scripts/emit_entrance_events.py                 # ALL customer cameras (export behaviour)
    python scripts/emit_entrance_events.py CAM1 CAM2 CAM3   # only these (e.g. ground-truth check)
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

# Optional camera filter from CLI args (e.g. `... CAM1 CAM2 CAM3`) — for ground-truth verification.
# No args => all customer cameras, which is what the exported service runs by default.
_cams = [a.strip() for a in sys.argv[1:] if a.strip()]
if _cams:
    os.environ["ENABLED_CAMERAS"] = ",".join(_cams)

from app.main import run_once  # noqa: E402
from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.logging import configure_logging, get_logger  # noqa: E402


def main() -> None:
    settings = get_settings()
    configure_logging("detector", settings.log_level)
    log = get_logger("detector")
    totals = run_once(settings, log)
    print(
        f"\nprocessed {totals['frames']} frames -> "
        f"unique_visitors={totals['unique_visitors']} (Re-ID deduped), "
        f"zone_events={totals['zone']} entries={totals['entries']} exits={totals['exits']} "
        f"reentry={totals['reentry']}"
    )
    print(f"events written to {settings.events_jsonl_path}")


if __name__ == "__main__":
    main()
