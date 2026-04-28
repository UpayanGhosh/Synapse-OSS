from __future__ import annotations

from pathlib import Path

from cli.chat_types import ChatLaunchOptions


def should_offer_cli_chat(non_interactive: bool, launch_chat: bool | None) -> bool:
    if launch_chat is not None:
        return launch_chat
    return not non_interactive


def build_post_onboard_chat_options(
    workspace_dir: Path,
    port: int,
    target: str = "the_creator",
    user_id: str = "local_cli",
) -> ChatLaunchOptions:
    return ChatLaunchOptions(
        target=target,
        user_id=user_id,
        session_type="safe",
        session_key=f"cli:{target}:{user_id}",
        port=port,
        auto_start_gateway=True,
        initial_message=None,
        workspace_dir=workspace_dir,
    )
