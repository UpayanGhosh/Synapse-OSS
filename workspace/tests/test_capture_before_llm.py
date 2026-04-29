import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.mark.asyncio
async def test_user_message_is_saved_when_persona_chat_hangs(tmp_path, monkeypatch):
    import sci_fi_dashboard.pipeline_helpers as ph
    from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache
    from sci_fi_dashboard.multiuser.session_key import build_session_key
    from sci_fi_dashboard.multiuser.session_store import SessionStore
    from sci_fi_dashboard.multiuser.transcript import load_messages, transcript_path

    async def _hang_persona_chat(*args, **kwargs):
        await asyncio.sleep(60)
        return {"reply": "never reached"}

    async def _never_spawn(*args, **kwargs):
        return None

    cfg = SimpleNamespace(
        data_root=tmp_path,
        session={
            "dmScope": "per-channel-peer",
            "identityLinks": {},
            "chat_timeout_seconds": 0.01,
        },
        channels={"whatsapp": {"dmHistoryLimit": 50}},
        tts={"enabled": False},
    )

    monkeypatch.setattr("synapse_config.SynapseConfig.load", classmethod(lambda cls: cfg))
    monkeypatch.setattr("sci_fi_dashboard.chat_pipeline.persona_chat", _hang_persona_chat)
    monkeypatch.setattr("sci_fi_dashboard.subagent.spawn.maybe_spawn_agent", _never_spawn)
    monkeypatch.setattr(ph.deps, "_resolve_target", lambda _chat_id: "the_creator")
    monkeypatch.setattr(ph.deps, "conversation_cache", ConversationCache(max_entries=20, ttl_s=60))

    user_msg = "please remember this even if llm hangs"
    chat_id = "+15550001111"

    reply = await ph.process_message_pipeline(user_msg, chat_id)
    assert "saved" in reply.lower()

    session_key = build_session_key(
        agent_id="the_creator",
        channel="whatsapp",
        peer_id=chat_id,
        peer_kind="direct",
        account_id="whatsapp",
        dm_scope="per-channel-peer",
        main_key="whatsapp:dm",
        identity_links={},
    )

    store = SessionStore(agent_id="the_creator", data_root=tmp_path)
    entry = await store.get(session_key)
    assert entry is not None
    t_path = transcript_path(entry, tmp_path, "the_creator")

    # Assistant reply is appended in background task; wait briefly for it.
    for _ in range(50):
        messages = await load_messages(t_path, limit=20)
        if any(m.get("role") == "assistant" for m in messages):
            break
        await asyncio.sleep(0.01)

    messages = await load_messages(t_path, limit=20)
    assert any(m.get("role") == "user" and m.get("content") == user_msg for m in messages)
    assert any(
        m.get("role") == "assistant" and "saved" in m.get("content", "").lower() for m in messages
    )
