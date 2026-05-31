"""Reusable video frame source for the detector.

Reads a CCTV clip and yields frames at a configurable sample rate (we don't need every frame —
sampling a few per second is enough for footfall and keeps CPU sane). Kept separate from the
detection logic so it can be tested and reused independently.

Usage:
    with VideoFrameSource("CAM 3.mp4", sample_fps=5) as src:
        for frame in src.frames():
            ...  # frame.image is a BGR ndarray, frame.ts_ms is source media time
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import cv2
import numpy as np


def compute_stride(source_fps: float, target_fps: float) -> int:
    """How many source frames to skip between samples. Pure + unit-testable.

    e.g. a 30 fps clip sampled at 5 fps -> take every 6th frame.
    """
    if source_fps <= 0 or target_fps <= 0:
        return 1
    return max(1, round(source_fps / target_fps))


@dataclass(frozen=True)
class Frame:
    """One sampled frame."""

    index: int          # frame position in the source clip
    ts_ms: int          # source media time in milliseconds (index / fps)
    image: np.ndarray   # BGR pixels (OpenCV convention)


class VideoFrameSource:
    """Context-managed reader over a single video file."""

    def __init__(self, path: str | Path, sample_fps: float = 5.0) -> None:
        self.path = Path(path)
        self.sample_fps = sample_fps
        self._cap: cv2.VideoCapture | None = None
        self.source_fps: float = 0.0
        self.total_frames: int = 0
        self.width: int = 0
        self.height: int = 0

    def __enter__(self) -> VideoFrameSource:
        if not self.path.exists():
            raise FileNotFoundError(f"Video not found: {self.path}")
        cap = cv2.VideoCapture(str(self.path))
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {self.path}")
        self._cap = cap
        self.source_fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        self.total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def stride(self) -> int:
        return compute_stride(self.source_fps, self.sample_fps)

    def _ts_ms(self, index: int) -> int:
        return int(index / self.source_fps * 1000) if self.source_fps else 0

    def frames(self) -> Iterator[Frame]:
        """Yield sampled frames in order until the clip ends."""
        if self._cap is None:
            raise RuntimeError("VideoFrameSource must be used as a context manager")
        stride = self.stride
        index = 0
        while True:
            ok, image = self._cap.read()
            if not ok:
                break
            if index % stride == 0:
                yield Frame(index=index, ts_ms=self._ts_ms(index), image=image)
            index += 1

    def grab_frame(self, fraction: float) -> Frame:
        """Seek to a fraction (0..1) of the clip and return that single frame.

        Handy for previews/calibration without iterating the whole video.
        """
        if self._cap is None:
            raise RuntimeError("VideoFrameSource must be used as a context manager")
        target = max(0, min(self.total_frames - 1, int(self.total_frames * fraction)))
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        ok, image = self._cap.read()
        if not ok:
            raise RuntimeError(f"Failed to read frame {target} of {self.path}")
        return Frame(index=target, ts_ms=self._ts_ms(target), image=image)
