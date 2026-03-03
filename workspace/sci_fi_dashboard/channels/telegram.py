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

Error handling:
  Conflict (409) — another instance polling same token; logs clearly, no crash.
  InvalidToken   — bad token; logs clearly, no crash.
  TelegramError  — any other Telegram API error; logs clearly, no crash.
  CancelledError — ChannelRegistry.stop_all() cancelled the task; stop() called,
                   error re-raised so ChannelRegistry is aware.
"""

import asyncio
import contextlib
import logging
from datetime import datetime

from telegram import Update
from telegram.constants import ChatAction
from telegram.error import Conflict, InvalidToken, TelegramError
from telegram.ext import ApplicationBuilder, MessageHandler, Updater, filters

from .base import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)


class TelegramChannel(BaseChannel):
    """
    Telegram channel adapter via python-telegram-bot v22+ long polling.

    Registers DM and group @mention handlers. Normalises PTB Update objects
    into ChannelMessage DTOs and routes them via the injected enqueue_fn
    callback into the existing MessageWorker pipeline.

    Args:
        token:      Telegram Bot API token from @BotFather.
        enqueue_fn: Async callable(ChannelMessage) -> None injected by api_gateway.py.
                    If None, incoming messages are logged and dropped (safe for tests).
    """

    def __init__(self, token: str, enqueue_fn=None) -> None:
        self._token = token
        self._enqueue_fn = enqueue_fn  # async callable(ChannelMessage) -> None
        self._app = None  # telegram.ext.Application
        self._updater = None  # telegram.ext.Updater
        self._status: str = "stopped"
        self._bot_info: dict = {}

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

        Called by ChannelRegistry.start_all() via asyncio.create_task().
        CancelledError propagates after calling stop().
        """
        self._app = ApplicationBuilder().token(self._token).updater(None).build()

        # Register handlers BEFORE initialize() — bot.username not yet available.
        # Use Entity("mention") filter + in-handler username check for groups
        # (avoids pre-initialize timing issue with filters.Mention).
        self._app.add_handler(
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                self._on_message,
            )
        )
        self._app.add_handler(
            MessageHandler(
                filters.ChatType.GROUPS & filters.TEXT & filters.Entity("mention"),
                self._on_group_message,
            )
        )

        # Create Updater manually — shares bot and update_queue with Application.
        self._updater = Updater(self._app.bot, update_queue=self._app.update_queue)

        try:
            # Clear any stale webhook to prevent 409 Conflict.
            await self._app.bot.delete_webhook(drop_pending_updates=True)
            logger.info("[TEL] Webhook cleared — starting long polling")

            await self._updater.initialize()
            await self._app.initialize()
            await self._updater.start_polling(drop_pending_updates=True)
            await self._app.start()

            self._status = "running"
            bot_me = await self._app.bot.get_me()
            self._bot_info = {"username": bot_me.username, "id": bot_me.id}
            logger.info("[TEL] Polling as @%s (id=%d)", bot_me.username, bot_me.id)

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
        Gracefully shut down the Updater and Application.

        Stops the Updater (halts long polling), then stops and shuts down the
        Application (closes the HTTP session). Sets _status to "stopped".
        """
        if self._updater and self._updater.running:
            await self._updater.stop()
        if self._app and self._app.running:
            await self._app.stop()
            await self._app.shutdown()  # MUST call shutdown() to close HTTP session
        self._status = "stopped"
        logger.info("[TEL] Telegram channel stopped")

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

        Args:
            chat_id: Telegram chat/user ID as a string.
            text:    Message body to deliver.

        Returns:
            True on success, False if Application is not ready or send failed.
        """
        if not self._app:
            return False
        try:
            await self._app.bot.send_message(chat_id=int(chat_id), text=text)
            return True
        except TelegramError as exc:
            logger.error("[TEL] send() failed for chat %s: %s", chat_id, exc)
            return False

    async def send_typing(self, chat_id: str) -> None:
        """
        Send a TYPING chat action to the given Telegram chat.

        Args:
            chat_id: Telegram chat/user ID as a string.
        """
        if not self._app:
            return
        with contextlib.suppress(TelegramError):
            await self._app.bot.send_chat_action(chat_id=int(chat_id), action=ChatAction.TYPING)

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """
        No-op — Telegram bots have no read-receipt API.

        Args:
            chat_id:    Telegram chat ID (unused).
            message_id: Message ID (unused).
        """

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
        Handle group messages — only dispatch if the bot is @mentioned.

        Uses a runtime in-handler check (context.bot.username) rather than
        filters.Mention to avoid the pre-initialize timing issue where
        filters.Mention tries to resolve bot.username before PTB is initialised.
        """
        text = update.message.text or ""
        bot_username = "@" + (context.bot.username or "")
        if bot_username.lower() not in text.lower():
            return
        await self._dispatch(update)

    async def _dispatch(self, update: Update) -> None:
        """
        Normalise a PTB Update to a ChannelMessage and enqueue it.

        Builds a ChannelMessage from the Update fields and calls the injected
        enqueue_fn. If enqueue_fn is None (test mode), logs a warning and drops.
        """
        msg = update.message
        chat = msg.chat
        is_group = chat.type in ("group", "supergroup")
        channel_msg = ChannelMessage(
            channel_id="telegram",
            user_id=str(msg.from_user.id) if msg.from_user else str(chat.id),
            chat_id=str(chat.id),
            text=msg.text or "",
            timestamp=msg.date if isinstance(msg.date, datetime) else datetime.now(),
            is_group=is_group,
            message_id=str(msg.message_id),
            sender_name=msg.from_user.full_name if msg.from_user else "",
            raw=update.to_dict(),
        )
        if self._enqueue_fn:
            await self._enqueue_fn(channel_msg)
        else:
            logger.warning(
                "[TEL] No enqueue_fn set — dropping message from %s", channel_msg.user_id
            )
