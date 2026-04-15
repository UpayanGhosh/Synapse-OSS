"""
TelegramChannel — python-telegram-bot v22+ async adapter for Synapse-OSS.

Lifecycle:
  start()  → clears stale webhook, builds PTB Application with updater=None,
             creates Updater manually, starts long polling, parks on asyncio.Event.
             Designed to run as asyncio.create_task() from ChannelRegistry.start_all().
  stop()   → stops Updater, stops/shuts down Application; sets _status="stopped".

Message handling:
  DM messages (ChatType.PRIVATE) → _on_message() → _dispatch()
  Group @mentions (ChatType.GROUPS + Entity "mention") → _on_group_message()
    ↳ In-handler bot_username check (avoids pre-initialize timing issue with
       filters.Mention which requires bot to be initialised first)
  Stickers → _on_sticker() → _dispatch() with "[Sticker: {emoji}]" text
  Voice messages → _on_voice() → _dispatch() with voice file_id in raw

Error handling:
  Conflict (409) — another instance polling same token; logs clearly, no crash.
  InvalidToken   — bad token; logs clearly, no crash.
  TelegramError  — any other Telegram API error; logs clearly, no crash.
  CancelledError — ChannelRegistry.stop_all() cancelled the task; stop() called,
                   error re-raised so ChannelRegistry is aware.

Polling resilience (Phase 5):
  - Persisted update offset via TelegramOffsetStore — survives restarts.
  - Stall watchdog via PollingWatchdog — auto-restarts on stall.
  - Network error classification via network_errors — smarter retry logic.
  - Per-account proxy support via PTB builder.

Telegram-specific features:
  - Forum topic routing via message_thread_id extraction.
  - Per-channel message splitting at 4096-char limit.
  - Typing indicator keepalive with circuit breaker (5-min backoff after 5 failures).
  - Configurable mention gating for group messages.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import Conflict, InvalidToken, TelegramError
from telegram.ext import ApplicationBuilder, MessageHandler, Updater, filters

from .base import BaseChannel, ChannelMessage
from .network_errors import is_safe_to_retry_send
from .polling_watchdog import PollingWatchdog
from .security import ChannelSecurityConfig, PairingStore, resolve_dm_access
from .telegram_offset_store import TelegramOffsetStore

logger = logging.getLogger(__name__)

# Default state directory for offset persistence
_DEFAULT_STATE_DIR = Path.home() / ".synapse" / "state"


class TelegramChannel(BaseChannel):
    """
    Telegram channel adapter via python-telegram-bot v22+ long polling.

    Registers DM and group @mention handlers. Normalises PTB Update objects
    into ChannelMessage DTOs and routes them via the injected enqueue_fn
    callback into the existing MessageWorker pipeline.

    Args:
        token:           Telegram Bot API token from @BotFather.
        enqueue_fn:      Async callable(ChannelMessage) -> None injected by
                         api_gateway.py. If None, incoming messages are logged
                         and dropped (safe for tests).
        state_dir:       Directory for persisting offset state.  Defaults to
                         ``~/.synapse/state``.
        proxy_url:       Optional SOCKS5/HTTP proxy URL for Telegram API requests.
        require_mention: If True (default), group messages are only processed
                         when the bot is @mentioned.  If False, all group
                         messages are processed.  Slash commands (``/``) always
                         bypass the mention gate.
    """

    MAX_CHARS: int = 4096  # Telegram per-message character limit

    def __init__(
        self,
        token: str,
        enqueue_fn=None,
        security_config: ChannelSecurityConfig | None = None,
        pairing_store: PairingStore | None = None,
        state_dir: Path | None = None,
        proxy_url: str | None = None,
        require_mention: bool = True,
    ) -> None:
        self._token = token
        self._enqueue_fn = enqueue_fn  # async callable(ChannelMessage) -> None
        self._app = None  # telegram.ext.Application
        self._updater = None  # telegram.ext.Updater
        self._status: str = "stopped"
        self._bot_info: dict = {}
        self.security_config = security_config
        self._pairing_store = pairing_store
        self._state_dir = state_dir or _DEFAULT_STATE_DIR
        self._proxy_url = proxy_url
        self._require_mention = require_mention

        # Offset persistence
        self._bot_id: str = TelegramOffsetStore.extract_bot_id(token)
        self._offset_store: TelegramOffsetStore | None = None
        self._last_offset: int = 0

        # Stall watchdog
        self._watchdog: PollingWatchdog | None = None

        # Typing indicator circuit breaker
        self._consecutive_typing_failures: int = 0
        self._typing_suspended_until: float = 0.0

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def channel_id(self) -> str:
        return "telegram"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Build PTB Application, register handlers, start long polling, park.

        Uses ApplicationBuilder().updater(None) (PTB v22 manual lifecycle) — never
        run_polling() which would block or call asyncio.run() internally.

        Clears any stale webhook with delete_webhook() before start_polling() to
        prevent 409 Conflict from a previously running instance.

        If a state_dir is configured, loads the last processed update_id so the
        bot resumes from where it left off.

        Called by ChannelRegistry.start_all() via asyncio.create_task().
        CancelledError propagates after calling stop().
        """
        # Build PTB Application with optional proxy
        builder = ApplicationBuilder().token(self._token).updater(None)
        if self._proxy_url:
            builder = builder.proxy(self._proxy_url).get_updates_proxy(self._proxy_url)
        self._app = builder.build()

        # Register handlers BEFORE initialize() — bot.username not yet available.
        # Use Entity("mention") filter + in-handler username check for groups
        # (avoids pre-initialize timing issue with filters.Mention).
        self._app.add_handler(
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                self._on_message,
            )
        )

        # Group text handler — Entity("mention") filter is only applied when
        # require_mention is True.  When False, all group text is accepted.
        group_filter = filters.ChatType.GROUPS & filters.TEXT
        if self._require_mention:
            group_filter = group_filter & filters.Entity("mention")
        self._app.add_handler(MessageHandler(group_filter, self._on_group_message))

        # Sticker handler — extract emoji equivalent and dispatch as text
        self._app.add_handler(
            MessageHandler(
                filters.Sticker.ALL,
                self._on_sticker,
            )
        )

        # Voice / voice-note handler — extract file_id for transcription pipeline
        self._app.add_handler(
            MessageHandler(
                filters.VOICE | filters.AUDIO,
                self._on_voice,
            )
        )

        # Create Updater manually — shares bot and update_queue with Application.
        self._updater = Updater(self._app.bot, update_queue=self._app.update_queue)

        # Load persisted offset
        self._offset_store = TelegramOffsetStore(self._state_dir, self._bot_id)
        self._last_offset = self._offset_store.load(self._bot_id)

        try:
            # Clear any stale webhook to prevent 409 Conflict.
            # drop_pending_updates=False preserves messages that arrived while
            # the bot was down so start_polling can pick them up from the
            # persisted offset.
            await self._app.bot.delete_webhook(drop_pending_updates=False)
            logger.info("[TEL] Webhook cleared — starting long polling")

            await self._updater.initialize()
            await self._app.initialize()

            # Resume from persisted offset if available.
            # PTB's start_polling() has no offset= param, so we seed the
            # server-side offset via a get_updates call first.  Telegram
            # confirms (discards) all updates with id < offset, so the
            # subsequent start_polling picks up right where we left off.
            if self._last_offset > 0:
                await self._app.bot.get_updates(offset=self._last_offset + 1, limit=1, timeout=0)
                logger.info("[TEL] Seeded server offset=%d", self._last_offset + 1)
                await self._updater.start_polling(drop_pending_updates=False)
            else:
                await self._updater.start_polling(drop_pending_updates=True)

            await self._app.start()

            self._status = "running"
            bot_me = await self._app.bot.get_me()
            self._bot_info = {"username": bot_me.username, "id": bot_me.id}
            logger.info("[TEL] Polling as @%s (id=%d)", bot_me.username, bot_me.id)

            # Start stall watchdog
            self._watchdog = PollingWatchdog(restart_callback=self._restart_polling)
            await self._watchdog.start()

            # Park here until CancelledError from ChannelRegistry.stop_all().
            await asyncio.Event().wait()

        except Conflict:
            self._status = "failed"
            logger.error(
                "[TEL] 409 Conflict — another instance is already polling this token. "
                "Stop it, then restart Synapse."
            )
        except InvalidToken:
            self._status = "failed"
            logger.error(
                "[TEL] Invalid token in channels.telegram.token — "
                "check synapse.json and regenerate via @BotFather if needed."
            )
        except TelegramError as exc:
            self._status = "failed"
            logger.error("[TEL] Unexpected Telegram error during startup: %s", exc)
        except asyncio.CancelledError:
            await self.stop()
            raise

    async def stop(self) -> None:
        """
        Gracefully shut down the Updater, Application, and watchdog.

        Stops the Updater (halts long polling), then stops and shuts down the
        Application (closes the HTTP session). Sets _status to "stopped".
        """
        if self._watchdog:
            await self._watchdog.stop()
            self._watchdog = None
        if self._updater and self._updater.running:
            await self._updater.stop()
        if self._app and self._app.running:
            await self._app.stop()
            await self._app.shutdown()  # MUST call shutdown() to close HTTP session
        self._status = "stopped"
        logger.info("[TEL] Telegram channel stopped")

    async def _restart_polling(self) -> None:
        """Restart the PTB updater after a stall.

        Called by PollingWatchdog when no updates have been received for the
        configured stall threshold.  Stops the existing updater and starts a
        new polling session using the last persisted offset.
        """
        logger.warning("[TEL] Restarting polling (last_offset=%d)", self._last_offset)

        if self._updater and self._updater.running:
            await self._updater.stop()

        if self._updater:
            if self._last_offset > 0:
                # Seed the server-side offset before polling resumes
                await self._updater.bot.get_updates(
                    offset=self._last_offset + 1, limit=1, timeout=0
                )
                await self._updater.start_polling(drop_pending_updates=False)
            else:
                await self._updater.start_polling(drop_pending_updates=True)

            logger.info("[TEL] Polling restarted successfully")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """
        Return a status dict describing the Telegram channel health.

        Returns:
            {
                "status":         "ok" | "down",
                "channel":        "telegram",
                "bot_info":       {"username": str, "id": int},
                "polling_status": str,   # internal _status field
            }
        """
        return {
            "status": "ok" if self._status == "running" else "down",
            "channel": "telegram",
            "bot_info": self._bot_info,
            "polling_status": self._status,
        }

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send(self, chat_id: str, text: str) -> bool:
        """
        Send a text message to the given Telegram chat.

        If *text* exceeds ``MAX_CHARS`` (4096) it is automatically split into
        multiple messages at natural boundaries (paragraph > line > word > hard
        cut).  Each chunk is sent with a small delay to respect rate limits.

        Uses network error classification for smarter retry decisions:
        pre-connect errors (safe to retry) are logged at WARNING, while
        post-connect errors are logged at ERROR.

        Args:
            chat_id: Telegram chat/user ID as a string.
            text:    Message body to deliver.

        Returns:
            True on success, False if Application is not ready or send failed.
        """
        if not self._app:
            return False

        chunks = self._split_message(text)
        all_ok = True
        for i, chunk in enumerate(chunks):
            try:
                await self._app.bot.send_message(chat_id=int(chat_id), text=chunk)
            except TelegramError as exc:
                all_ok = False
                if is_safe_to_retry_send(exc):
                    logger.warning(
                        "[TEL] send() pre-connect failure for chat %s (retryable): %s",
                        chat_id,
                        exc,
                    )
                else:
                    logger.error("[TEL] send() failed for chat %s: %s", chat_id, exc)
                break  # stop sending remaining chunks on failure
            # Small delay between chunks to avoid rate limiting
            if i < len(chunks) - 1:
                await asyncio.sleep(0.3)
        return all_ok

    async def send_typing(self, chat_id: str) -> None:
        """
        Send a TYPING chat action to the given Telegram chat.

        Includes a circuit breaker: after 5 consecutive failures, typing
        indicators are suppressed for 5 minutes to avoid hammering a
        broken endpoint (e.g. 401 from a revoked token).

        Args:
            chat_id: Telegram chat/user ID as a string.
        """
        if not self._app:
            return
        # Circuit breaker — skip if suspended
        if time.time() < self._typing_suspended_until:
            return
        try:
            await self._app.bot.send_chat_action(chat_id=int(chat_id), action=ChatAction.TYPING)
            self._consecutive_typing_failures = 0
        except TelegramError as exc:
            self._consecutive_typing_failures += 1
            if self._consecutive_typing_failures >= 5:
                self._typing_suspended_until = time.time() + 300  # 5-min backoff
                logger.warning(
                    "[TEL] Typing indicator suspended for 5 min after %d "
                    "consecutive failures (last: %s)",
                    self._consecutive_typing_failures,
                    exc,
                )

    async def send_typing_loop(self, chat_id: str, cancel_event: asyncio.Event) -> None:
        """
        Send typing indicators every 4 seconds until *cancel_event* is set.

        Designed to run as an ``asyncio.create_task()`` during long-running
        LLM calls so the user sees a continuous typing indicator.

        Args:
            chat_id:      Telegram chat/user ID as a string.
            cancel_event: Set this event to stop the loop.
        """
        while not cancel_event.is_set():
            await self.send_typing(chat_id)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(cancel_event.wait(), timeout=4.0)

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """
        No-op — Telegram bots have no read-receipt API.

        Args:
            chat_id:    Telegram chat ID (unused).
            message_id: Message ID (unused).
        """

    async def send_voice(self, chat_id: str, voice_path: str) -> bool:
        """
        Send a voice message to the given Telegram chat.

        Args:
            chat_id:    Telegram chat/user ID as a string.
            voice_path: Local file path to an OGG/Opus voice file.

        Returns:
            True on success, False if Application is not ready or send failed.
        """
        if not self._app:
            return False
        try:
            with open(voice_path, "rb") as f:
                await self._app.bot.send_voice(chat_id=int(chat_id), voice=f)
            return True
        except (TelegramError, OSError) as exc:
            logger.error("[TEL] send_voice() failed for chat %s: %s", chat_id, exc)
            return False

    async def receive(self, raw_payload: dict) -> ChannelMessage:
        """
        Not used — TelegramChannel uses PTB handler callbacks, not raw webhooks.

        Raises:
            NotImplementedError: Always — inbound normalisation goes through
                                 _on_message() / _on_group_message() / _dispatch().
        """
        raise NotImplementedError(
            "TelegramChannel uses PTB handler callbacks (not raw webhook payloads). "
            "Inbound messages are dispatched via _on_message() / _on_group_message()."
        )

    # ------------------------------------------------------------------
    # PTB handlers
    # ------------------------------------------------------------------

    async def _on_message(self, update: Update, context) -> None:
        """Handle incoming DM (ChatType.PRIVATE) messages."""
        await self._dispatch(update)

    async def _on_group_message(self, update: Update, context) -> None:
        """
        Handle group messages with configurable mention gating.

        When ``require_mention`` is True (default), only dispatches if the bot
        is @mentioned in the text.  When False, all group messages are processed.

        Slash commands (messages starting with ``/``) always bypass the mention
        gate so that group commands work regardless of the setting.

        Uses a runtime in-handler check (context.bot.username) rather than
        filters.Mention to avoid the pre-initialize timing issue where
        filters.Mention tries to resolve bot.username before PTB is initialised.
        """
        text = update.message.text or ""

        # Slash commands always bypass mention gating
        if not text.startswith("/") and self._require_mention:
            bot_username = "@" + (context.bot.username or "")
            if bot_username.lower() not in text.lower():
                return
        await self._dispatch(update)

    async def _on_sticker(self, update: Update, context) -> None:
        """
        Handle incoming sticker messages.

        Extracts the sticker's emoji equivalent (if available) and dispatches
        it as a text message like ``[Sticker: {emoji}]`` so the pipeline can
        at least acknowledge the sticker.
        """
        sticker = update.message.sticker
        text = f"[Sticker: {sticker.emoji}]" if sticker and sticker.emoji else "[Sticker]"
        await self._dispatch(update, text_override=text)

    async def _on_voice(self, update: Update, context) -> None:
        """
        Handle incoming voice messages and audio files.

        Extracts the voice ``file_id`` and populates it in the ChannelMessage
        ``raw`` dict for downstream transcription (e.g. AudioProcessor).
        """
        voice = update.message.voice or update.message.audio
        if not voice:
            return
        text = "[Voice message]"
        await self._dispatch(
            update,
            text_override=text,
            extra_raw={
                "voice_file_id": voice.file_id,
                "voice_duration": voice.duration,
                "voice_mime_type": getattr(voice, "mime_type", ""),
            },
        )

    async def _dispatch(
        self,
        update: Update,
        text_override: str | None = None,
        extra_raw: dict | None = None,
    ) -> None:
        """
        Normalise a PTB Update to a ChannelMessage and enqueue it.

        Builds a ChannelMessage from the Update fields and calls the injected
        enqueue_fn. If enqueue_fn is None (test mode), logs a warning and drops.

        DM security check runs here (NOT in receive()) because TelegramChannel
        uses PTB handler callbacks — receive() always raises NotImplementedError.

        After successful enqueue, persists the update_id and records activity
        for the stall watchdog.

        Args:
            update:        The PTB Update object.
            text_override: If set, use this instead of ``msg.text`` (used by
                           sticker and voice handlers).
            extra_raw:     Additional keys merged into the ``raw`` dict (e.g.
                           ``voice_file_id``).
        """
        # Record offset and watchdog activity for EVERY update (including
        # blocked DMs) so that:
        #   1. _last_offset advances — blocked updates won't replay after restart
        #   2. record_activity() fires — blocked DMs don't trigger stall detection
        update_id = update.update_id
        if update_id is not None and self._offset_store:
            self._last_offset = update_id
            self._offset_store.save(update_id, self._bot_id)
        if self._watchdog:
            self._watchdog.record_activity()

        msg = update.message
        chat = msg.chat
        is_group = chat.type in ("group", "supergroup")

        # Build raw dict and merge extra data if provided
        raw = update.to_dict()
        if extra_raw:
            raw.update(extra_raw)

        # Extract forum topic thread ID (supergroups with topics enabled)
        thread_id = getattr(msg, "message_thread_id", None)
        if thread_id is not None:
            raw["message_thread_id"] = str(thread_id)

        channel_msg = ChannelMessage(
            channel_id="telegram",
            user_id=str(msg.from_user.id) if msg.from_user else str(chat.id),
            chat_id=str(chat.id),
            text=text_override if text_override is not None else (msg.text or ""),
            timestamp=msg.date if isinstance(msg.date, datetime) else datetime.now(),
            is_group=is_group,
            message_id=str(msg.message_id),
            sender_name=msg.from_user.full_name if msg.from_user else "",
            raw=raw,
        )

        # DM security check — only for direct messages, skip groups
        if self.security_config and self._pairing_store and not channel_msg.is_group:
            access = resolve_dm_access(
                channel_msg.user_id, self.security_config, self._pairing_store
            )
            if access != "allow":
                logger.info("[TEL] DM from %s blocked (%s)", channel_msg.user_id, access)
                return

        if self._enqueue_fn:
            await self._enqueue_fn(channel_msg)
        else:
            logger.warning(
                "[TEL] No enqueue_fn set — dropping message from %s", channel_msg.user_id
            )

        # Offset and watchdog activity already recorded at the top of _dispatch

    # ------------------------------------------------------------------
    # Message splitting
    # ------------------------------------------------------------------

    def _split_message(self, text: str) -> list[str]:
        """
        Split *text* into chunks that each fit within ``MAX_CHARS``.

        Split strategy (in priority order):
          1. Paragraph boundaries (``\\n\\n``)
          2. Line boundaries (``\\n``)
          3. Space boundaries
          4. Hard cut at ``MAX_CHARS``

        Returns a list with at least one element (the original text if it
        fits within the limit).
        """
        limit = self.MAX_CHARS
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            # Try paragraph boundary
            cut = remaining.rfind("\n\n", 0, limit)
            if cut > 0:
                chunks.append(remaining[:cut])
                remaining = remaining[cut + 2 :]  # skip the \n\n
                continue

            # Try line boundary
            cut = remaining.rfind("\n", 0, limit)
            if cut > 0:
                chunks.append(remaining[:cut])
                remaining = remaining[cut + 1 :]  # skip the \n
                continue

            # Try space boundary
            cut = remaining.rfind(" ", 0, limit)
            if cut > 0:
                chunks.append(remaining[:cut])
                remaining = remaining[cut + 1 :]  # skip the space
                continue

            # Hard cut — no natural boundary found
            chunks.append(remaining[:limit])
            remaining = remaining[limit:]

        return chunks
