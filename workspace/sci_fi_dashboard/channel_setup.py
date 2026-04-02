"""Optional channel registration (Telegram, Discord, Slack)."""
import logging
import uuid

from sci_fi_dashboard import _deps as deps

logger = logging.getLogger(__name__)


def _make_flood_enqueue(channel_id: str):
    """
    Factory: returns an async callable that routes a ChannelMessage through
    FloodGate (with dedup) instead of passing it directly to task_queue.enqueue().

    CHAN-05 reference pattern: see unified_webhook() which calls flood.incoming().
    The inner _enqueue function receives a ChannelMessage (not MessageTask) -- the
    FloodGate on_batch_ready callback constructs the MessageTask with a uuid4 task_id.
    This avoids the AttributeError: 'ChannelMessage' object has no attribute 'task_id'
    that would occur if enqueue_fn=task_queue.enqueue were used directly.
    """

    async def _enqueue(channel_msg):
        # H-09: Generate UUID fallback if message_id is empty/None
        effective_id = channel_msg.message_id or str(uuid.uuid4())
        if deps.dedup.is_duplicate(effective_id):
            return
        await deps.flood.incoming(
            chat_id=channel_msg.chat_id,
            message=channel_msg.text,
            metadata={
                "message_id": channel_msg.message_id,
                "sender_name": channel_msg.sender_name,
                "channel_id": channel_id,
                "is_group": getattr(channel_msg, "is_group", False),
            },
        )

    return _enqueue


def register_optional_channels():
    """Register Telegram, Discord, Slack channels if tokens are configured."""
    cfg = deps._synapse_cfg
    ch_cfg = cfg.channels  # dict[str, dict] from synapse.json "channels" key

    # --- Telegram ---
    tg_token = ch_cfg.get("telegram", {}).get("token", "").strip()
    if tg_token:
        try:
            from channels.telegram import TelegramChannel

            tel_enqueue = _make_flood_enqueue("telegram")
            deps.channel_registry.register(
                TelegramChannel(token=tg_token, enqueue_fn=tel_enqueue)
            )
            logger.info("Telegram channel registered")
        except ImportError:
            logger.warning(
                "Telegram token configured but python-telegram-bot not installed. "
                "Run: pip install python-telegram-bot>=22.0"
            )
    else:
        logger.info(
            "Telegram channel not configured — skipping "
            "(add channels.telegram.token to synapse.json to enable)"
        )

    # --- Discord ---
    ds_token = ch_cfg.get("discord", {}).get("token", "").strip()
    if ds_token:
        try:
            from channels.discord_channel import DiscordChannel

            ds_allowed = [
                int(x) for x in ch_cfg.get("discord", {}).get("allowed_channel_ids", [])
            ]
            dis_enqueue = _make_flood_enqueue("discord")
            deps.channel_registry.register(
                DiscordChannel(
                    token=ds_token, allowed_channel_ids=ds_allowed, enqueue_fn=dis_enqueue
                )
            )
            logger.info("Discord channel registered")
        except ImportError:
            logger.warning(
                "Discord token configured but discord.py not installed. "
                "Run: pip install discord.py>=2.4.0"
            )
    else:
        logger.info(
            "Discord channel not configured — skipping "
            "(add channels.discord.token to synapse.json to enable)"
        )

    # --- Slack ---
    slk_bot = ch_cfg.get("slack", {}).get("bot_token", "").strip()
    slk_app = ch_cfg.get("slack", {}).get("app_token", "").strip()
    if slk_bot and slk_app:
        try:
            from channels.slack import SlackChannel

            slk_enqueue = _make_flood_enqueue("slack")
            deps.channel_registry.register(
                SlackChannel(bot_token=slk_bot, app_token=slk_app, enqueue_fn=slk_enqueue)
            )
            logger.info("Slack channel registered")
        except ImportError:
            logger.warning(
                "Slack tokens configured but slack-bolt not installed. "
                "Run: pip install slack-bolt>=1.18.0"
            )
        except ValueError as exc:
            logger.error("Slack channel configuration error — channel disabled: %s", exc)
    else:
        logger.info(
            "Slack channel not configured — skipping "
            "(add channels.slack.bot_token and channels.slack.app_token "
            "to synapse.json to enable)"
        )
