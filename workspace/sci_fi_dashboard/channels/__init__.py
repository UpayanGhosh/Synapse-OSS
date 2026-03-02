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

__all__ = ["BaseChannel", "ChannelMessage", "ChannelRegistry", "StubChannel", "WhatsAppChannel"]
