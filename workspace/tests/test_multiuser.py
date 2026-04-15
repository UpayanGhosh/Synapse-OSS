"""test_multiuser.py — Unit tests for the multiuser memory system.

Covers (per team-plan.md):
  - build_session_key(): all 4 dmScope variants, group key, thread suffix
  - Identity link substitution via build_session_key()
  - parse_session_key(): happy path + None on invalid input
  - limit_history_turns(): 10 messages → limit=3 returns exactly 3 user turns
  - merge_session_entry() (_merge_entry): new entry gets UUID, updatedAt=now;
    existing entry shallow-merges without regenerating UUID
  - load_bootstrap_files(): minimal set flag (subagent key excludes HEARTBEAT.md)
  - compact_session(): below-threshold path returns compacted=False
  - compact_session(): timeout path returns ok=False, compacted=False, reason=timeout
  - compact_session(): above-threshold path returns compacted=True, token count drops
  - assemble_context(): raises ContextWindowTooSmallError when remaining < 16000
  - SessionStore.update(): concurrent calls produce no data loss
  - SessionStore.get(): TTL cache expiry re-reads from disk
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure workspace/ is on the import path regardless of cwd.
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional import guard (RED-phase pattern from test_session_actor.py)
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.multiuser.compaction import (
        compact_session,
        estimate_tokens,
        should_compact,
    )
    from sci_fi_dashboard.multiuser.context_assembler import (
        ContextWindowTooSmallError,
        assemble_context,
    )
    from sci_fi_dashboard.multiuser.memory_manager import (
        BOOTSTRAP_FILES,
        MINIMAL_BOOTSTRAP_FILES,
        load_bootstrap_files,
        seed_workspace,
    )
    from sci_fi_dashboard.multiuser.session_key import build_session_key, parse_session_key
    from sci_fi_dashboard.multiuser.session_store import SessionStore, _merge_entry
    from sci_fi_dashboard.multiuser.transcript import (
        append_message,
        archive_transcript,
        limit_history_turns,
        load_messages,
    )

    AVAILABLE = True
except ImportError:
    AVAILABLE = False

pytestmark = pytest.mark.asyncio

_skip = pytest.mark.skipif(
    not AVAILABLE,
    reason="sci_fi_dashboard/multiuser not yet available",
)


# ===========================================================================
# Session Key Tests
# ===========================================================================


class TestBuildSessionKey:
    """Tests for build_session_key() — all dmScope variants and edge cases."""

    @_skip
    def test_dm_scope_main(self):
        """dmScope='main' — all DMs share one session keyed on main_key."""
        key = build_session_key(
            agent_id="jarvis",
            channel="whatsapp",
            peer_id="919876543210",
            peer_kind="direct",
            account_id="acc1",
            dm_scope="main",
            main_key="whatsapp:dm",
            identity_links={},
        )
        assert key == "agent:jarvis:whatsapp:dm"

    @_skip
    def test_dm_scope_per_peer(self):
        """dmScope='per-peer' — key includes peer_id but not account_id."""
        key = build_session_key(
            agent_id="jarvis",
            channel="whatsapp",
            peer_id="919876543210",
            peer_kind="direct",
            account_id="acc1",
            dm_scope="per-peer",
            main_key="whatsapp:dm",
            identity_links={},
        )
        assert key == "agent:jarvis:whatsapp:dm:919876543210"

    @_skip
    def test_dm_scope_per_channel_peer(self):
        """dmScope='per-channel-peer' — key includes channel + peer_id."""
        key = build_session_key(
            agent_id="jarvis",
            channel="telegram",
            peer_id="123456789",
            peer_kind="direct",
            account_id="acc1",
            dm_scope="per-channel-peer",
            main_key="telegram:dm",
            identity_links={},
        )
        assert key == "agent:jarvis:telegram:dm:123456789"

    @_skip
    def test_dm_scope_per_account_channel_peer(self):
        """dmScope='per-account-channel-peer' — key includes account_id + peer_id."""
        key = build_session_key(
            agent_id="jarvis",
            channel="whatsapp",
            peer_id="919876543210",
            peer_kind="direct",
            account_id="myaccount",
            dm_scope="per-account-channel-peer",
            main_key="whatsapp:dm",
            identity_links={},
        )
        assert key == "agent:jarvis:whatsapp:dm:myaccount:919876543210"

    @_skip
    def test_group_key(self):
        """Non-direct peer_kind produces group key shape."""
        key = build_session_key(
            agent_id="jarvis",
            channel="whatsapp",
            peer_id="120363000000000001@g.us",
            peer_kind="group",
            account_id="acc1",
            dm_scope="per-peer",
            main_key="whatsapp:dm",
            identity_links={},
        )
        # peer_id sanitized: '@' becomes '-', leading/trailing dashes stripped
        assert key.startswith("agent:jarvis:whatsapp:group:")
        assert "thread" not in key

    @_skip
    def test_group_key_with_thread_suffix(self):
        """Non-direct key with thread_id gets :thread:<id> suffix."""
        key = build_session_key(
            agent_id="jarvis",
            channel="discord",
            peer_id="server123",
            peer_kind="channel",
            account_id="acc1",
            dm_scope="per-peer",
            main_key="discord:dm",
            identity_links={},
            thread_id="thread-abc",
        )
        assert key.endswith(":thread:thread-abc")
        assert "agent:jarvis:discord:channel:server123" in key

    @_skip
    def test_peer_id_sanitization_fallback_unknown(self):
        """Peer ID that sanitizes to empty string falls back to 'unknown'."""
        key = build_session_key(
            agent_id="jarvis",
            channel="whatsapp",
            peer_id="@@@",  # all invalid chars → empty after stripping
            peer_kind="direct",
            account_id="acc1",
            dm_scope="per-peer",
            main_key="whatsapp:dm",
            identity_links={},
        )
        assert key.endswith(":unknown")

    @_skip
    def test_identity_link_substitution(self):
        """Identity link maps raw peer_id to canonical name in the key."""
        identity_links = {
            "alice": ["919876543210", "telegram:123456789"],
        }
        # WhatsApp peer
        key_wa = build_session_key(
            agent_id="jarvis",
            channel="whatsapp",
            peer_id="919876543210",
            peer_kind="direct",
            account_id="acc1",
            dm_scope="per-peer",
            main_key="whatsapp:dm",
            identity_links=identity_links,
        )
        assert key_wa.endswith(":alice")

        # Telegram peer via channel-prefixed candidate
        key_tg = build_session_key(
            agent_id="jarvis",
            channel="telegram",
            peer_id="123456789",
            peer_kind="direct",
            account_id="acc1",
            dm_scope="per-channel-peer",
            main_key="telegram:dm",
            identity_links=identity_links,
        )
        assert key_tg.endswith(":alice")

    @_skip
    def test_identity_link_not_applied_on_main_scope(self):
        """Identity links are NOT applied when dm_scope='main'."""
        identity_links = {"alice": ["919876543210"]}
        key = build_session_key(
            agent_id="jarvis",
            channel="whatsapp",
            peer_id="919876543210",
            peer_kind="direct",
            account_id="acc1",
            dm_scope="main",
            main_key="whatsapp:dm",
            identity_links=identity_links,
        )
        # main scope → key uses main_key; no peer substitution
        assert "alice" not in key


class TestParseSessionKey:
    """Tests for parse_session_key()."""

    @_skip
    def test_happy_path(self):
        """Valid key returns ParsedSessionKey with correct agent_id and rest."""
        result = parse_session_key("agent:jarvis:whatsapp:dm:alice")
        assert result is not None
        assert result.agent_id == "jarvis"
        assert result.rest == "whatsapp:dm:alice"

    @_skip
    def test_minimal_valid_key(self):
        """Minimum valid key has exactly 3 parts."""
        result = parse_session_key("agent:bot:main")
        assert result is not None
        assert result.agent_id == "bot"
        assert result.rest == "main"

    @_skip
    def test_returns_none_on_wrong_prefix(self):
        """Key not starting with 'agent' returns None."""
        assert parse_session_key("user:bot:whatsapp") is None

    @_skip
    def test_returns_none_on_too_few_parts(self):
        """Key with fewer than 3 colon-segments returns None."""
        assert parse_session_key("agent:jarvis") is None

    @_skip
    def test_returns_none_on_empty_string(self):
        """Empty string returns None."""
        assert parse_session_key("") is None


# ===========================================================================
# Transcript Tests
# ===========================================================================


class TestLimitHistoryTurns:
    """Tests for limit_history_turns()."""

    def _make_messages(self, roles: list[str]) -> list[dict]:
        return [{"role": r, "content": f"msg {i}"} for i, r in enumerate(roles)]

    @_skip
    def test_limit_returns_correct_user_turns(self):
        """10 messages with 5 user turns → limit=3 returns tail with 3 user turns."""
        messages = self._make_messages(
            [
                "user",
                "assistant",
                "user",
                "assistant",
                "user",
                "assistant",
                "user",
                "assistant",
                "user",
                "assistant",
            ]
        )
        # 5 user turns; limit=3 → keep last 3 user turns
        result = limit_history_turns(messages, 3)
        user_count = sum(1 for m in result if m["role"] == "user")
        assert user_count == 3

    @_skip
    def test_limit_fewer_turns_than_limit_returns_all(self):
        """Fewer user turns than limit → full list returned."""
        messages = self._make_messages(["user", "assistant", "user"])
        result = limit_history_turns(messages, 5)
        assert result == messages

    @_skip
    def test_limit_exact_match(self):
        """Exactly limit user turns → full list returned."""
        messages = self._make_messages(["user", "assistant", "user", "assistant"])
        result = limit_history_turns(messages, 2)
        assert result == messages

    @_skip
    def test_limit_zero_returns_empty_tail(self):
        """Limit=0 — walk never triggers, returns all messages (no user exceeds 0)."""
        messages = self._make_messages(["user", "assistant"])
        # limit=0 means user_count never exceeds 0, so full list returned
        result = limit_history_turns(messages, 0)
        # Any user turn immediately causes user_count > 0, so returns tail after first user
        # Walk: index 1 (assistant) -> skip, index 0 (user) -> count=1 > 0 → return [1:]
        assert len(result) == 1
        assert result[0]["role"] == "assistant"

    @_skip
    async def test_append_and_load_messages(self, tmp_path):
        """append_message writes JSONL; load_messages reads it back."""
        p = tmp_path / "transcript.jsonl"
        msg = {"role": "user", "content": "hello", "timestamp": time.time()}
        await append_message(p, msg)
        loaded = await load_messages(p)
        assert len(loaded) == 1
        assert loaded[0]["role"] == "user"
        assert loaded[0]["content"] == "hello"

    @_skip
    async def test_load_messages_skips_corrupt_lines(self, tmp_path):
        """Corrupt JSONL lines are skipped without raising."""
        p = tmp_path / "transcript.jsonl"
        p.write_text(
            '{"role":"user","content":"good"}\nNOT JSON\n{"role":"assistant","content":"ok"}\n'
        )
        loaded = await load_messages(p)
        assert len(loaded) == 2
        assert loaded[0]["role"] == "user"
        assert loaded[1]["role"] == "assistant"

    @_skip
    async def test_archive_transcript(self, tmp_path):
        """archive_transcript renames file to .deleted.<timestamp> form."""
        p = tmp_path / "test.jsonl"
        p.write_text('{"role":"user","content":"hi"}\n')
        await archive_transcript(p)
        # Original file should be gone
        assert not p.exists()
        # A .deleted.<ts> file should exist
        deleted_files = list(tmp_path.glob("test.jsonl.deleted.*"))
        assert len(deleted_files) == 1

    @_skip
    async def test_load_messages_with_limit(self, tmp_path):
        """load_messages(limit=N) applies limit_history_turns correctly."""
        p = tmp_path / "transcript.jsonl"
        # Write 10 messages: alternating user/assistant
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            msg = {"role": role, "content": f"msg {i}", "timestamp": time.time()}
            await append_message(p, msg)

        loaded = await load_messages(p, limit=3)
        user_count = sum(1 for m in loaded if m["role"] == "user")
        assert user_count == 3


# ===========================================================================
# Session Store Tests
# ===========================================================================


class TestMergeSessionEntry:
    """Tests for _merge_entry() — the core merge logic of SessionStore."""

    @_skip
    def test_new_entry_gets_uuid(self):
        """New entry (no existing) gets a generated UUID session_id."""
        result = _merge_entry(None, {})
        assert "session_id" in result
        assert len(result["session_id"]) == 36  # UUID4 string length

    @_skip
    def test_new_entry_has_updated_at_near_now(self):
        """New entry's updated_at is close to current time."""
        before = time.time()
        result = _merge_entry(None, {})
        after = time.time()
        assert before <= result["updated_at"] <= after + 0.1

    @_skip
    def test_existing_entry_uuid_stable(self):
        """Subsequent update does not regenerate the session_id."""
        first = _merge_entry(None, {})
        original_id = first["session_id"]
        second = _merge_entry(first, {"compaction_count": 1})
        assert second["session_id"] == original_id

    @_skip
    def test_shallow_merge_applies_patch(self):
        """Patch values are applied onto the existing entry."""
        existing = _merge_entry(None, {})
        updated = _merge_entry(existing, {"compaction_count": 5})
        assert updated["compaction_count"] == 5

    @_skip
    async def test_store_update_creates_entry_with_stable_uuid(self, tmp_path, monkeypatch):
        """SessionStore.update() creates a new entry with a stable UUID."""
        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        store = SessionStore("test-agent", data_root=tmp_path)
        entry1 = await store.update("agent:test-agent:whatsapp:dm:alice", {})
        entry2 = await store.update("agent:test-agent:whatsapp:dm:alice", {"compaction_count": 1})
        assert entry1.session_id == entry2.session_id
        assert entry2.compaction_count == 1

    @_skip
    async def test_concurrent_updates_no_data_loss(self, tmp_path, monkeypatch):
        """Concurrent update() calls on the same key must not lose any patch.

        Fires two simultaneous updates via asyncio.gather — one sets
        compaction_count=7, the other sets memory_flush_at=1234.0.  After both
        settle exactly one of the values must be in the final entry AND the
        session_id must remain stable (not regenerated mid-race).
        """
        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        store = SessionStore("test-agent", data_root=tmp_path)
        session_key = "agent:test-agent:whatsapp:dm:concurrent"

        # Create a baseline entry first so session_id is stable.
        baseline = await store.update(session_key, {})
        original_id = baseline.session_id

        # Fire two patches concurrently.
        patch_a = {"compaction_count": 7}
        patch_b = {"memory_flush_at": 1234.0}
        entry_a, entry_b = await asyncio.gather(
            store.update(session_key, patch_a),
            store.update(session_key, patch_b),
        )

        # Re-read the final state from disk (bypasses cache).
        from sci_fi_dashboard.multiuser.session_store import _load_store_sync

        final_raw = _load_store_sync(store._path)
        final = final_raw[session_key]

        # session_id must never change.
        assert final["session_id"] == original_id

        # Because update() serialises on asyncio.Lock, the second writer always
        # reads the first writer's result and keeps it — both patches present.
        assert final["compaction_count"] == 7
        assert final["memory_flush_at"] == 1234.0

    @_skip
    async def test_ttl_cache_expiry_rereads_disk(self, tmp_path, monkeypatch):
        """get() returns a fresh value after the TTL expires.

        Strategy: set TTL to 0 ms so every call is a cache miss, write an
        updated entry directly to disk, then verify get() returns the new value.
        """
        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        # Zero-millisecond TTL — cache entries expire immediately.
        monkeypatch.setenv("SYNAPSE_SESSION_CACHE_TTL_MS", "0")

        from sci_fi_dashboard.multiuser.session_store import _cache_invalidate

        store = SessionStore("test-agent", data_root=tmp_path)
        session_key = "agent:test-agent:whatsapp:dm:ttl-test"

        # Seed an initial entry.
        entry_v1 = await store.update(session_key, {"compaction_count": 1})
        assert entry_v1.compaction_count == 1

        # Manually invalidate the cache entry to simulate expiry.
        _cache_invalidate(session_key)

        # Write a newer value directly to disk, bypassing the cache entirely.
        store_path = store._path
        from sci_fi_dashboard.multiuser.session_store import (
            _load_store_sync,
            _save_store_sync,
        )

        raw = _load_store_sync(store_path)
        raw[session_key]["compaction_count"] = 99
        _save_store_sync(store_path, raw)

        # With TTL=0 the cached entry (if any) is stale; get() must re-read disk.
        entry_v2 = await store.get(session_key)
        assert entry_v2 is not None
        assert entry_v2.compaction_count == 99


