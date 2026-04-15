"""
SlackChannel — slack-bolt AsyncApp + Socket Mode adapter that subclasses BaseChannel.

No public webhook URL required — communicates via Socket Mode WebSocket connection,
making it suitable for self-hosters behind NAT.

Lifecycle:
  start()  → creates AsyncApp + AsyncSocketModeHandler, registers event handlers,
             calls connect_async() (non-blocking), then parks with asyncio.sleep(inf).
             Designed to run as asyncio.create_task(channel.start()) from ChannelRegistry.
  stop()   → calls handler.close_async(); sets status to "stopped".

Token requirements:
  bot_token (xoxb- prefix): for API calls via AsyncWebClient (chat_postMessage etc.)
  app_token (xapp- prefix): for Socket Mode WebSocket; must have connections:write scope

Event routing:
  DMs:            @app.event("message") restricted to channel_type=="im" to prevent
                  double-dispatch when a channel @mention triggers both events.
  Channel @mentions: @app.event("app_mention")

Thread context:
  Incoming messages with ``thread_ts`` are detected as thread replies. Replies sent
  by the bot automatically go back into the same thread. Active threads (threads
  where the bot has participated within the last 24 h) are auto-monitored: messages
  in those threads are processed even without an @mention.
"""

import asyncio
import logging
import time
from datetime import datetime

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from .base import BaseChannel, ChannelMessage
from .security import ChannelSecurityConfig, PairingStore, resolve_dm_access

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token validation helper
# ---------------------------------------------------------------------------


def _validate_slack_tokens(bot_token: str, app_token: str) -> None:
    """
    Validate Slack token prefixes at construction time.

    Raises ValueError with a clear message if either token has the wrong format.
    Called from SlackChannel.__init__ — fail-fast before ChannelRegistry.start_all().

    Args:
        bot_token: Must start with 'xoxb-'. Create in Slack app OAuth & Permissions.
        app_token: Must start with 'xapp-'. Create in Basic Information -> App-Level Tokens
                   with the connections:write scope.

    Raises:
        ValueError: If either token has an incorrect prefix.
    """
    if not bot_token.startswith("xoxb-"):
        raise ValueError(
            f"Slack bot_token must start with 'xoxb-', got prefix: {bot_token[:10]!r}. "
            "Create a bot token in your Slack app's OAuth & Permissions page."
        )
    if not app_token.startswith("xapp-"):
        raise ValueError(
            f"Slack app_token must start with 'xapp-', got prefix: {app_token[:10]!r}. "
            "Create an app-level token in Basic Information -> App-Level Tokens "
            "with the connections:write scope."
        )


# ---------------------------------------------------------------------------
# SlackChannel
# ---------------------------------------------------------------------------


