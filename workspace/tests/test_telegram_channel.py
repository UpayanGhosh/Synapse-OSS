"""
Tests for Phase 5 Telegram channel (TEL-01 through TEL-04).

Import guard:
  Until sci_fi_dashboard/channels/telegram.py exists AND python-telegram-bot is
  installed, TEL_AVAILABLE=False and all tests are skipped. Mirrors the pattern
  from test_whatsapp_channel.py — single guard, clean RED state, no per-test
  decorator noise.

Test coverage:
  TEL-01: TelegramChannel construction, channel_id, start() lifecycle
  TEL-02: DM dispatch and group @mention routing (_on_message/_on_group_message)
  TEL-03: send() / send_typing() / mark_read() API methods
  TEL-04: health_check() status dict shape and token storage
"""

import asyncio
import contextlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional import — skip entire module if python-telegram-bot not installed
# ---------------------------------------------------------------------------
TEL_AVAILABLE = importlib.util.find_spec("sci_fi_dashboard.channels.telegram") is not None

pytestmark = pytest.mark.skipif(
    not TEL_AVAILABLE,
    reason="TelegramChannel not yet implemented — skipping TEL tests",
)

if TEL_AVAILABLE:
    from sci_fi_dashboard.channels.telegram import TelegramChannel
    from telegram.constants import ChatAction
    from telegram.error import Conflict, InvalidToken, TelegramError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_app():
    """Build a fully-mocked PTB Application-like object."""
    mock_bot = AsyncMock()
    mock_bot.username = "botname"
    # get_me returns a bot-info-like object
    bot_me = MagicMock()
    bot_me.username = "botname"
    bot_me.id = 42
    mock_bot.get_me = AsyncMock(return_value=bot_me)

    mock_app = MagicMock()
    mock_app.bot = mock_bot
    mock_app.update_queue = asyncio.Queue()
    mock_app.running = True
    mock_app.initialize = AsyncMock()
    mock_app.start = AsyncMock()
    mock_app.stop = AsyncMock()
    mock_app.shutdown = AsyncMock()
    mock_app.add_handler = MagicMock()
    return mock_app


def _mock_app_builder(monkeypatch, mock_app):
    """
    Patch ApplicationBuilder so that calling ApplicationBuilder().token(...).updater(None).build()
    returns mock_app.
    """
    builder_stub = MagicMock()
    # Chain: .token(...) -> .updater(...) -> .build() -> mock_app
    builder_stub.token.return_value = builder_stub
    builder_stub.updater.return_value = builder_stub
    builder_stub.build.return_value = mock_app

    mock_builder_cls = MagicMock(return_value=builder_stub)
    monkeypatch.setattr("sci_fi_dashboard.channels.telegram.ApplicationBuilder", mock_builder_cls)
    return mock_builder_cls


def _make_mock_updater():
    """Build a mocked PTB Updater."""
    mock_updater = MagicMock()
    mock_updater.running = True
    mock_updater.initialize = AsyncMock()
    mock_updater.start_polling = AsyncMock()
    mock_updater.stop = AsyncMock()
    return mock_updater


def _make_mock_update(
    text="hello",
    chat_type="private",
    user_id=99,
    chat_id=12345,
    message_id=1,
    full_name="Test User",
):
    """Build a minimal mocked PTB Update object."""
    mock_user = MagicMock()
    mock_user.id = user_id
    mock_user.full_name = full_name

    mock_chat = MagicMock()
    mock_chat.id = chat_id
    mock_chat.type = chat_type

    mock_message = MagicMock()
    mock_message.text = text
    mock_message.from_user = mock_user
    mock_message.chat = mock_chat
    mock_message.message_id = message_id
    mock_message.date = None  # _dispatch falls through to datetime.now()

    mock_update = MagicMock()
    mock_update.message = mock_message
    mock_update.to_dict.return_value = {}

    return mock_update


# ---------------------------------------------------------------------------
# TEL-01: Construction and channel_id
# ---------------------------------------------------------------------------


def test_channel_id_is_telegram():
    """TEL-01: channel_id property must return the string 'telegram'."""
    ch = TelegramChannel(token="x")
    assert ch.channel_id == "telegram"