# ===========================================================================
# Memory Manager Tests
# ===========================================================================


class TestLoadBootstrapFiles:
    """Tests for load_bootstrap_files() — file selection and content loading."""

    @_skip
    async def test_loads_full_set_for_normal_key(self, tmp_path):
        """Normal session key → BOOTSTRAP_FILES set is attempted."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "SOUL.md").write_text("soul content")
        (ws / "AGENTS.md").write_text("agents content")

        result = await load_bootstrap_files(ws, session_key="agent:jarvis:whatsapp:dm:alice")
        names = [r["name"] for r in result]
        assert "SOUL.md" in names
        assert "AGENTS.md" in names

    @_skip
    async def test_minimal_set_for_subagent_key(self, tmp_path):
        """Subagent key → MINIMAL_BOOTSTRAP_FILES; BOOTSTRAP.md excluded."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        for fname in BOOTSTRAP_FILES:
            (ws / fname).write_text(f"content of {fname}")

        subagent_key = "agent:jarvis:whatsapp:subagent:task1"
        result = await load_bootstrap_files(ws, session_key=subagent_key)
        names = [r["name"] for r in result]

        # All minimal files present
        for f in MINIMAL_BOOTSTRAP_FILES:
            assert f in names

        # Non-minimal files excluded (BOOTSTRAP.md, MEMORY.md)
        extra = set(BOOTSTRAP_FILES) - set(MINIMAL_BOOTSTRAP_FILES)
        for f in extra:
            assert f not in names, f"{f} should not be in minimal set"

    @_skip
    async def test_missing_files_silently_skipped(self, tmp_path):
        """Missing bootstrap files are skipped without raising."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        # Only create SOUL.md; all others absent
        (ws / "SOUL.md").write_text("soul")
        result = await load_bootstrap_files(ws)
        assert len(result) == 1
        assert result[0]["name"] == "SOUL.md"

    @_skip
    async def test_content_truncated_at_2mb(self, tmp_path):
        """File content exceeding 2 MB is truncated to 2 MB."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        two_mb = 2 * 1024 * 1024
        (ws / "SOUL.md").write_bytes(b"x" * (two_mb + 500))
        result = await load_bootstrap_files(ws)
        assert len(result[0]["content"]) == two_mb

    @_skip
    async def test_seed_workspace_does_not_overwrite(self, tmp_path):
        """seed_workspace() does not overwrite an existing SOUL.md."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        soul = ws / "SOUL.md"
        soul.write_text("existing soul")
        await seed_workspace(ws)
        assert soul.read_text() == "existing soul"

    @_skip
    async def test_seed_workspace_creates_empty_files(self, tmp_path):
        """seed_workspace() creates empty placeholder files that don't exist."""
        ws = tmp_path / "workspace"
        await seed_workspace(ws)
        assert ws.exists()
        for fname in BOOTSTRAP_FILES:
            assert (ws / fname).exists()
            # Created as empty files
            if fname != "MEMORY.md":  # MEMORY.md might be case-variant
                assert (ws / fname).read_text() == ""

    @_skip
    async def test_memory_md_fallback(self, tmp_path):
        """Tries MEMORY.md then memory.md on case-sensitive fs."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / "memory.md").write_text("lower case memory")
        # MEMORY.md (uppercase) is absent; fallback to memory.md
        result = await load_bootstrap_files(ws)
        names = [r["name"] for r in result]
        # Either MEMORY.md (if case-insensitive fs found it) or memory.md
        assert any(n.lower() == "memory.md" for n in names)


# ===========================================================================
# Compaction Tests
# ===========================================================================


class TestCompactionBelowThreshold:
    """Tests for compact_session() — below-threshold path."""

    @_skip
    async def test_below_threshold_returns_not_compacted(self, tmp_path):
        """Transcript below 80% threshold returns compacted=False."""
        # Write a tiny transcript (well below threshold)
        transcript = tmp_path / "sessions" / "test.jsonl"
        transcript.parent.mkdir(parents=True)
        msg = {"role": "user", "content": "hi", "timestamp": time.time()}
        import json

        transcript.write_text(json.dumps(msg) + "\n")

        store = SessionStore("test-agent", data_root=tmp_path)
        store_path = tmp_path / "state" / "agents" / "test-agent" / "sessions" / "sessions.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)

        mock_llm = AsyncMock()

        result = await compact_session(
            transcript_path=transcript,
            context_window_tokens=100_000,  # huge window → tiny transcript is well below 80%
            llm_client=mock_llm,
            agent_id="test-agent",
            session_key="agent:test-agent:test",
            store_path=store_path,
            session_store=store,
            data_root=tmp_path,
        )
        assert result["ok"] is True
        assert result["compacted"] is False
        assert "below threshold" in result["reason"]

    @_skip
    async def test_estimate_tokens_heuristic(self):
        """estimate_tokens returns sum(len(content)//4) for messages."""
        messages = [
            {"role": "user", "content": "abcd"},  # 4 chars → 1 token
            {"role": "assistant", "content": "abcdef"},  # 6 chars → 1 token
        ]
        assert estimate_tokens(messages) == 2  # 4//4 + 6//4 = 1 + 1

    @_skip
    def test_should_compact_true_above_threshold(self):
        """should_compact returns True when tokens exceed threshold_ratio of window."""
        # 100 messages of 400 chars each → 10000 tokens; window=12000; 80% = 9600 → True
        messages = [{"role": "user", "content": "a" * 400} for _ in range(100)]
        assert should_compact(messages, context_window_tokens=12_000, threshold_ratio=0.8)

    @_skip
    def test_should_compact_false_below_threshold(self):
        """should_compact returns False when tokens are below threshold."""
        messages = [{"role": "user", "content": "hi"}]
        assert not should_compact(messages, context_window_tokens=100_000)


class TestCompactionTimeoutPath:
    """compact_session() must return ok=False when the LLM call never resolves."""

    @_skip
    async def test_timeout_returns_ok_false(self, tmp_path):
        """Monkeypatching asyncio.wait_for to raise TimeoutError exercises the timeout branch."""
        transcript = tmp_path / "sessions" / "test.jsonl"
        transcript.parent.mkdir(parents=True)
        # Write enough content to be above threshold for context_window_tokens=100.
        # 5 messages × 32 chars each = 160 chars → 40 tokens > 80 tokens threshold.
        msgs = [{"role": "user", "content": "a" * 32, "timestamp": time.time()} for _ in range(5)]
        transcript.write_text("\n".join(json.dumps(m) for m in msgs) + "\n")

        store = SessionStore("test-agent", data_root=tmp_path)
        store_path = tmp_path / "state" / "agents" / "test-agent" / "sessions" / "sessions.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)

        # Replace asyncio.wait_for so it immediately raises TimeoutError,
        # simulating the 900 s guard triggering.
        async def _never_complete(*_args, **_kwargs):
            raise TimeoutError

        with patch(
            "sci_fi_dashboard.multiuser.compaction.asyncio.wait_for",
            side_effect=_never_complete,
        ):
            result = await compact_session(
                transcript_path=transcript,
                context_window_tokens=100,
                llm_client=AsyncMock(),
                agent_id="test-agent",
                session_key="agent:test-agent:test",
                store_path=store_path,
                session_store=store,
                data_root=tmp_path,
            )

        assert result["ok"] is False
        assert result["compacted"] is False
        assert result["reason"] == "timeout"


class TestCompactionAboveThreshold:
    """compact_session() must rewrite the transcript and update the session store."""

    @_skip
    async def test_above_threshold_compacts_and_updates_store(self, tmp_path):
        """Full compaction path: transcript exceeds 80 % → compacted=True, token count drops.

        Uses context_window_tokens=100.  Each message has 32 chars → 8 tokens each.
        10 messages → 80 tokens = 80 % of 100 = exactly at threshold; we need > 80 %
        so we use 11 messages → 88 tokens > 80 tokens.
        """
        transcript = tmp_path / "sessions" / "test.jsonl"
        transcript.parent.mkdir(parents=True)

        n_messages = 11  # 11 × 8 tokens = 88 > 80 tokens (80 % of 100)
        msgs = [
            {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": "a" * 32,
                "timestamp": time.time(),
            }
            for i in range(n_messages)
        ]
        transcript.write_text("\n".join(json.dumps(m) for m in msgs) + "\n")

        store = SessionStore("test-agent", data_root=tmp_path)
        store_path = tmp_path / "state" / "agents" / "test-agent" / "sessions" / "sessions.json"
        store_path.parent.mkdir(parents=True, exist_ok=True)

        # Seed the session entry so compaction_count starts at 0.
        await store.update("agent:test-agent:test", {})

        # Mock LLM: every acompletion() call returns "SUMMARY TEXT".
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "SUMMARY TEXT"
        mock_llm = AsyncMock()
        mock_llm.acompletion = AsyncMock(return_value=mock_response)

        original_tokens = estimate_tokens(msgs)

        result = await compact_session(
            transcript_path=transcript,
            context_window_tokens=100,
            llm_client=mock_llm,
            agent_id="test-agent",
            session_key="agent:test-agent:test",
            store_path=store_path,
            session_store=store,
            data_root=tmp_path,
        )

        assert result["ok"] is True
        assert result["compacted"] is True

        # compaction_count must be incremented.
        updated_entry = await store.get("agent:test-agent:test")
        assert updated_entry is not None
        assert updated_entry.compaction_count == 1

        # JSONL must have been rewritten — retained count < original.
        retained = result["result"]["retained_message_count"]
        assert retained < n_messages

        # Token count after compaction must be lower than before.
        new_messages = await load_messages(transcript)
        new_tokens = estimate_tokens(new_messages)
        assert new_tokens < original_tokens

        # The first line of the rewritten JSONL must be the system summary.
        assert new_messages[0]["role"] == "system"
        assert new_messages[0]["content"] == "SUMMARY TEXT"


# ===========================================================================
# Context Assembler Tests
# ===========================================================================


class TestAssembleContext:
    """Tests for assemble_context() — ContextWindowTooSmallError guard."""

    def _make_config(self, channels: dict | None = None):
        """Build a minimal mock config object."""
        cfg = MagicMock()
        cfg.channels = channels or {}
        return cfg

    @_skip
    async def test_raises_context_window_too_small(self, tmp_path, monkeypatch):
        """assemble_context raises ContextWindowTooSmallError when remaining < 16000."""
        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        # Create workspace with a large SOUL.md to inflate system_prompt
        ws = tmp_path / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        # 64K chars of content → ~16K tokens just from system prompt
        (ws / "SOUL.md").write_text("x" * 65_536)

        config = self._make_config()

        # context_window_tokens so small that remaining < CONTEXT_WINDOW_HARD_MIN_TOKENS
        with pytest.raises(ContextWindowTooSmallError):
            await assemble_context(
                session_key="agent:test:whatsapp:dm:alice",
                agent_id="test",
                data_root=tmp_path,
                config=config,
                context_window_tokens=1_000,  # tiny → remaining will be negative
            )

    @_skip
    async def test_returns_system_prompt_and_messages(self, tmp_path, monkeypatch):
        """assemble_context returns dict with system_prompt and messages keys."""
        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        ws = tmp_path / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "SOUL.md").write_text("You are a helpful assistant.")

        config = self._make_config()

        result = await assemble_context(
            session_key="agent:test:whatsapp:dm:alice",
            agent_id="test",
            data_root=tmp_path,
            config=config,
            context_window_tokens=200_000,  # large window → no error
        )
        assert "system_prompt" in result
        assert "messages" in result

    @_skip
    async def test_system_prompt_contains_project_context(self, tmp_path, monkeypatch):
        """System prompt contains '# Project Context' and bootstrap file header."""
        monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
        ws = tmp_path / "workspace"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "SOUL.md").write_text("Be helpful.")

        config = self._make_config()

        result = await assemble_context(
            session_key="agent:test:whatsapp:dm:alice",
            agent_id="test",
            data_root=tmp_path,
            config=config,
            context_window_tokens=200_000,
        )
        sp = result["system_prompt"]
        assert "# Project Context" in sp
        assert "## SOUL.md" in sp
