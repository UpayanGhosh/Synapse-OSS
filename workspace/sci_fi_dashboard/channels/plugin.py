"""ChannelPlugin protocol and ChannelCapabilities dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ChannelCapabilities:
    """Declares what a channel adapter can do."""

    chat_types: list[str] = field(default_factory=lambda: ["direct"])
    polls: bool = False
    reactions: bool = False
    edit: bool = False
    unsend: bool = False
    reply: bool = False
    effects: bool = False
    group_management: bool = False
    threads: bool = False
    media: bool = False
    native_commands: bool = False
    block_streaming: bool = False
    markdown_capable: bool = True
    max_message_length: int = 4000


@runtime_checkable
class ChannelPlugin(Protocol):
    """Structural interface for next-gen channel adapters."""

    @property
    def id(self) -> str: ...

    @property
    def capabilities(self) -> ChannelCapabilities: ...

    async def start_account(self, account_id: str) -> None: ...

    async def stop_account(self, account_id: str) -> None: ...

    async def send_text(self, to: str, text: str) -> dict: ...

    async def send_media(self, to: str, media_url: str) -> dict: ...
