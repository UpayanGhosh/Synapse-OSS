"""Run an isolated real Synapse memory/personality scenario via the Luna relay.

The operator starts this process, reads each JSON request under the run
directory, obtains one fresh GPT-6 Luna inference, and writes the matching
response JSON. Synthetic data only; channel transport is an in-process fake.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import types
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "workspace") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "workspace"))


TURN_PLAN = (
    ("alice", "alice-style", "My default vibe: relaxed, a little playful, and pretty brief. I like a goofy callback now and then."),
    ("alice", "alice-incident", "At Monday's meeting my tiny red umbrella flipped inside out as I walked in. You called it my CEO umbrella; that's our joke. Remember the umbrella incident."),
    ("bob", "bob-style", "For me, please be calm, direct, and concise. I don't enjoy jokes in practical messages."),
    ("bob", "bob-incident", "A pigeon stole my lunch sandwich from the balcony today. I called it our CFO; keep that as my joke."),
    ("alice", "alice-correction", "Correction to my preference: for my default, use straightforward and formal language; no playful jokes. Keep replies brief."),
    ("alice", "alice-unrelated", "What is 17 percent of 235?"),
    ("alice", "alice-recall", "Search your memory for our small meeting incident. What detail did we joke about?"),
    ("bob", "bob-recall", "Search your memory for my lunch incident. What got taken?"),
    ("alice", "alice-override", "For just this one note, ignore my formal default and give me one playful, brief line about starting our project update."),
)
BLOCKED_AUTO_CONTINUATIONS: list[dict[str, str]] = []


def _extend_service_extraction_timeout_for_agent_relay(timeout_seconds: float = 420.0) -> None:
    """Override only the service module's wait_for for this slow test relay."""
    import sci_fi_dashboard.personal_memory_service as memory_service_module

    actual_asyncio = asyncio

    async def wait_for(awaitable, timeout):
        if timeout == 15.0:
            timeout = timeout_seconds
        return await actual_asyncio.wait_for(awaitable, timeout=timeout)

    memory_service_module.asyncio = types.SimpleNamespace(
        wait_for=wait_for,
        **{
            name: getattr(actual_asyncio, name)
            for name in dir(actual_asyncio)
            if name != "wait_for" and not name.startswith("__")
        },
    )


class FakeChannel:
    channel_id = "whatsapp"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, recipient: str, text: str) -> bool:
        self.sent.append((recipient, text))
        return True

    async def mark_read(self, _recipient: str, _message_id: str) -> None:
        return None

    async def send_typing(self, _recipient: str) -> None:
        return None


class FakeChannelRegistry:
    def __init__(self, channel: FakeChannel) -> None:
        self.channel = channel

    def get(self, channel_id: str):
        return self.channel if channel_id == "whatsapp" else None


async def _wait_until(check, *, timeout: float = 360.0, label: str) -> Any:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        value = check()
        if value:
            return value
        await asyncio.sleep(0.025)
    raise TimeoutError(f"timed out waiting for {label}")


