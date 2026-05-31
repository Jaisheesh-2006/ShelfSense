"""Entrance-line calibration helper for CAM 3.

Grabs a real frame, overlays a coordinate grid + the candidate entrance line (+ which side is
INSIDE), and saves an annotated image so we can place the line precisely by eye, then copy the
coordinates into shelfsense_common.contracts.zones.

Usage:
    python scripts/calibrate_entrance.py                 # use the line currently in zones.py
    python scripts/calibrate_entrance.py 300 250 1250 700  # try a candidate line x1 y1 x2 y2
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))
sys.path.insert(0, str(REPO / "services" / "detector"))

from app.frames import VideoFrameSource  # noqa: E402

from shelfsense_common.contracts import STORE, EntranceLine  # noqa: E402

CAM3 = REPO / "docs" / "raw" / "CCTV Footage" / "CCTV Footage" / "CAM 3.mp4"
OUT = REPO / "docs" / "wiki" / "frames" / "CAM3_entrance_calibration.jpg"
GRID = 160
GRAY = (170, 170, 170)
GREEN = (0, 230, 0)
RED = (0, 0, 255)


def candidate_line() -> EntranceLine:
    if len(sys.argv) == 5:
        x1, y1, x2, y2 = (float(a) for a in sys.argv[1:5])
        return EntranceLine(x1=x1, y1=y1, x2=x2, y2=y2)
    cam = STORE.entrance_camera
    assert cam and cam.entrance_line
    return cam.entrance_line


def draw_grid(img) -> None:
    h, w = img.shape[:2]
    for x in range(0, w, GRID):
        cv2.line(img, (x, 0), (x, h), GRAY, 1)
        cv2.putText(img, str(x), (x + 2, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GRAY, 1)
    for y in range(0, h, GRID):
        cv2.line(img, (0, y), (w, y), GRAY, 1)
        cv2.putText(img, str(y), (2, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, GRAY, 1)


def main() -> None:
    line = candidate_line()
    with VideoFrameSource(CAM3, sample_fps=5.0) as src:
        print(f"CAM3: {src.width}x{src.height} @ {src.source_fps:.2f}fps, "
              f"{src.total_frames} frames, stride={src.stride}")
        frame = src.grab_frame(0.5)

    img = frame.image.copy()
    draw_grid(img)

    p1, p2 = (int(line.x1), int(line.y1)), (int(line.x2), int(line.y2))
    cv2.line(img, p1, p2, GREEN, 3)
    for p in (p1, p2):
        cv2.circle(img, p, 7, RED, -1)
        cv2.putText(img, f"{p}", (p[0] + 8, p[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, RED, 2)

    # Label which side the code currently treats as INSIDE (store interior).
    h, w = img.shape[:2]
    for cx, cy in ((w // 4, h // 4), (3 * w // 4, 3 * h // 4)):
        label = "INSIDE" if line.is_inside(cx, cy) else "OUTSIDE"
        col = GREEN if label == "INSIDE" else RED
        cv2.putText(img, label, (cx - 40, cy), cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 3)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT), img)
    print(f"line = ({p1}) -> ({p2}), inside_sign={line.inside_sign}")
    print(f"annotated frame -> {OUT}")


if __name__ == "__main__":
    main()
