"""
Channel abstraction layer — BaseChannel, ChannelRegistry, ChannelMessage, StubChannel.

All future channel adapters (WhatsApp, Telegram, Discord, Slack) subclass BaseChannel
and register with ChannelRegistry. Import from this package, not from submodules.

Example usage in FastAPI lifespan:

    from sci_fi_dashboard.channels import ChannelRegistry, StubChannel

    registry = ChannelRegistry()
    registry.register(StubChannel("whatsapp"))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await registry.start_all()
        yield
        await registry.stop_all()
"""

from .base import BaseChannel, ChannelMessage
from .registry import ChannelRegistry
from .stub import StubChannel
from .whatsapp import WhatsAppChannel

# Optional channel adapters — only importable if their SDK is installed
try:
    from .telegram import TelegramChannel
except ImportError:
    TelegramChannel = None  # type: ignore[assignment, misc]

try:
    from .discord_channel import DiscordChannel
except ImportError:
    DiscordChannel = None  # type: ignore[assignment, misc]

try:
    from .slack import SlackChannel
except ImportError:
    SlackChannel = None  # type: ignore[assignment, misc]

__all__ = [
    "BaseChannel",
    "ChannelMessage",
    "ChannelRegistry",
    "DiscordChannel",
    "SlackChannel",
    "StubChannel",
    "TelegramChannel",
    "WhatsAppChannel",
]