def _configure_isolated_workspace(run_dir: Path) -> Path:
    home = run_dir / "synapse-home"
    home.mkdir(parents=True, exist_ok=True)
    os.environ["SYNAPSE_HOME"] = str(home)
    config = {
        "model_mappings": {
            "casual": {"model": "openai_codex/gpt-6-luna", "prompt_tier": "frontier"}
        },
        "session": {
            "dmScope": "per-channel-peer",
            "dual_cognition_enabled": False,
            "chat_timeout_seconds": 600,
        },
        "channels": {"whatsapp": {"dmHistoryLimit": 30}},
        "embedding": {},
        "mcp": {"enabled": False},
        "tts": {"enabled": False},
        "heartbeat": {"enabled": False},
    }
    (home / "synapse.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    workspace = home / "workspace" / "simulation-agent"
    workspace.mkdir(parents=True, exist_ok=True)
    canonical = {
        "INSTRUCTIONS": "You are answering a synthetic memory simulation. Be truthful and concise.",
        "SOUL": "Warm, conversational, and respectful.",
        "CORE": "Do not invent facts. Use scoped retrieved memories only when relevant.",
        "CODE": "Follow the tool schemas supplied for this turn.",
        "IDENTITY": "You are Synapse, a personal assistant.",
        "TOOLS": "Use only tools explicitly available in this request.",
        "AGENTS": "Keep everyday replies short and natural.",
        "USER": "SYNTHETIC_PRIVATE_SENTINEL_ALICE_ONLY",
        "MEMORY": "SYNTHETIC_PRIVATE_SENTINEL_BOB_ONLY",
    }
    for name, text in canonical.items():
        (workspace / f"{name}.md").write_text(text, encoding="utf-8")
    return home


def _write_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


async def _new_worker_stack(
    data_root: Path,
    router,
    channel: FakeChannel,
    artifact_dir: Path,
    *,
    service_started: bool = True,
    style_extract_timeout: float = 15.0,
    style_lease_seconds: float = 60.0,
):
    from sci_fi_dashboard import _deps as deps
    from sci_fi_dashboard.gateway.durable_io import InboxStore
    from sci_fi_dashboard.gateway.flood import FloodGate
    from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue
    from sci_fi_dashboard.gateway.retry_queue import RetryQueue
    from sci_fi_dashboard.gateway.worker import MessageWorker
    from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache
    from sci_fi_dashboard.personal_memory import PersonalMemoryStore
    from sci_fi_dashboard.personal_memory_service import PersonalMemoryService
    from sci_fi_dashboard.pipeline_helpers import process_message_pipeline

    _extend_service_extraction_timeout_for_agent_relay()
    store = PersonalMemoryStore(data_root / "workspace" / "db" / "memory.db")
    retry = RetryQueue(data_root)
    service = PersonalMemoryService(
        store,
        retry_queue=retry,
        router=router,
        embedding_config={"embedding": {}},
        poll_seconds=0.1,
        style_extract_timeout=style_extract_timeout,
        style_lease_seconds=style_lease_seconds,
    )
    inbox = InboxStore(data_root)
    flood = FloodGate(batch_window_seconds=0.001)
    flood.set_inbox_store(inbox)
    queue = TaskQueue()
    registry = FakeChannelRegistry(channel)

    async def on_batch(chat_id: str, text: str, metadata: dict) -> None:
        await queue.enqueue(
            MessageTask(
                task_id=str(metadata["message_id"]),
                chat_id=chat_id,
                user_message=text,
                message_id=str(metadata["message_id"]),
                channel_id=str(metadata.get("channel_id", "whatsapp")),
                inbox_ids=list(metadata.get("inbox_ids") or []),
                inbox_claimed=bool(metadata.get("inbox_claimed", False)),
            )
        )

    flood.set_callback(on_batch)
    worker = MessageWorker(
        queue,
        process_message_pipeline,
        num_workers=1,
        channel_registry=registry,
        retry_queue=retry,
        inbox_store=inbox,
        inbox_replay=flood.replay,
        personal_memory_service=service,
        inbox_poll_seconds=0.02,
    )

    deps._synapse_cfg = deps.SynapseConfig.load()
    deps.synapse_llm_router = router
    deps.personal_memory_service = service
    deps.conversation_cache = ConversationCache(max_entries=200, ttl_s=300)
    deps._resolve_target = lambda _peer: "the_creator"
    deps._proactive_engine = None
    deps.tool_registry = _memory_only_registry(artifact_dir)
    deps._TOOL_REGISTRY_AVAILABLE = True
    deps._TOOL_SAFETY_AVAILABLE = False
    deps._TOOL_FEATURES_AVAILABLE = False
    deps._SKILL_SYSTEM_AVAILABLE = False
    deps.skill_router = None
    deps.skill_registry = None
    deps.consent_protocol = None
    deps.pending_consents.clear()

    from sci_fi_dashboard import chat_pipeline
    from sci_fi_dashboard._deps import _scoped_sbs_registry

    async def no_external_auto_continue(*_args, **_kwargs):
        BLOCKED_AUTO_CONTINUATIONS.append({"kind": "persona_auto_continue"})
        return None

    # Auto-continue bypasses the worker/outbox and can use an initialized real
    # channel plus a provider-specific Gemini wrapper. Keep this memory-focused
    # simulation confined to the relay and fake transport.
    chat_pipeline.continue_conversation = no_external_auto_continue
    deps.channel_registry = registry

    workspace = Path(deps._synapse_cfg.data_root) / "workspace" / "simulation-agent"
    chat_pipeline._resolve_agent_workspace_path = lambda name: workspace / f"{name}.md"
    chat_pipeline.clear_agent_workspace_session_prefix()
    chat_pipeline._agent_workspace_cache["mtimes"] = {}
    chat_pipeline._agent_workspace_cache["content_by_tier"].clear()
    _scoped_sbs_registry.clear()

    if service_started:
        await service.start()
    await retry.start(registry)
    await worker.start()
    return store, service, inbox, flood, queue, retry, registry, worker


def _memory_only_registry(artifact_dir: Path):
    from sci_fi_dashboard.tool_registry import ToolRegistry, _query_memory_factory

    registry = ToolRegistry()

    base_factory = _query_memory_factory(None)

    def recording_factory(context):
        tool = base_factory(context)
        execute = tool.execute

        async def recording_execute(arguments):
            result = await execute(arguments)
            try:
                content = json.loads(result.content)
            except (json.JSONDecodeError, TypeError):
                content = result.content
            person = getattr(context.person_context, "person_id", None)
            _write_jsonl(
                artifact_dir / "memory_tool_receipts.jsonl",
                {
                    "person_id": person,
                    "query": arguments.get("query", ""),
                    "is_error": bool(result.is_error),
                    "result": content,
                },
            )
            return result

        tool.execute = recording_execute
        return tool

    registry.register_factory("query_memory", recording_factory)
    return registry


async def _finish_worker_stack(stack) -> None:
    _store, service, _inbox, _flood, _queue, retry, _registry, worker = stack
    await service.stop()
    await worker.stop()
    await retry.stop()


def _inbox_status(inbox, message_id: str) -> tuple[int, str] | None:
    with sqlite3.connect(inbox.path) as conn:
        row = conn.execute(
            "SELECT id,status FROM inbound_messages WHERE channel_id='whatsapp' AND message_id=?",
            (message_id,),
        ).fetchone()
    return None if row is None else (int(row[0]), str(row[1]))


def _outbox_row(retry, message_key: str):
    with sqlite3.connect(retry._db_path) as conn:
        return conn.execute(
            "SELECT status,text,owner_id,parent_episode_id FROM retry_queue WHERE message_key=?",
            (message_key,),
        ).fetchone()


def _source_episode_id(store, message_id: str) -> str | None:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT episode_id FROM personal_episodes WHERE source_message_id=? AND role='user'",
            (message_id,),
        ).fetchone()
    return None if row is None else str(row[0])


