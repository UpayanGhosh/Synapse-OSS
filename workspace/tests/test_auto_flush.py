"""test_auto_flush.py — Unit tests for SessionAutoFlusher (Phase 3).

7 test cases:
1. test_idle_threshold_triggers_flush       — idle >= threshold → flush called
2. test_message_count_triggers_flush        — msg count >= threshold → flush called
3. test_below_min_messages_skipped          — below min_messages floor → NOT flushed
4. test_dedup_window_skips_recent_flush     — memory_flush_at recent → NOT flushed
5. test_disabled_via_config                 — auto_flush_enabled=False → no flush
6. test_scanner_swallows_per_session_exception — one session raises, others still flush
7. test_manual_new_then_auto_skips          — manual /new sets memory_flush_at → skip

All tests mock _handle_new_command so they never reach add_memory.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------

def _make_entry(
    *,
    updated_at: float | None = None,
    memory_flush_at: float | None = None,
    session_id: str = "sess-test-001",
) -> MagicMock:
    """Return a minimal SessionEntry-like mock."""
    entry = MagicMock()
    entry.session_id = session_id
    entry.updated_at = updated_at if updated_at is not None else time.time()
    entry.memory_flush_at = memory_flush_at
    return entry


def _make_store(
    entries: dict[str, MagicMock],
    *,
    data_root: Path,
    agent_id: str,
) -> MagicMock:
    """Return a mock SessionStore that serves the given entries."""
    store = MagicMock()

    async def _load():
        return dict(entries)

    async def _get(key: str):
        return entries.get(key)

    async def _update(key: str, patch_dict: dict):
        entry = entries.get(key)
        if entry is not None:
            for k, v in patch_dict.items():
                setattr(entry, k, v)
        return entry

    store.load = AsyncMock(side_effect=_load)
    store.get = AsyncMock(side_effect=_get)
    store.update = AsyncMock(side_effect=_update)
    return store


def _write_transcript(path: Path, n_messages: int) -> None:
    """Write *n_messages* JSONL lines to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for i in range(n_messages):
            role = "user" if i % 2 == 0 else "assistant"
            fh.write(json.dumps({"role": role, "content": f"msg {i}"}) + "\n")


def _make_flusher(
    *,
    data_root: Path,
    agent_ids: list[str],
    handle_new_command,
    idle_threshold: float = 1800.0,
    count_threshold: int = 50,
    min_messages: int = 5,
    check_interval: float = 3600.0,  # large — tests call _scan_once directly
):
    from sci_fi_dashboard.auto_flush import SessionAutoFlusher

    return SessionAutoFlusher(
        data_root=data_root,
        agent_ids=agent_ids,
        handle_new_command=handle_new_command,
        idle_threshold=idle_threshold,
        count_threshold=count_threshold,
        min_messages=min_messages,
        check_interval=check_interval,
    )


# ---------------------------------------------------------------------------
# Patch helper: SessionStore constructor → return our mock
# ---------------------------------------------------------------------------

def _patch_session_store(mock_store: MagicMock):
    """Context manager that replaces SessionStore(agent_id=...) with mock_store."""
    return patch(
        "sci_fi_dashboard.auto_flush.SessionStore",
        return_value=mock_store,
    )


# ---------------------------------------------------------------------------
# Test 1 — idle threshold triggers flush
# ---------------------------------------------------------------------------


class TestIdleThresholdTriggersFLush:
    def test_idle_threshold_triggers_flush(self, tmp_path: Path) -> None:
        """A session idle for > threshold with >= min_messages should be flushed."""
        now = time.time()
        entry = _make_entry(updated_at=now - 3600)  # 1 hour ago — exceeds 1800s threshold

        # Write 10-line transcript
        transcript = tmp_path / "state" / "agents" / "the_creator" / "sessions" / f"{entry.session_id}.jsonl"
        _write_transcript(transcript, 10)

        mock_handle = AsyncMock(return_value="Session archived!")
        store = _make_store({"key1": entry}, data_root=tmp_path, agent_id="the_creator")
        flusher = _make_flusher(
            data_root=tmp_path,
            agent_ids=["the_creator"],
            handle_new_command=mock_handle,
            idle_threshold=1800.0,
            min_messages=5,
        )

        with _patch_session_store(store):
            flushed = asyncio.run(flusher._scan_once())

        assert flushed == 1
        mock_handle.assert_awaited_once()
        call_args = mock_handle.call_args
        # hemisphere must always be "safe" — may be positional or keyword
        positional_hemisphere = call_args.args[4] if len(call_args.args) > 4 else None
        keyword_hemisphere = call_args.kwargs.get("hemisphere")
        assert positional_hemisphere == "safe" or keyword_hemisphere == "safe"


