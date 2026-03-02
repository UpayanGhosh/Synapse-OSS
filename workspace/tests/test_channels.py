"""
Tests for Phase 3 Channel Abstraction Layer (CHAN-01 through CHAN-07).

RED phase state:
  CHAN-01/02/03/06: GREEN after 03-01 ships (channels/ subpackage).
  CHAN-04/05:       xfail until 03-03 adds POST /channels/{channel_id}/webhook + /whatsapp/enqueue shim.
  CHAN-07:          xfail until 03-04 generalizes worker.py dispatch.

Import guard:
  Until 03-01 ships sci_fi_dashboard/channels/, CHANNELS_AVAILABLE=False and
  TestBaseChannel/TestChannelRegistry/TestStubChannelBehavior tests are skipped.
  This mirrors the pattern from test_llm_router.py — single guard, clean RED state,
  one-line removal when the package ships.
"""

import asyncio
import sys
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional import: RED phase guard for channels/ subpackage
#
# Until Plan 03-01 creates sci_fi_dashboard/channels/, CHANNELS_AVAILABLE=False
# and channel-specific tests are skipped. That is the correct RED state.
# ---------------------------------------------------------------------------
try:
    from sci_fi_dashboard.channels import BaseChannel, ChannelMessage, ChannelRegistry, StubChannel

    CHANNELS_AVAILABLE = True
except ImportError:
    CHANNELS_AVAILABLE = False

_channels_skip = pytest.mark.skipif(
    not CHANNELS_AVAILABLE,
    reason="channels/ subpackage not yet implemented — RED phase (Plan 03-01 will create it)",
)


class TestBaseChannel:
    """CHAN-01: BaseChannel ABC enforcement + CHAN-03: ChannelMessage dataclass."""

    @_channels_skip
    def test_base_channel_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseChannel()

    @_channels_skip
    def test_incomplete_subclass_cannot_be_instantiated(self):
        class PartialChannel(BaseChannel):
            @property
            def channel_id(self) -> str:
                return "partial"
            # Missing: receive, send, send_typing, mark_read, health_check

        with pytest.raises(TypeError):
            PartialChannel()

    @_channels_skip
    def test_complete_subclass_instantiates(self):
        stub = StubChannel("test")
        assert stub.channel_id == "test"

    @_channels_skip
    def test_channel_message_defaults(self):
        msg = ChannelMessage(channel_id="stub", user_id="u", chat_id="c", text="hi")
        assert msg.is_group is False
        assert msg.message_id == ""
        assert msg.raw == {}
        assert msg.timestamp is not None

    @_channels_skip
    def test_channel_message_no_shared_mutable_default(self):
        msg1 = ChannelMessage(channel_id="a", user_id="u", chat_id="c", text="t")
        msg2 = ChannelMessage(channel_id="b", user_id="u", chat_id="c", text="t")
        msg1.raw["key"] = "val"
        assert "key" not in msg2.raw, "Shared mutable default bug in ChannelMessage.raw"


class TestChannelRegistry:
    """CHAN-02: ChannelRegistry lifecycle. CHAN-06: asyncio task pattern."""

    @_channels_skip
    async def test_register_and_get(self):
        reg = ChannelRegistry()
        stub = StubChannel("wa")
        reg.register(stub)
        assert reg.get("wa") is stub
        assert reg.get("missing") is None

    @_channels_skip
    def test_duplicate_register_raises(self):
        reg = ChannelRegistry()
        stub = StubChannel("wa")
        reg.register(stub)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(StubChannel("wa"))

    @_channels_skip
    async def test_list_ids(self):
        reg = ChannelRegistry()
        reg.register(StubChannel("wa"))
        reg.register(StubChannel("tg"))
        assert sorted(reg.list_ids()) == ["tg", "wa"]

    @_channels_skip
    async def test_start_all_marks_channels_started(self):
        """CHAN-06: asyncio.create_task() pattern — no RuntimeError."""
        reg = ChannelRegistry()
        s1 = StubChannel("s1")
        s2 = StubChannel("s2")
        reg.register(s1)
        reg.register(s2)
        await reg.start_all()
        # Give tasks a moment to run
        await asyncio.sleep(0)
        assert s1._started is True
        assert s2._started is True
        await reg.stop_all()

    @_channels_skip
    async def test_stop_all_marks_channels_stopped(self):
        reg = ChannelRegistry()
        stub = StubChannel("wa")
        reg.register(stub)
        await reg.start_all()
        await asyncio.sleep(0)
        await reg.stop_all()
        assert stub._started is False

    @_channels_skip
    async def test_two_stubs_start_without_event_loop_error(self):
        """CHAN-06: Critical — no RuntimeError: This event loop is already running."""
        reg = ChannelRegistry()
        reg.register(StubChannel("ch1"))
        reg.register(StubChannel("ch2"))
        # If asyncio.run() were used internally, this would raise RuntimeError here.
        await reg.start_all()
        await asyncio.sleep(0)
        await reg.stop_all()