def _observation_status(store, episode_id: str) -> str | None:
    with store._connect() as conn:
        row = conn.execute(
            "SELECT status FROM user_memory_observations WHERE source_episode_id=?",
            (episode_id,),
        ).fetchone()
    return None if row is None else str(row[0])


async def _run_turn(run_dir: Path, stack, channel: FakeChannel, owner: str, message_id: str, text: str) -> dict:
    store, service, inbox, flood, _queue, retry, _registry, _worker = stack
    accepted_before = len(channel.sent)
    new = await flood.incoming(
        owner,
        text,
        {"message_id": message_id, "channel_id": "whatsapp", "sender_name": owner},
    )
    if not new:
        raise AssertionError(f"synthetic inbound {message_id} was unexpectedly deduplicated")
    await _wait_until(
        lambda: _inbox_status(inbox, message_id), label=f"inbox capture {message_id}"
    )
    await _wait_until(
        lambda: "completed" if _inbox_status(inbox, message_id)[1] == "completed" else None,
        label=f"worker completion {message_id}",
    )
    outbox = await _wait_until(
        lambda: _outbox_row(retry, f"reply:{message_id}:0")
        if (_outbox_row(retry, f"reply:{message_id}:0") or (None,))[0] == "accepted"
        else None,
        label=f"accepted fake-channel receipt {message_id}",
    )
    await _wait_until(
        lambda: True if len(channel.sent) > accepted_before else None,
        label=f"fake channel send {message_id}",
    )
    episode_id = _source_episode_id(store, message_id)
    if episode_id is None:
        raise AssertionError(f"raw episode missing for {message_id}")
    _write_jsonl(
        run_dir / "delivery-events.jsonl",
        {
            "message_id": message_id,
            "status": outbox[0],
            "channel_id": "whatsapp",
            "recipient": owner,
            "parent_episode_id": outbox[3],
        },
    )
    await _wait_until(
        lambda: "processed" if _observation_status(store, episode_id) == "processed" else None,
        timeout=900,
        label=f"personal memory extraction {message_id}",
    )
    item = {
        "message_id": message_id,
        "owner": owner,
        "user": text,
        "reply": outbox[1],
        "inbox_status": _inbox_status(inbox, message_id)[1],
        "outbox_status": outbox[0],
        "outbox_owner": outbox[2],
        "source_episode_id": episode_id,
        "accepted_send": True,
    }
    _write_jsonl(run_dir / "turns.jsonl", item)
    _write_jsonl(
        run_dir / "receipts.jsonl",
        {
            "message_id": message_id,
            "status": outbox[0],
            "channel_id": "whatsapp",
            "recipient": owner,
            "parent_episode_id": outbox[3],
        },
    )
    return item


