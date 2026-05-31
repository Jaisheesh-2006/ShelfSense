"""Extract sample frames from the raw CCTV clips for inspection / zone definition.

Reads each CAM*.mp4 in docs/raw/CCTV Footage, grabs a few frames across the clip, and
writes them to docs/wiki/frames/. Also prints resolution / fps / frame count per camera
so we can record real video specs in GROUND_TRUTH.md.

Usage:  python scripts/extract_frames.py
"""
from __future__ import annotations

from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[1]
RAW_DIR = REPO / "docs" / "raw" / "CCTV Footage" / "CCTV Footage"
OUT_DIR = REPO / "docs" / "wiki" / "frames"
# Fractions of the clip to sample (avoid the very first frame; mid-clip is most informative).
SAMPLE_POSITIONS = (0.10, 0.50, 0.90)


def extract() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    videos = sorted(RAW_DIR.glob("*.mp4"))
    if not videos:
        raise SystemExit(f"No .mp4 files found in {RAW_DIR}")

    for video in videos:
        cap = cv2.VideoCapture(str(video))
        if not cap.isOpened():
            print(f"!! could not open {video.name}")
            continue
        fps = cap.get(cv2.CAP_PROP_FPS)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        dur = total / fps if fps else 0
        print(f"{video.name:12} {w}x{h}  fps={fps:.2f}  frames={total}  dur={dur:.1f}s")

        stem = video.stem.replace(" ", "_")
        for frac in SAMPLE_POSITIONS:
            idx = int(total * frac)
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok:
                print(f"   !! failed to read frame {idx} ({frac:.0%})")
                continue
            out = OUT_DIR / f"{stem}_{int(frac * 100):02d}pct.jpg"
            cv2.imwrite(str(out), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        cap.release()
    print(f"\nFrames written to {OUT_DIR}")


if __name__ == "__main__":
    extract()
