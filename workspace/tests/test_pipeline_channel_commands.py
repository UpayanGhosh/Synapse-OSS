import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.asyncio
async def test_channel_pipeline_uses_telegram_session_key(tmp_path, monkeypatch):
    import sci_fi_dashboard.pipeline_helpers as ph
    from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache
    from sci_fi_dashboard.multiuser.session_key import build_session_key
    from sci_fi_dashboard.multiuser.session_store import SessionStore

    captured = {}

    async def _persona_chat(request, *args, **kwargs):
        captured["channel_id"] = request.channel_id
        return {"reply": "saved"}

    async def _never_spawn(*args, **kwargs):
        return None

    cfg = SimpleNamespace(
        data_root=tmp_path,
        session={
            "dmScope": "per-channel-peer",
            "identityLinks": {},
            "chat_timeout_seconds": 1,
        },
        channels={"telegram": {"dmHistoryLimit": 50}},
        tts={"enabled": False},
    )

    monkeypatch.setattr("synapse_config.SynapseConfig.load", classmethod(lambda cls: cfg))
    monkeypatch.setattr("sci_fi_dashboard.chat_pipeline.persona_chat", _persona_chat)
    monkeypatch.setattr("sci_fi_dashboard.subagent.spawn.maybe_spawn_agent", _never_spawn)
    monkeypatch.setattr(ph.deps, "_resolve_target", lambda _chat_id: "the_creator")
    monkeypatch.setattr(ph.deps, "conversation_cache", ConversationCache(max_entries=20, ttl_s=60))

    await ph.process_message_pipeline("telegram memory", "12345", channel_id="telegram")

    assert captured["channel_id"] == "telegram"

    expected_key = build_session_key(
        agent_id="the_creator",
        channel="telegram",
        peer_id="12345",
        peer_kind="direct",
        account_id="telegram",
        dm_scope="per-channel-peer",
        main_key="telegram:dm",
        identity_links={},
    )
    wrong_key = build_session_key(
        agent_id="the_creator",
        channel="whatsapp",
        peer_id="12345",
        peer_kind="direct",
        account_id="whatsapp",
        dm_scope="per-channel-peer",
        main_key="whatsapp:dm",
        identity_links={},
    )

    store = SessionStore(agent_id="the_creator", data_root=tmp_path)
    assert await store.get(expected_key) is not None
    assert await store.get(wrong_key) is None


@pytest.mark.asyncio
async def test_tools_command_lists_resolved_tools(monkeypatch):
    import sci_fi_dashboard.pipeline_helpers as ph
    from sci_fi_dashboard.tool_registry import SynapseTool, ToolResult, ToolRegistry

    async def _execute(_args):
        return ToolResult(content="ok")

    registry = ToolRegistry()
    registry.register_tool(
        SynapseTool(
            name="query_memory",
            description="Search saved memory.",
            parameters={"type": "object", "properties": {}},
            execute=_execute,
        )
    )
    monkeypatch.setattr(ph.deps, "tool_registry", registry)

    reply = await ph.process_message_pipeline("/tools", "chat-1", channel_id="telegram")

    assert "Available tools" in reply
    assert "query_memory" in reply


def test_parse_reminder_request_explicit_datetime():
    import sci_fi_dashboard.pipeline_helpers as ph

    parsed = ph._parse_reminder_request(
        "remind me to send Mira the wireframe by Friday May 1 at 5 PM",
        now=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
    )

    assert parsed is not None
    assert parsed.task == "send Mira the wireframe"
    assert parsed.when.isoformat().startswith("2026-05-01T17:00:00")


def test_parse_reminder_request_nudge_before_event():
    import sci_fi_dashboard.pipeline_helpers as ph

    parsed = ph._parse_reminder_request(
        (
            "Tomorrow the Kestrel demo is at 11:30 AM, and I need at least "
            "20 minutes before it to clean the flow. Can you nudge me "
            "30 minutes before?"
        ),
        now=datetime(2026, 4, 30, 16, 50, tzinfo=UTC),
    )

    assert parsed is not None
    assert parsed.task == "clean the flow for the Kestrel demo"
    assert parsed.when.isoformat().startswith("2026-05-01T11:00:00")


def test_channel_reply_strips_markdown_and_diagnostics():
    import sci_fi_dashboard.pipeline_helpers as ph

    reply = ph._ensure_user_visible_reply(
        "**Done** - check `Kestrel` now.\n\n"
        "- one thing\n\n"
        "---\n"
        "**Context Usage:** 1 / 100\n"
        "**Model:** test"
    )

    assert reply == "Done - check Kestrel now.\n- one thing"


