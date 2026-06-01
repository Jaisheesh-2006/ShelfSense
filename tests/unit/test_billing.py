# PROMPT
# Task:
#   - Unit-test the BillingTracker: queue-join emission, queue_depth, staff exclusion, idempotency.
# Context:
#   - On the checkout camera, a non-staff visitor entering the billing zone emits BILLING_QUEUE_JOIN
#     with queue_depth = current customers in the zone (including the joiner). Staff never join; a
#     repeated entry for an already-counted track emits nothing; leave() frees the slot.
# Constraints:
#   - Pure logic only: drive join()/leave() directly; no frames, no model.
# Output:
#   - Tests: first join depth 1, second depth 2; staff excluded; repeat join is a no-op; leave frees
#     a slot so a later join re-counts; occupancy reflects current customers.
"""Unit tests for the billing-queue tracker."""

from app.billing import BillingTracker
from shelfsense_common.contracts import BehaviorEventType


def test_join_emits_with_increasing_queue_depth():
    bt = BillingTracker()
    first = bt.join(1, ts_ms=0, confidence=0.9, is_staff=False)
    second = bt.join(2, ts_ms=100, confidence=0.9, is_staff=False)
    assert len(first) == 1 and first[0].event_type is BehaviorEventType.BILLING_QUEUE_JOIN
    assert first[0].queue_depth == 1
    assert second[0].queue_depth == 2  # two customers now in the zone
    assert bt.occupancy == 2


def test_staff_never_join_the_queue():
    bt = BillingTracker()
    assert bt.join(1, ts_ms=0, confidence=0.9, is_staff=True) == []
    assert bt.occupancy == 0


def test_repeat_join_is_idempotent():
    bt = BillingTracker()
    bt.join(1, ts_ms=0, confidence=0.9, is_staff=False)
    assert bt.join(1, ts_ms=50, confidence=0.9, is_staff=False) == []  # already counted
    assert bt.occupancy == 1


def test_leave_frees_slot_and_allows_recount():
    bt = BillingTracker()
    bt.join(1, ts_ms=0, confidence=0.9, is_staff=False)
    bt.leave(1)
    assert bt.occupancy == 0
    again = bt.join(1, ts_ms=200, confidence=0.9, is_staff=False)  # returned to the queue
    assert len(again) == 1 and again[0].queue_depth == 1


def test_leave_unknown_track_is_noop():
    bt = BillingTracker()
    bt.leave(99)  # never joined
    assert bt.occupancy == 0
