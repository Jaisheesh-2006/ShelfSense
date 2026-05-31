"""Unit tests for the detector frame sampling logic (pure, no video needed)."""
import numpy as np

from app.frames import Frame, compute_stride


def test_compute_stride_typical_clips():
    # 30 fps sampled at 5 fps -> every 6th frame; our clips are 29.97 / 24.98 fps.
    assert compute_stride(30.0, 5.0) == 6
    assert compute_stride(29.97, 5.0) == 6
    assert compute_stride(24.98, 5.0) == 5


def test_compute_stride_guards_against_bad_input():
    assert compute_stride(0.0, 5.0) == 1
    assert compute_stride(30.0, 0.0) == 1
    # Asking for more frames than the source has still yields a valid stride of 1.
    assert compute_stride(30.0, 100.0) == 1


def test_frame_is_immutable_record():
    f = Frame(index=6, ts_ms=200, image=np.zeros((2, 2, 3), dtype=np.uint8))
    assert (f.index, f.ts_ms) == (6, 200)
    assert f.image.shape == (2, 2, 3)
