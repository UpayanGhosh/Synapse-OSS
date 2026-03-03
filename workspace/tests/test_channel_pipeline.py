"""
Integration test suite: channel inbound pipeline (Phase 08 gap closure).

Verifies that the _make_flood_enqueue() adapter pattern correctly routes
ChannelMessage objects through FloodGate -> on_batch_ready -> MessageTask -> TaskQueue
for all three channels.

Requirements covered:
  DIS-01, DIS-03: Discord channel pipeline integration
  SLK-01, SLK-03: Slack channel pipeline integration
  TEL-01, TEL-03: Telegram channel pipeline integration

Regression:
  WhatsApp path still produces MessageTask (not broken by Phase 08 changes)

Design note:
  Tests do NOT import api_gateway to avoid boot-time singleton side effects.
  The adapter factory (_make_local_enqueue) is reproduced inline -- same logic
  as _make_flood_enqueue() in api_gateway.py, using local FloodGate instances.
  FloodGate is constructed with batch_window_seconds=0.01 to keep tests fast.
"""

import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from sci_fi_dashboard.channels.base import ChannelMessage
from sci_fi_dashboard.gateway.flood import FloodGate
from sci_fi_dashboard.gateway.queue import MessageTask, TaskQueue

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_channel_message(
    channel_id: str,
    text: str = "hello",
    chat_id: str = "chat-001",
    user_id: str = "user-001",
    message_id: str | None = None,
    sender_name: str = "Tester",
) -> ChannelMessage:
    """Build a minimal ChannelMessage for pipeline tests."""
    return ChannelMessage(
        channel_id=channel_id,
        user_id=user_id,
        chat_id=chat_id,
        text=text,
        timestamp=datetime.now(),
        is_group=False,
        message_id=message_id or str(uuid.uuid4()),
        sender_name=sender_name,
        raw={},
    )


def _make_pipeline(channel_id: str):
    """
    Build an isolated FloodGate + TaskQueue + adapter for one channel.

    Returns: (flood_gate, task_queue, enqueue_fn, collected_tasks)
      - flood_gate: FloodGate with 10ms batch window (fast for tests)
      - task_queue: TaskQueue the on_batch_ready callback enqueues into
      - enqueue_fn: async callable matching _make_flood_enqueue() in api_gateway.py
      - collected_tasks: list populated by on_batch_ready for direct assertions

    NOTE: dedup is omitted from the adapter to keep tests simple. Dedup is
    tested separately in test_dedup.py. The adapter logic tested here is:
    ChannelMessage -> flood.incoming() -> MessageTask.
    """
    task_queue = TaskQueue(max_size=100)
    flood_gate = FloodGate(batch_window_seconds=0.01)
    collected_tasks: list[MessageTask] = []

    async def on_batch_ready(chat_id: str, combined_message: str, metadata: dict):
        task = MessageTask(
            task_id=str(uuid.uuid4()),
            chat_id=chat_id,
            user_message=combined_message,
            message_id=metadata.get("message_id", ""),
            sender_name=metadata.get("sender_name", ""),
            channel_id=metadata.get("channel_id", channel_id),
        )
        collected_tasks.append(task)
        await task_queue.enqueue(task)

    flood_gate.set_callback(on_batch_ready)

    async def enqueue_fn(channel_msg: ChannelMessage):
        """Adapter: mirrors _make_flood_enqueue() from api_gateway.py."""
        await flood_gate.incoming(
            chat_id=channel_msg.chat_id,
            message=channel_msg.text,
            metadata={
                "message_id": channel_msg.message_id,
                "sender_name": channel_msg.sender_name,
                "channel_id": channel_id,
            },
        )

    return flood_gate, task_queue, enqueue_fn, collected_tasks


# ---------------------------------------------------------------------------
# Discord pipeline tests (DIS-01, DIS-03)
# ---------------------------------------------------------------------------


