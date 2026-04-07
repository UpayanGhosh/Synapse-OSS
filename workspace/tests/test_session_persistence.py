"""Tests for session persistence wiring (Phase 0, Plan 00-04).

Covers: SESS-01 (per-sender sessions), SESS-02 (history in ChatRequest),
SESS-04 (restart persistence), SESS-05 (compaction threshold),
SESS-06 (sessions API), SESS-07 (this test file itself).

All disk operations use `tmp_path` to avoid touching real ~/.synapse/ data.
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
# Conditional import guard — skip entire suite if multiuser package is absent.
# ---------------------------------------------------------------------------

try:
    from sci_fi_dashboard.multiuser.session_key import build_session_key
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import (
        append_message,
        load_messages,
        transcript_path,
    )
    from sci_fi_dashboard.multiuser.compaction import estimate_tokens
    from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_skip = pytest.mark.skipif(
    not _AVAILABLE,
    reason="sci_fi_dashboard/multiuser not yet available",
)


# ---------------------------------------------------------------------------
# Session key tests (SESS-01)
# ---------------------------------------------------------------------------


@_skip
def test_session_key_unique_per_sender():
    """Two different phone numbers produce different session keys."""
    key_a = build_session_key(
        agent_id="the_creator",
        channel="whatsapp",
        peer_id="+91111111",
        peer_kind="direct",
        account_id="whatsapp",
        dm_scope="per-channel-peer",
        main_key="whatsapp:dm",
        identity_links={},
    )
    key_b = build_session_key(
        agent_id="the_creator",
        channel="whatsapp",
        peer_id="+91222222",
        peer_kind="direct",
        account_id="whatsapp",
        dm_scope="per-channel-peer",
        main_key="whatsapp:dm",
        identity_links={},
    )
    assert key_a != key_b
    # After sanitization, '+' becomes '-' then stripped from edges; digits remain
    assert "91111111" in key_a
    assert "91222222" in key_b


@_skip
def test_session_key_group_vs_direct():
    """Group and direct messages for same peer produce different keys."""
    key_direct = build_session_key(
        agent_id="the_creator",
        channel="whatsapp",
        peer_id="chatid123",
        peer_kind="direct",
        account_id="whatsapp",
        dm_scope="per-channel-peer",
        main_key="whatsapp:dm",
        identity_links={},
    )
    key_group = build_session_key(
        agent_id="the_creator",
        channel="whatsapp",
        peer_id="chatid123",
        peer_kind="group",
        account_id="whatsapp",
        dm_scope="per-channel-peer",
        main_key="whatsapp:dm",
        identity_links={},
    )
    assert key_direct != key_group


@_skip
def test_session_key_contains_agent_prefix():
    """Session key always starts with 'agent:' prefix."""
    key = build_session_key(
        agent_id="the_creator",
        channel="whatsapp",
        peer_id="12345",
        peer_kind="direct",
        account_id="whatsapp",
        dm_scope="per-channel-peer",
        main_key="whatsapp:dm",
        identity_links={},
    )
    assert key.startswith("agent:")


# ---------------------------------------------------------------------------
# Transcript load/save tests (SESS-02, SESS-04)
# ---------------------------------------------------------------------------


@_skip
@pytest.mark.asyncio
async def test_history_loads_from_transcript(tmp_path):
    """Messages written to JSONL transcript are loadable."""
    t_file = tmp_path / "test_transcript.jsonl"
    msg1 = {"role": "user", "content": "hello"}
    msg2 = {"role": "assistant", "content": "hi there"}

    await append_message(t_file, msg1)
    await append_message(t_file, msg2)

    messages = await load_messages(t_file)
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "hello"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["content"] == "hi there"


@_skip
@pytest.mark.asyncio
async def test_history_survives_restart(tmp_path):
    """Transcript persists across SessionStore re-instantiation (simulated restart)."""
    data_root = tmp_path
    agent_id = "the_creator"

    # First "session": create entry and write messages
    store1 = SessionStore(agent_id=agent_id, data_root=data_root)
    entry = await store1.update("test:session:key", {})
    t_path = transcript_path(entry, data_root, agent_id)

    await append_message(t_path, {"role": "user", "content": "message before restart"})
    await append_message(t_path, {"role": "assistant", "content": "reply before restart"})

    # Second "session" (simulated restart): new store instance, same data_root
    store2 = SessionStore(agent_id=agent_id, data_root=data_root)
    entry2 = await store2.get("test:session:key")
    assert entry2 is not None
    assert entry2.session_id == entry.session_id

    t_path2 = transcript_path(entry2, data_root, agent_id)
    messages = await load_messages(t_path2)
    assert len(messages) == 2
    assert messages[0]["content"] == "message before restart"


@_skip
@pytest.mark.asyncio
async def test_load_messages_returns_empty_for_nonexistent_file(tmp_path):
    """load_messages() returns [] if the transcript file does not exist."""
    missing = tmp_path / "no_such_transcript.jsonl"
    messages = await load_messages(missing)
    assert messages == []


# ---------------------------------------------------------------------------
# Session isolation test (SESS-01)
# ---------------------------------------------------------------------------


@_skip
@pytest.mark.asyncio
async def test_session_isolation(tmp_path):
    """Two senders get separate transcript files."""
    data_root = tmp_path
    agent_id = "the_creator"
    store = SessionStore(agent_id=agent_id, data_root=data_root)

    entry_a = await store.update("agent:the_creator:whatsapp:dm:sender_a", {})
    entry_b = await store.update("agent:the_creator:whatsapp:dm:sender_b", {})

    t_path_a = transcript_path(entry_a, data_root, agent_id)
    t_path_b = transcript_path(entry_b, data_root, agent_id)

    # Different UUIDs -> different transcript files
    assert t_path_a != t_path_b

    await append_message(t_path_a, {"role": "user", "content": "from sender A"})
    await append_message(t_path_b, {"role": "user", "content": "from sender B"})

    msgs_a = await load_messages(t_path_a)
    msgs_b = await load_messages(t_path_b)

    assert len(msgs_a) == 1
    assert msgs_a[0]["content"] == "from sender A"
    assert len(msgs_b) == 1
    assert msgs_b[0]["content"] == "from sender B"


# ---------------------------------------------------------------------------
# Compaction threshold tests (SESS-05)
# ---------------------------------------------------------------------------


@_skip
def test_compaction_trigger_threshold():
    """estimate_tokens exceeds 60% of 32k when enough messages are present.

    Pipeline uses 60% of 32k = 19,200 tokens as its threshold.
    Each message of 100 chars = 100//4 = 25 tokens.
    800 messages * 25 = 20,000 tokens > 19,200 threshold.
    """
    big_messages = [
        {"role": "user", "content": "x" * 100}
        for _ in range(800)
    ]
    tokens = estimate_tokens(big_messages)
    ctx_window = 32_000
    threshold = int(ctx_window * 0.6)
    assert tokens > threshold, (
        f"Expected > {threshold} tokens, got {tokens}"
    )


@_skip
def test_compaction_below_threshold():
    """Small conversation does not trigger compaction (60% of 32k threshold)."""
    small_messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    tokens = estimate_tokens(small_messages)
    ctx_window = 32_000
    threshold = int(ctx_window * 0.6)
    assert tokens < threshold


@_skip
def test_estimate_tokens_heuristic():
    """estimate_tokens returns chars//4 per message."""
    messages = [
        {"role": "user", "content": "abcd"},        # 4 chars -> 1 token
        {"role": "assistant", "content": "abcdef"},  # 6 chars -> 1 token
    ]
    # 4//4 + 6//4 = 1 + 1 = 2
    assert estimate_tokens(messages) == 2


