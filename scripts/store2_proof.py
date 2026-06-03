"""Proof montage for Store_2 (ST1009): the people the pipeline counted, labelled customer vs staff.

Re-runs the SAME detection path as the service over Store_2's cameras (same per-store Re-ID
distance, dwell, box-size + entrance-line gates), captures the clearest crop of each de-duplicated
`visitor_id`, and labels it from the **VLM verdict cache** (`data/store2_cache.json`, written by the
Groq run) — so no new API calls. Writes one labelled grid so a reviewer can eyeball who was counted
and how each person was classified (green = customer, red = staff), with the model's confidence.

Usage:  python scripts/store2_proof.py
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
from app.gating import passes_size_gate  # noqa: E402
from app.reid import SIGNATURE_LEN, ReIDGallery, appearance_signature  # noqa: E402
from app.visits import VisitorRegistry  # noqa: E402
from app.vlm import build_vlm_client  # noqa: E402
from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.logging import configure_logging, get_logger  # noqa: E402
from shelfsense_common.stores import get_store  # noqa: E402

STORE_ID = "ST1009"
CCTV = REPO / "docs" / "raw" / "Store_CCTV_Clips"
CACHE = REPO / "data" / "store2_cache.json"
OUT = REPO / "docs" / "wiki" / "frames" / "store2_customers_staff.jpg"
GREEN, RED, WHITE, BG = (0, 200, 0), (0, 0, 255), (255, 255, 255), (24, 24, 24)
TILE_H, PER_ROW = 200, 8


def _norm(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def main() -> None:
    s = get_settings()
    configure_logging("proof", "ERROR")
    log = get_logger("proof")
    store = get_store(STORE_ID)
    reid = store.reid_max_distance or s.reid_max_distance
    dwell = store.min_zone_dwell_ms or s.min_zone_dwell_ms

    from app.track import PersonTracker

    tracker = PersonTracker(
        s.yolo_model, s.detection_confidence, s.person_class_id,
        tracker_cfg=s.tracker_cfg, imgsz=s.detector_imgsz, iou=s.detection_iou,
    )
    registry = VisitorRegistry(
        ReIDGallery(max_distance=reid, reentry_min_gap_ms=s.reid_reentry_min_gap_ms)
    )
    recs: dict[tuple[str, int], dict] = {}

    for cam in store.customer_cameras:
        clip = CCTV / store.clips_dir / cam.file
        if not clip.exists():
            continue
        tracker.reset()
        with VideoFrameSource(clip, sample_fps=s.tracker_sample_fps) as src:
            fh, fw = src.height, src.width
            print(f"{cam.camera_id}: {src.total_frames} frames")
            for frame in src.frames():
                for t in tracker.update(frame.image):
                    b = t.bbox
                    if not passes_size_gate(b.w, b.h, fw, fh, s.min_detection_box_frac):
                        continue
                    fx, fy = t.foot_point
                    if cam.entrance_line is not None and not cam.entrance_line.is_inside(fx, fy):
                        continue  # mall pass-by — not counted (same gate as the pipeline)
                    x, y, w, h = int(b.x), int(b.y), int(b.w), int(b.h)
                    key = (cam.camera_id, t.track_id)
                    rec = recs.get(key)
                    if rec is None:
                        rec = recs[key] = {
                            "first": frame.ts_ms, "sig": np.zeros(SIGNATURE_LEN, np.float32),
                            "resolved": False, "vid": None, "area": 0, "crop": None,
                        }
                    area = max(0, w) * max(0, h)
                    if area > rec["area"]:
                        x0, y0 = max(0, x), max(0, y)
                        x1, y1 = min(fw, x + w), min(fh, y + h)
                        if x1 > x0 and y1 > y0:
                            rec["area"], rec["crop"] = area, frame.image[y0:y1, x0:x1].copy()
                    if not rec["resolved"]:
                        rec["sig"] = rec["sig"] + appearance_signature(frame.image, x, y, w, h)
                        if frame.ts_ms - rec["first"] >= dwell:
                            res = registry.resolve(
                                cam.camera_id, t.track_id, _norm(rec["sig"]), frame.ts_ms
                            )
                            rec["resolved"], rec["vid"] = True, res.visitor_id

    # Best crop per global visitor + the cached VLM verdict.
    visitors: dict[str, dict] = {}
    for rec in recs.values():
        if not rec["resolved"] or rec["crop"] is None:
            continue
        v = visitors.setdefault(rec["vid"], {"area": 0, "crop": None})
        if rec["area"] > v["area"]:
            v["area"], v["crop"] = rec["area"], rec["crop"]
    # Label each visitor's clearest crop with a LIVE VLM call on that exact crop — the label shown
    # is literally the model's verdict on the pictured person (self-consistent proof, not a lookup).
    vlm = build_vlm_client(s, log)
    for vid, v in sorted(visitors.items()):
        v["staff"], v["conf"] = False, 0.0
        if vlm is None:
            continue
        try:
            verdict = vlm.classify_staff(v["crop"], staff_hint=store.staff_uniform_hint)
            v["staff"], v["conf"] = verdict.is_staff, verdict.confidence
        except Exception as err:  # noqa: BLE001 — leave as customer if the call fails
            print(f"{vid}: vlm failed: {str(err)[:80]}")

    customers = [(k, v) for k, v in visitors.items() if not v["staff"]]
    staff = [(k, v) for k, v in visitors.items() if v["staff"]]
    print(f"\nvisitors={len(visitors)}  customers={len(customers)}  staff={len(staff)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT), _montage(customers, staff))
    print(f"proof montage -> {OUT}")


def _tile(vid: str, v: dict, label: str, colour) -> np.ndarray:
    crop = v["crop"]
    scale = TILE_H / crop.shape[0]
    img = cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), TILE_H))
    w = max(img.shape[1], 150)
    if img.shape[1] < w:
        e = w - img.shape[1]
        img = cv2.copyMakeBorder(img, 0, 0, e // 2, e - e // 2, cv2.BORDER_CONSTANT, value=BG)
    img = cv2.copyMakeBorder(img, 0, 0, 4, 4, cv2.BORDER_CONSTANT, value=colour)
    bar = np.full((46, img.shape[1], 3), 30, np.uint8)
    cv2.putText(bar, f"{label} {v['conf']:.2f}", (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)
    cv2.putText(bar, vid, (6, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
    return cv2.vconcat([bar, img])


def _grid(items: list, label: str, colour) -> np.ndarray:
    tiles = [_tile(k, v, label, colour) for k, v in sorted(items)]
    if not tiles:
        return np.full((10, 10, 3), BG, np.uint8)
    rows = []
    for i in range(0, len(tiles), PER_ROW):
        chunk = tiles[i : i + PER_ROW]
        hgt = max(t.shape[0] for t in chunk)
        chunk = [cv2.copyMakeBorder(t, 0, hgt - t.shape[0], 6, 6, cv2.BORDER_CONSTANT, value=BG)
                 for t in chunk]
        rows.append(cv2.hconcat(chunk))
    w = max(r.shape[1] for r in rows)
    rows = [cv2.copyMakeBorder(r, 6, 6, 0, w - r.shape[1], cv2.BORDER_CONSTANT, value=BG)
            for r in rows]
    return cv2.vconcat(rows)


def _hdr(text: str, colour, width: int) -> np.ndarray:
    bar = np.full((40, width, 3), 18, np.uint8)
    cv2.putText(bar, text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
    return bar


def _montage(customers: list, staff: list) -> np.ndarray:
    cg, sg = _grid(customers, "CUST", GREEN), _grid(staff, "STAFF", RED)
    width = max(cg.shape[1], sg.shape[1], 600)
    parts = [
        _hdr(f"STORE_2 (ST1009) - VLM (Llama-4 Scout via Groq).  CUSTOMERS = {len(customers)}",
             GREEN, width),
        cv2.copyMakeBorder(cg, 0, 0, 0, width - cg.shape[1], cv2.BORDER_CONSTANT, value=BG),
        _hdr(f"STAFF = {len(staff)}  (excluded from customer metrics)", RED, width),
        cv2.copyMakeBorder(sg, 0, 0, 0, width - sg.shape[1], cv2.BORDER_CONSTANT, value=BG),
    ]
    return cv2.vconcat(parts)


if __name__ == "__main__":
    main()
