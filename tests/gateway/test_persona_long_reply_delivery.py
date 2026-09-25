from __future__ import annotations

import asyncio
import importlib.util
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue
from sci_fi_dashboard.gateway.retry_queue import RetryQueue
from sci_fi_dashboard.gateway.worker import MessageWorker
from sci_fi_dashboard.schemas import ChatRequest

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
_guard_spec = importlib.util.spec_from_file_location(
    "synapse_test_external_io_guard", TOOLS_DIR / "external_io_guard.py"
)
assert _guard_spec and _guard_spec.loader
_guard_module = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(_guard_module)
ExternalIOBlockedError = _guard_module.ExternalIOBlockedError
ExternalIODenyGuard = _guard_module.ExternalIODenyGuard


class FakeChannel:
    def __init__(self, channel_id: str, sent: list[tuple[str, str, str]]) -> None:
        self.channel_id = channel_id
        self.sent = sent

    async def send(self, recipient: str, text: str) -> bool:
        self.sent.append((self.channel_id, recipient, text))
        return True

    async def mark_read(self, *_args) -> None:
        return None

    async def send_typing(self, *_args) -> None:
        return None


class FakeRegistry:
    def __init__(self) -> None:
        self.requested: list[str] = []
        self.sent: list[tuple[str, str, str]] = []
        self.channels = {
            name: FakeChannel(name, self.sent) for name in ("telegram", "whatsapp")
        }

    def get(self, channel_id: str):
        self.requested.append(channel_id)
        return self.channels.get(channel_id)


class FakeRouter:
    def __init__(self) -> None:
        self.reply_calls = 0
        self.continuation_calls = 0

    async def call_with_metadata(self, *_args, **_kwargs):
        self.reply_calls += 1
        return SimpleNamespace(
            text=(
                "I hear you—let’s keep this project update warm, easy to scan, and "
                "focused on the decisions that matter most to the team 🙂"
            ),
            model="fake-test-model",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        )

    async def call(self, *_args, **_kwargs) -> str:
        self.continuation_calls += 1
        return "I’ll keep the next step clear."


class FakeSBS:
    def __init__(self) -> None:
        self.profile_mgr = SimpleNamespace(load_layer=lambda _name: {})

    def on_message(self, *_args, **_kwargs):
        return {"msg_id": "fake-sbs-message"}

    def get_system_prompt(self, base, _proactive):
        return base