@pytest.mark.asyncio
async def test_reminder_command_creates_cron_job(monkeypatch):
    import sci_fi_dashboard.pipeline_helpers as ph

    class FakeCron:
        def __init__(self):
            self.jobs = []

        def add(self, job):
            self.jobs.append(job)
            return SimpleNamespace(id="job1", state=SimpleNamespace(next_run_at_ms=1))

    cron = FakeCron()
    monkeypatch.setattr(ph.deps, "cron_service", cron, raising=False)

    reply = await ph._maybe_handle_reminder_command(
        "remind me to send Mira the wireframe by Friday May 1 at 5 PM",
        chat_id="tg-chat",
        channel_id="telegram",
        now=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
    )

    assert reply is not None
    assert "Done - I'll nudge you" in reply
    assert cron.jobs[0]["delivery"] == {
        "mode": "announce",
        "channel": "telegram",
        "to": "tg-chat",
    }
    assert "Reminder due now: send Mira the wireframe." in cron.jobs[0]["payload"]["message"]
    assert "Output only the Telegram reminder text" in cron.jobs[0]["payload"]["message"]


@pytest.mark.asyncio
async def test_periodic_memory_flush_after_50_messages(tmp_path, monkeypatch):
    import sci_fi_dashboard.pipeline_helpers as ph
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import append_message, transcript_path

    store = SessionStore(agent_id="the_creator", data_root=tmp_path)
    session_key = "agent:the_creator:telegram:dm:tg-chat"
    entry = await store.update(session_key, {})
    t_path = transcript_path(entry, tmp_path, "the_creator")
    for i in range(50):
        await append_message(t_path, {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"})

    captured = []

    async def fake_ingest(*, archived_path, agent_id, session_key, hemisphere="safe"):
        captured.append((archived_path, agent_id, session_key, hemisphere))

    monkeypatch.setattr(ph, "_ingest_session_background", fake_ingest)

    await ph._maybe_schedule_periodic_memory_flush(
        session_key=session_key,
        agent_id="the_creator",
        data_root=tmp_path,
        transcript_file=t_path,
        session_store=store,
        hemisphere="safe",
    )

    for _ in range(50):
        if captured:
            break
        await ph.asyncio.sleep(0.01)

    assert captured
    snapshot_path, agent_id, flushed_key, hemisphere = captured[0]
    assert snapshot_path.exists()
    assert agent_id == "the_creator"
    assert flushed_key == session_key
    assert hemisphere == "safe"

    updated = await store.get(session_key)
    assert updated is not None
    assert updated.memory_flush_message_count == 50
    assert updated.memory_flush_at is not None
    assert t_path.exists(), "periodic flush must not rotate or delete active transcript"


@pytest.mark.asyncio
async def test_periodic_memory_flush_after_6_hours_without_prior_flush(tmp_path, monkeypatch):
    import time

    import sci_fi_dashboard.pipeline_helpers as ph
    from sci_fi_dashboard.multiuser.transcript import append_message, transcript_path

    session_key = "agent:the_creator:telegram:dm:tg-chat"
    entry = SimpleNamespace(
        session_id="six-hour-session",
        updated_at=time.time() - ph.PERIODIC_MEMORY_FLUSH_SECONDS - 5,
        memory_flush_at=None,
        memory_flush_message_count=0,
    )
    t_path = transcript_path(entry, tmp_path, "the_creator")
    await append_message(t_path, {"role": "user", "content": "long-lived memory"})

    captured = []
    updates = []

    class FakeStore:
        async def get(self, key):
            return entry

        async def update(self, key, patch):
            updates.append((key, patch))
            for patch_key, patch_value in patch.items():
                setattr(entry, patch_key, patch_value)
            return entry

    async def fake_ingest(*, archived_path, agent_id, session_key, hemisphere="safe"):
        captured.append((archived_path, agent_id, session_key, hemisphere))

    monkeypatch.setattr(ph, "_ingest_session_background", fake_ingest)

    await ph._maybe_schedule_periodic_memory_flush(
        session_key=session_key,
        agent_id="the_creator",
        data_root=tmp_path,
        transcript_file=t_path,
        session_store=FakeStore(),
        hemisphere="safe",
    )

    for _ in range(50):
        if captured:
            break
        await ph.asyncio.sleep(0.01)

    assert captured
    assert updates
    assert entry.memory_flush_message_count == 1