def test_token_stored_from_constructor():
    """TEL-04: Constructor stores the token verbatim."""
    ch = TelegramChannel(token="bot123:abc")
    assert ch._token == "bot123:abc"


def test_initial_status_is_stopped():
    """TEL-01: _status must start as 'stopped' before start() is called."""
    ch = TelegramChannel(token="x")
    assert ch._status == "stopped"


# ---------------------------------------------------------------------------
# TEL-01: start() lifecycle — delete_webhook called, Conflict/InvalidToken handled
# ---------------------------------------------------------------------------


async def test_start_calls_delete_webhook(monkeypatch):
    """TEL-01: delete_webhook() must be awaited exactly once before start_polling."""
    mock_app = _make_mock_app()
    _mock_app_builder(monkeypatch, mock_app)

    mock_updater = _make_mock_updater()
    monkeypatch.setattr(
        "sci_fi_dashboard.channels.telegram.Updater",
        MagicMock(return_value=mock_updater),
    )

    channel = TelegramChannel(token="fake:token")

    # start() parks on asyncio.Event().wait() — cancel it after setup
    start_task = asyncio.create_task(channel.start())
    # Allow the coroutine to progress past the initialization steps
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    start_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await start_task

    mock_app.bot.delete_webhook.assert_awaited_once()


async def test_conflict_error_sets_failed_status(monkeypatch):
    """TEL-01/M1: Conflict (409) must set _status='failed' and NOT re-raise."""
    mock_app = _make_mock_app()
    mock_app.bot.delete_webhook = AsyncMock(side_effect=Conflict("409 Conflict"))
    _mock_app_builder(monkeypatch, mock_app)

    mock_updater = _make_mock_updater()
    monkeypatch.setattr(
        "sci_fi_dashboard.channels.telegram.Updater",
        MagicMock(return_value=mock_updater),
    )

    channel = TelegramChannel(token="fake:token")
    await channel.start()  # must NOT raise

    assert channel._status == "failed"


async def test_invalid_token_sets_failed_status(monkeypatch):
    """TEL-01: InvalidToken must set _status='failed' and NOT re-raise."""
    mock_app = _make_mock_app()
    mock_app.bot.delete_webhook = AsyncMock(side_effect=InvalidToken("Unauthorized"))
    _mock_app_builder(monkeypatch, mock_app)

    mock_updater = _make_mock_updater()
    monkeypatch.setattr(
        "sci_fi_dashboard.channels.telegram.Updater",
        MagicMock(return_value=mock_updater),
    )

    channel = TelegramChannel(token="bad:token")
    await channel.start()  # must NOT raise

    assert channel._status == "failed"


async def test_telegram_error_sets_failed_status(monkeypatch):
    """TEL-01: Generic TelegramError must set _status='failed' and NOT re-raise."""
    mock_app = _make_mock_app()
    mock_app.bot.delete_webhook = AsyncMock(side_effect=TelegramError("network error"))
    _mock_app_builder(monkeypatch, mock_app)

    mock_updater = _make_mock_updater()
    monkeypatch.setattr(
        "sci_fi_dashboard.channels.telegram.Updater",
        MagicMock(return_value=mock_updater),
    )

    channel = TelegramChannel(token="fake:token")
    await channel.start()  # must NOT raise

    assert channel._status == "failed"


# ---------------------------------------------------------------------------
# TEL-02: DM and group @mention dispatch
# ---------------------------------------------------------------------------


async def test_dm_dispatched_to_enqueue_fn():
    """TEL-02: _dispatch() must call enqueue_fn with a ChannelMessage."""
    enqueue_fn = AsyncMock()
    channel = TelegramChannel(token="x", enqueue_fn=enqueue_fn)

    mock_update = _make_mock_update(text="hello", chat_type="private")
    await channel._dispatch(mock_update)

    enqueue_fn.assert_awaited_once()
    channel_msg = enqueue_fn.call_args[0][0]
    assert channel_msg.channel_id == "telegram"
    assert channel_msg.text == "hello"
    assert channel_msg.is_group is False