# ---------------------------------------------------------------------------
# ConversationCache tests
# ---------------------------------------------------------------------------


@_skip
def test_conversation_cache_hit():
    """Cache returns stored messages on get()."""
    cache = ConversationCache(max_entries=10, ttl_s=60)
    msgs = [{"role": "user", "content": "cached"}]
    cache.put("key1", msgs)
    result = cache.get("key1")
    assert result is not None
    assert len(result) == 1
    assert result[0]["content"] == "cached"


@_skip
def test_conversation_cache_miss():
    """Cache returns None for unknown key."""
    cache = ConversationCache(max_entries=10, ttl_s=60)
    assert cache.get("nonexistent") is None


@_skip
def test_conversation_cache_append_noop_on_miss():
    """append() on missing key does not create an entry."""
    cache = ConversationCache(max_entries=10, ttl_s=60)
    cache.append("missing", {"role": "user", "content": "test"})
    assert cache.get("missing") is None


@_skip
def test_conversation_cache_invalidate():
    """invalidate() removes the entry so get() returns None."""
    cache = ConversationCache(max_entries=10, ttl_s=60)
    cache.put("key1", [{"role": "user", "content": "test"}])
    cache.invalidate("key1")
    assert cache.get("key1") is None


@_skip
def test_conversation_cache_append_extends_list():
    """append() on a live entry adds the message to the cached list."""
    cache = ConversationCache(max_entries=10, ttl_s=60)
    cache.put("key1", [{"role": "user", "content": "first"}])
    cache.append("key1", {"role": "assistant", "content": "second"})
    result = cache.get("key1")
    assert result is not None
    assert len(result) == 2
    assert result[1]["content"] == "second"