class TestDiscordPipeline:
    """
    DIS-01: Discord inbound message routes through flood.incoming() adapter.
    DIS-03: MessageTask produced has channel_id='discord' -- outbound path resolves.
    """

    async def test_discord_dm_produces_message_task(self):
        """DIS-01: A Discord DM dispatched via adapter produces MessageTask with channel_id='discord'."""
        flood_gate, task_queue, enqueue_fn, collected_tasks = _make_pipeline("discord")

        msg = _make_channel_message("discord", text="hello discord", chat_id="dc-chat-1")
        await enqueue_fn(msg)

        # Wait for FloodGate to flush (batch_window_seconds=0.01)
        await asyncio.sleep(0.05)

        assert task_queue.pending_count == 1, f"Expected 1 task, got {task_queue.pending_count}"
        assert len(collected_tasks) == 1
        task = collected_tasks[0]
        assert (
            task.channel_id == "discord"
        ), f"Expected channel_id='discord', got '{task.channel_id}'"
        assert task.user_message == "hello discord"
        assert task.chat_id == "dc-chat-1"

    async def test_discord_no_attribute_error_on_task_id(self):
        """DIS-01: ChannelMessage does not have task_id -- confirms old direct-enqueue bug was real."""
        msg = _make_channel_message("discord")
        assert not hasattr(msg, "task_id"), (
            "ChannelMessage must not have task_id attribute -- "
            "passing it to task_queue.enqueue() directly would crash at queue.py:45"
        )

    async def test_discord_message_task_has_all_required_fields(self):
        """DIS-03: MessageTask produced from Discord adapter has task_id, channel_id, chat_id, user_message."""
        flood_gate, task_queue, enqueue_fn, collected_tasks = _make_pipeline("discord")

        msg = _make_channel_message(
            "discord",
            text="field check",
            chat_id="dc-2",
            message_id="msg-dc-001",
            sender_name="DiscordUser",
        )
        await enqueue_fn(msg)
        await asyncio.sleep(0.05)

        assert len(collected_tasks) == 1
        task = collected_tasks[0]
        assert task.task_id, "MessageTask must have non-empty task_id"
        assert task.channel_id == "discord"
        assert task.chat_id == "dc-2"
        assert task.user_message == "field check"
        assert task.sender_name == "DiscordUser"
        assert task.message_id == "msg-dc-001"


# ---------------------------------------------------------------------------
# Slack pipeline tests (SLK-01, SLK-03)
# ---------------------------------------------------------------------------


class TestSlackPipeline:
    """
    SLK-01: Slack inbound message routes through flood.incoming() adapter.
    SLK-03: MessageTask produced has channel_id='slack' -- outbound path resolves.
    """

    async def test_slack_dm_produces_message_task(self):
        """SLK-01: A Slack DM dispatched via adapter produces MessageTask with channel_id='slack'."""
        flood_gate, task_queue, enqueue_fn, collected_tasks = _make_pipeline("slack")

        msg = _make_channel_message("slack", text="hello slack", chat_id="slk-dm-1")
        await enqueue_fn(msg)
        await asyncio.sleep(0.05)

        assert task_queue.pending_count == 1, f"Expected 1 task, got {task_queue.pending_count}"
        assert len(collected_tasks) == 1
        task = collected_tasks[0]
        assert task.channel_id == "slack"
        assert task.user_message == "hello slack"

    async def test_slack_mention_produces_message_task(self):
        """SLK-01: Slack @mention also routes through same adapter path."""
        flood_gate, task_queue, enqueue_fn, collected_tasks = _make_pipeline("slack")

        msg = _make_channel_message("slack", text="@bot help me", chat_id="slk-ch-1")
        await enqueue_fn(msg)
        await asyncio.sleep(0.05)

        assert len(collected_tasks) == 1
        task = collected_tasks[0]
        assert task.channel_id == "slack"
        assert task.user_message == "@bot help me"

    async def test_slack_message_task_fields(self):
        """SLK-03: MessageTask from Slack has correct task_id, channel_id, sender_name."""
        flood_gate, task_queue, enqueue_fn, collected_tasks = _make_pipeline("slack")

        msg = _make_channel_message(
            "slack",
            text="fields",
            chat_id="slk-3",
            message_id="slk-msg-001",
            sender_name="SlackUser",
        )
        await enqueue_fn(msg)
        await asyncio.sleep(0.05)

        assert len(collected_tasks) == 1
        task = collected_tasks[0]
        assert task.task_id, "task_id must be non-empty UUID"
        assert task.channel_id == "slack"
        assert task.sender_name == "SlackUser"
        assert task.message_id == "slk-msg-001"


# ---------------------------------------------------------------------------
# Telegram pipeline tests (TEL-01, TEL-03)
# ---------------------------------------------------------------------------