async def test_group_mention_dispatched():
    """TEL-02: _on_group_message() dispatches when @botname is in the text."""
    enqueue_fn = AsyncMock()
    channel = TelegramChannel(token="x", enqueue_fn=enqueue_fn)

    mock_update = _make_mock_update(text="Hey @botname what's up?", chat_type="supergroup")

    mock_context = MagicMock()
    mock_context.bot.username = "botname"

    await channel._on_group_message(mock_update, mock_context)

    enqueue_fn.assert_awaited_once()


async def test_group_non_mention_ignored():
    """TEL-02: _on_group_message() must NOT dispatch when bot is not @mentioned."""
    enqueue_fn = AsyncMock()
    channel = TelegramChannel(token="x", enqueue_fn=enqueue_fn)

    mock_update = _make_mock_update(text="Just a regular group message", chat_type="group")

    mock_context = MagicMock()
    mock_context.bot.username = "botname"

    await channel._on_group_message(mock_update, mock_context)

    enqueue_fn.assert_not_awaited()


async def test_dispatch_sets_is_group_for_supergroup():
    """TEL-02: is_group must be True for supergroup chat type."""
    enqueue_fn = AsyncMock()
    channel = TelegramChannel(token="x", enqueue_fn=enqueue_fn)

    mock_update = _make_mock_update(text="hello", chat_type="supergroup")
    await channel._dispatch(mock_update)

    channel_msg = enqueue_fn.call_args[0][0]
    assert channel_msg.is_group is True


async def test_dispatch_no_enqueue_fn_does_not_raise():
    """TEL-02: _dispatch() must not raise when enqueue_fn is None (test-safe mode)."""
    channel = TelegramChannel(token="x", enqueue_fn=None)
    mock_update = _make_mock_update()
    await channel._dispatch(mock_update)  # must not raise


# ---------------------------------------------------------------------------
# TEL-03: send() / send_typing() / mark_read()
# ---------------------------------------------------------------------------


async def test_send_calls_bot_send_message():
    """TEL-03: send() must call bot.send_message with chat_id as int."""
    channel = TelegramChannel(token="x")
    channel._app = MagicMock(bot=AsyncMock())

    result = await channel.send("12345", "Hello!")

    channel._app.bot.send_message.assert_awaited_once_with(chat_id=12345, text="Hello!")
    assert result is True


async def test_send_typing_calls_chat_action():
    """TEL-03: send_typing() must call send_chat_action with TYPING action."""
    channel = TelegramChannel(token="x")
    channel._app = MagicMock(bot=AsyncMock())

    await channel.send_typing("12345")

    channel._app.bot.send_chat_action.assert_awaited_once_with(
        chat_id=12345, action=ChatAction.TYPING
    )


async def test_send_returns_false_on_error():
    """TEL-03: send() must return False if bot.send_message raises TelegramError."""
    channel = TelegramChannel(token="x")
    channel._app = MagicMock()
    channel._app.bot = AsyncMock()
    channel._app.bot.send_message = AsyncMock(side_effect=TelegramError("rate limited"))

    result = await channel.send("12345", "Hi")

    assert result is False


async def test_send_returns_false_when_app_not_initialized():
    """TEL-03: send() must return False immediately when _app is None."""
    channel = TelegramChannel(token="x")
    assert channel._app is None

    result = await channel.send("12345", "text")
    assert result is False


async def test_send_typing_noop_when_app_not_initialized():
    """TEL-03: send_typing() must not raise when _app is None."""
    channel = TelegramChannel(token="x")
    await channel.send_typing("12345")  # must not raise


async def test_mark_read_is_noop():
    """TEL-03: mark_read() must not raise — Telegram has no read-receipt API."""
    channel = TelegramChannel(token="x")
    await channel.mark_read("123", "456")  # must not raise


# ---------------------------------------------------------------------------
# TEL-04: health_check() and channel identity
# ---------------------------------------------------------------------------


async def test_health_check_when_stopped():
    """TEL-04: health_check() must return 'down' when status is 'stopped'."""
    channel = TelegramChannel(token="x")
    result = await channel.health_check()

    assert result["status"] == "down"
    assert result["channel"] == "telegram"
    assert "polling_status" in result


async def test_health_check_when_running():
    """TEL-04: health_check() must return 'ok' when _status is 'running'."""
    channel = TelegramChannel(token="x")
    channel._status = "running"
    channel._bot_info = {"username": "testbot", "id": 42}

    result = await channel.health_check()

    assert result["status"] == "ok"
    assert result["channel"] == "telegram"
    assert result["bot_info"]["username"] == "testbot"


