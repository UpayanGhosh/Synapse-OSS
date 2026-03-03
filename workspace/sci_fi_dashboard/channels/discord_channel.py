"""
DiscordChannel — discord.py v2.x async client adapter for the Synapse channel pipeline.

CRITICAL NAMING: This file is intentionally named `discord_channel.py` (NOT `discord.py`).
Naming it `discord.py` would shadow the `discord` package itself, breaking all imports.

Lifecycle:
  start()  → creates discord.Client with message_content privileged intent,
             registers on_ready / on_message event handlers, then awaits
             client.start(token). Never uses client.run() — that blocks the
             event loop. ChannelRegistry wraps start() in asyncio.create_task().
  stop()   → closes the discord client gracefully; sets status to "stopped".

Message routing:
  DMs (message.guild is None) are always dispatched to the pipeline.
  Server messages are dispatched only when the bot is @mentioned.
  Empty content for DM/@mention = MESSAGE_CONTENT privileged intent not enabled
  in Discord Developer Portal → logs CRITICAL + disables channel.

Windows note:
  discord.py 2.x requires the ProactorEventLoop on Windows; this is already set
  by whatsapp.py at module import time. No double-set needed here.
"""

import asyncio
import logging
from datetime import datetime

import discord

from .base import BaseChannel, ChannelMessage

logger = logging.getLogger(__name__)