class SlackChannel(BaseChannel):
    """
    Slack channel adapter using slack-bolt AsyncApp with Socket Mode transport.

    Receives DMs via @app.event('message') (filtered to channel_type=='im') and
    channel @mentions via @app.event('app_mention'). Sends replies via
    AsyncWebClient.chat_postMessage. No public webhook URL required.

    Thread awareness:
      Incoming messages with ``thread_ts != ts`` are treated as thread replies.
      The bot tracks threads it has participated in via ``_active_threads`` and
      auto-processes messages in those threads (within 24 h) without requiring
      an @mention.
    """

    MAX_CHARS: int = 3000  # Slack section limit (4000 msg limit, 3000 section limit)

    # 24 hours in seconds — auto-participation window for active threads
    _THREAD_TTL_SECS: float = 86_400.0

    # Maximum tracked threads before oldest-eviction kicks in
    _MAX_ACTIVE_THREADS: int = 500

    def __init__(
        self,
        bot_token: str,  # xoxb- prefix: for API calls
        app_token: str,  # xapp- prefix: for Socket Mode WebSocket
        enqueue_fn=None,  # async callable(ChannelMessage) -> None
        security_config: ChannelSecurityConfig | None = None,
        pairing_store: PairingStore | None = None,
    ) -> None:
        """
        Initialize SlackChannel with token validation.

        Args:
            bot_token:  Slack bot OAuth token (xoxb- prefix). Used for API calls.
            app_token:  Slack app-level token (xapp- prefix). Used for Socket Mode.
            enqueue_fn: Async callable receiving a ChannelMessage; routes into the
                        pipeline. Pass None in tests / when channel is wired separately.
            security_config: Optional DM access control config.
            pairing_store:   Optional pairing store for DM access control.

        Raises:
            ValueError: If bot_token or app_token has wrong prefix (fail-fast at init).
        """
        _validate_slack_tokens(bot_token, app_token)  # fail-fast at construction time
        self._bot_token = bot_token
        self._app_token = app_token
        self._enqueue_fn = enqueue_fn
        self._app: AsyncApp | None = None
        self._handler: AsyncSocketModeHandler | None = None
        self._status: str = "stopped"
        self._web_client = AsyncWebClient(token=bot_token)
        self.security_config = security_config
        self._pairing_store = pairing_store

        # Thread tracking -------------------------------------------------
        # Maps thread_ts → last-activity monotonic timestamp for threads the
        # bot has participated in. Capped at _MAX_ACTIVE_THREADS entries.
        self._active_threads: dict[str, float] = {}
        # Maps chat_id → most recent thread_ts for that conversation, so
        # outbound send() can reply in the correct thread automatically.
        self._last_thread_ts: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def channel_id(self) -> str:
        return "slack"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Register Slack event handlers and connect Socket Mode as a background task.

        Creates AsyncApp + AsyncSocketModeHandler, registers event handlers BEFORE
        connecting (events can arrive immediately on connect), then calls connect_async()
        which opens the WebSocket without blocking (unlike start_async() which would
        park here forever). Parks with asyncio.sleep(float('inf')) until CancelledError
        from ChannelRegistry.stop_all().

        Called by ChannelRegistry.start_all() as asyncio.create_task(channel.start()).
        CancelledError propagates after graceful stop().
        """
        self._app = AsyncApp(token=self._bot_token)
        self._handler = AsyncSocketModeHandler(self._app, self._app_token)

        # Register handlers BEFORE connecting — events can arrive immediately on connect
        self._register_handlers()

        try:
            # connect_async() opens the WebSocket and returns immediately (no blocking)
            # Do NOT use await self._handler.start_async() — that calls asyncio.sleep(inf)
            # internally and would block ChannelRegistry.start_all() for this channel only.
            await self._handler.connect_async()
            self._status = "running"
            logger.info("[Slack] Socket Mode connected")

            # Park until CancelledError from ChannelRegistry.stop_all()
            await asyncio.sleep(float("inf"))

        except asyncio.CancelledError:
            await self.stop()
            raise
        except Exception as exc:
            self._status = "failed"
            logger.error("[Slack] Failed to connect Socket Mode: %s", exc)

    async def stop(self) -> None:
        """
        Gracefully disconnect from Slack Socket Mode.

        Calls handler.close_async() if a handler exists. Safe to call multiple times.
        """
        if self._handler:
            try:
                await self._handler.close_async()
            except Exception as exc:
                logger.warning("[Slack] Error during Socket Mode close: %s", exc)
        self._status = "stopped"
        logger.info("[Slack] Socket Mode disconnected")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> dict:
        """
        Return a status dict describing the Slack channel health.

        Returns:
            {
                "status":      "ok" | "down",
                "channel":     "slack",
                "socket_mode": str,  # internal _status value
            }
        """
        return {
            "status": "ok" if self._status == "running" else "down",
            "channel": "slack",
            "socket_mode": self._status,
        }

    # ------------------------------------------------------------------
    # Messaging (outbound)
    # ------------------------------------------------------------------

    async def send(
        self,
        chat_id: str,
        text: str,
        thread_ts: str | None = None,
    ) -> bool:
        """
        Send text to a Slack channel or DM via chat_postMessage.

        If *text* exceeds ``MAX_CHARS`` (3000) it is automatically split into
        multiple messages at natural boundaries (paragraph > line > word > hard
        cut). Each chunk is sent with a small delay to respect rate limits.

        When *thread_ts* is provided (or a thread_ts was recorded for *chat_id*
        by a prior inbound message), the reply is posted into that thread.

        Args:
            chat_id:   Slack channel ID (e.g. 'C12345') or DM channel ID ('D67890').
            text:      Message body to deliver.
            thread_ts: Optional Slack thread timestamp. If omitted, falls back to
                       the most recent inbound thread_ts for *chat_id*.

        Returns:
            True on success, False if the Slack API call failed.
        """
        # Resolve thread_ts: explicit param > last-known inbound thread
        resolved_thread = thread_ts or self._last_thread_ts.get(chat_id)

        chunks = self._split_message(text)
        all_ok = True
        for i, chunk in enumerate(chunks):
            try:
                kwargs: dict = {"channel": chat_id, "text": chunk}
                if resolved_thread:
                    kwargs["thread_ts"] = resolved_thread
                await self._web_client.chat_postMessage(**kwargs)
            except Exception as exc:
                all_ok = False
                logger.error("[Slack] send() failed for channel %s: %s", chat_id, exc)
                break  # stop sending remaining chunks on failure
            # Small delay between chunks to avoid burst rate-limits
            if i < len(chunks) - 1:
                await asyncio.sleep(0.3)

        # Record bot participation so auto-participation picks up future msgs
        if all_ok and resolved_thread:
            self._track_thread(resolved_thread)

        return all_ok

    async def send_typing(self, chat_id: str) -> None:
        """
        No-op — Slack bots cannot show typing indicators via the Web API.

        The ``users.typing`` endpoint is undocumented, user-token only, and
        explicitly unsupported for bot tokens. Socket Mode does not expose a
        typing affordance for bots either. This method exists solely to satisfy
        the BaseChannel contract. If Slack adds official bot typing support in
        the future, implement it here.
        """
        pass

    async def mark_read(self, chat_id: str, message_id: str) -> None:
        """
        Slack does not support marking messages as read for bots — no-op.

        The Slack API does not expose a read-status endpoint for bot users.
        This method is a no-op to satisfy the BaseChannel contract.
        """
        pass

    # ------------------------------------------------------------------
    # Inbound normalization
    # ------------------------------------------------------------------

    async def receive(self, raw_payload: dict) -> ChannelMessage:
        """
        Normalize a raw Slack event dict to a ChannelMessage.

        Args:
            raw_payload: Raw Slack event dict (from webhook or test fixture).

        Returns:
            Normalized ChannelMessage ready for the pipeline.
        """
        return ChannelMessage(
            channel_id="slack",
            user_id=raw_payload.get("user", ""),
            chat_id=raw_payload.get("channel", ""),
            text=raw_payload.get("text", ""),
            timestamp=datetime.now(),
            is_group=raw_payload.get("is_group", False),
            message_id=raw_payload.get("ts", ""),
            sender_name=raw_payload.get("user", ""),
            raw=raw_payload,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        """
        Register @app.event handlers on self._app. Called BEFORE connect_async().

        DM handling: @app.event('message') restricted to channel_type=='im'.
        Slack sends BOTH a 'message' event AND an 'app_mention' event for channel
        @mentions. Restricting the message handler to DMs prevents double-dispatch.

        Mention handling: @app.event('app_mention') for channel @mentions.

        Auto-participation: messages in threads the bot has recently participated in
        (within 24 h) are processed without requiring an @mention. This allows
        natural conversation flow once the bot joins a thread.
        """

        @self._app.event("message")
        async def handle_dm(event, say) -> None:  # noqa: F841
            if "bot_id" in event:
                return  # ignore self-messages and other bots

            channel_type = event.get("channel_type", "")

            if channel_type == "im":
                # DMs always processed — no mention required
                await self._dispatch(event, is_group=False)
                return

            # Non-DM channel message — check for auto-participation in threads
            thread_ts = event.get("thread_ts")
            if thread_ts and self._is_active_thread(thread_ts):
                await self._dispatch(event, is_group=True)

        @self._app.event("app_mention")
        async def handle_mention(event, say) -> None:  # noqa: F841
            if "bot_id" in event:
                return  # ignore self-triggered mention events
            await self._dispatch(event, is_group=True)

    async def _dispatch(self, event: dict, is_group: bool) -> None:
        """
        Normalize a Slack event dict to a ChannelMessage and enqueue into the pipeline.

        Thread context:
          If the event contains ``thread_ts`` that differs from ``ts``, the message
          is a reply inside a thread. ``thread_ts`` is stored in ``raw`` so that
          downstream ``MsgContext.from_channel_message()`` can populate
          ``message_thread_id``.  The thread is also recorded in
          ``_last_thread_ts`` so that ``send()`` replies in the correct thread.

        Args:
            event:    Raw Slack event dict from the bolt event handler.
            is_group: True for channel @mentions, False for DMs.
        """
        ts = event.get("ts", "")
        thread_ts = event.get("thread_ts")
        chat_id = event.get("channel", "")
        user_id = event.get("user", "")

        # DM security check — only for direct messages, skip group mentions
        if self.security_config and self._pairing_store and not is_group:
            access = resolve_dm_access(user_id, self.security_config, self._pairing_store)
            if access != "allow":
                logger.info("[Slack] DM from %s blocked (%s)", user_id, access)
                return

        # Build raw dict — include thread_ts for MsgContext population
        raw = dict(event)
        if thread_ts and thread_ts != ts:
            raw["message_thread_id"] = thread_ts

        msg = ChannelMessage(
            channel_id="slack",
            user_id=user_id,
            chat_id=chat_id,
            text=event.get("text", ""),
            timestamp=datetime.now(),
            is_group=is_group,
            message_id=ts,
            sender_name=event.get("user", ""),
            raw=raw,
        )

        # Track thread context for outbound reply routing
        if thread_ts:
            self._last_thread_ts[chat_id] = thread_ts
            self._track_thread(thread_ts)

        if self._enqueue_fn:
            await self._enqueue_fn(msg)

    # ------------------------------------------------------------------
    # Thread tracking
    # ------------------------------------------------------------------

    def _track_thread(self, thread_ts: str) -> None:
        """
        Record bot participation in *thread_ts* for auto-participation tracking.

        Evicts the oldest entry when the dict exceeds ``_MAX_ACTIVE_THREADS``.
        Uses ``time.monotonic()`` so expiry checks are immune to wall-clock
        adjustments.
        """
        self._active_threads[thread_ts] = time.monotonic()

        # Evict oldest entries when cap is exceeded
        if len(self._active_threads) > self._MAX_ACTIVE_THREADS:
            # Sort by timestamp ascending, remove the oldest excess entries
            sorted_threads = sorted(self._active_threads.items(), key=lambda kv: kv[1])
            excess = len(self._active_threads) - self._MAX_ACTIVE_THREADS
            for ts_key, _ in sorted_threads[:excess]:
                self._active_threads.pop(ts_key, None)

    def _is_active_thread(self, thread_ts: str) -> bool:
        """
        Check whether *thread_ts* is a thread the bot has participated in
        within the last ``_THREAD_TTL_SECS`` (24 h).

        Expired entries are lazily removed on access.
        """
        last_activity = self._active_threads.get(thread_ts)
        if last_activity is None:
            return False

        elapsed = time.monotonic() - last_activity
        if elapsed > self._THREAD_TTL_SECS:
            # Expired — remove lazily
            self._active_threads.pop(thread_ts, None)
            return False

        return True

    # ------------------------------------------------------------------
    # Message splitting
    # ------------------------------------------------------------------

    @staticmethod
    def _split_message(text: str) -> list[str]:
        """
        Split *text* into chunks that each fit within ``MAX_CHARS`` (3000).

        Split strategy (in priority order):
          1. Paragraph boundaries (``\\n\\n``)
          2. Line boundaries (``\\n``)
          3. Space boundaries
          4. Hard cut at ``MAX_CHARS``

        Returns a list with at least one element (the original text if it
        fits within the limit).
        """
        limit = SlackChannel.MAX_CHARS
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
