"""Billing-queue detection for the checkout camera (Slice 2.5).

A small, pure state machine that turns checkout-zone presence into `BILLING_QUEUE_JOIN` events with
a `queue_depth`. It is driven off the existing `ZoneTracker` ZONE_ENTER / ZONE_EXIT on the checkout
camera (no new CV): when a **customer** (not staff) enters the checkout zone we record them as a
queue occupant and emit a JOIN carrying the current queue size; when they leave we drop them.

Why separate from `ZoneTracker`: `queue_depth` is a *cross-track* count ("how many are at the
checkout right now"), which doesn't belong in its per-track presence logic. Keeping it apart leaves
both single-responsibility and independently unit-testable.

Staff are excluded from the queue (the cashier is not a customer waiting to pay).
`BILLING_QUEUE_ABANDON` is **not** decided here — it needs the POS sales data the detector
deliberately doesn't see; it is derived later in shelfsense_common.conversion (no matching sale).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shelfsense_common.contracts import BehaviorEventType


@dataclass(frozen=True)
class BillingEvent:
    """A queue-join for one track — raw material for a BILLING_QUEUE_JOIN BehaviorEvent."""

    track_id: int
    event_type: BehaviorEventType  # BILLING_QUEUE_JOIN
    ts_ms: int
    queue_depth: int  # number of customers in the billing zone, including this joiner
    confidence: float


@dataclass
class BillingTracker:
    """Tracks customers currently in the checkout zone and emits queue-join events."""

    _occupants: set[int] = field(default_factory=set)

    def join(
        self, track_id: int, ts_ms: int, confidence: float, *, is_staff: bool
    ) -> list[BillingEvent]:
        """Customer entered the checkout zone -> record + emit JOIN with the live queue depth.

        Staff are ignored (not part of the customer queue). Idempotent: a repeated entry for a track
        already counted emits nothing.
        """
        if is_staff or track_id in self._occupants:
            return []
        self._occupants.add(track_id)
        return [
            BillingEvent(
                track_id,
                BehaviorEventType.BILLING_QUEUE_JOIN,
                ts_ms,
                len(self._occupants),
                confidence,
            )
        ]

    def leave(self, track_id: int) -> None:
        """Track left the checkout zone — free its queue slot (no-op if it never joined)."""
        self._occupants.discard(track_id)

    @property
    def occupancy(self) -> int:
        """Current number of customers in the checkout zone."""
        return len(self._occupants)
