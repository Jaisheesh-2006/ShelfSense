"""Diagnose per-track geometry + appearance to calibrate staff darkness and the CAM5 floor mask.

Runs YOLO+ByteTrack once over the chosen cameras and, per track, records: how long it lived, its
mean foot-point (where it "stands"), the vertical range of that foot-point, and its mean
dark-uniform score (staff.uniform_darkness). Two questions this answers honestly from the video:

  1. CAM5 mirror: do phantom tracks appear whose foot-point sits high/right (on the mirror/display
     wall) rather than on the walkable floor? Their foot-points cluster away from the real floor.
  2. Staff darkness: do the all-black staff score clearly higher than the grey/violet customers?

It also saves the single frame with the MOST simultaneous tracks per camera (boxes drawn) so the
geometry can be eyeballed. No pipeline emission here — pure measurement.

Usage:
    python scripts/diagnose_tracks.py            # CAM1 CAM2 CAM3 CAM5
    python scripts/diagnose_tracks.py CAM5       # one camera
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))
sys.path.insert(0, str(REPO / "services" / "detector"))

import cv2  # noqa: E402
from app.frames import VideoFrameSource  # noqa: E402
from app.staff import uniform_darkness  # noqa: E402
from app.track import PersonTracker  # noqa: E402
from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.contracts import STORE  # noqa: E402

RAW = REPO / "docs" / "raw" / "CCTV Footage" / "CCTV Footage"
OUT = REPO / "docs" / "wiki" / "frames"


def main() -> None:
    settings = get_settings()
    wanted = {a.upper().replace(" ", "") for a in sys.argv[1:]} or {"CAM1", "CAM2", "CAM3", "CAM5"}
    cameras = [c for c in STORE.cameras if c.camera_id in wanted]
    tracker = PersonTracker(
        settings.yolo_model,
        settings.detection_confidence,
        settings.person_class_id,
        tracker_cfg=settings.tracker_cfg,
        imgsz=settings.detector_imgsz,
        iou=settings.detection_iou,
    )

    for cam in cameras:
        clip = RAW / cam.file
        if not clip.exists():
            print(f"{cam.camera_id}: clip missing {clip}")
            continue
        tracker.reset()
        tracks: dict[int, dict] = {}
        best_frame = None  # (count, image, boxes) for the busiest frame
        with VideoFrameSource(clip, sample_fps=settings.tracker_sample_fps) as src:
            print(f"\n{cam.camera_id}: {src.total_frames} frames @ {src.source_fps:.1f}fps")
            for frame in src.frames():
                frame_tracks = tracker.update(frame.image)
                boxes = []
                for t in frame_tracks:
                    b = t.bbox
                    fx, fy = t.foot_point
                    d = uniform_darkness(frame.image, int(b.x), int(b.y), int(b.w), int(b.h))
                    boxes.append((t.track_id, int(b.x), int(b.y), int(b.w), int(b.h), d))
                    rec = tracks.get(t.track_id)
                    if rec is None:
                        tracks[t.track_id] = {
                            "n": 1, "first": frame.ts_ms, "last": frame.ts_ms,
                            "fx": fx, "fy": fy, "fy_min": fy, "fy_max": fy, "dark": d,
                        }
                    else:
                        rec["n"] += 1
                        rec["last"] = frame.ts_ms
                        rec["fx"] += fx
                        rec["fy"] += fy
                        rec["fy_min"] = min(rec["fy_min"], fy)
                        rec["fy_max"] = max(rec["fy_max"], fy)
                        rec["dark"] += d
                if best_frame is None or len(boxes) > best_frame[0]:
                    best_frame = (len(boxes), frame.image.copy(), boxes)

        # Report qualifying tracks (lived at least the min zone dwell, as the pipeline would count).
        rows = []
        for tid, r in tracks.items():
            dur = r["last"] - r["first"]
            if dur < settings.min_zone_dwell_ms:
                continue
            rows.append(
                (tid, r["n"], dur / 1000.0, r["fx"] / r["n"], r["fy"] / r["n"],
                 r["fy_min"], r["fy_max"], r["dark"] / r["n"])
            )
        rows.sort(key=lambda x: -x[2])  # longest-lived first
        print(f"  qualifying tracks (>= {settings.min_zone_dwell_ms/1000:.0f}s): {len(rows)}")
        print(f"  {'tid':>4} {'frames':>6} {'dur_s':>6} {'foot_x':>7} {'foot_y':>7} "
              f"{'fy_min':>7} {'fy_max':>7} {'dark':>6}")
        for tid, n, dur, fx, fy, fymin, fymax, dark in rows:
            print(f"  {tid:>4} {n:>6} {dur:>6.1f} {fx:>7.0f} {fy:>7.0f} "
                  f"{fymin:>7.0f} {fymax:>7.0f} {dark:>6.2f}")

        if best_frame is not None:
            _, img, boxes = best_frame
            for tid, x, y, w, h, d in boxes:
                colour = (0, 0, 255) if d >= 0.5 else (0, 200, 0)  # red=dark/staff, green=customer
                cv2.rectangle(img, (x, y), (x + w, y + h), colour, 2)
                fx, fy = x + w // 2, y + h
                cv2.circle(img, (fx, fy), 5, (255, 0, 255), -1)  # foot-point
                cv2.putText(img, f"{tid}:{d:.2f}", (x, y - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)
            out = OUT / f"diag_{cam.camera_id}_maxdet.jpg"
            cv2.imwrite(str(out), img)
            print(f"  busiest frame: {best_frame[0]} tracks -> {out.name}")


if __name__ == "__main__":
    main()
