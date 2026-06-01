"""Walkable-floor polygon calibration helper (Slice 2.4b).

Grabs a real frame for a camera, overlays a coordinate grid + a candidate floor polygon, shades
the OUTSIDE (masked) region, and saves an annotated image so the polygon can be placed by eye and
the vertices copied into shelfsense_common.contracts.zones. Mirrors calibrate_entrance.py.

Used for CAM5, where a back doorway + accessories light-box / mirror produce detections whose
foot-point is not on the shopping floor; the polygon keeps only real floor.

Usage:
    python scripts/calibrate_floor.py CAM5            # use the polygon currently in zones.py
    python scripts/calibrate_floor.py CAM5 0.3        # grab the frame at 30% through the clip
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))
sys.path.insert(0, str(REPO / "services" / "detector"))

from app.frames import VideoFrameSource  # noqa: E402
from shelfsense_common.contracts import STORE  # noqa: E402

RAW = REPO / "docs" / "raw" / "CCTV Footage" / "CCTV Footage"
OUT_DIR = REPO / "docs" / "wiki" / "frames"
GRID = 160
GRAY = (170, 170, 170)
GREEN = (0, 230, 0)
RED = (0, 0, 255)


def draw_grid(img) -> None:
    h, w = img.shape[:2]
    for x in range(0, w, GRID):
        cv2.line(img, (x, 0), (x, h), GRAY, 1)
        cv2.putText(img, str(x), (x + 2, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GRAY, 1)
    for y in range(0, h, GRID):
        cv2.line(img, (0, y), (w, y), GRAY, 1)
        cv2.putText(img, str(y), (2, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GRAY, 1)


def main() -> None:
    cam_id = (sys.argv[1].upper().replace(" ", "") if len(sys.argv) > 1 else "CAM5")
    at = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
    cam = STORE.camera(cam_id)
    if cam is None or cam.floor_region is None:
        print(f"{cam_id}: no floor_region defined in zones.py")
        return

    with VideoFrameSource(RAW / cam.file, sample_fps=5.0) as src:
        print(f"{cam_id}: {src.width}x{src.height} @ {src.source_fps:.2f}fps")
        frame = src.grab_frame(at)

    img = frame.image.copy()
    draw_grid(img)

    pts = np.array([[int(x), int(y)] for x, y in cam.floor_region.vertices], dtype=np.int32)
    # Shade the masked-out (outside) area so it's obvious what gets dropped.
    mask = np.zeros(img.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [pts], 255)
    shade = img.copy()
    shade[mask == 0] = (0, 0, 0)
    img = cv2.addWeighted(img, 0.65, shade, 0.35, 0)
    cv2.polylines(img, [pts], isClosed=True, color=GREEN, thickness=3)
    for x, y in cam.floor_region.vertices:
        cv2.circle(img, (int(x), int(y)), 6, RED, -1)
        cv2.putText(img, f"({int(x)},{int(y)})", (int(x) + 6, int(y) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, RED, 2)

    out = OUT_DIR / f"{cam_id}_floor_calibration.jpg"
    cv2.imwrite(str(out), img)
    print(f"floor_region vertices = {cam.floor_region.vertices}")
    print(f"annotated frame -> {out}")


if __name__ == "__main__":
    main()