def test_long_emoji_reply_uses_only_one_channel_outbox_send() -> None:
    """A complete long reply ending in emoji must not trigger a second direct send."""
    import sci_fi_dashboard.chat_pipeline as chat_pipeline
    from sci_fi_dashboard import _deps as deps

    data_root = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "long-reply" / uuid4().hex
    data_root.mkdir(parents=True)
    router = FakeRouter()
    registry = FakeRegistry()

    monkeypatch_values = {
        "pending_consents": {},
        "consent_protocol": None,
        "memory_engine": SimpleNamespace(query=lambda *_a, **_k: {"results": []}),
        "personal_memory_service": SimpleNamespace(
            recall=lambda *_a, **_k: asyncio.sleep(0, result=[]), store=None
        ),
        "toxic_scorer": SimpleNamespace(score=lambda _text: 0.0),
        "dual_cognition": SimpleNamespace(
            trajectory=None, build_cognitive_context=lambda *_a, **_k: ""
        ),
        "get_sbs_for_target": lambda *_a, **_k: FakeSBS(),
        "_proactive_engine": None,
        "tool_registry": None,
        "synapse_llm_router": router,
        "channel_registry": registry,
        "_synapse_cfg": SimpleNamespace(
            session={"dual_cognition_enabled": False},
            model_mappings={},
            image_gen={},
            db_dir=data_root,
            raw={},
        ),
    }
    old_values = {name: getattr(deps, name, None) for name in monkeypatch_values}
    old_prefix = chat_pipeline._load_agent_workspace_prefix_for_session
    old_recent = chat_pipeline._fetch_recent_session_recall_context
    chat_pipeline._load_agent_workspace_prefix_for_session = lambda *_a, **_k: "CANONICAL BASE"
    chat_pipeline._fetch_recent_session_recall_context = lambda *_a, **_k: ""
    for name, value in monkeypatch_values.items():
        setattr(deps, name, value)

    queue = TaskQueue()
    retry = RetryQueue(data_root)
    io_guard = ExternalIODenyGuard(data_root / "outbound-attempts.json")

    async def process(message: str, chat_id: str, **_kwargs) -> str:
        request = ChatRequest(
            message=message,
            user_id=chat_id,
            session_type="spicy",
            session_key=f"telegram:{chat_id}",
            history=[],
        )
        result = await chat_pipeline.persona_chat(request, "the_creator")
        return result["reply"]

    worker = MessageWorker(
        queue,
        process,
        channel_registry=registry,
        retry_queue=retry,
        num_workers=1,
    )

    async def scenario() -> None:
        await retry.start(registry)
        await worker.start()
        io_guard.install()
        try:
            await queue.enqueue(
                MessageTask(
                    task_id="long-telegram-reply",
                    chat_id="telegram:alice",
                    user_message="Give me a short project update.",
                    message_id="long-telegram-reply",
                    channel_id="telegram",
                )
            )
            deadline = asyncio.get_running_loop().time() + 1.5
            while asyncio.get_running_loop().time() < deadline:
                with sqlite3.connect(retry._db_path) as conn:
                    rows = conn.execute(
                        "SELECT status,text FROM retry_queue WHERE message_key=?",
                        ("reply:long-telegram-reply:0",),
                    ).fetchall()
                if rows and rows[0][0] == "accepted":
                    break
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)
            assert rows == [("accepted", router_text)]
            assert registry.sent == [("telegram", "telegram:alice", router_text)]
            assert registry.requested
            assert set(registry.requested) == {"telegram"}
            assert router.reply_calls == 1
            assert router.continuation_calls == 0
            with sqlite3.connect(retry._db_path) as conn:
                assert conn.execute("SELECT COUNT(*) FROM retry_queue").fetchone()[0] == 1
        finally:
            io_guard.restore()
            await worker.stop()
            await retry.stop()

    router_text = (
        "I hear you—let’s keep this project update warm, easy to scan, and "
        "focused on the decisions that matter most to the team 🙂"
    )
    try:
        asyncio.run(scenario())
        assert io_guard.attempts == []
    finally:
        chat_pipeline._load_agent_workspace_prefix_for_session = old_prefix
        chat_pipeline._fetch_recent_session_recall_context = old_recent
        for name, value in old_values.items():
            setattr(deps, name, value)


def test_external_io_guard_blocks_network_and_child_process() -> None:
    guard = ExternalIODenyGuard()
    guard.install()
    try:
        left, right = socket.socketpair()
        left.close()
        right.close()
        sock = socket.socket()
        try:
            with pytest.raises(ExternalIOBlockedError, match="socket.connect"):
                sock.connect(("127.0.0.1", 5010))
            with pytest.raises(ExternalIOBlockedError, match="socket.connect_ex"):
                sock.connect_ex(("127.0.0.1", 5010))
        finally:
            sock.close()
        with pytest.raises(ExternalIOBlockedError, match="socket.create_connection"):
            socket.create_connection(("127.0.0.1", 5010), timeout=0.01)
        with pytest.raises(ExternalIOBlockedError, match="subprocess.Popen"):
            subprocess.Popen([sys.executable, "-c", "pass"])
    finally:
        guard.restore()
    assert [entry["kind"] for entry in guard.attempts] == [
        "socket.connect",
        "socket.connect_ex",
        "socket.create_connection",
        "subprocess.Popen",
    ]


def test_external_io_guard_blocks_httpx_async_connect_and_async_subprocess() -> None:
    import httpx

    guard = ExternalIODenyGuard()

    async def scenario() -> None:
        guard.install()
        try:
            async with httpx.AsyncClient(timeout=0.2) as client:
                with pytest.raises(
                    ExternalIOBlockedError,
                    match="httpx.AsyncHTTPTransport.handle_async_request",
                ):
                    await client.get("http://127.0.0.1:5010/send")
            with pytest.raises(ExternalIOBlockedError):
                await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        finally:
            guard.restore()

    asyncio.run(scenario())
    kinds = {attempt["kind"] for attempt in guard.attempts}
    assert "httpx.AsyncHTTPTransport.handle_async_request" in kinds
    assert "asyncio.create_subprocess_exec" in kinds
