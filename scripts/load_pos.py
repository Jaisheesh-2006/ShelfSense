"""Quick sanity check for the POS loader (Slice 2.5; corrected dataset).

Finds the POS sales CSV under docs/raw/ and prints the baskets + the free day-level metrics
(count, total sales, average basket, peak hour, top brand). No video, no model.

Usage:
    python scripts/load_pos.py
"""

from __future__ import annotations

import glob
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "common"))

from shelfsense_common.config import get_settings  # noqa: E402
from shelfsense_common.conversion import pos_day_metrics  # noqa: E402
from shelfsense_common.pos_loader import load_transactions  # noqa: E402


def _find_csv(fallback: str) -> str:
    hits = sorted(glob.glob(str(REPO / "docs" / "raw" / "*.csv")))
    return hits[0] if hits else fallback


def main() -> None:
    s = get_settings()
    csv = _find_csv(s.pos_csv_path)
    txns = load_transactions(csv, s.store_timezone)
    print(f"loaded {len(txns)} transactions from {Path(csv).name}\n")
    print(f"  {'time (UTC)':<17} {'amount':>9}  brand")
    for t in txns:
        when = t.timestamp.strftime("%Y-%m-%d %H:%M")
        print(f"  {when:<17} {t.amount:>9.2f}  {t.brand}")
    m = pos_day_metrics(txns, s.store_timezone)
    print(
        f"\nday metrics: {m['transaction_count']} sales | total Rs {m['total_gmv']:.0f} | "
        f"avg basket Rs {m['avg_basket']:.0f} | peak hour {m['peak_hour']}:00 | "
        f"top brand {m['top_brand']}"
    )


if __name__ == "__main__":
    main()
