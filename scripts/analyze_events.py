"""Analyse a detector events JSONL and print a per-camera / per-visitor breakdown.

A validation aid (not part of the pipeline): given the events the detector emitted, summarise what
was counted so it can be compared, camera by camera, against hand-labelled ground truth — distinct
visitors, the staff/customer split (any-flag rule, matching the API), ENTRY/EXIT/REENTRY counts,
and a per-visitor trace (cameras seen on, event types, staff flag, confidence, dwell).

Usage:
    python scripts/analyze_events.py data/events/store1_local.jsonl
    python scripts/analyze_events.py data/events/store2_local.jsonl --store ST1009
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _load(path: Path, store: str | None) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        ev = json.loads(line)
        if store and ev.get("store_id") != store:
            continue
        rows.append(ev)
    return rows


def _staff_visitors(events: list[dict]) -> set[str]:
    """Any-flag rule: a visitor is staff if ANY of its events is is_staff=true."""
    flagged: dict[str, bool] = defaultdict(bool)
    for e in events:
        flagged[e["visitor_id"]] = flagged[e["visitor_id"]] or bool(e.get("is_staff"))
    return {v for v, s in flagged.items() if s}


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarise detector events for GT comparison.")
    ap.add_argument("path", help="events JSONL file")
    ap.add_argument("--store", default="", help="filter to one store_id")
    args = ap.parse_args()

    events = _load(Path(args.path), args.store or None)
    if not events:
        print("no events")
        return

    staff = _staff_visitors(events)
    all_vids = {e["visitor_id"] for e in events}
    customers = all_vids - staff

    stores = sorted({e["store_id"] for e in events})
    print(f"=== {args.path}  stores={stores}  events={len(events)} ===")
    print(f"UNIQUE PEOPLE: {len(all_vids)}  -> customers={len(customers)}  staff={len(staff)}")

    # Overall event-type counts.
    type_counts: dict[str, int] = defaultdict(int)
    for e in events:
        type_counts[e["event_type"]] += 1
    print("event_types:", dict(sorted(type_counts.items())))

    # Per-camera breakdown.
    print("\n--- per camera ---")
    cams = sorted({e["camera_id"] for e in events})
    for cam in cams:
        cev = [e for e in events if e["camera_id"] == cam]
        cv = {e["visitor_id"] for e in cev}
        cstaff = cv & staff
        ccust = cv - staff
        tc: dict[str, int] = defaultdict(int)
        for e in cev:
            tc[e["event_type"]] += 1
        entries = tc.get("ENTRY", 0)
        exits = tc.get("EXIT", 0)
        reentry = tc.get("REENTRY", 0)
        print(
            f"{cam:8} people={len(cv):2} (cust={len(ccust)} staff={len(cstaff)})  "
            f"ENTRY={entries} EXIT={exits} REENTRY={reentry}  types={dict(sorted(tc.items()))}"
        )

    # Per-visitor trace.
    print("\n--- per visitor ---")
    by_vid: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_vid[e["visitor_id"]].append(e)
    for vid in sorted(by_vid, key=lambda v: (v in staff, v)):
        evs = by_vid[vid]
        vcams = sorted({e["camera_id"] for e in evs})
        vtypes = sorted({e["event_type"] for e in evs})
        confs = [e.get("confidence", 0.0) for e in evs]
        dwell = max((e.get("dwell_ms", 0) for e in evs), default=0)
        tag = "STAFF " if vid in staff else "cust  "
        print(
            f"{tag}{vid[:14]:14} cams={','.join(vcams):20} "
            f"conf={min(confs):.2f}-{max(confs):.2f} max_dwell={dwell:6}ms types={vtypes}"
        )


if __name__ == "__main__":
    main()
