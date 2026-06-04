"""Assemble the per-visitor crops dumped by the detector (STAFF_CROP_DUMP_DIR) into one labelled
montage per store — a staff row and a customer row, each tile captioned with the visitor id, the
classification, the colour score and the decision source. A human-adjudication / proof aid.

Crops are produced by a detection run with STAFF_CROP_DUMP_DIR set; filenames carry the metadata:
    {store}_{VIS_xxxx}_{cust|STAFF}_c{score}_{source}.jpg

Usage:  python scripts/crops_montage.py [--crops data/crops] [--out data/crops]
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

GREEN, RED, WHITE, BG = (0, 200, 0), (0, 0, 255), (255, 255, 255), (24, 24, 24)
TILE_H, PER_ROW = 220, 8
# {store}_{visitor}_{label}_c{score}_{source}.jpg  (label = cust|STAFF; source may contain "_")
NAME = re.compile(
    r"^(?P<store>[^_]+)_(?P<vid>VIS_\d+)_(?P<label>cust|STAFF)_c(?P<score>[0-9.]+)_(?P<src>.+)$"
)


def _tile(path: Path, vid: str, label: str, score: str, src: str) -> np.ndarray:
    img = cv2.imread(str(path))
    if img is None:
        img = np.full((TILE_H, 140, 3), BG, np.uint8)
    scale = TILE_H / img.shape[0]
    img = cv2.resize(img, (max(1, int(img.shape[1] * scale)), TILE_H))
    img = cv2.copyMakeBorder(img, 0, 0, 4, 4, cv2.BORDER_CONSTANT,
                             value=RED if label == "STAFF" else GREEN)
    w = max(img.shape[1], 168)
    if img.shape[1] < w:
        e = w - img.shape[1]
        img = cv2.copyMakeBorder(img, 0, 0, e // 2, e - e // 2, cv2.BORDER_CONSTANT, value=BG)
    bar = np.full((58, img.shape[1], 3), 30, np.uint8)
    colour = RED if label == "STAFF" else GREEN
    cv2.putText(bar, f"{vid}  c={score}", (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
    cv2.putText(bar, label, (6, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)
    cv2.putText(bar, src[:20], (6, 53), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (160, 160, 160), 1)
    return cv2.vconcat([bar, img])


def _grid(tiles: list[np.ndarray]) -> np.ndarray:
    if not tiles:
        return np.full((10, 10, 3), BG, np.uint8)
    rows = []
    for i in range(0, len(tiles), PER_ROW):
        chunk = tiles[i : i + PER_ROW]
        h = max(t.shape[0] for t in chunk)
        chunk = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 6, 6, cv2.BORDER_CONSTANT, value=BG)
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


def main() -> None:
    ap = argparse.ArgumentParser(description="Montage the dumped per-visitor crops, per store.")
    ap.add_argument("--crops", default="data/crops")
    ap.add_argument("--out", default="data/crops")
    args = ap.parse_args()

    crops_dir, out_dir = Path(args.crops), Path(args.out)
    by_store: dict[str, list[Path]] = defaultdict(list)
    for p in sorted(crops_dir.glob("*.jpg")):
        m = NAME.match(p.stem)
        if m:
            by_store[m.group("store")].append(p)

    for store, paths in sorted(by_store.items()):
        staff, cust = [], []
        for p in paths:
            m = NAME.match(p.stem)
            tile = _tile(p, m.group("vid"), m.group("label"), m.group("score"), m.group("src"))
            (staff if m.group("label") == "STAFF" else cust).append(tile)
        cg, sg = _grid(cust), _grid(staff)
        width = max(cg.shape[1], sg.shape[1], 600)
        parts = [
            _hdr(f"{store}  CUSTOMERS = {len(cust)}", GREEN, width),
            cv2.copyMakeBorder(cg, 0, 0, 0, width - cg.shape[1], cv2.BORDER_CONSTANT, value=BG),
            _hdr(f"{store}  STAFF = {len(staff)}", RED, width),
            cv2.copyMakeBorder(sg, 0, 0, 0, width - sg.shape[1], cv2.BORDER_CONSTANT, value=BG),
        ]
        out = out_dir / f"montage_{store}.jpg"
        cv2.imwrite(str(out), cv2.vconcat(parts))
        print(f"{store}: customers={len(cust)} staff={len(staff)} -> {out}")


if __name__ == "__main__":
    main()
