# PROMPT
# Task:
#   - Unit-test staff classification by dark-uniform appearance: the pure dark_fraction measure and
#     the StaffClassifier threshold/fallback policy.
# Context:
#   - Brigade staff wear complete black; the two real customers wear grey/violet (ADR-0009).
#     dark_fraction = share of HSV pixels with Value <= v_max. StaffClassifier accumulates per-track
#     darkness (running mean) and flags is_staff when mean >= threshold, with an optional
#     presence-time fallback (off by default).
# Constraints:
#   - Pure logic only — feed synthetic HSV arrays / plain darkness scores; no OpenCV, no model.
# Output:
#   - Tests: dark_fraction on all-dark / all-bright / half arrays; a dark track is staff, a bright
#     (customer) track is not; the running mean is used; presence fallback flags only when enabled.
"""Unit tests for the dark-uniform staff classifier."""

import numpy as np
from app.staff import StaffClassifier, dark_fraction


def _hsv(value: int, shape=(10, 10)) -> np.ndarray:
    """An (H,W,3) HSV image whose Value channel is a constant; H,S left at 0."""
    img = np.zeros((*shape, 3), dtype=np.uint8)
    img[:, :, 2] = value
    return img


def test_dark_fraction_all_dark_and_all_bright():
    assert dark_fraction(_hsv(10), v_max=70) == 1.0  # every pixel below threshold -> fully dark
    assert dark_fraction(_hsv(200), v_max=70) == 0.0  # every pixel bright -> none dark


def test_dark_fraction_half_dark():
    img = _hsv(200)
    img[:5, :, 2] = 10  # top half black, bottom half bright -> 50%
    assert abs(dark_fraction(img, v_max=70) - 0.5) < 1e-6


def test_dark_fraction_empty_is_zero():
    assert dark_fraction(np.zeros((0, 0, 3), dtype=np.uint8)) == 0.0


def test_dark_track_is_staff_bright_is_not():
    clf = StaffClassifier(threshold=0.5)
    for _ in range(5):
        clf.observe("CAM1", 1, 0.9)  # black uniform
        clf.observe("CAM1", 2, 0.1)  # grey/violet customer
    assert clf.is_staff("CAM1", 1)
    assert not clf.is_staff("CAM1", 2)


def test_uses_running_mean_not_last_sample():
    clf = StaffClassifier(threshold=0.5)
    clf.observe("CAM1", 7, 0.9)
    clf.observe("CAM1", 7, 0.9)
    clf.observe("CAM1", 7, 0.0)  # one bright frame shouldn't flip a mostly-dark track
    assert abs(clf.mean_darkness("CAM1", 7) - 0.6) < 1e-6
    assert clf.is_staff("CAM1", 7)


def test_unseen_track_is_not_staff():
    clf = StaffClassifier(threshold=0.5)
    assert clf.mean_darkness("CAM1", 99) == 0.0
    assert not clf.is_staff("CAM1", 99)


def test_presence_fallback_off_by_default():
    clf = StaffClassifier(threshold=0.5)  # no fallback
    clf.observe("CAM1", 3, 0.1)  # not dark
    assert not clf.is_staff("CAM1", 3, dwell_ms=999_000)  # long dwell ignored when fallback off


def test_presence_fallback_flags_long_presence_when_enabled():
    clf = StaffClassifier(threshold=0.5, presence_fallback_ms=90_000)
    clf.observe("CAM1", 3, 0.1)  # not dark
    assert not clf.is_staff("CAM1", 3, dwell_ms=10_000)  # short -> still customer
    assert clf.is_staff("CAM1", 3, dwell_ms=120_000)  # long -> staff via fallback
