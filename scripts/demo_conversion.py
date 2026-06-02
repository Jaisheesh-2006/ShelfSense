"""Conversion: the honest clip reading + a clearly-labelled full-day mechanism demo (Slice 2.5).

Reads the real emitted events (data/events/behavior.jsonl) and the real sales CSV, then:

  * HONEST (default): correlates real billing-zone customers with real sales. On the 2-minute clip
    no customer reaches the checkout and no sale falls in the window, so conversion is **0%** with
    `data_confidence=low` and a real funnel drop-off — the truthful reading.

  * DEMO (POS_DEMO_ALIGNMENT=true): injects two *representative* billing visitors — one positioned
    2 minutes before a REAL sale (flips to CONVERTED), one with no following sale (ABANDONED) — so a
    reviewer can watch the correlation work over the full day. The real sales are used unchanged;
    only the alignment of the representative visitors is synthetic, and it is loudly labelled as
    such. The honest number above is never overwritten (the demo logic lives only in this script).

Usage:
    python scripts/emit_entrance_events.py          # first, to produce the events
    python scripts/demo_conversion.py               # honest reading
    POS_DEMO_ALIGNMENT=true python scripts/demo_conversion.py   # + the mechanism demo
"""

from __future__ import annotations

import glob
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))

from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.conversion import (  # noqa: E402
    BillingPresence,
    correlate_conversions,
    pos_day_metrics,
)
from shelfsense_common.pos_loader import load_transactions  # noqa: E402

EVENTS = REPO / "data" / "events" / "behavior.jsonl"


def _find_csv(fallback: str) -> str:
    hits = sorted(glob.glob(str(REPO / "docs" / "raw" / "*.csv")))
    return hits[0] if hits else fallback


def _load_events() -> list[dict]:
    if not EVENTS.exists():
        print(f"no events at {EVENTS} — run scripts/emit_entrance_events.py first")
        return []
    return [json.loads(ln) for ln in EVENTS.read_text(encoding="utf-8").splitlines() if ln.strip()]


def main() -> None:
    s = get_settings()
    txns = load_transactions(_find_csv(s.pos_csv_path), s.store_timezone)
    events = _load_events()

    # A visitor is staff if ANY of their events is flagged (API rule); customers = the rest.
    staff_any: dict[str, bool] = {}
    for e in events:
        v = e["visitor_id"]
        staff_any[v] = staff_any.get(v, False) or e["is_staff"]
    customers = {v for v, st in staff_any.items() if not st}
    zone_visitors = {
        e["visitor_id"] for e in events
        if e["event_type"].startswith("ZONE_") and not staff_any[e["visitor_id"]]
    }
    presences = [
        BillingPresence(e["visitor_id"], datetime.fromisoformat(e["timestamp"]))
        for e in events
        if e["event_type"] == "BILLING_QUEUE_JOIN" and not staff_any[e["visitor_id"]]
    ]

    honest = correlate_conversions(
        presences, txns, customers, s.pos_correlation_window_ms, s.conversion_low_sample_threshold
    )
    print("=== HONEST CLIP READING (real events + real sales) ===")
    print(f"unique customers           : {honest.unique_visitors}")
    print(f"billing-zone customers     : {len(presences)}")
    print(f"converted                  : {len(honest.converted_visitor_ids)}")
    print(f"CONVERSION RATE            : {honest.conversion_rate:.0%}   "
          f"(data_confidence={honest.data_confidence})")
    print(f"funnel:  Entry {len(customers)}  ->  Zone Visit {len(zone_visitors)}  ->  "
          f"Billing Queue {len(presences)}  ->  Purchase {len(honest.converted_visitor_ids)}")
    print("note: 2-min clip - customers browsed (CAM2), none reached checkout, and no sale fell in "
          "the window. Honest 0, not a bug (the window mismatch).\n")

    m = pos_day_metrics(txns, s.store_timezone)
    print(f"real POS day-metrics       : {m['transaction_count']} sales | "
          f"total Rs {m['total_gmv']:.0f} | avg basket Rs {m['avg_basket']:.0f} | "
          f"peak {m['peak_hour']}:00 | top brand {m['top_brand']}\n")

    demo_on = s.pos_demo_alignment or os.environ.get("POS_DEMO_ALIGNMENT", "").lower() == "true"
    if not demo_on:
        print("(set POS_DEMO_ALIGNMENT=true to see the correlation shown against a real sale)")
        return

    # DEMO: representative billing visitors aligned to REAL sales (synthetic alignment, labelled).
    buyer_txn = txns[len(txns) // 2]
    buyer = BillingPresence("VIS_demo_buyer", buyer_txn.timestamp - timedelta(minutes=2))
    leaver = BillingPresence("VIS_demo_leaver", txns[-1].timestamp + timedelta(seconds=1))
    demo_customers = customers | {"VIS_demo_buyer", "VIS_demo_leaver"}
    demo = correlate_conversions(
        [buyer, leaver, *presences], txns, demo_customers,
        s.pos_correlation_window_ms, s.conversion_low_sample_threshold,
    )
    print("=== FULL-DAY MECHANISM DEMO (representative visitors aligned to REAL sales) ===")
    print("!! NOT a reading of the 2-min clip - demonstrates the correlation logic only. !!")
    print(f"VIS_demo_buyer : at billing 2 min before real sale {buyer_txn.transaction_id} "
          f"({buyer_txn.timestamp:%H:%M} UTC, Rs {buyer_txn.amount:.0f})  ->  "
          f"CONVERTED={'VIS_demo_buyer' in demo.converted_visitor_ids}")
    print(f"VIS_demo_leaver: at billing with no following sale  ->  "
          f"ABANDONED={'VIS_demo_leaver' in demo.abandoned_visitor_ids}")
    print(f"demo conversion rate       : {demo.conversion_rate:.0%} "
          f"({len(demo.converted_visitor_ids)}/{demo.unique_visitors})")


if __name__ == "__main__":
    main()
