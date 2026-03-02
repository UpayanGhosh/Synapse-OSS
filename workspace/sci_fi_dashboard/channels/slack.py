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
"""

import asyncio
import logging
from datetime import datetime

from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp
from slack_sdk.web.async_client import AsyncWebClient

from .base import BaseChannel, ChannelMessage

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
    """

    def __init__(
        self,
        bot_token: str,  # xoxb- prefix: for API calls
        app_token: str,  # xapp- prefix: for Socket Mode WebSocket
        enqueue_fn=None,  # async callable(ChannelMessage) -> None
    ) -> None:
        """
        Initialize SlackChannel with token validation.

        Args:
            bot_token:  Slack bot OAuth token (xoxb- prefix). Used for API calls.
            app_token:  Slack app-level token (xapp- prefix). Used for Socket Mode.
            enqueue_fn: Async callable receiving a ChannelMessage; routes into the
                        pipeline. Pass None in tests / when channel is wired separately.

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

    async def send(self, chat_id: str, text: str) -> bool:
        """
        Send text to a Slack channel or DM via chat_postMessage.

        Args:
            chat_id: Slack channel ID (e.g. 'C12345') or DM channel ID (e.g. 'D67890').
            text:    Message body to deliver.

        Returns:
            True on success, False if the Slack API call failed.
        """
        try:
            await self._web_client.chat_postMessage(channel=chat_id, text=text)
            return True
        except Exception as exc:
            logger.error("[Slack] send() failed for channel %s: %s", chat_id, exc)
            return False

    async def send_typing(self, chat_id: str) -> None:
        """
        Slack typing indicators are unreliable via API — no-op per design decision.

        The Slack Web API does not provide a stable way to send typing indicators
        for bots. This method is a no-op to satisfy the BaseChannel contract.
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
        """

        @self._app.event("message")
        async def handle_dm(event, say) -> None:  # noqa: F841
            # Filter to DMs only (channel_type "im")
            if "bot_id" in event:
                return  # ignore self-messages and other bots
            if event.get("channel_type") != "im":
                return  # channel messages handled by app_mention, not here
            await self._dispatch(event, is_group=False)

        @self._app.event("app_mention")
        async def handle_mention(event, say) -> None:  # noqa: F841
            if "bot_id" in event:
                return  # ignore self-triggered mention events
            await self._dispatch(event, is_group=True)

    async def _dispatch(self, event: dict, is_group: bool) -> None:
        """
        Normalize a Slack event dict to a ChannelMessage and enqueue into the pipeline.

        Args:
            event:    Raw Slack event dict from the bolt event handler.
            is_group: True for channel @mentions, False for DMs.
        """
        msg = ChannelMessage(
            channel_id="slack",
            user_id=event.get("user", ""),
            chat_id=event.get("channel", ""),
            text=event.get("text", ""),
            timestamp=datetime.now(),
            is_group=is_group,
            message_id=event.get("ts", ""),
            sender_name=event.get("user", ""),
            raw=event,
        )
        if self._enqueue_fn:
            await self._enqueue_fn(msg)
