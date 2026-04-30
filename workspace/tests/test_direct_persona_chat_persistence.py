import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def direct_persona_env(tmp_path, monkeypatch):
    import sci_fi_dashboard.pipeline_helpers as ph
    from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache

    cfg = SimpleNamespace(
        data_root=tmp_path,
        session={"chat_timeout_seconds": 0.05},
        channels={},
        tts={"enabled": False},
    )
    monkeypatch.setattr("synapse_config.SynapseConfig.load", classmethod(lambda cls: cfg))
    monkeypatch.setattr(ph.deps, "conversation_cache", ConversationCache(max_entries=20, ttl_s=60))
    return ph


@pytest.mark.asyncio
async def test_direct_persona_chat_persists_turns_before_and_after_llm(
    direct_persona_env, monkeypatch, tmp_path
):
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import load_messages, transcript_path
    from sci_fi_dashboard.schemas import ChatRequest

    ph = direct_persona_env

    async def fake_persona_chat(request, target, background_tasks=None, mcp_context=""):
        assert request.history == []
        return {"reply": "stored reply", "model": "fake-model"}

    monkeypatch.setattr("sci_fi_dashboard.chat_pipeline.persona_chat", fake_persona_chat)

    result = await ph.process_direct_persona_chat(
        ChatRequest(
            message="remember direct persona persistence",
            user_id="cli-user",
            session_type="safe",
            session_key="cli:the_creator:cli-user",
        ),
        "the_creator",
    )

    assert result["reply"] == "stored reply"
    store = SessionStore("the_creator", data_root=tmp_path)
    entry = await store.get("cli:the_creator:cli-user")
    assert entry is not None
    messages = await load_messages(transcript_path(entry, tmp_path, "the_creator"))
    assert messages == [
        {"role": "user", "content": "remember direct persona persistence"},
        {"role": "assistant", "content": "stored reply"},
    ]


@pytest.mark.asyncio
async def test_direct_persona_chat_handles_new_by_archiving_captured_transcript(
    direct_persona_env, monkeypatch, tmp_path
):
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import load_messages
    from sci_fi_dashboard.schemas import ChatRequest

    ph = direct_persona_env
    archived_seen = []

    async def fake_persona_chat(request, target, background_tasks=None, mcp_context=""):
        return {"reply": f"reply to {request.message}", "model": "fake-model"}

    async def fake_ingest(*, archived_path, agent_id, session_key, hemisphere="safe"):
        archived_seen.append((archived_path, agent_id, session_key, hemisphere))

    monkeypatch.setattr("sci_fi_dashboard.chat_pipeline.persona_chat", fake_persona_chat)
    monkeypatch.setattr(ph, "_ingest_session_background", fake_ingest)

    req = ChatRequest(
        message="Project Aurora direct memory should survive new",
        user_id="cli-user",
        session_type="safe",
        session_key="cli:the_creator:cli-user",
    )
    await ph.process_direct_persona_chat(req, "the_creator")

    result = await ph.process_direct_persona_chat(
        ChatRequest(
            message="/new",
            user_id="cli-user",
            session_type="safe",
            session_key="cli:the_creator:cli-user",
        ),
        "the_creator",
    )

    assert "remember" in result["reply"].lower()
    for _ in range(50):
        if archived_seen:
            break
        await asyncio.sleep(0.01)

    assert archived_seen
    archived_path, agent_id, session_key, hemisphere = archived_seen[0]
    assert agent_id == "the_creator"
    assert session_key == "cli:the_creator:cli-user"
    assert hemisphere == "safe"
    archived_messages = await load_messages(archived_path)
    assert archived_messages[0]["content"] == "Project Aurora direct memory should survive new"

    store = SessionStore("the_creator", data_root=tmp_path)
    entry_after = await store.get("cli:the_creator:cli-user")
    assert entry_after is not None
    assert not archived_path.with_suffix("").exists()


@pytest.mark.asyncio
async def test_direct_persona_chat_saves_user_message_when_llm_times_out(
    direct_persona_env, monkeypatch, tmp_path
):
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import load_messages, transcript_path
    from sci_fi_dashboard.schemas import ChatRequest

    ph = direct_persona_env

    async def hanging_persona_chat(*args, **kwargs):
        await asyncio.sleep(60)
        return {"reply": "never"}

    monkeypatch.setattr("sci_fi_dashboard.chat_pipeline.persona_chat", hanging_persona_chat)

    result = await ph.process_direct_persona_chat(
        ChatRequest(
            message="save this before timeout",
            user_id="cli-user",
            session_type="safe",
            session_key="cli:the_creator:cli-user",
        ),
        "the_creator",
    )

    assert "saved" in result["reply"].lower()
    store = SessionStore("the_creator", data_root=tmp_path)
    entry = await store.get("cli:the_creator:cli-user")
    messages = await load_messages(transcript_path(entry, tmp_path, "the_creator"))
    assert messages[0] == {"role": "user", "content": "save this before timeout"}
    assert "saved" in messages[1]["content"].lower()


def test_channel_pipeline_replaces_diagnostics_only_reply():
    from sci_fi_dashboard.pipeline_helpers import _ensure_user_visible_reply

    footer_only = "\n\n---\n**Context Usage:** 120 / 1,000,000 (0.0%)"
    friendly_with_footer = (
        "Yeah, that's a garbage combo. Rohan tossed you a fireball.\n\n"
        "---\n**Context Usage:** 16,443 / 1,000,000 (1.6%)\n"
        "**Model:** openai_codex/gpt-5.4"
    )

    assert _ensure_user_visible_reply(footer_only).startswith("I heard you.")
    assert _ensure_user_visible_reply("\u200b\n\t").startswith("I heard you.")
    assert _ensure_user_visible_reply(friendly_with_footer) == (
        "Yeah, that's a garbage combo. Rohan tossed you a fireball."
    )
    assert _ensure_user_visible_reply("Done.").startswith("Done.")