@_skip
def test_conversation_cache_multiple_keys_isolated():
    """Two different keys remain independent in the cache."""
    cache = ConversationCache(max_entries=10, ttl_s=60)
    cache.put("key_a", [{"role": "user", "content": "for A"}])
    cache.put("key_b", [{"role": "user", "content": "for B"}])

    result_a = cache.get("key_a")
    result_b = cache.get("key_b")

    assert result_a is not None
    assert result_b is not None
    assert result_a[0]["content"] == "for A"
    assert result_b[0]["content"] == "for B"


# ---------------------------------------------------------------------------
# SessionStore delete + rotation tests
# ---------------------------------------------------------------------------


@_skip
@pytest.mark.asyncio
async def test_session_store_delete_removes_entry(tmp_path):
    """delete() removes the session key from the store."""
    store = SessionStore(agent_id="the_creator", data_root=tmp_path)
    session_key = "agent:the_creator:whatsapp:dm:testuser"

    # Create entry
    await store.update(session_key, {})
    entry = await store.get(session_key)
    assert entry is not None

    # Delete it
    await store.delete(session_key)
    entry_after = await store.get(session_key)
    assert entry_after is None


@_skip
@pytest.mark.asyncio
async def test_session_store_delete_then_update_rotates_session_id(tmp_path):
    """delete() + update() produces a new session_id (rotation)."""
    store = SessionStore(agent_id="the_creator", data_root=tmp_path)
    session_key = "agent:the_creator:whatsapp:dm:rotate_test"

    entry_v1 = await store.update(session_key, {})
    original_id = entry_v1.session_id

    # Delete + re-create to rotate session_id
    await store.delete(session_key)
    entry_v2 = await store.update(session_key, {})

    assert entry_v2.session_id != original_id


# ---------------------------------------------------------------------------
# Sessions API endpoint tests (SESS-06)
# ---------------------------------------------------------------------------

# Attempt to import the FastAPI app — skip integration tests gracefully if unavailable
_APP_AVAILABLE = False
try:
    import os as _os
    _os.environ.setdefault("SYNAPSE_GATEWAY_TOKEN", "test-token")
    from fastapi.testclient import TestClient
    from sci_fi_dashboard.api_gateway import app  # noqa: F401
    _APP_AVAILABLE = True
except Exception:
    pass


@pytest.fixture
def api_client():
    """Create a test client for the FastAPI app."""
    import os
    os.environ.setdefault("SYNAPSE_GATEWAY_TOKEN", "test-token")
    from fastapi.testclient import TestClient
    from sci_fi_dashboard.api_gateway import app
    return TestClient(app, headers={"Authorization": "Bearer test-token"})


@pytest.mark.skipif(not _APP_AVAILABLE, reason="api_gateway import failed — missing ML deps")
def test_get_sessions_returns_list(api_client):
    """GET /api/sessions returns a JSON list (empty or populated)."""
    resp = api_client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.skipif(not _APP_AVAILABLE, reason="api_gateway import failed — missing ML deps")
def test_session_reset_404_for_unknown(api_client):
    """POST /api/sessions/{key}/reset returns 404 for a nonexistent key."""
    resp = api_client.post("/api/sessions/nonexistent:key:here/reset")
    assert resp.status_code == 404