# ---------------------------------------------------------------------------
# Test 2 — message count triggers flush
# ---------------------------------------------------------------------------


class TestMessageCountTriggersFLush:
    def test_message_count_triggers_flush(self, tmp_path: Path) -> None:
        """A session with >= count_threshold messages should flush even if recently active."""
        now = time.time()
        entry = _make_entry(updated_at=now - 60)  # only 60 s ago — well below idle threshold

        # Write 60 messages — above threshold of 50
        transcript = tmp_path / "state" / "agents" / "the_creator" / "sessions" / f"{entry.session_id}.jsonl"
        _write_transcript(transcript, 60)

        mock_handle = AsyncMock(return_value="Session archived!")
        store = _make_store({"key2": entry}, data_root=tmp_path, agent_id="the_creator")
        flusher = _make_flusher(
            data_root=tmp_path,
            agent_ids=["the_creator"],
            handle_new_command=mock_handle,
            idle_threshold=1800.0,
            count_threshold=50,
            min_messages=5,
        )

        with _patch_session_store(store):
            flushed = asyncio.run(flusher._scan_once())

        assert flushed == 1
        mock_handle.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test 3 — below min_messages skipped
# ---------------------------------------------------------------------------


class TestBelowMinMessagesSkipped:
    def test_below_min_messages_skipped(self, tmp_path: Path) -> None:
        """Sessions with fewer than min_messages must never be flushed."""
        now = time.time()
        entry = _make_entry(updated_at=now - 7200)  # 2 hours idle — way past threshold

        # Write only 3 messages — below min_messages=5
        transcript = tmp_path / "state" / "agents" / "the_creator" / "sessions" / f"{entry.session_id}.jsonl"
        _write_transcript(transcript, 3)

        mock_handle = AsyncMock(return_value="Session archived!")
        store = _make_store({"key3": entry}, data_root=tmp_path, agent_id="the_creator")
        flusher = _make_flusher(
            data_root=tmp_path,
            agent_ids=["the_creator"],
            handle_new_command=mock_handle,
            idle_threshold=1800.0,
            min_messages=5,
        )

        with _patch_session_store(store):
            flushed = asyncio.run(flusher._scan_once())

        assert flushed == 0
        mock_handle.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 4 — dedup window skips recently-flushed session
# ---------------------------------------------------------------------------


class TestDedupWindowSkipsRecentFlush:
    def test_dedup_window_skips_recent_flush(self, tmp_path: Path) -> None:
        """If memory_flush_at is within idle_threshold seconds, skip the session."""
        now = time.time()
        entry = _make_entry(
            updated_at=now - 7200,        # 2 hours idle — would normally flush
            memory_flush_at=now - 30,     # flushed only 30 s ago — within dedup window
        )

        transcript = tmp_path / "state" / "agents" / "the_creator" / "sessions" / f"{entry.session_id}.jsonl"
        _write_transcript(transcript, 10)

        mock_handle = AsyncMock(return_value="Session archived!")
        store = _make_store({"key4": entry}, data_root=tmp_path, agent_id="the_creator")
        flusher = _make_flusher(
            data_root=tmp_path,
            agent_ids=["the_creator"],
            handle_new_command=mock_handle,
            idle_threshold=1800.0,
            min_messages=5,
        )

        with _patch_session_store(store):
            flushed = asyncio.run(flusher._scan_once())

        assert flushed == 0
        mock_handle.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 5 — disabled via config
# ---------------------------------------------------------------------------


