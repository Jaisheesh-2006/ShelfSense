"""Offline transform: enrich the committed behaviour events with the sample_events.jsonl superset.

# PROMPT
Task: Re-emit data/events/behavior.jsonl with the ADR-0040 metadata superset, filled HONESTLY from
      real signals (never fabricated):
        - zone_name/zone_type/is_revenue_zone <- derived from zone_id (build_event_metadata)
        - queue_position_at_join              <- queue_depth at the JOIN
        - wait_seconds (billing events)       <- the visitor's real checkout-zone dwell
        - group_id/group_size (entry/exit)    <- co-entry heuristic (people arriving together)
        - gender_pred/age_bucket + hotspot    <- OPTIONAL VLM sidecar, merged if present
      Deterministic + idempotent; demographics only appear when the sidecar exists.
Context: events follow the delivered sample's richer schema as a metadata superset; the flat page-5
      top-level stays intact. The sidecar is produced by the detector's VLM pass and merged here BY
      visitor_id, so the validated counts never change.
Constraints: stdlib + shelfsense_common only; preserve event_id + top-level fields; validate against
      BehaviorEvent; serialise via model_dump_json (matches JsonlEventSink).
Output: rewrites data/events/behavior.jsonl (same order/count); prints per-store + demo counts.

# CHANGES MADE
- ADR-0040. Two-pass enrich: aggregate per-visitor signals, then write metadata. Sidecar-optional.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from shelfsense_common.contracts import BehaviorEvent, BehaviorEventType, build_event_metadata
from shelfsense_common.contracts.zones import ZoneName

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "data" / "events" / "behavior.jsonl"
# Demographics harvest sidecar (optional): {"<store_id>:<visitor_id>": {gender_pred, age_bucket,
# hotspot_x, hotspot_y, ...}}. Produced by the detector's VLM pass; merged if present.
SIDECAR = ROOT / "data" / "vlm" / "demographics.json"

# Two ENTRY crossings within this gap (same store) are treated as one arriving group (ADR-0040).
GROUP_WINDOW_MS = 4000

_ENTRY_TYPES = {BehaviorEventType.ENTRY, BehaviorEventType.EXIT, BehaviorEventType.REENTRY}
_BILLING_TYPES = {BehaviorEventType.BILLING_QUEUE_JOIN, BehaviorEventType.BILLING_QUEUE_ABANDON}


def _load_sidecar() -> dict[str, dict]:
    try:
        return json.loads(SIDECAR.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _group_assignments(events: list[BehaviorEvent]) -> dict[tuple[str, str], tuple[str, int]]:
    """Cluster ENTRY crossings that happen close together (per store) into co-arriving groups.

    Returns {(store_id, visitor_id): (group_id, group_size)} for visitors in a group of >= 2.
    A documented heuristic — the delivered sample's `group_id`/`group_size` are exactly people who
    entered together; with no group label in the source we infer it from co-entry timing.
    """
    entries: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for e in events:
        if e.event_type is BehaviorEventType.ENTRY:
            entries[e.store_id].append((int(e.timestamp.timestamp() * 1000), e.visitor_id))

    out: dict[tuple[str, str], tuple[str, int]] = {}
    for store_id, arrivals in entries.items():
        arrivals.sort()
        clusters: list[list[str]] = []
        prev_ts: int | None = None
        for ts, vid in arrivals:
            if prev_ts is None or ts - prev_ts > GROUP_WINDOW_MS:
                clusters.append([])
            clusters[-1].append(vid)
            prev_ts = ts
        seq = 0
        for members in clusters:
            unique = list(dict.fromkeys(members))
            if len(unique) >= 2:
                seq += 1
                gid = f"G_{store_id}_{seq}"
                for vid in unique:
                    out[(store_id, vid)] = (gid, len(unique))
    return out


def main() -> None:
    lines = [ln for ln in EVENTS.read_text(encoding="utf-8").splitlines() if ln.strip()]
    events = [BehaviorEvent.model_validate_json(ln) for ln in lines]

    sidecar = _load_sidecar()
    groups = _group_assignments(events)

    # Per-visitor real checkout-zone dwell -> wait_seconds for that visitor's billing events.
    checkout_ms: dict[tuple[str, str], int] = defaultdict(int)
    for e in events:
        if e.zone_id == ZoneName.CHECKOUT.value and e.dwell_ms:
            key = (e.store_id, e.visitor_id)
            checkout_ms[key] = max(checkout_ms[key], e.dwell_ms)

    enriched: list[str] = []
    by_store: dict[str, int] = defaultdict(int)
    demo_filled = 0
    for e in events:
        key = (e.store_id, e.visitor_id)
        meta = build_event_metadata(
            event_type=e.event_type,
            zone_id=e.zone_id,
            session_seq=e.metadata.session_seq,
            queue_depth=e.metadata.queue_depth,
            sku_zone=e.metadata.sku_zone,
        )
        if e.event_type in _BILLING_TYPES and checkout_ms.get(key):
            meta.wait_seconds = round(checkout_ms[key] / 1000)
        if e.event_type in _ENTRY_TYPES and key in groups:
            meta.group_id, meta.group_size = groups[key]
        demo = sidecar.get(f"{e.store_id}:{e.visitor_id}")
        if demo:
            meta.gender_pred = demo.get("gender_pred")
            meta.age_bucket = demo.get("age_bucket")
            if e.zone_id is not None:  # hotspot is a within-zone position
                meta.zone_hotspot_x = demo.get("hotspot_x")
                meta.zone_hotspot_y = demo.get("hotspot_y")
            if meta.gender_pred or meta.age_bucket:
                demo_filled += 1

        e.metadata = meta
        enriched.append(e.model_dump_json())
        by_store[e.store_id] += 1

    EVENTS.write_text("\n".join(enriched) + "\n", encoding="utf-8")
    print(f"enriched {len(enriched)} events -> {EVENTS}")
    for store, n in sorted(by_store.items()):
        print(f"  {store}: {n}")
    print(
        f"groups: {len({g for g, _ in groups.values()})} · demographics on {demo_filled} events"
        f" · sidecar {'present' if sidecar else 'absent'}"
    )


if __name__ == "__main__":
    main()