async def _run_simulation(run_dir: Path) -> dict:
    home = _configure_isolated_workspace(run_dir)
    from luna_file_relay import FileRelayRouter
    from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache
    from synapse_config import SynapseConfig
    cfg = SynapseConfig.load()
    if cfg.data_root.resolve() != home.resolve():
        raise AssertionError("SYNAPSE_HOME did not isolate Synapse data root")

    router = FileRelayRouter(
        run_dir,
        timeout_seconds=180,
        poll_interval_seconds=0.05,
        max_requests=40,
    )
    channel = FakeChannel()
    stack = await _new_worker_stack(cfg.data_root, router, channel, run_dir)
    results: list[dict] = []
    try:
        for person, message_id, text in TURN_PLAN[:6]:
            results.append(
                await _run_turn(run_dir, stack, channel, f"{person}-peer", message_id, text)
            )
    finally:
        await _finish_worker_stack(stack)

    # A new store/service/worker and empty in-memory history; disk state is retained.
    from sci_fi_dashboard import _deps as deps
    from sci_fi_dashboard.gateway.durable_io import InboxStore
    from sci_fi_dashboard.gateway.flood import FloodGate
    from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue
    from sci_fi_dashboard.gateway.retry_queue import RetryQueue
    from sci_fi_dashboard.gateway.worker import MessageWorker
    from sci_fi_dashboard.personal_memory import PersonalMemoryStore
    from sci_fi_dashboard.personal_memory_service import PersonalMemoryService
    from sci_fi_dashboard.pipeline_helpers import process_message_pipeline

    _extend_service_extraction_timeout_for_agent_relay()
    reopened_store = PersonalMemoryStore(cfg.db_dir / "memory.db")
    retry = RetryQueue(cfg.data_root)
    service = PersonalMemoryService(
        reopened_store,
        retry_queue=retry,
        router=router,
        embedding_config={"embedding": {}},
        poll_seconds=0.1,
    )
    inbox = InboxStore(cfg.data_root)
    flood = FloodGate(batch_window_seconds=0.001)
    flood.set_inbox_store(inbox)
    queue = TaskQueue()
    registry = FakeChannelRegistry(channel)

    async def on_batch(chat_id: str, text: str, metadata: dict) -> None:
        await queue.enqueue(
            MessageTask(
                task_id=str(metadata["message_id"]),
                chat_id=chat_id,
                user_message=text,
                message_id=str(metadata["message_id"]),
                channel_id="whatsapp",
                inbox_ids=list(metadata.get("inbox_ids") or []),
                inbox_claimed=bool(metadata.get("inbox_claimed", False)),
            )
        )

    flood.set_callback(on_batch)
    worker = MessageWorker(
        queue,
        process_message_pipeline,
        num_workers=1,
        channel_registry=registry,
        retry_queue=retry,
        inbox_store=inbox,
        inbox_replay=flood.replay,
        personal_memory_service=service,
        inbox_poll_seconds=0.02,
    )
    deps.personal_memory_service = service
    deps.conversation_cache = ConversationCache(max_entries=200, ttl_s=300)
    from sci_fi_dashboard import chat_pipeline
    from sci_fi_dashboard._deps import _scoped_sbs_registry
    async def no_external_auto_continue(*_args, **_kwargs):
        BLOCKED_AUTO_CONTINUATIONS.append({"kind": "persona_auto_continue"})
        return None

    chat_pipeline.continue_conversation = no_external_auto_continue
    deps.channel_registry = registry
    _scoped_sbs_registry.clear()
    chat_pipeline.clear_agent_workspace_session_prefix()
    chat_pipeline._agent_workspace_cache["mtimes"] = {}
    chat_pipeline._agent_workspace_cache["content_by_tier"].clear()
    await service.start()
    await retry.start(registry)
    await worker.start()
    stack = (reopened_store, service, inbox, flood, queue, retry, registry, worker)
    try:
        for person, message_id, text in TURN_PLAN[6:]:
            results.append(
                await _run_turn(run_dir, stack, channel, f"{person}-peer", message_id, text)
            )
    finally:
        await _finish_worker_stack(stack)

    alice_context = _context_for_peer(cfg, "alice-peer")
    bob_context = _context_for_peer(cfg, "bob-peer")
    alice_profile = reopened_store.get_relationship(alice_context)
    bob_profile = reopened_store.get_relationship(bob_context)
    alice_rows = reopened_store.recall(alice_context, "umbrella meeting CEO", limit=8)
    bob_rows = reopened_store.recall(bob_context, "pigeon sandwich CFO balcony", limit=8)
    alice_foreign = reopened_store.recall(alice_context, "pigeon sandwich CFO balcony", limit=8)
    bob_foreign = reopened_store.recall(bob_context, "umbrella meeting CEO", limit=8)
    assert alice_context.person_id != bob_context.person_id
    assert alice_rows and all(row.person_id == alice_context.person_id for row in alice_rows)
    assert bob_rows and all(row.person_id == bob_context.person_id for row in bob_rows)
    assert all("pigeon" not in row.content.lower() for row in alice_foreign)
    assert all("umbrella" not in row.content.lower() for row in bob_foreign)
    assert alice_profile.get("preferences") != bob_profile.get("preferences")

    requests = sorted((run_dir / "requests").glob("*.json"))
    assert 0 < len(requests) <= 40
    packet_texts = {path.stem: path.read_text(encoding="utf-8") for path in requests}
    for _path, body in packet_texts.items():
        assert "SYNTHETIC_PRIVATE_SENTINEL_ALICE_ONLY" not in body
        assert "SYNTHETIC_PRIVATE_SENTINEL_BOB_ONLY" not in body
    with sqlite3.connect(reopened_store.db_path) as conn:
        facts = conn.execute(
            "SELECT user_id,kind,key,value,source_episode_id,status FROM user_memory_facts"
        ).fetchall()
        episodes = conn.execute(
            "SELECT owner_key,role,content,delivery_state,occurred_at_source FROM personal_episodes"
        ).fetchall()
    summary = {
        "model": "gpt-6-luna (fresh agent-mediated inference per router request)",
        "embedding_mode": "lexical fallback; no embedding provider configured",
        "turn_count": len(results),
        "inference_request_count": len(requests),
        "accepted_channel_sends": len(channel.sent),
        "alice_profile": alice_profile,
        "bob_profile": bob_profile,
        "alice_owner": alice_context.person_id,
        "bob_owner": bob_context.person_id,
        "query_memory_calls": _query_memory_receipt_count(run_dir),
        "facts": facts,
        "episode_count": len(episodes),
        "assertions": {
            "different_person_owners": alice_context.person_id != bob_context.person_id,
            "cross_person_recall_empty": not alice_foreign and not bob_foreign,
            "profile_preferences_differ": alice_profile.get("preferences") != bob_profile.get("preferences"),
            "all_fake_channel_sends_accepted": len(channel.sent) == len(results),
            "private_workspace_sentinels_absent_from_prompts": True,
        },
        "results": results,
        "sent": channel.sent,
        "blocked_auto_continue_attempts": len(BLOCKED_AUTO_CONTINUATIONS),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, default=str, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "run_dir": str(run_dir),
        "turns": len(results),
        "inference_requests": len(requests),
        "query_memory_calls": summary["query_memory_calls"],
        "assertions": summary["assertions"],
    }, ensure_ascii=False), flush=True)
    return summary


