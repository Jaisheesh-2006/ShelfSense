"""Slice 2.2 validation: prove the entrance line + crossing logic count footfall correctly.

Runs the SAME PersonTracker + CrossingDetector the detector service uses, over the whole CAM3
clip, draws each track's id/box/foot-point and the calibrated line, and saves the frames where a
crossing fires (annotated ENTRY/EXIT) plus a few evenly spaced context frames. Prints the system's
ENTRY/EXIT tally and a per-event log so a human can eye-count entries from the saved frames and
compare. If the counts are off, nudge the line in zones.py or the fps/confirm-frames and re-run.

Usage:
    python scripts/validate_entrance.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))
sys.path.insert(0, str(REPO / "services" / "detector"))

from app.crossing import CrossingDetector  # noqa: E402
from app.frames import VideoFrameSource  # noqa: E402
from app.track import PersonTracker  # noqa: E402
from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.contracts import STORE  # noqa: E402

RAW = REPO / "docs" / "raw" / "CCTV Footage" / "CCTV Footage"
OUT = REPO / "docs" / "wiki" / "frames"
GREEN = (0, 230, 0)
CYAN = (230, 230, 0)
RED = (0, 0, 230)
MAX_CONTEXT_FRAMES = 4


def _draw(img, tracks, line, banner: str | None):
    for t in tracks:
        b = t.bbox
        p1, p2 = (int(b.x), int(b.y)), (int(b.x + b.w), int(b.y + b.h))
        fx, fy = (int(v) for v in t.foot_point)
        cv2.rectangle(img, p1, p2, GREEN, 2)
        cv2.circle(img, (fx, fy), 5, RED, -1)  # foot-point: what the line test uses
        cv2.putText(
            img, f"id{t.track_id}", (p1[0], p1[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, GREEN, 2
        )
    cv2.line(img, (int(line.x1), int(line.y1)), (int(line.x2), int(line.y2)), CYAN, 3)
    if banner:
        cv2.putText(img, banner, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, RED, 3)


def main() -> None:
    settings = get_settings()
    cam = STORE.entrance_camera
    clip_path = RAW / cam.file
    line = cam.entrance_line

    tracker = PersonTracker(
        settings.yolo_model,
        settings.detection_confidence,
        settings.person_class_id,
        tracker_cfg=settings.tracker_cfg,
    )
    crossing = CrossingDetector(line, confirm_frames=settings.crossing_confirm_frames)

    OUT.mkdir(parents=True, exist_ok=True)
    entries = exits = saved = 0
    events: list[str] = []
    sides_seen: dict[int, set[int]] = {}  # track_id -> set of line sides observed (diagnostics)
    track_pts: dict[int, list[tuple[int, int]]] = {}  # track_id -> foot-points (trajectory map)
    frames_with_tracks = 0
    backdrop = None

    with VideoFrameSource(clip_path, sample_fps=settings.tracker_sample_fps) as src:
        total = src.total_frames
        context_at = {int(total * f) for f in (0.2, 0.4, 0.6, 0.8)}
        print(
            f"{cam.camera_id}: {src.width}x{src.height} @ {src.source_fps:.2f}fps, "
            f"sampling {settings.tracker_sample_fps}fps, "
            f"line={line.x1, line.y1}->{line.x2, line.y2}, conf={settings.detection_confidence}"
        )
        for frame in src.frames():
            if backdrop is None:
                backdrop = frame.image.copy()  # first frame, as a map background
            tracks = tracker.update(frame.image)
            frames_with_tracks += bool(tracks)
            crosses = []
            for t in tracks:
                fx, fy = t.foot_point
                sides_seen.setdefault(t.track_id, set()).add(line.side(fx, fy))
                track_pts.setdefault(t.track_id, []).append((int(fx), int(fy)))
                crosses.extend(crossing.update(t.track_id, fx, fy, frame.ts_ms, t.confidence))

            for c in crosses:
                kind = c.event_type.value
                entries += kind == "ENTRY"
                exits += kind == "EXIT"
                events.append(f"  t={c.ts_ms / 1000:6.1f}s  {kind:5}  (track {c.track_id})")

            near_ctx = any(abs(frame.index - c) < src.stride for c in context_at)
            should_save = bool(crosses) or near_ctx
            if should_save and saved < 16:
                img = frame.image.copy()
                banner = "  ".join(c.event_type.value for c in crosses) or None
                _draw(img, tracks, line, banner)
                tag = "cross" if crosses else "ctx"
                out = OUT / f"CAM3_track_{tag}_{frame.index:04d}.jpg"
                cv2.imwrite(str(out), img)
                saved += 1

    print("\nEvents (system):")
    print("\n".join(events) if events else "  (none)")
    both_sides = {tid: s for tid, s in sides_seen.items() if {-1, 1} <= s}
    print("\nDiagnostics:")
    print(f"  distinct tracks: {len(sides_seen)}  |  frames with >=1 track: {frames_with_tracks}")
    print(f"  tracks on BOTH sides (potential crossers): {len(both_sides)} {list(both_sides)[:10]}")
    # Tracks that move the most vertically (toward/away from camera) — candidate entry paths.
    movers = sorted(
        ((tid, pts) for tid, pts in track_pts.items() if len(pts) >= 5),
        key=lambda kv: max(p[1] for p in kv[1]) - min(p[1] for p in kv[1]),
        reverse=True,
    )[:8]
    print("  top vertical-movers (track: x[min..max] y[min..max] nframes):")
    for tid, pts in movers:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        print(f"    id{tid}: x[{min(xs)}..{max(xs)}] y[{min(ys)}..{max(ys)}] n={len(pts)}")

    # Foot-point trajectory map: every track's path drawn on the first frame.
    if backdrop is not None:
        palette = [(0, 230, 0), (0, 200, 255), (255, 120, 0), (200, 0, 255), (0, 0, 255)]
        for i, (_tid, pts) in enumerate(track_pts.items()):
            color = palette[i % len(palette)]
            for p in pts:
                cv2.circle(backdrop, p, 3, color, -1)
        cv2.line(backdrop, (int(line.x1), int(line.y1)), (int(line.x2), int(line.y2)), CYAN, 2)
        cv2.imwrite(str(OUT / "CAM3_footfall_map.jpg"), backdrop)
        print("  trajectory map -> docs/wiki/frames/CAM3_footfall_map.jpg")
    print(f"\nSYSTEM TALLY  entries={entries}  exits={exits}  (saved {saved} frames)")


if __name__ == "__main__":
    main()
