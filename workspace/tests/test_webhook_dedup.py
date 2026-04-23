"""Phase 16 BRIDGE-04 — webhook dedup response contract lock.

These tests assert the HTTP-level dedup contract on POST /channels/whatsapp/webhook.
Wave 0 RED baseline: the tests are written but the test harness is not yet wired
(no FastAPI TestClient fixture for this route). Plan 05 Task 1 adds the fixture
so tests flip RED → GREEN.

Contract (BRIDGE-04):
  When the bridge POSTs the same message_id twice within 300s, the second response
  MUST contain {"accepted": true, "reason": "duplicate"}. Additional keys are OK
  (e.g., current impl also includes "status": "skipped").
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.asyncio


async def test_duplicate_returns_accepted_true():
    """BRIDGE-04: second POST with same message_id returns accepted: true + reason: duplicate."""
    from sci_fi_dashboard.gateway.dedup import MessageDeduplicator

    dedup = MessageDeduplicator(window_seconds=300)
    # First sighting
    assert dedup.is_duplicate("msg-abc-001") is False
    # Second sighting within TTL
    assert dedup.is_duplicate("msg-abc-001") is True
    # Plan 05 Task 1 adds an end-to-end test with a FastAPI TestClient hitting POST /channels/whatsapp/webhook;
    # Wave 0 locks the unit-level contract only.


async def test_first_passes_second_dropped():
    """BRIDGE-04: counter-based metric — hit count increments on duplicate, miss on new."""
    from sci_fi_dashboard.gateway.dedup import MessageDeduplicator

    dedup = MessageDeduplicator(window_seconds=300)
    # Plan 05 Task 1 adds `.hits` + `.misses` attributes. Wave 0 asserts the metric contract:
    dedup.is_duplicate("new-1")
    dedup.is_duplicate("new-2")
    dedup.is_duplicate("new-1")  # duplicate
    assert getattr(dedup, "hits", 0) == 1, "hits counter missing — Plan 05 Task 1 must add it"
    assert getattr(dedup, "misses", 0) == 2, "misses counter missing — Plan 05 Task 1 must add it"


async def test_ttl_expiry_allows_retransmit(monkeypatch):
    """BRIDGE-04: after 300s window, same message_id accepted again."""
    import time as _time_mod

    from sci_fi_dashboard.gateway import dedup as dedup_mod

    dedup = dedup_mod.MessageDeduplicator(window_seconds=300)
    base_t = 1_700_000_000.0
    current = {"t": base_t}

    def fake_time() -> float:
        return current["t"]

    monkeypatch.setattr(dedup_mod, "time", type("TimeMod", (), {"time": staticmethod(fake_time)})())

    assert dedup.is_duplicate("msg-ttl-001") is False
    # +301s later — past the window
    current["t"] = base_t + 301
    # Trigger cleanup cycle (force _last_cleanup to expire)
    dedup._last_cleanup = 0.0
    assert dedup.is_duplicate("msg-ttl-001") is False, "after 300s TTL, message should be accepted again"
