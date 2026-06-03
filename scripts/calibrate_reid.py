"""Calibrate the Re-ID distance threshold against a known person count.

Ground truth from the user: ~7 people (incl. staff) appear across CAM1/CAM2/CAM3. The per-camera
pipeline over-counts heavily — mostly because ByteTrack fragments one person into several track ids
over a clip. This tool runs the tracker ONCE over the chosen cameras, captures each qualifying
track's appearance signature + timing, then **replays the Re-ID gallery offline at many distance
thresholds** so we can see which threshold collapses the fragments/duplicates closest to the truth —
without a slow full pipeline run per threshold.

Usage:
    python scripts/calibrate_reid.py                 # CAM1, CAM2, CAM3
    python scripts/calibrate_reid.py CAM1 CAM2        # a subset
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))
sys.path.insert(0, str(REPO / "services" / "detector"))

from app.frames import VideoFrameSource  # noqa: E402
from app.reid import ReIDGallery, appearance_signature  # noqa: E402
from app.track import PersonTracker  # noqa: E402
from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.contracts import STORE  # noqa: E402

RAW = REPO / "docs" / "raw" / "CCTV Footage" / "CCTV Footage"
THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.45, 0.55, 0.65]
GROUND_TRUTH = 7  # people incl. staff across CAM1/CAM2/CAM3 (user-observed)


def main() -> None:
    settings = get_settings()
    wanted = {a.upper().replace(" ", "") for a in sys.argv[1:]} or {"CAM1", "CAM2", "CAM3"}
    cameras = [c for c in STORE.cameras if c.camera_id in wanted]
    tracker = PersonTracker(
        settings.yolo_model, settings.detection_confidence, settings.person_class_id,
        tracker_cfg=settings.tracker_cfg, imgsz=settings.detector_imgsz, iou=settings.detection_iou,
    )

    # Capture one representative (summed, then normalised) signature per (camera, track) + timing.
    tracks: dict[tuple[str, int], dict] = {}
    for cam in cameras:
        clip = RAW / cam.file
        tracker.reset()
        with VideoFrameSource(clip, sample_fps=settings.tracker_sample_fps) as src:
            print(f"{cam.camera_id}: scanning {src.total_frames} frames @ {src.source_fps:.1f}fps")
            for frame in src.frames():
                for t in tracker.update(frame.image):
                    key = (cam.camera_id, t.track_id)
                    b = t.bbox
                    sig = appearance_signature(frame.image, int(b.x), int(b.y), int(b.w), int(b.h))
                    rec = tracks.get(key)
                    if rec is None:
                        tracks[key] = {"sum": sig, "first": frame.ts_ms, "last": frame.ts_ms}
                    else:
                        rec["sum"] = rec["sum"] + sig
                        rec["last"] = frame.ts_ms

    # Keep only tracks present at least min_zone_dwell (mirrors what the pipeline would emit/count).
    qualifying = [
        r for r in tracks.values() if (r["last"] - r["first"]) >= settings.min_zone_dwell_ms
    ]
    qualifying.sort(key=lambda r: r["first"])  # replay in arrival order (clips are time-synced)
    sigs = []
    for r in qualifying:
        norm = float(np.linalg.norm(r["sum"]))
        sigs.append((r["sum"] / norm if norm > 0 else r["sum"], r["first"]))

    print(f"\ncameras: {sorted(wanted)}")
    print(f"raw per-camera tracks (>= min dwell, NO Re-ID): {len(sigs)}")
    print(f"ground-truth people (incl. staff): {GROUND_TRUTH}\n")
    print(f"{'threshold':>10} | {'unique visitors':>15} | vs truth")
    print("-" * 44)
    for thr in THRESHOLDS:
        gallery = ReIDGallery(max_distance=thr, id_factory=_counter())
        for sig, ts in sigs:
            gallery.resolve(sig, ts)
        n = gallery.unique_count
        mark = "  <-- matches" if n == GROUND_TRUTH else ""
        print(f"{thr:>10.2f} | {n:>15} | {n - GROUND_TRUTH:+d}{mark}")


def _counter():
    import itertools

    c = itertools.count()
    return lambda: f"V{next(c)}"


if __name__ == "__main__":
    main()
