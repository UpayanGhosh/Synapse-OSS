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

Features:
  - Thread support: create_thread detection, send_in_thread(), thread_id in MsgContext.
  - Rate-limit aware retry: 429 → sleep(retry_after + jitter) + 1 retry; 5xx → 2 retries
    with exponential backoff; 4xx (non-429) → no retry.
  - Message splitting: auto-splits outbound text at paragraph/line/word/hard boundaries
    when exceeding Discord's 2000-char limit.
  - Typing keepalive: send_typing_loop() triggers typing every 8s until cancelled.
  - Voice message sending via discord.File.
  - PluralKit proxy dedup: skips messages from the PluralKit bot to avoid double-processing.

Windows note:
  discord.py 2.x requires the ProactorEventLoop on Windows; this is already set
  by whatsapp.py at module import time. No double-set needed here.
"""

import asyncio
import logging
import random
from collections import OrderedDict
from datetime import datetime

import discord

from .base import BaseChannel, ChannelMessage
from .security import ChannelSecurityConfig, PairingStore, resolve_dm_access

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

    MAX_CHARS: int = 2000
    """Discord's per-message character limit."""

    _PLURALKIT_BOT_ID: int = 466378653216014359
    """PluralKit's application/bot ID — used to skip proxy messages."""

    _SENT_CACHE_MAX: int = 1000
    """Max entries in the sent-message LRU cache."""

    def __init__(
        self,
        token: str,
        allowed_channel_ids: list[int] | None = None,
        enqueue_fn=None,
        security_config: ChannelSecurityConfig | None = None,
        pairing_store: PairingStore | None = None,
    ) -> None:
        """
        Args:
            token:               Discord bot token from Developer Portal.
            allowed_channel_ids: Optional allowlist of guild channel IDs. When set,
                                 server @mentions in channels not on the list are
                                 silently ignored. Has no effect on DMs.
            enqueue_fn:          Async callable(ChannelMessage) -> None. Called for
                                 each accepted inbound message.
            security_config:     Optional DM access control config.
            pairing_store:       Optional pairing store for DM access control.
        """
        self._token = token
        self._allowed_channel_ids: list[int] = allowed_channel_ids or []
        self._enqueue_fn = enqueue_fn  # async callable(ChannelMessage) -> None
        self._client: discord.Client | None = None
        self._status: str = "stopped"
        self._shutdown_task: asyncio.Task | None = None
        self.security_config = security_config
        self._pairing_store = pairing_store

        # Sent-message LRU cache: internal_message_id → Discord message.id
        self._sent_message_cache: OrderedDict[str, int] = OrderedDict()

        # Rate-limit observability counter
        self._rate_limit_hits: int = 0

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

            # PluralKit proxy dedup — skip messages from PluralKit bot webhooks
            if message.webhook_id is not None and message.application_id == self._PLURALKIT_BOT_ID:
                logger.debug("[DIS] Skipping PluralKit proxy message %s", message.id)
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
                self._shutdown_task = asyncio.create_task(self.stop())
                self._shutdown_task.add_done_callback(
                    lambda t: t.result() if not t.cancelled() and not t.exception() else None
                )
                return

            # Detect thread context
            thread_id = ""
            if message.thread is not None:
                thread_id = str(message.thread.id)

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
                    "thread_id": thread_id,
                }
            )
            if channel_msg is None:
                return  # blocked by DM access control
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
        Send text to a Discord channel by ID, with auto-splitting and retry.

        Uses get_channel() (cache-first) with fetch_channel() as a fallback for
        channels not in the local cache (e.g. private threads, cross-guild channels).

        If the text exceeds MAX_CHARS (2000), it is split into multiple chunks
        sent sequentially with a 0.5s delay between them.

        On 429 rate-limit errors, sleeps for retry_after + jitter and retries once.
        On 5xx server errors, retries up to 2 more times with exponential backoff.
        On 4xx client errors (except 429), fails immediately.

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
        except discord.NotFound:
            logger.error("[DIS] Channel %s not found", chat_id)
            return False
        except discord.HTTPException as exc:
            logger.error("[DIS] Failed to fetch channel %s: %s", chat_id, exc)
            return False

        chunks = self._split_message(text)
        last_msg: discord.Message | None = None
        for i, chunk in enumerate(chunks):
            msg = await self._send_chunk(channel, chunk)
            if msg is None:
                return False
            last_msg = msg
            # Delay between chunks to avoid burst rate-limits
            if i < len(chunks) - 1:
                await asyncio.sleep(0.5)
        # Cache the last sent message for future reply-to functionality
        if last_msg is not None:
            self._cache_sent_message(str(last_msg.id), last_msg.id)
        return True

    async def _send_chunk(self, channel, text: str) -> discord.Message | None:
        """Send a single chunk with rate-limit and server-error retry logic.

        Returns the discord.Message on success, None on unrecoverable failure.
        """
        # First attempt
        result = await self._try_send(channel, text)
        if isinstance(result, discord.Message):
            return result
        if result is False:
            return None

        # result is an HTTPException — decide retry strategy
        exc = result

        # 429 rate-limit: sleep + jitter, retry once
        if exc.status == 429:
            self._rate_limit_hits += 1
            retry_after = getattr(exc, "retry_after", 1.0) or 1.0
            jitter = random.uniform(0.1, 0.5)
            logger.warning(
                "[DIS] Rate-limited (429). Retrying after %.2fs (retry_after=%.2f + jitter=%.2f)",
                retry_after + jitter,
                retry_after,
                jitter,
            )
            await asyncio.sleep(retry_after + jitter)
            retry_result = await self._try_send(channel, text)
            if isinstance(retry_result, discord.Message):
                return retry_result
            logger.error("[DIS] send() failed after rate-limit retry: %s", retry_result)
            return None

        # 5xx server error: retry up to 2 more times with exponential backoff
        if exc.status >= 500:
            for attempt, backoff in enumerate((1.0, 2.0), start=1):
                logger.warning(
                    "[DIS] Server error (%d). Retry %d/2 after %.1fs",
                    exc.status,
                    attempt,
                    backoff,
                )
                await asyncio.sleep(backoff)
                retry_result = await self._try_send(channel, text)
                if isinstance(retry_result, discord.Message):
                    return retry_result
                if retry_result is False:
                    return None
                # Update exc for logging if we exhaust retries
                exc = retry_result
            logger.error("[DIS] send() failed after 2 server-error retries: %s", exc)
            return None

        # 4xx (non-429): don't retry
        logger.error("[DIS] send() failed with client error (%d): %s", exc.status, exc)
        return None

    @staticmethod
    async def _try_send(channel, text: str) -> discord.Message | bool | discord.HTTPException:
        """Attempt a single channel.send().

        Returns:
            discord.Message on success, False on NotFound, or the HTTPException
            for retry decisions.
        """
        try:
            return await channel.send(text)
        except discord.NotFound:
            logger.error("[DIS] Channel disappeared during send")
            return False
        except discord.HTTPException as exc:
            return exc

    @staticmethod
    def _split_message(text: str) -> list[str]:
        """Split text into chunks that fit within Discord's 2000-char limit.

        Split priority:
          1. Paragraph boundaries (\\n\\n)
          2. Line boundaries (\\n)
          3. Space boundaries
          4. Hard cut at MAX_CHARS
        """
        limit = DiscordChannel.MAX_CHARS
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break

            # Try paragraph boundary
            cut = text.rfind("\n\n", 0, limit)
            if cut > 0:
                chunks.append(text[:cut])
                text = text[cut + 2 :]  # skip the \n\n separator
                continue

            # Try line boundary
            cut = text.rfind("\n", 0, limit)
            if cut > 0:
                chunks.append(text[:cut])
                text = text[cut + 1 :]  # skip the \n separator
                continue

            # Try space boundary
            cut = text.rfind(" ", 0, limit)
            if cut > 0:
                chunks.append(text[:cut])
                text = text[cut + 1 :]  # skip the space
                continue

            # Hard cut — no natural boundary found
            chunks.append(text[:limit])
            text = text[limit:]

        return chunks

    async def send_typing(self, chat_id: str) -> None:
        """
        Send a single typing indicator to the given Discord channel.

        Uses trigger_typing() which sends one typing event lasting ~10s on the
        client side. For long-running operations, use send_typing_loop() instead.

        Args:
            chat_id: Discord channel ID as a string.
        """
        if not self._client:
            return
        try:
            channel = self._client.get_channel(int(chat_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(chat_id))
            await channel.trigger_typing()
        except Exception:
            logger.debug("[DIS] send_typing() failed for channel %s", chat_id)

    async def send_typing_loop(self, chat_id: str, cancel_event: asyncio.Event) -> None:
        """Send typing indicator every 8s until cancel_event is set.

        Discord typing indicators last ~10s client-side; re-triggering every 8s
        keeps the indicator visible continuously. The loop breaks immediately
        when cancel_event is set or on any send error.

        Args:
            chat_id:      Discord channel ID as a string.
            cancel_event: asyncio.Event — set this to stop the loop.
        """
        if not self._client:
            return
        try:
            channel = self._client.get_channel(int(chat_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(chat_id))
        except Exception:
            return
        if not channel:
            return
        while not cancel_event.is_set():
            try:
                await channel.trigger_typing()
            except Exception:
                break
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=8.0)
                break
            except TimeoutError:
                continue

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """No-op: Discord bots cannot mark messages as read via the bot API."""
        pass  # Discord bots cannot mark messages as read via API

    # ------------------------------------------------------------------
    # Voice / Thread / Extended messaging
    # ------------------------------------------------------------------

    async def send_voice(self, chat_id: str, file_path: str) -> bool:
        """Send a voice/audio file to a Discord channel.

        Uses discord.File to upload the file. Returns True on success, False on
        any error (missing client, channel not found, upload failure).

        Args:
            chat_id:   Discord channel ID as a string.
            file_path: Local filesystem path to the audio file.

        Returns:
            True on success, False on failure.
        """
        if not self._client:
            return False
        try:
            channel = self._client.get_channel(int(chat_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(chat_id))
            await channel.send(file=discord.File(file_path))
            return True
        except discord.NotFound:
            logger.error("[DIS] Channel %s not found for send_voice()", chat_id)
            return False
        except (discord.HTTPException, FileNotFoundError, OSError) as exc:
            logger.error("[DIS] send_voice() failed: %s", exc)
            return False

    async def send_in_thread(self, channel_id: str, thread_name: str, text: str) -> str | None:
        """Create a thread on a channel and send text in it.

        Looks up the channel, creates a public thread with the given name, sends
        the text message inside the thread, and returns the thread ID as a string.

        Args:
            channel_id:  Discord channel ID as a string.
            thread_name: Display name for the new thread.
            text:        Message to send inside the newly created thread.

        Returns:
            The thread ID as a string on success, None on failure.
        """
        if not self._client:
            return None
        try:
            channel = self._client.get_channel(int(channel_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(channel_id))
            thread = await channel.create_thread(
                name=thread_name, type=discord.ChannelType.public_thread
            )
            await thread.send(text)
            return str(thread.id)
        except discord.NotFound:
            logger.error("[DIS] Channel %s not found for send_in_thread()", channel_id)
            return None
        except discord.HTTPException as exc:
            logger.error("[DIS] send_in_thread() failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Sent-message cache helpers
    # ------------------------------------------------------------------

    def _cache_sent_message(self, internal_id: str, discord_id: int) -> None:
        """Record a sent message in the LRU cache.

        Evicts the oldest entry when the cache exceeds _SENT_CACHE_MAX.
        """
        if internal_id in self._sent_message_cache:
            self._sent_message_cache.move_to_end(internal_id)
        self._sent_message_cache[internal_id] = discord_id
        while len(self._sent_message_cache) > self._SENT_CACHE_MAX:
            self._sent_message_cache.popitem(last=False)

    def _get_cached_discord_id(self, internal_id: str) -> int | None:
        """Look up a Discord message ID by internal message ID."""
        return self._sent_message_cache.get(internal_id)

    # ------------------------------------------------------------------
    # Inbound normalisation
    # ------------------------------------------------------------------

    async def receive(self, raw_payload: dict) -> ChannelMessage | None:
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

        Returns None for blocked DMs.
        """
        is_group = raw_payload.get("is_group", False)
        user_id = raw_payload.get("author_id", "")

        # DM security check — only for direct messages, skip groups
        if self.security_config and self._pairing_store and not is_group:
            access = resolve_dm_access(user_id, self.security_config, self._pairing_store)
            if access != "allow":
                logger.info("[DIS] DM from %s blocked (%s)", user_id, access)
                return None

        return ChannelMessage(
            channel_id="discord",
            user_id=user_id,
            chat_id=str(raw_payload.get("channel_discord_id", "")),
            text=raw_payload.get("content", ""),
            timestamp=datetime.now(),
            is_group=is_group,
            message_id=raw_payload.get("message_id", ""),
            sender_name=raw_payload.get("author_name", ""),
            raw=raw_payload,
        )