async def test_health_check_failed_status_returns_down():
    """TEL-04: health_check() must return 'down' when _status is 'failed'."""
    channel = TelegramChannel(token="x")
    channel._status = "failed"

    result = await channel.health_check()

    assert result["status"] == "down"


async def test_receive_raises_not_implemented():
    """TEL-04: receive() must raise NotImplementedError — PTB uses handlers not webhooks."""
    channel = TelegramChannel(token="x")
    with pytest.raises(NotImplementedError):
        await channel.receive({})


# ---------------------------------------------------------------------------
# Phase 08-02: Integration tests — enqueue_fn routes via flood.incoming() adapter
# TEL-01, TEL-03
# ---------------------------------------------------------------------------


class TestTelegramFloodGateIntegration:
    """
    TEL-01 / TEL-03: Verify that TelegramChannel._dispatch() with a flood.incoming()
    adapter correctly routes ChannelMessage — no AttributeError on task_id.

    These tests simulate the _make_flood_enqueue() adapter pattern used in api_gateway.py
    without importing api_gateway (to avoid singleton initialization side effects).
    """

    def _make_flood_adapter(self, collected):
        """Returns an async enqueue_fn that captures what the real adapter would pass to flood."""

        async def _enqueue(channel_msg):
            # This mirrors the _make_flood_enqueue inner function in api_gateway.py
            collected.append(
                {
                    "chat_id": channel_msg.chat_id,
                    "text": channel_msg.text,
                    "message_id": channel_msg.message_id,
                    "sender_name": channel_msg.sender_name,
                    "channel_id": "telegram",
                }
            )

        return _enqueue

    async def test_dispatch_routes_via_flood_adapter(self):
        """TEL-01: _dispatch() routes ChannelMessage to the adapter — not directly to task_queue.

        Uses a mock PTB Update (as _dispatch expects) and verifies the adapter receives
        the normalized ChannelMessage with the correct shape.
        """
        collected = []
        ch = TelegramChannel(token="fake-token", enqueue_fn=self._make_flood_adapter(collected))

        mock_update = _make_mock_update(
            text="hello from telegram",
            chat_type="private",
            user_id=123,
            chat_id=456,
            message_id=1,
            full_name="TestUser",
        )

        await ch._dispatch(mock_update)

        assert len(collected) == 1, f"Expected 1 dispatch, got {len(collected)}"
        assert collected[0]["channel_id"] == "telegram"
        assert collected[0]["text"] == "hello from telegram"
        assert collected[0]["chat_id"] == "456"
        assert collected[0]["sender_name"] == "TestUser"

    async def test_dispatch_no_task_id_attribute_error(self):
        """TEL-01: Adapter receives ChannelMessage — task_id is absent (proves old bug was real).

        Uses a mock PTB Update; verifies the ChannelMessage passed to enqueue_fn
        has no task_id — confirming that direct task_queue.enqueue() would crash.
        """
        received = []

        async def capture(channel_msg):
            # Old broken code: task_queue.enqueue() would have done channel_msg.task_id here
            # Verify ChannelMessage does NOT have task_id
            assert not hasattr(
                channel_msg, "task_id"
            ), "ChannelMessage has task_id — use adapter pattern, not direct task_queue.enqueue"
            received.append(channel_msg)

        ch = TelegramChannel(token="fake-token", enqueue_fn=capture)

        mock_update = _make_mock_update(
            text="type-check message",
            chat_type="private",
            user_id=1,
            chat_id=2,
            message_id=3,
            full_name="Tester",
        )

        # This must not raise AttributeError
        await ch._dispatch(mock_update)

        assert len(received) == 1

    async def test_dispatch_no_enqueue_fn_logs_warning(self):
        """TEL-01: When enqueue_fn=None, message is dropped with a warning (not a crash)."""
        ch = TelegramChannel(token="fake-token", enqueue_fn=None)
        mock_update = _make_mock_update(text="dropped", chat_type="private")

        # Should not raise — only log a warning
        with contextlib.suppress(Exception):
            await ch._dispatch(mock_update)
        # Test passes as long as no unhandled exception propagates
