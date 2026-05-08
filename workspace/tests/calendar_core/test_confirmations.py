from __future__ import annotations

import pytest

from sci_fi_dashboard.calendar_core.confirmations import (
    DEFAULT_MAX_ENTRIES,
    DEFAULT_TTL_SECONDS,
    PendingActionStore,
    default_store,
    reset_default_store_for_tests,
)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_put_and_peek_returns_same_action_until_expiry():
    clock = FakeClock()
    store = PendingActionStore(ttl_seconds=10, clock=clock)
    action = store.put(chat_id="c1", kind="delete", payload={"event_id": "evt_1"})
    assert action.confirmation_id
    assert store.peek("c1") is action
    clock.advance(9.99)
    assert store.peek("c1") is action
    clock.advance(0.02)
    assert store.peek("c1") is None


def test_get_and_clear_consumes_action():
    store = PendingActionStore()
    store.put(chat_id="c1", kind="delete", payload={"event_id": "evt_1"})
    first = store.get_and_clear("c1")
    assert first is not None
    assert store.get_and_clear("c1") is None


def test_per_chat_id_isolation():
    store = PendingActionStore()
    store.put(chat_id="c1", kind="delete", payload={"event_id": "evt_1"})
    store.put(chat_id="c2", kind="move", payload={"event_id": "evt_2"})
    a1 = store.peek("c1")
    a2 = store.peek("c2")
    assert a1 is not None and a1.kind == "delete"
    assert a2 is not None and a2.kind == "move"


def test_max_entries_eviction_drops_oldest_first():
    clock = FakeClock()
    store = PendingActionStore(ttl_seconds=600, max_entries=2, clock=clock)
    store.put(chat_id="c1", kind="delete", payload="a")
    store.put(chat_id="c2", kind="delete", payload="b")
    store.put(chat_id="c3", kind="delete", payload="c")
    assert store.peek("c1") is None
    assert store.peek("c2") is not None
    assert store.peek("c3") is not None


def test_put_rejects_blank_chat_id():
    store = PendingActionStore()
    with pytest.raises(ValueError, match="chat_id"):
        store.put(chat_id="", kind="delete", payload={})


def test_construction_validates_ttl_and_capacity():
    with pytest.raises(ValueError, match="ttl_seconds"):
        PendingActionStore(ttl_seconds=0)
    with pytest.raises(ValueError, match="max_entries"):
        PendingActionStore(max_entries=0)


def test_prune_removes_expired_entries():
    clock = FakeClock()
    store = PendingActionStore(ttl_seconds=5, clock=clock)
    store.put(chat_id="c1", kind="delete", payload={})
    clock.advance(6)
    assert store.prune() == 1
    assert len(store) == 0


def test_discard_returns_true_when_present():
    store = PendingActionStore()
    store.put(chat_id="c1", kind="delete", payload={})
    assert store.discard("c1") is True
    assert store.discard("c1") is False


def test_default_store_is_singleton_with_expected_defaults():
    reset_default_store_for_tests()
    first = default_store()
    second = default_store()
    assert first is second
    assert first._max == DEFAULT_MAX_ENTRIES  # noqa: SLF001
    assert first._ttl == DEFAULT_TTL_SECONDS  # noqa: SLF001
    reset_default_store_for_tests()


def test_put_refreshes_expiry_when_overwriting_same_chat():
    clock = FakeClock()
    store = PendingActionStore(ttl_seconds=10, clock=clock)
    store.put(chat_id="c1", kind="delete", payload="a")
    clock.advance(9)
    store.put(chat_id="c1", kind="move", payload="b")
    clock.advance(5)
    action = store.peek("c1")
    assert action is not None
    assert action.kind == "move"
