"""Dev/replay fallback: POST a behavior.jsonl into the API, then print the live metrics/funnel.

As of Slice 2.8 (ADR-0015) the **detector auto-POSTs** its events to `/events/ingest`, so the stack
feeds itself with no manual step. This script remains useful for (a) replaying a pre-recorded JSONL
into a fresh API, and (b) demonstrating **idempotency**: re-running reports the same events as
`duplicates` and the metrics do not change.

Usage (API must be running, e.g. `docker compose up` or `uvicorn shelfsense_api.main:app`):
    python scripts/ingest_events.py
    python scripts/ingest_events.py --api http://localhost:8000 --events data/events/behavior.jsonl
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

BATCH = 500  # the API accepts <=500 events per request (API_SPEC)


def _post(api: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        api + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (local dev/demo tool)
        return json.loads(resp.read())


def _get(api: str, path: str) -> dict:
    with urllib.request.urlopen(api + path) as resp:  # noqa: S310
        return json.loads(resp.read())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--events", default="data/events/behavior.jsonl")
    parser.add_argument("--store", default="ST1008")
    args = parser.parse_args()

    path = Path(args.events)
    if not path.is_file():
        raise SystemExit(f"events file not found: {path} (run the pipeline first)")

    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    events = [json.loads(ln) for ln in lines]
    print(f"Read {len(events)} events from {path}")

    totals = {"accepted": 0, "duplicates": 0, "rejected": 0}
    for start in range(0, len(events), BATCH):
        resp = _post(args.api, "/events/ingest", {"events": events[start : start + BATCH]})
        for key in totals:
            totals[key] += resp.get(key, 0)
        if resp.get("errors"):
            print("  sample errors:", resp["errors"][:3])
    print(f"Ingest totals: {totals}")

    print(f"\nGET /stores/{args.store}/metrics:")
    print(json.dumps(_get(args.api, f"/stores/{args.store}/metrics"), indent=2))
    print(f"\nGET /stores/{args.store}/funnel:")
    print(json.dumps(_get(args.api, f"/stores/{args.store}/funnel"), indent=2))


if __name__ == "__main__":
    main()