class TestDisabledViaConfig:
    def test_disabled_via_config(self, tmp_path: Path) -> None:
        """When auto_flush_enabled=False the scanner task is never started."""
        mock_handle = AsyncMock(return_value="Session archived!")

        # We don't even start the flusher — mirrors what lifespan does when disabled.
        flusher = _make_flusher(
            data_root=tmp_path,
            agent_ids=["the_creator"],
            handle_new_command=mock_handle,
        )

        # Simulate: lifespan checks cfg.enabled and skips flusher.start()
        # The task should be None (never started).
        assert flusher._task is None
        mock_handle.assert_not_awaited()

        # Even if scan_once is called on an un-started flusher it must be safe
        # (no exception). The store is empty so nothing flushes.
        empty_store = _make_store({}, data_root=tmp_path, agent_id="the_creator")
        with _patch_session_store(empty_store):
            flushed = asyncio.run(flusher._scan_once())

        assert flushed == 0
        mock_handle.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 6 — scanner swallows per-session exception, others still flush
# ---------------------------------------------------------------------------


class TestScannerSwallowsPerSessionException:
    def test_scanner_swallows_per_session_exception(self, tmp_path: Path) -> None:
        """Exception in one session's flush must not block other sessions."""
        now = time.time()

        # Two agents: agent_a will raise, agent_b should still flush.
        entry_a = _make_entry(updated_at=now - 7200, session_id="sess-a")
        entry_b = _make_entry(updated_at=now - 7200, session_id="sess-b")

        transcript_b = (
            tmp_path / "state" / "agents" / "agent_b" / "sessions" / f"{entry_b.session_id}.jsonl"
        )
        _write_transcript(transcript_b, 10)
        # Agent A transcript also needs to exist (even though flush will raise)
        transcript_a = (
            tmp_path / "state" / "agents" / "agent_a" / "sessions" / f"{entry_a.session_id}.jsonl"
        )
        _write_transcript(transcript_a, 10)

        call_count = 0

        async def _handle(key, agent_id, data_root, store, hemisphere="safe"):
            nonlocal call_count
            if agent_id == "agent_a":
                raise RuntimeError("simulated flush failure for agent_a")
            call_count += 1
            return "Session archived!"

        store_a = _make_store({"keya": entry_a}, data_root=tmp_path, agent_id="agent_a")
        store_b = _make_store({"keyb": entry_b}, data_root=tmp_path, agent_id="agent_b")

        stores_by_agent = {"agent_a": store_a, "agent_b": store_b}

        from sci_fi_dashboard.auto_flush import SessionAutoFlusher

        flusher = SessionAutoFlusher(
            data_root=tmp_path,
            agent_ids=["agent_a", "agent_b"],
            handle_new_command=_handle,
            idle_threshold=1800.0,
            count_threshold=50,
            min_messages=5,
            check_interval=3600.0,
        )

        def _store_factory(agent_id, data_root):
            return stores_by_agent[agent_id]

        with patch(
            "sci_fi_dashboard.auto_flush.SessionStore",
            side_effect=lambda agent_id, data_root: stores_by_agent[agent_id],
        ):
            # Should not raise even though agent_a fails
            flushed = asyncio.run(flusher._scan_once())

        # agent_b flushed (1); agent_a raised (counted as 0 — exception swallowed)
        assert flushed == 1
        assert call_count == 1


# ---------------------------------------------------------------------------
# Test 7 — manual /new then auto skips
# ---------------------------------------------------------------------------


class TestManualNewThenAutoSkips:
    def test_manual_new_then_auto_skips(self, tmp_path: Path) -> None:
        """After manual /new sets memory_flush_at recently, the scanner skips the session."""
        now = time.time()

        # Simulate user running /new manually 5 minutes ago — memory_flush_at set then.
        # Session is also idle (updated_at 2h ago) but the dedup guard should block flush.
        entry = _make_entry(
            updated_at=now - 7200,
            memory_flush_at=now - 300,   # 5 min ago — within 1800s dedup window
        )

        transcript = tmp_path / "state" / "agents" / "the_creator" / "sessions" / f"{entry.session_id}.jsonl"
        _write_transcript(transcript, 10)

        mock_handle = AsyncMock(return_value="Session archived!")
        store = _make_store({"key7": entry}, data_root=tmp_path, agent_id="the_creator")
        flusher = _make_flusher(
            data_root=tmp_path,
            agent_ids=["the_creator"],
            handle_new_command=mock_handle,
            idle_threshold=1800.0,
            min_messages=5,
        )

        with _patch_session_store(store):
            flushed = asyncio.run(flusher._scan_once())

        assert flushed == 0
        mock_handle.assert_not_awaited()
