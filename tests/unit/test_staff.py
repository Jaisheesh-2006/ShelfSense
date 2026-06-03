# PROMPT
# Task:
#   - Unit-test staff classification by color-uniform appearance: the color_fraction measure and
#     the StaffClassifier threshold/fallback policy.
# Context:
#   - color_fraction = share of HSV pixels within bounds. StaffClassifier accumulates per-track
#     color score (running mean) and flags is_staff when mean >= threshold, with an optional
#     presence-time fallback (off by default).
# Constraints:
#   - Pure logic only — feed synthetic HSV arrays / plain color scores.
# Output:
#   - Tests: color_fraction on all-in-bounds / all-out / half
#     arrays; a high-scoring track is staff, a low-scoring
#     (customer) track is not; the running mean is used; presence fallback flags only when enabled.
"""Unit tests for the color-uniform staff classifier."""

import numpy as np
from app.staff import StaffClassifier, color_fraction


def _hsv(value: int, shape=(10, 10)) -> np.ndarray:
    """An (H,W,3) HSV image whose Value channel is a constant; H,S left at 0."""
    img = np.zeros((*shape, 3), dtype=np.uint8)
    img[:, :, 2] = value
    return img


def test_color_fraction_all_dark_and_all_bright():
    lower = (0, 0, 0)
    upper = (179, 255, 70)
    # every pixel below threshold -> fully in bounds
    assert color_fraction(_hsv(10), lower, upper) == 1.0
    # every pixel bright -> none in bounds
    assert color_fraction(_hsv(200), lower, upper) == 0.0


def test_color_fraction_half_dark():
    lower = (0, 0, 0)
    upper = (179, 255, 70)
    img = _hsv(200)
    img[:5, :, 2] = 10  # top half black, bottom half bright -> 50%
    assert abs(color_fraction(img, lower, upper) - 0.5) < 1e-6


def test_color_fraction_empty_is_zero():
    lower = (0, 0, 0)
    upper = (179, 255, 70)
    assert color_fraction(np.zeros((0, 0, 3), dtype=np.uint8), lower, upper) == 0.0


def test_track_is_staff_low_score_is_not():
    clf = StaffClassifier(threshold=0.5)
    for _ in range(5):
        clf.observe("CAM1", 1, 0.9)  # high color score uniform
        clf.observe("CAM1", 2, 0.1)  # low score customer
    assert clf.is_staff("CAM1", 1)
    assert not clf.is_staff("CAM1", 2)


def test_uses_running_mean_not_last_sample():
    clf = StaffClassifier(threshold=0.5)
    clf.observe("CAM1", 7, 0.9)
    clf.observe("CAM1", 7, 0.9)
    clf.observe("CAM1", 7, 0.0)  # one low score frame shouldn't flip a mostly-high track
    assert abs(clf.mean_color_score("CAM1", 7) - 0.6) < 1e-6
    assert clf.is_staff("CAM1", 7)


def test_unseen_track_is_not_staff():
    clf = StaffClassifier(threshold=0.5)
    assert clf.mean_color_score("CAM1", 99) == 0.0
    assert not clf.is_staff("CAM1", 99)


def test_presence_fallback_off_by_default():
    clf = StaffClassifier(threshold=0.5)  # no fallback
    clf.observe("CAM1", 3, 0.1)  # not high score
    assert not clf.is_staff("CAM1", 3, dwell_ms=999_000)  # long dwell ignored when fallback off


def test_presence_fallback_flags_long_presence_when_enabled():
    clf = StaffClassifier(threshold=0.5, presence_fallback_ms=90_000)
    clf.observe("CAM1", 3, 0.1)  # not high score
    assert not clf.is_staff("CAM1", 3, dwell_ms=10_000)  # short -> still customer
    assert clf.is_staff("CAM1", 3, dwell_ms=120_000)  # long -> staff via fallback
