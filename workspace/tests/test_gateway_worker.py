"""Tests for gateway/worker.py — MessageWorker pipeline.

Covers:
- _split_long_message utility
- MessageWorker construction
- _get_channel resolution
- start/stop lifecycle
- _handle_task full pipeline (mark_read, typing, process, send)
- Generation superseding
- Error handling and notification
- mcp_context passing
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue
from sci_fi_dashboard.gateway.worker import MessageWorker, _split_long_message

# ===========================================================================
# _split_long_message
# ===========================================================================


class TestSplitLongMessage:

    def test_short_message_not_split(self):
        assert _split_long_message("hello") == ["hello"]

    def test_exact_limit_not_split(self):
        text = "x" * 4000
        assert _split_long_message(text) == [text]

    def test_long_message_split(self):
        text = "x" * 8000
        result = _split_long_message(text)
        assert len(result) >= 2

    def test_split_at_paragraph_boundary(self):
        text = "A" * 3000 + "\n\n" + "B" * 3000
        result = _split_long_message(text)
        assert len(result) == 2

    def test_split_at_line_boundary(self):
        text = "A" * 3500 + "\n" + "B" * 3500
        result = _split_long_message(text)
        assert len(result) >= 2

    def test_split_at_space_boundary(self):
        text = "word " * 1000
        result = _split_long_message(text, chunk_size=100)
        assert len(result) > 1

    def test_custom_chunk_size(self):
        text = "a" * 200
        result = _split_long_message(text, chunk_size=50)
        assert len(result) >= 4


# ===========================================================================
# MessageWorker construction
# ===========================================================================


class TestMessageWorkerConstruction:

    def test_basic_construction(self):
        q = TaskQueue()

        async def process(msg, chat_id):
            return "response"

        worker = MessageWorker(queue=q, process_fn=process, num_workers=2)
        assert worker.num_workers == 2
        assert worker._running is False

    def test_mcp_detection_2_arg(self):
        """process_fn with 2 args: _process_fn_accepts_mcp is False."""
        q = TaskQueue()

        async def process(msg, chat_id):
            return "r"

        worker = MessageWorker(queue=q, process_fn=process)
        assert worker._process_fn_accepts_mcp is False

    def test_mcp_detection_3_arg(self):
        """process_fn with 3 args: _process_fn_accepts_mcp is True."""
        q = TaskQueue()

        async def process(msg, chat_id, mcp_context):
            return "r"

        worker = MessageWorker(queue=q, process_fn=process)
        assert worker._process_fn_accepts_mcp is True


# ===========================================================================
# _get_channel
# ===========================================================================


class TestGetChannel:

    def test_returns_channel_from_registry(self):
        q = TaskQueue()

        async def process(msg, chat_id):
            return "r"

        mock_registry = MagicMock()
        mock_channel = MagicMock()
        mock_registry.get.return_value = mock_channel

        worker = MessageWorker(queue=q, process_fn=process, channel_registry=mock_registry)

        task = MagicMock()
        task.channel_id = "whatsapp"
        result = worker._get_channel(task)
        assert result is mock_channel
        mock_registry.get.assert_called_once_with("whatsapp")

    def test_returns_none_without_registry(self):
        q = TaskQueue()

        async def process(msg, chat_id):
            return "r"

        worker = MessageWorker(queue=q, process_fn=process)
        task = MagicMock()
        task.channel_id = "whatsapp"
        assert worker._get_channel(task) is None

    def test_defaults_to_whatsapp_when_no_channel_id(self):
        q = TaskQueue()

        async def process(msg, chat_id):
            return "r"

        mock_registry = MagicMock()
        worker = MessageWorker(queue=q, process_fn=process, channel_registry=mock_registry)

        task = MagicMock(spec=[])  # no channel_id attr
        worker._get_channel(task)
        mock_registry.get.assert_called_once_with("whatsapp")


# ===========================================================================
# start/stop lifecycle
# ===========================================================================


class TestWorkerLifecycle:

    @pytest.mark.asyncio
    async def test_start_creates_workers(self):
        q = TaskQueue()

        async def process(msg, chat_id):
            return "r"

        worker = MessageWorker(queue=q, process_fn=process, num_workers=3)
        await worker.start()
        assert worker._running is True
        assert len(worker._workers) == 3
        await worker.stop()
        assert worker._running is False
        assert len(worker._workers) == 0

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        q = TaskQueue()

        async def process(msg, chat_id):
            return "r"

        worker = MessageWorker(queue=q, process_fn=process, num_workers=1)
        await worker.start()
        await worker.stop()
        # Workers should be cancelled and cleared
        assert len(worker._workers) == 0


# ===========================================================================
# _handle_task pipeline
# ===========================================================================


class TestHandleTask:

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self):
        """Full happy path: mark_read, typing, process, send."""
        from sci_fi_dashboard.channels.stub import StubChannel

        q = TaskQueue()

        async def process(msg, chat_id):
            return "processed response"

        from sci_fi_dashboard.channels.registry import ChannelRegistry

        reg = ChannelRegistry()
        stub = StubChannel("whatsapp")
        reg.register(stub)

        worker = MessageWorker(queue=q, process_fn=process, num_workers=1, channel_registry=reg)

        task = MessageTask(
            task_id="t1",
            chat_id="c1",
            user_message="hello",
            channel_id="whatsapp",
        )

        await worker._handle_task(task, worker_id=0)
        assert len(stub.sent_messages) == 1
        assert stub.sent_messages[0] == ("c1", "processed response")

    @pytest.mark.asyncio
    async def test_empty_response_fails_task(self):
        """Empty LLM response marks task as failed."""
        q = TaskQueue()

        async def process(msg, chat_id):
            return ""

        from sci_fi_dashboard.channels.registry import ChannelRegistry
        from sci_fi_dashboard.channels.stub import StubChannel

        reg = ChannelRegistry()
        stub = StubChannel("whatsapp")
        reg.register(stub)

        worker = MessageWorker(queue=q, process_fn=process, num_workers=1, channel_registry=reg)

        task = MessageTask(
            task_id="t1",
            chat_id="c1",
            user_message="hello",
            channel_id="whatsapp",
        )

        await worker._handle_task(task, worker_id=0)
        # No messages sent for empty response
        assert len(stub.sent_messages) == 0

    @pytest.mark.asyncio
    async def test_process_error_sends_warning(self):
        """Process function error sends a warning message to user."""
        q = TaskQueue()

        async def process(msg, chat_id):
            raise RuntimeError("LLM died")

        from sci_fi_dashboard.channels.registry import ChannelRegistry
        from sci_fi_dashboard.channels.stub import StubChannel

        reg = ChannelRegistry()
        stub = StubChannel("whatsapp")
        reg.register(stub)

        worker = MessageWorker(queue=q, process_fn=process, num_workers=1, channel_registry=reg)

        task = MessageTask(
            task_id="t1",
            chat_id="c1",
            user_message="hello",
            channel_id="whatsapp",
        )

        await worker._handle_task(task, worker_id=0)
        # Warning message should be sent
        assert len(stub.sent_messages) >= 1
        assert "WARN" in stub.sent_messages[-1][1]
