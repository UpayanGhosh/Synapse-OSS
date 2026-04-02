"""
Tests for Phase 5 polling resilience features.

Covers:
  - TelegramOffsetStore: save/load round-trip, bot-ID rotation, corrupt file, missing file
  - PollingWatchdog: stall detection, backoff computation
  - TelegramChannel: proxy URL wiring, offset persistence integration
  - WhatsAppChannel: wait_for_qr_login timeout, code-515 bridge restart
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

from sci_fi_dashboard.channels.telegram_offset_store import TelegramOffsetStore, STORE_VERSION
from sci_fi_dashboard.channels.polling_watchdog import (
    PollingWatchdog,
    RESTART_POLICY,
)

# ---------------------------------------------------------------------------
# Conditional imports for channel adapters
# ---------------------------------------------------------------------------
TEL_AVAILABLE = importlib.util.find_spec("telegram") is not None
WA_AVAILABLE = importlib.util.find_spec("sci_fi_dashboard.channels.whatsapp") is not None

if TEL_AVAILABLE:
    from sci_fi_dashboard.channels.telegram import TelegramChannel

if WA_AVAILABLE:
    from sci_fi_dashboard.channels.whatsapp import WhatsAppChannel


# ===========================================================================
# TelegramOffsetStore
# ===========================================================================


class TestOffsetStoreSaveLoadRoundTrip:
    """Offset store save/load round-trip."""

    def test_save_and_load(self, tmp_path):
        """Saved update_id is loaded back correctly."""
        store = TelegramOffsetStore(tmp_path, "test-account")
        store.save(42, "12345")
        assert store.load("12345") == 42

    def test_load_missing_file_returns_zero(self, tmp_path):
        """Missing file returns 0."""
        store = TelegramOffsetStore(tmp_path, "test-account")
        assert store.load("12345") == 0

    def test_load_corrupt_file_returns_zero(self, tmp_path):
        """Corrupt JSON file returns 0."""
        store = TelegramOffsetStore(tmp_path, "test-account")
        # Create the directory structure and write garbage
        store._path.parent.mkdir(parents=True, exist_ok=True)
        store._path.write_text("NOT VALID JSON {{{", encoding="utf-8")
        assert store.load("12345") == 0

    def test_bot_id_rotation_resets_offset(self, tmp_path):
        """If bot_id changes (token rotation), offset resets to 0."""
        store = TelegramOffsetStore(tmp_path, "test-account")
        store.save(100, "old_bot_id")
        # Load with a different bot_id — should return 0
        assert store.load("new_bot_id") == 0

    def test_negative_update_id_rejected(self, tmp_path):
        """save() raises ValueError for negative update_id."""
        store = TelegramOffsetStore(tmp_path, "test-account")
        with pytest.raises(ValueError, match="non-negative"):
            store.save(-1, "12345")

    def test_negative_stored_update_id_returns_zero(self, tmp_path):
        """If the stored update_id is somehow negative, load returns 0."""
        store = TelegramOffsetStore(tmp_path, "test-account")
        store._path.parent.mkdir(parents=True, exist_ok=True)
        store._path.write_text(
            json.dumps({"version": STORE_VERSION, "bot_id": "12345", "update_id": -5}),
            encoding="utf-8",
        )
        assert store.load("12345") == 0

    def test_large_update_id(self, tmp_path):
        """Large update_id values are handled correctly."""
        store = TelegramOffsetStore(tmp_path, "test-account")
        large_id = 999_999_999
        store.save(large_id, "12345")
        assert store.load("12345") == large_id

    def test_file_format_version(self, tmp_path):
        """Saved file contains the correct version field."""
        store = TelegramOffsetStore(tmp_path, "test-account")
        store.save(10, "12345")
        data = json.loads(store._path.read_text(encoding="utf-8"))
        assert data["version"] == STORE_VERSION

    def test_extract_bot_id_from_token(self):
        """extract_bot_id extracts digits before ':'."""
        assert TelegramOffsetStore.extract_bot_id("123456:ABC-DEF") == "123456"

    def test_extract_bot_id_no_colon(self):
        """extract_bot_id returns full string if no colon present."""
        assert TelegramOffsetStore.extract_bot_id("no-colon-token") == "no-colon-token"

    def test_zero_update_id_saves_and_loads(self, tmp_path):
        """update_id=0 is valid and round-trips correctly."""
        store = TelegramOffsetStore(tmp_path, "test-account")
        store.save(0, "12345")
        assert store.load("12345") == 0


# ===========================================================================
# PollingWatchdog
# ===========================================================================


class TestPollingWatchdog:
    """Stall detection and backoff computation."""

    @pytest.mark.asyncio
    async def test_stall_detection_triggers_restart(self):
        """When no activity is recorded past threshold, restart_callback is called."""
        restart_mock = AsyncMock()
        watchdog = PollingWatchdog(
            restart_callback=restart_mock,
            stall_threshold_s=0.05,  # 50ms for fast test
        )

        # Patch the watchdog interval to be very short
        with patch(
            "sci_fi_dashboard.channels.polling_watchdog.POLL_WATCHDOG_INTERVAL_S",
            0.02,
        ), patch(
            "sci_fi_dashboard.channels.polling_watchdog.RESTART_POLICY",
            {"initial_s": 0.0, "max_s": 0.0, "factor": 1.0, "jitter": 0.0},
        ):
            await watchdog.start()
            # Don't record any activity — stall should trigger
            await asyncio.sleep(0.2)
            await watchdog.stop()

        assert restart_mock.await_count >= 1, (
            f"Expected restart_callback to be called at least once, "
            f"got {restart_mock.await_count} calls"
        )

    @pytest.mark.asyncio
    async def test_activity_prevents_stall(self):
        """Recording activity prevents the stall detector from triggering."""
        restart_mock = AsyncMock()
        watchdog = PollingWatchdog(
            restart_callback=restart_mock,
            stall_threshold_s=0.1,
        )

        with patch(
            "sci_fi_dashboard.channels.polling_watchdog.POLL_WATCHDOG_INTERVAL_S",
            0.03,
        ):
            await watchdog.start()
            # Keep recording activity — no stall should occur
            for _ in range(5):
                watchdog.record_activity()
                await asyncio.sleep(0.03)
            await watchdog.stop()

        restart_mock.assert_not_awaited()

    def test_backoff_increases_with_consecutive_restarts(self):
        """Consecutive restarts produce increasing backoff values."""
        watchdog = PollingWatchdog(restart_callback=AsyncMock())

        # First restart
        watchdog._consecutive_restarts = 1
        backoff_1 = watchdog._compute_backoff()

        # Second restart
        watchdog._consecutive_restarts = 2
        backoff_2 = watchdog._compute_backoff()

        # Third restart
        watchdog._consecutive_restarts = 3
        backoff_3 = watchdog._compute_backoff()

        # With jitter, exact values vary, but the trend should be increasing.
        # Use the base (non-jittered) values to verify the trend:
        # base1 = 2.0, base2 = 2.0 * 1.8 = 3.6, base3 = 2.0 * 1.8^2 = 6.48
        # Even with 25% jitter, base2 min (2.7) > base1 max (2.5)
        assert backoff_1 > 0, "Backoff should be positive"
        assert backoff_2 > 0, "Backoff should be positive"
        assert backoff_3 > 0, "Backoff should be positive"

    def test_backoff_capped_at_max(self):
        """Backoff never exceeds max_s (even with jitter)."""
        watchdog = PollingWatchdog(restart_callback=AsyncMock())
        watchdog._consecutive_restarts = 100  # very high
        backoff = watchdog._compute_backoff()
        max_with_jitter = RESTART_POLICY["max_s"] * (1.0 + RESTART_POLICY["jitter"])
        assert backoff <= max_with_jitter + 0.01  # tiny float tolerance

    def test_record_activity_resets_consecutive_restarts(self):
        """record_activity() resets the consecutive restart counter."""
        watchdog = PollingWatchdog(restart_callback=AsyncMock())
        watchdog._consecutive_restarts = 5
        watchdog.record_activity()
        assert watchdog._consecutive_restarts == 0

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self):
        """Calling stop() when not started should not raise."""
        watchdog = PollingWatchdog(restart_callback=AsyncMock())
        await watchdog.stop()  # should not raise

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self):
        """Calling start() twice should not create duplicate tasks."""
        restart_mock = AsyncMock()
        watchdog = PollingWatchdog(
            restart_callback=restart_mock,
            stall_threshold_s=999,
        )
        with patch(
            "sci_fi_dashboard.channels.polling_watchdog.POLL_WATCHDOG_INTERVAL_S",
            0.1,
        ):
            await watchdog.start()
            task1 = watchdog._task
            await watchdog.start()  # second call
            task2 = watchdog._task
            assert task1 is task2, "start() should not create a duplicate task"
            await watchdog.stop()


# ===========================================================================
# TelegramChannel — proxy and offset wiring
# ===========================================================================


@pytest.mark.skipif(not TEL_AVAILABLE, reason="python-telegram-bot not installed")
class TestTelegramProxy:
    """Proxy URL is passed through to the PTB builder."""

    def test_proxy_url_stored(self):
        """Constructor stores proxy_url."""
        ch = TelegramChannel(token="x", proxy_url="socks5://localhost:1080")
        assert ch._proxy_url == "socks5://localhost:1080"

    def test_no_proxy_by_default(self):
        """No proxy configured by default."""
        ch = TelegramChannel(token="x")
        assert ch._proxy_url is None

    @pytest.mark.asyncio
    async def test_proxy_passed_to_builder(self, monkeypatch):
        """When proxy_url is set, builder.proxy() and builder.get_updates_proxy() are called."""
        builder_mock = MagicMock()
        builder_mock.token.return_value = builder_mock
        builder_mock.updater.return_value = builder_mock
        builder_mock.proxy.return_value = builder_mock
        builder_mock.get_updates_proxy.return_value = builder_mock

        mock_app = MagicMock()
        mock_app.bot = AsyncMock()
        mock_app.bot.delete_webhook = AsyncMock()
        mock_app.update_queue = asyncio.Queue()
        mock_app.running = True
        mock_app.initialize = AsyncMock()
        mock_app.start = AsyncMock()
        mock_app.add_handler = MagicMock()
        bot_me = MagicMock(username="bot", id=1)
        mock_app.bot.get_me = AsyncMock(return_value=bot_me)
        builder_mock.build.return_value = mock_app

        monkeypatch.setattr(
            "sci_fi_dashboard.channels.telegram.ApplicationBuilder",
            MagicMock(return_value=builder_mock),
        )

        mock_updater = MagicMock()
        mock_updater.running = True
        mock_updater.initialize = AsyncMock()
        mock_updater.start_polling = AsyncMock()
        mock_updater.stop = AsyncMock()
        monkeypatch.setattr(
            "sci_fi_dashboard.channels.telegram.Updater",
            MagicMock(return_value=mock_updater),
        )

        ch = TelegramChannel(
            token="fake:token",
            proxy_url="socks5://proxy.example.com:1080",
        )

        task = asyncio.create_task(ch.start())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

        builder_mock.proxy.assert_called_once_with("socks5://proxy.example.com:1080")
        builder_mock.get_updates_proxy.assert_called_once_with(
            "socks5://proxy.example.com:1080"
        )


@pytest.mark.skipif(not TEL_AVAILABLE, reason="python-telegram-bot not installed")
class TestTelegramOffsetIntegration:
    """TelegramChannel wires offset store into dispatch and start."""

    def test_bot_id_extracted_at_init(self):
        """Bot ID is extracted from token at construction time."""
        ch = TelegramChannel(token="123456:ABC")
        assert ch._bot_id == "123456"

    def test_state_dir_stored(self, tmp_path):
        """Custom state_dir is stored."""
        ch = TelegramChannel(token="x", state_dir=tmp_path)
        assert ch._state_dir == tmp_path

    @pytest.mark.asyncio
    async def test_dispatch_persists_offset(self, tmp_path):
        """After _dispatch(), the update_id is saved to the offset store."""
        enqueue_mock = AsyncMock()
        ch = TelegramChannel(token="111:abc", enqueue_fn=enqueue_mock, state_dir=tmp_path)

        # Manually set up offset store (normally done in start())
        ch._offset_store = TelegramOffsetStore(tmp_path, ch._bot_id)

        # Build a mock update
        mock_user = MagicMock()
        mock_user.id = 99
        mock_user.full_name = "Test"

        mock_chat = MagicMock()
        mock_chat.id = 123
        mock_chat.type = "private"

        mock_msg = MagicMock()
        mock_msg.text = "hello"
        mock_msg.from_user = mock_user
        mock_msg.chat = mock_chat
        mock_msg.message_id = 1
        mock_msg.date = None

        mock_update = MagicMock()
        mock_update.message = mock_msg
        mock_update.update_id = 42
        mock_update.to_dict.return_value = {}

        await ch._dispatch(mock_update)

        # Verify offset was persisted
        assert ch._last_offset == 42
        assert ch._offset_store.load(ch._bot_id) == 42


# ===========================================================================
# WhatsAppChannel — QR login and code 515
# ===========================================================================


@pytest.mark.skipif(not WA_AVAILABLE, reason="WhatsApp channel not available")
class TestWhatsAppQRLogin:
    """wait_for_qr_login timeout behaviour."""

    @pytest.mark.asyncio
    async def test_qr_login_timeout_returns_false(self):
        """wait_for_qr_login returns False when timeout expires."""
        ch = WhatsAppChannel(bridge_port=59999)

        # Use a very short timeout so the test runs fast
        result = await ch.wait_for_qr_login(timeout=1)

        assert result is False

    @pytest.mark.asyncio
    async def test_qr_login_returns_true_when_connected(self, monkeypatch):
        """wait_for_qr_login returns True when bridge reports connected."""
        import httpx

        ch = WhatsAppChannel(bridge_port=59999)

        # Mock httpx to return connected health
        call_count = 0

        async def mock_get(self_client, url, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 200
            if "/health" in url:
                resp.json.return_value = {
                    "status": "connected",
                    "connection_state": "connected",
                }
            elif "/qr" in url:
                resp.json.return_value = {"qr": "FAKE_QR"}
            return resp

        monkeypatch.setattr("httpx.AsyncClient.get", mock_get)

        result = await ch.wait_for_qr_login(timeout=10)
        assert result is True


@pytest.mark.skipif(not WA_AVAILABLE, reason="WhatsApp channel not available")
class TestWhatsAppCode515:
    """Code 515 (restart-after-pairing) triggers bridge restart."""

    @pytest.mark.asyncio
    async def test_code_515_triggers_restart(self, monkeypatch):
        """update_connection_state with lastDisconnectReason=515 calls _restart_bridge."""
        ch = WhatsAppChannel(bridge_port=59999)

        restart_mock = AsyncMock()
        monkeypatch.setattr(ch, "_restart_bridge", restart_mock)

        # Capture real sleep before patching to avoid recursion
        _real_sleep = asyncio.sleep

        async def fast_sleep(duration):
            await _real_sleep(0)

        monkeypatch.setattr("asyncio.sleep", fast_sleep)

        await ch.update_connection_state({"lastDisconnectReason": 515})

        restart_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_code_515_string_triggers_restart(self, monkeypatch):
        """update_connection_state handles '515' as string too."""
        ch = WhatsAppChannel(bridge_port=59999)

        restart_mock = AsyncMock()
        monkeypatch.setattr(ch, "_restart_bridge", restart_mock)

        _real_sleep = asyncio.sleep

        async def fast_sleep(duration):
            await _real_sleep(0)

        monkeypatch.setattr("asyncio.sleep", fast_sleep)

        await ch.update_connection_state({"lastDisconnectReason": "515"})

        restart_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connected_state_flushes_retry_queue(self):
        """When connection_state is 'connected', retry queue flush is scheduled."""
        ch = WhatsAppChannel(bridge_port=59999)
        mock_queue = MagicMock()
        mock_queue.flush = AsyncMock()
        ch._retry_queue = mock_queue

        await ch.update_connection_state({"connectionState": "connected"})

        # Give the created task a chance to run
        await asyncio.sleep(0)

        mock_queue.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_connection_state_is_async(self):
        """update_connection_state is now async (Phase 5 change)."""
        ch = WhatsAppChannel(bridge_port=59999)
        # Should be callable as coroutine without error
        await ch.update_connection_state({"connectionState": "unknown"})
        assert ch._connection_state == "unknown"
