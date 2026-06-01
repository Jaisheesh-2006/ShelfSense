"""Evidence montage: show the actual people the pipeline counted, labelled customer vs staff.

Re-runs the same detection path as the service over the SHOPPING-FLOOR cameras (CAM1/CAM2/CAM5;
the entrance camera counts footfall only, ADR-0011; CAM4 is the empty stockroom) and, for every
de-duplicated `visitor_id`, captures the clearest crop of that person plus the staff decision. It
then writes a single labelled image so a reviewer can eyeball: *these two are the customers I
counted (grey / violet), these are staff (black uniform)*.

It mirrors `run_once`: same tracker/gallery/registry/staff-classifier and config, the CAM5 floor
mask, and the lazy resolve at `min_zone_dwell`. So the montage reproduces the live count
(2 customers + N staff). Crops are for human verification only — no events are emitted.

Usage:
    python scripts/evidence_visitors.py            # CAM1 CAM2 CAM5
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))
sys.path.insert(0, str(REPO / "services" / "detector"))

import cv2  # noqa: E402
from app.frames import VideoFrameSource  # noqa: E402
from app.reid import SIGNATURE_LEN, ReIDGallery, appearance_signature  # noqa: E402
from app.staff import StaffClassifier, uniform_darkness  # noqa: E402
from app.track import PersonTracker  # noqa: E402
from app.visits import VisitorRegistry  # noqa: E402
from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.contracts import STORE, CameraRole  # noqa: E402

RAW = REPO / "docs" / "raw" / "CCTV Footage" / "CCTV Footage"
OUT = REPO / "docs" / "wiki" / "frames" / "evidence_visitors.jpg"
GREEN, RED, WHITE = (0, 200, 0), (0, 0, 255), (255, 255, 255)
TILE_H = 260


def _norm(vec: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(vec))
    return vec / n if n > 0 else vec


def main() -> None:
    settings = get_settings()
    wanted = {a.upper().replace(" ", "") for a in sys.argv[1:]} or {"CAM1", "CAM2", "CAM5"}
    cameras = [
        c for c in STORE.cameras
        if c.camera_id in wanted and c.is_customer_area and c.role is not CameraRole.ENTRANCE
    ]
    tracker = PersonTracker(
        settings.yolo_model, settings.detection_confidence, settings.person_class_id,
        tracker_cfg=settings.tracker_cfg,
    )
    gallery = ReIDGallery(
        max_distance=settings.reid_max_distance, reentry_min_gap_ms=settings.reid_reentry_min_gap_ms
    )
    registry = VisitorRegistry(gallery)
    staff = StaffClassifier(
        threshold=settings.staff_darkness_threshold,
        presence_fallback_ms=(
            settings.staff_min_presence_ms if settings.staff_presence_fallback else None
        ),
    )
    # (camera, track) -> record. Resolve mirrors the pipeline: at min_zone_dwell with the signature
    # accumulated so far; darkness is observed only pre-resolve, exactly as the service does.
    recs: dict[tuple[str, int], dict] = {}

    for cam in cameras:
        clip = RAW / cam.file
        if not clip.exists():
            print(f"{cam.camera_id}: clip missing")
            continue
        tracker.reset()
        with VideoFrameSource(clip, sample_fps=settings.tracker_sample_fps) as src:
            print(f"{cam.camera_id}: scanning {src.total_frames} frames")
            for frame in src.frames():
                for t in tracker.update(frame.image):
                    if cam.floor_region is not None:
                        fx, fy = t.foot_point
                        if not cam.floor_region.contains(fx, fy):
                            continue
                    b = t.bbox
                    x, y, w, h = int(b.x), int(b.y), int(b.w), int(b.h)
                    key = (cam.camera_id, t.track_id)
                    rec = recs.get(key)
                    if rec is None:
                        rec = recs[key] = {
                            "first": frame.ts_ms, "sig": np.zeros(SIGNATURE_LEN, np.float32),
                            "resolved": False, "vid": None, "area": 0, "crop": None,
                        }
                    # Keep the largest (clearest) crop of this person for the montage.
                    area = max(0, w) * max(0, h)
                    if area > rec["area"]:
                        x0, y0 = max(0, x), max(0, y)
                        x1 = min(frame.image.shape[1], x + w)
                        y1 = min(frame.image.shape[0], y + h)
                        if x1 > x0 and y1 > y0:
                            rec["area"] = area
                            rec["crop"] = frame.image[y0:y1, x0:x1].copy()
                    if not rec["resolved"]:
                        rec["sig"] = rec["sig"] + appearance_signature(frame.image, x, y, w, h)
                        staff.observe(
                            cam.camera_id, t.track_id,
                            uniform_darkness(frame.image, x, y, w, h, settings.staff_dark_v_max),
                        )
                        if frame.ts_ms - rec["first"] >= settings.min_zone_dwell_ms:
                            res = registry.resolve(
                                cam.camera_id, t.track_id, _norm(rec["sig"]), frame.ts_ms
                            )
                            rec["resolved"], rec["vid"] = True, res.visitor_id

    # Group resolved tracks by global visitor; staff if ANY of its tracks is flagged (API rule).
    visitors: dict[str, dict] = {}
    for (cam_id, tid), rec in recs.items():
        if not rec["resolved"] or rec["crop"] is None:
            continue
        is_staff = staff.is_staff(cam_id, tid)
        dark = staff.mean_darkness(cam_id, tid)
        v = visitors.setdefault(rec["vid"], {"staff": False, "area": 0, "crop": None,
                                             "dark": dark, "cams": set()})
        v["staff"] = v["staff"] or is_staff
        v["cams"].add(cam_id)
        if rec["area"] > v["area"]:  # clearest crop across this visitor's cameras
            v["area"], v["crop"], v["dark"] = rec["area"], rec["crop"], dark

    customers = [(k, v) for k, v in visitors.items() if not v["staff"]]
    staff_v = [(k, v) for k, v in visitors.items() if v["staff"]]
    print(f"\nunique visitors: {len(visitors)} -> customers={len(customers)} staff={len(staff_v)}")

    montage = _build_montage(customers, staff_v)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT), montage)
    print(f"evidence montage -> {OUT}")


def _tile(vid: str, v: dict, label: str, colour) -> np.ndarray:
    """One labelled crop: resized to TILE_H, coloured border, caption bar above."""
    crop = v["crop"]
    scale = TILE_H / crop.shape[0]
    img = cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), TILE_H))
    img = cv2.copyMakeBorder(img, 0, 0, 6, 6, cv2.BORDER_CONSTANT, value=colour)
    w = max(img.shape[1], 210)  # min width so the caption never clips
    if img.shape[1] < w:
        extra = w - img.shape[1]
        img = cv2.copyMakeBorder(img, 0, 0, extra // 2, extra - extra // 2,
                                 cv2.BORDER_CONSTANT, value=(20, 20, 20))
    bar = np.full((54, w, 3), 30, np.uint8)
    cv2.putText(bar, f"{label}  dark={v['dark']:.2f}", (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, colour, 2)
    cv2.putText(bar, f"{vid[-6:]}  {'+'.join(sorted(v['cams']))}", (8, 44),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
    return cv2.vconcat([bar, img])


def _row(items: list, label: str, colour) -> np.ndarray:
    tiles = [_tile(k, v, label, colour) for k, v in sorted(items, key=lambda kv: kv[1]["dark"])]
    h = max(t.shape[0] for t in tiles)
    pad = (20, 20, 20)
    padded = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 8, 8, cv2.BORDER_CONSTANT, value=pad)
              for t in tiles]
    return cv2.hconcat(padded)


def _build_montage(customers: list, staff_v: list) -> np.ndarray:
    sections = []  # (header text, colour, row image)
    if customers:
        sections.append((f"CUSTOMERS ({len(customers)}) - counted in conversion",
                         GREEN, _row(customers, "CUSTOMER", GREEN)))
    if staff_v:
        sections.append((f"STAFF ({len(staff_v)}) - excluded from customer metrics",
                         RED, _row(staff_v, "STAFF", RED)))
    width = max(r.shape[1] for _, _, r in sections)
    rows = []
    for text, colour, r in sections:
        rows.append(_header(text, colour, width))
        rows.append(cv2.copyMakeBorder(r, 0, 0, 0, width - r.shape[1],
                                       cv2.BORDER_CONSTANT, value=(20, 20, 20)))
    return cv2.vconcat(rows)


def _header(text: str, colour, width: int) -> np.ndarray:
    bar = np.full((44, width, 3), 20, np.uint8)
    cv2.putText(bar, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
    return bar


if __name__ == "__main__":
    main()
