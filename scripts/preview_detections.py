"""Verification tool for Slice 2.1: overlay YOLO person boxes on real CAM 3 frames.

Runs the same PersonDetector the service uses, on a few frames across the clip, and saves
annotated images so we can confirm the boxes land on actual people. Also draws the calibrated
entrance line for context.

Usage:
    python scripts/preview_detections.py            # CAM 3, a few frames
    python scripts/preview_detections.py "CAM 1"    # a different camera clip
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))
sys.path.insert(0, str(REPO / "services" / "detector"))

from app.detect import PersonDetector  # noqa: E402
from app.frames import VideoFrameSource  # noqa: E402
from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.contracts import STORE  # noqa: E402

RAW = REPO / "docs" / "raw" / "CCTV Footage" / "CCTV Footage"
OUT = REPO / "docs" / "wiki" / "frames"
FRACTIONS = (0.25, 0.5, 0.75, 0.9)
GREEN = (0, 230, 0)
CYAN = (230, 230, 0)


def main() -> None:
    clip_name = sys.argv[1] if len(sys.argv) > 1 else "CAM 3"
    clip_path = RAW / f"{clip_name}.mp4"
    settings = get_settings()

    detector = PersonDetector(settings.yolo_model, settings.detection_confidence)
    line = STORE.entrance_camera.entrance_line if clip_name == "CAM 3" else None

    OUT.mkdir(parents=True, exist_ok=True)
    with VideoFrameSource(clip_path, sample_fps=settings.detector_sample_fps) as src:
        print(f"{clip_name}: {src.width}x{src.height} @ {src.source_fps:.2f}fps")
        for frac in FRACTIONS:
            frame = src.grab_frame(frac)
            detections = detector.detect(frame.image)
            img = frame.image.copy()
            for d in detections:
                b = d.bbox
                p1 = (int(b.x), int(b.y))
                p2 = (int(b.x + b.w), int(b.y + b.h))
                cv2.rectangle(img, p1, p2, GREEN, 2)
                cv2.putText(
                    img,
                    f"{d.confidence:.2f}",
                    (p1[0], p1[1] - 6),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    GREEN,
                    2,
                )
            if line is not None:
                cv2.line(img, (int(line.x1), int(line.y1)), (int(line.x2), int(line.y2)), CYAN, 3)
            out_path = OUT / f"{clip_name.replace(' ', '_')}_det_{int(frac * 100):02d}pct.jpg"
            cv2.imwrite(str(out_path), img)
            print(f"  {frac:.0%}: {len(detections)} person(s) -> {out_path.name}")


if __name__ == "__main__":
    main()