class TestStubChannelBehavior:
    """CHAN-03: ChannelMessage normalization via StubChannel.receive()."""

    @_channels_skip
    async def test_receive_maps_raw_payload(self):
        stub = StubChannel("stub")
        msg = await stub.receive(
            {
                "user_id": "u123",
                "chat_id": "c456",
                "text": "hello",
                "message_id": "m789",
                "sender_name": "Alice",
            }
        )
        assert msg.channel_id == "stub"
        assert msg.user_id == "u123"
        assert msg.chat_id == "c456"
        assert msg.text == "hello"
        assert msg.message_id == "m789"
        assert msg.sender_name == "Alice"

    @_channels_skip
    async def test_receive_defaults_missing_fields(self):
        stub = StubChannel("stub")
        msg = await stub.receive({"text": "hi"})
        assert msg.user_id == "stub_user"
        assert msg.chat_id == "stub_chat"

    @_channels_skip
    async def test_send_records_message(self):
        stub = StubChannel("stub")
        result = await stub.send("chat_1", "hello world")
        assert result is True
        assert stub.sent_messages == [("chat_1", "hello world")]

    @_channels_skip
    async def test_health_check_returns_ok(self):
        stub = StubChannel("stub")
        health = await stub.health_check()
        assert health["status"] == "ok"
        assert health["channel"] == "stub"


class TestUnifiedWebhook:
    """CHAN-04: POST /channels/{channel_id}/webhook. CHAN-05: /whatsapp/enqueue shim."""

    @pytest.mark.xfail(strict=False, reason="Routes added in plan 03-03")
    async def test_unified_webhook_returns_queued(self):
        import httpx
        from sci_fi_dashboard.api_gateway import app

        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.post(
                "/channels/stub/webhook",
                json={
                    "text": "hello",
                    "user_id": "u1",
                    "chat_id": "c1",
                    "message_id": "m001",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True
        assert data["status"] == "queued"

    @pytest.mark.xfail(strict=False, reason="Routes added in plan 03-03")
    async def test_unified_webhook_unknown_channel_404(self):
        import httpx
        from sci_fi_dashboard.api_gateway import app

        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.post("/channels/nonexistent/webhook", json={"text": "hi"})
        assert resp.status_code == 404

    @pytest.mark.xfail(strict=False, reason="Routes added in plan 03-03")
    async def test_unified_webhook_invalid_json_400(self):
        import httpx
        from sci_fi_dashboard.api_gateway import app

        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.post(
                "/channels/stub/webhook",
                content=b"not-json",
                headers={"content-type": "application/json"},
            )
        assert resp.status_code == 400

    @pytest.mark.xfail(strict=False, reason="Shim added in plan 03-03")
    async def test_whatsapp_enqueue_shim_delegates(self):
        """CHAN-05: /whatsapp/enqueue shim delegates to unified handler."""
        import httpx
        from sci_fi_dashboard.api_gateway import app

        async with httpx.AsyncClient(app=app, base_url="http://test") as client:
            resp = await client.post(
                "/whatsapp/enqueue",
                json={
                    "text": "hello",
                    "user_id": "u1",
                    "chat_id": "c1",
                    "message_id": "shim001",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["accepted"] is True


class TestMessageTaskChannelId:
    """CHAN-07: MessageTask has channel_id; worker dispatches via registry."""

    @pytest.mark.xfail(strict=False, reason="channel_id added to MessageTask in 03-03")
    def test_message_task_has_channel_id_field(self):
        """CHAN-07: MessageTask must carry channel_id for registry dispatch."""
        from sci_fi_dashboard.gateway.queue import MessageTask

        task = MessageTask(task_id="t1", chat_id="c1", user_message="hi")
        assert hasattr(task, "channel_id"), "MessageTask missing channel_id field (added in 03-03)"
        assert task.channel_id == "whatsapp", "channel_id default should be 'whatsapp'"

    @pytest.mark.xfail(strict=False, reason="worker.py generalized in plan 03-04")
    async def test_worker_dispatches_via_registry_not_sender(self):
        """CHAN-07: MessageWorker uses ChannelRegistry.get(task.channel_id).send()."""
        from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue
        from sci_fi_dashboard.gateway.worker import MessageWorker

        if not CHANNELS_AVAILABLE:
            pytest.skip("channels/ not yet available — skipping until 03-01 ships")

        reg = ChannelRegistry()
        stub = StubChannel("whatsapp")
        reg.register(stub)

        async def mock_process(msg, chat_id):
            return "processed response"

        worker = MessageWorker(
            queue=TaskQueue(),
            channel_registry=reg,
            process_fn=mock_process,
            num_workers=1,
        )

        task = MessageTask(
            task_id="t1",
            chat_id="chat_wa",
            user_message="test",
            channel_id="whatsapp",
        )
        await worker._handle_task(task, worker_id=0)
        assert len(stub.sent_messages) == 1
        assert stub.sent_messages[0] == ("chat_wa", "processed response")