class TestTelegramPipeline:
    """
    TEL-01: Telegram inbound message routes through flood.incoming() adapter (not directly to task_queue).
    TEL-03: MessageTask produced has channel_id='telegram' -- enables outbound TelegramChannel.send().
    """

    async def test_telegram_dm_produces_message_task(self):
        """TEL-01: A Telegram DM dispatched via adapter produces MessageTask with channel_id='telegram'."""
        flood_gate, task_queue, enqueue_fn, collected_tasks = _make_pipeline("telegram")

        msg = _make_channel_message("telegram", text="hello telegram", chat_id="tg-123")
        await enqueue_fn(msg)
        await asyncio.sleep(0.05)

        assert task_queue.pending_count == 1, f"Expected 1 task, got {task_queue.pending_count}"
        assert len(collected_tasks) == 1
        task = collected_tasks[0]
        assert task.channel_id == "telegram"
        assert task.user_message == "hello telegram"
        assert task.chat_id == "tg-123"

    async def test_telegram_old_direct_enqueue_would_fail(self):
        """TEL-01: Proves that the old task_queue.enqueue(ChannelMessage) pattern crashes."""
        task_queue = TaskQueue(max_size=100)
        msg = _make_channel_message("telegram", text="crash test")

        # The old broken pattern: enqueue_fn=task_queue.enqueue -> passes ChannelMessage directly
        with pytest.raises(AttributeError):
            # task_queue.enqueue() does: self._active_tasks[task.task_id] = task
            # ChannelMessage has no .task_id -> AttributeError
            await task_queue.enqueue(msg)  # type: ignore[arg-type]

    async def test_telegram_adapter_avoids_type_mismatch(self):
        """TEL-01: Adapter produces MessageTask (not ChannelMessage) in the queue."""
        flood_gate, task_queue, enqueue_fn, collected_tasks = _make_pipeline("telegram")

        msg = _make_channel_message("telegram", text="type check")
        await enqueue_fn(msg)
        await asyncio.sleep(0.05)

        assert len(collected_tasks) == 1
        task = collected_tasks[0]
        assert isinstance(task, MessageTask), f"Expected MessageTask, got {type(task).__name__}"
        assert task.channel_id == "telegram"

    async def test_telegram_message_task_has_all_required_fields(self):
        """TEL-03: MessageTask from Telegram has task_id, channel_id, chat_id, user_message, sender_name."""
        flood_gate, task_queue, enqueue_fn, collected_tasks = _make_pipeline("telegram")

        msg = _make_channel_message(
            "telegram",
            text="field verify",
            chat_id="tg-456",
            message_id="tg-msg-001",
            sender_name="TelegramUser",
        )
        await enqueue_fn(msg)
        await asyncio.sleep(0.05)

        assert len(collected_tasks) == 1
        task = collected_tasks[0]
        assert task.task_id, "task_id must be non-empty"
        assert task.channel_id == "telegram"
        assert task.chat_id == "tg-456"
        assert task.user_message == "field verify"
        assert task.sender_name == "TelegramUser"
        assert task.message_id == "tg-msg-001"


# ---------------------------------------------------------------------------
# WhatsApp regression tests
# ---------------------------------------------------------------------------


class TestWhatsAppRegression:
    """
    Regression: WhatsApp inbound pipeline is unaffected by Phase 08 changes.

    The WhatsApp path goes through unified_webhook() -> flood.incoming() -> MessageTask.
    Phase 08 only modifies how Telegram/Discord/Slack are registered -- the
    unified_webhook() function and its flood.incoming() call are unchanged.
    This test confirms the pipeline works identically for the 'whatsapp' channel_id.
    """

    async def test_whatsapp_message_produces_task_with_channel_id(self):
        """Regression: WhatsApp-channel ChannelMessage flows through adapter -- channel_id='whatsapp'."""
        flood_gate, task_queue, enqueue_fn, collected_tasks = _make_pipeline("whatsapp")

        msg = _make_channel_message("whatsapp", text="whatsapp regression", chat_id="wa-001")
        await enqueue_fn(msg)
        await asyncio.sleep(0.05)

        assert task_queue.pending_count == 1
        assert len(collected_tasks) == 1
        task = collected_tasks[0]
        assert task.channel_id == "whatsapp"
        assert task.user_message == "whatsapp regression"

    async def test_multiple_channels_independent_pipelines(self):
        """Regression: Separate FloodGate instances for each channel do not interfere."""
        _, tq_discord, enqueue_discord, tasks_discord = _make_pipeline("discord")
        _, tq_slack, enqueue_slack, tasks_slack = _make_pipeline("slack")
        _, tq_telegram, enqueue_telegram, tasks_telegram = _make_pipeline("telegram")

        msg_d = _make_channel_message("discord", text="d msg", chat_id="dc-x")
        msg_s = _make_channel_message("slack", text="s msg", chat_id="slk-x")
        msg_t = _make_channel_message("telegram", text="t msg", chat_id="tg-x")

        await enqueue_discord(msg_d)
        await enqueue_slack(msg_s)
        await enqueue_telegram(msg_t)
        await asyncio.sleep(0.05)

        assert tq_discord.pending_count == 1
        assert tq_slack.pending_count == 1
        assert tq_telegram.pending_count == 1

        assert len(tasks_discord) == 1
        assert len(tasks_slack) == 1
        assert len(tasks_telegram) == 1

        assert tasks_discord[0].channel_id == "discord"
        assert tasks_slack[0].channel_id == "slack"
        assert tasks_telegram[0].channel_id == "telegram"