def _context_for_peer(cfg, peer: str):
    from sci_fi_dashboard.multiuser.session_key import build_session_key
    from sci_fi_dashboard.personal_memory import (
        PersonMemoryContext,
        resolve_person_memory_context,
        scope_conversation_key,
    )

    base_key = build_session_key(
        agent_id="the_creator",
        channel="whatsapp",
        peer_id=peer,
        peer_kind="direct",
        account_id="whatsapp",
        dm_scope=cfg.session.get("dmScope", "per-channel-peer"),
        main_key="whatsapp:dm",
        identity_links=cfg.session.get("identityLinks", {}),
    )
    context = resolve_person_memory_context(
        channel_id="whatsapp",
        peer_id=peer,
        conversation_id=base_key,
        identity_links=cfg.session.get("identityLinks", {}),
        origin="channel",
    )
    session_key = scope_conversation_key(
        base_key,
        context,
        dm_scope=cfg.session.get("dmScope", "per-channel-peer"),
        agent_id="the_creator",
    )
    assert context is not None
    return PersonMemoryContext(context.person_id, session_key, context.visibility)


def _query_memory_receipt_count(run_dir: Path) -> int:
    path = run_dir / "memory_tool_receipts.jsonl"
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _summarize_existing_run(run_dir: Path) -> dict[str, Any]:
    """Summarize persisted run artifacts without replaying any conversation."""
    home = _configure_isolated_workspace(run_dir)
    from sci_fi_dashboard.personal_memory import PersonalMemoryStore
    from synapse_config import SynapseConfig

    cfg = SynapseConfig.load()
    store = PersonalMemoryStore(cfg.db_dir / "memory.db")
    alice_context = _context_for_peer(cfg, "alice-peer")
    bob_context = _context_for_peer(cfg, "bob-peer")
    alice_profile = store.get_relationship(alice_context)
    bob_profile = store.get_relationship(bob_context)
    alice_rows = store.recall(alice_context, "umbrella meeting CEO", limit=8)
    bob_rows = store.recall(bob_context, "pigeon sandwich CFO balcony", limit=8)
    alice_foreign = store.recall(alice_context, "pigeon sandwich CFO balcony", limit=8)
    bob_foreign = store.recall(bob_context, "umbrella meeting CEO", limit=8)
    assert alice_rows and all(row.person_id == alice_context.person_id for row in alice_rows)
    assert bob_rows and all(row.person_id == bob_context.person_id for row in bob_rows)
    results = [
        json.loads(line)
        for line in (run_dir / "turns.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    receipts = [
        json.loads(line)
        for line in (run_dir / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    requests = sorted((run_dir / "requests").glob("*.json"))
    if not 0 < len(requests) <= 40:
        raise AssertionError(f"inference request count out of bounds: {len(requests)}")
    if len(results) != len(receipts):
        raise AssertionError("persisted turn and receipt counts differ")
    for path in requests:
        body = path.read_text(encoding="utf-8")
        assert "SYNTHETIC_PRIVATE_SENTINEL_ALICE_ONLY" not in body
        assert "SYNTHETIC_PRIVATE_SENTINEL_BOB_ONLY" not in body
    with sqlite3.connect(store.db_path) as conn:
        facts = conn.execute(
            "SELECT user_id,kind,key,value,source_episode_id,status FROM user_memory_facts"
        ).fetchall()
        episodes = conn.execute(
            "SELECT owner_key,role,content,delivery_state,occurred_at_source FROM personal_episodes"
        ).fetchall()
    summary = {
        "model": "gpt-6-luna (fresh agent-mediated inference per router request)",
        "embedding_mode": "lexical fallback; no embedding provider configured",
        "turn_count": len(results),
        "inference_request_count": len(requests),
        "accepted_channel_sends": sum(r.get("status") == "accepted" for r in receipts),
        "alice_profile": alice_profile,
        "bob_profile": bob_profile,
        "alice_owner": alice_context.person_id,
        "bob_owner": bob_context.person_id,
        "query_memory_calls": _query_memory_receipt_count(run_dir),
        "facts": facts,
        "episode_count": len(episodes),
        "assertions": {
            "different_person_owners": alice_context.person_id != bob_context.person_id,
            "cross_person_recall_empty": not alice_foreign and not bob_foreign,
            "profile_preferences_differ": alice_profile.get("preferences") != bob_profile.get("preferences"),
            "all_fake_channel_sends_accepted": all(r.get("status") == "accepted" for r in receipts),
            "private_workspace_sentinels_absent_from_prompts": True,
        },
        "results": results,
        "receipts": receipts,
        "blocked_auto_continue_attempts": len(BLOCKED_AUTO_CONTINUATIONS),
        "data_root": str(home),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, default=str, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "run_dir": str(run_dir),
        "turns": len(results),
        "inference_requests": len(requests),
        "query_memory_calls": summary["query_memory_calls"],
        "assertions": summary["assertions"],
    }, ensure_ascii=False), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_DATASETS_OFFLINE"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
    from external_io_guard import ExternalIODenyGuard

    io_guard = ExternalIODenyGuard(run_dir / "outbound-attempts.json")
    print(json.dumps({"run_dir": str(run_dir), "stage": "starting"}), flush=True)

    async def guarded_run() -> None:
        asyncio.get_running_loop()
        io_guard.install()
        try:
            if args.summary_only:
                _summarize_existing_run(run_dir)
            else:
                await _run_simulation(run_dir)
            if io_guard.attempts:
                raise RuntimeError("simulation blocked outbound I/O; inspect outbound-attempts.json")
            if BLOCKED_AUTO_CONTINUATIONS:
                raise RuntimeError("unexpected auto-continuation was blocked during simulation")
        finally:
            io_guard.restore()

    asyncio.run(guarded_run())


if __name__ == "__main__":
    main()