class DiscordChannel(BaseChannel):
    """
    Discord channel adapter via discord.py v2.x.

    Listens for DMs and bot @mentions, normalises them into ChannelMessage objects,
    and dispatches them to an async enqueue_fn. Outbound messages are sent via
    channel.send() using get_channel() with fetch_channel() as a fallback.

    The privileged MESSAGE_CONTENT intent is required and must also be enabled in
    the Discord Developer Portal (Bot -> Privileged Gateway Intents).
    """

    def __init__(
        self,
        token: str,
        allowed_channel_ids: list[int] | None = None,
        enqueue_fn=None,
    ) -> None:
        """
        Args:
            token:               Discord bot token from Developer Portal.
            allowed_channel_ids: Optional allowlist of guild channel IDs. When set,
                                 server @mentions in channels not on the list are
                                 silently ignored. Has no effect on DMs.
            enqueue_fn:          Async callable(ChannelMessage) -> None. Called for
                                 each accepted inbound message.
        """
        self._token = token
        self._allowed_channel_ids: list[int] = allowed_channel_ids or []
        self._enqueue_fn = enqueue_fn  # async callable(ChannelMessage) -> None
        self._client: discord.Client | None = None
        self._status: str = "stopped"

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def channel_id(self) -> str:
        return "discord"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Connect to Discord and run the event loop until cancelled or login fails.

        Uses await client.start(token) — never client.run() — so it is safe to
        call inside an existing asyncio event loop (e.g. uvicorn's).

        CancelledError is caught, stop() is called for graceful shutdown, then
        re-raised so the ChannelRegistry task is properly cancelled.
        """
        intents = discord.Intents.default()
        intents.message_content = True  # privileged — also enable in Discord Developer Portal

        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready() -> None:
            logger.info("[DIS] Logged in as %s (id=%s)", self._client.user, self._client.user.id)
            self._status = "running"

        @self._client.event
        async def on_message(message: discord.Message) -> None:
            # Never respond to own messages
            if message.author == self._client.user:
                return

            is_dm = message.guild is None
            is_mention = self._client.user in message.mentions

            # Ignore server messages that are not @mentions
            if not is_dm and not is_mention:
                return

            # Allowed channel filter (server messages only)
            if (
                not is_dm
                and self._allowed_channel_ids
                and message.channel.id not in self._allowed_channel_ids
            ):
                return

            # Guard: DMs and @mentions are exempt from MESSAGE_CONTENT intent restriction.
            # Empty content here = privileged intent NOT enabled in Discord Developer Portal.
            if not message.content.strip():
                logger.critical(
                    "[DIS] MESSAGE_CONTENT privileged intent is missing from Discord Developer "
                    "Portal. Bot received empty content for DM/@mention from %s. Disabling "
                    "Discord channel. Fix: Developer Portal -> Bot -> Privileged Gateway "
                    "Intents -> MESSAGE CONTENT.",
                    message.author,
                )
                self._status = "failed"
                asyncio.create_task(self.stop())
                return

            # Normalize and enqueue
            channel_msg = await self.receive(
                {
                    "content": message.content,
                    "author_id": str(message.author.id),
                    "author_name": message.author.display_name,
                    "channel_discord_id": message.channel.id,
                    "message_id": str(message.id),
                    "is_group": not is_dm,
                    "reply_callable": message.reply,  # stored for native Discord reply threading
                }
            )
            if self._enqueue_fn:
                await self._enqueue_fn(channel_msg)

        try:
            await self._client.start(self._token)
        except discord.LoginFailure as exc:
            self._status = "failed"
            logger.error(
                "[DIS] Login failed — invalid bot token. "
                "Check channels.discord.token in synapse.json: %s",
                exc,
            )
        except asyncio.CancelledError:
            await self.stop()
            raise

    async def stop(self) -> None:
        """Close the discord client and set status to 'stopped'."""
        if self._client and not self._client.is_closed():
            await self._client.close()
        self._status = "stopped"
        logger.info("[DIS] Discord channel stopped")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """
        Return a status dict describing the Discord channel health.

        Returns:
            {
                "status":     "ok" | "down",
                "channel":    "discord",
                "bot_user":   str | None,
                "bot_status": str,
                "guilds":     int,
            }
        """
        is_ready = (
            self._client is not None
            and not self._client.is_closed()
            and self._client.user is not None
        )
        return {
            "status": "ok" if is_ready else "down",
            "channel": "discord",
            "bot_user": str(self._client.user) if is_ready else None,
            "bot_status": self._status,
            "guilds": len(self._client.guilds) if is_ready else 0,
        }

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    async def send(self, chat_id: str, text: str) -> bool:
        """
        Send text to a Discord channel by ID.

        Uses get_channel() (cache-first) with fetch_channel() as a fallback for
        channels not in the local cache (e.g. private threads, cross-guild channels).

        Args:
            chat_id: Discord channel ID as a string (e.g. "1234567890123456789").
            text:    Message text to send.

        Returns:
            True on success, False on any error.
        """
        if not self._client:
            return False
        try:
            channel = self._client.get_channel(int(chat_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(chat_id))
            await channel.send(text)
            return True
        except discord.NotFound:
            logger.error("[DIS] Channel %s not found", chat_id)
            return False
        except discord.HTTPException as exc:
            logger.error("[DIS] send() failed: %s", exc)
            return False

    async def send_typing(self, chat_id: str) -> None:
        """
        No-op: Discord typing is managed inline in the on_message handler via
        `async with message.channel.typing():` before processing. A standalone
        send_typing() has no message context and no useful Discord API equivalent.
        """
        pass  # Discord typing managed inline in on_message handler; no standalone API

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """No-op: Discord bots cannot mark messages as read via the bot API."""
        pass  # Discord bots cannot mark messages as read via API

    # ------------------------------------------------------------------
    # Inbound normalisation
    # ------------------------------------------------------------------

    async def receive(self, raw_payload: dict) -> ChannelMessage:
        """
        Normalise a raw on_message event dict into a ChannelMessage.

        Expected keys in raw_payload (all optional — missing keys yield safe defaults):
            content            : str   — message text
            author_id          : str   — Discord user snowflake ID
            author_name        : str   — display name
            channel_discord_id : int   — Discord channel snowflake ID (used as chat_id)
            message_id         : str   — Discord message snowflake ID
            is_group           : bool  — True for server messages, False for DMs
            reply_callable     : any   — stored as-is in raw for downstream threading
        """
        return ChannelMessage(
            channel_id="discord",
            user_id=raw_payload.get("author_id", ""),
            chat_id=str(raw_payload.get("channel_discord_id", "")),
            text=raw_payload.get("content", ""),
            timestamp=datetime.now(),
            is_group=raw_payload.get("is_group", False),
            message_id=raw_payload.get("message_id", ""),
            sender_name=raw_payload.get("author_name", ""),
            raw=raw_payload,
        )
