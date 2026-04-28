from __future__ import annotations

from dataclasses import dataclass


def normalize_session_type(value: str | None) -> str:
    normalized = (value or "safe").strip().lower()
    if not normalized:
        return "safe"
    if normalized not in {"safe", "spicy"}:
        raise ValueError("session type must be safe or spicy")
    return normalized


@dataclass(frozen=True)
class ChatTurn:
    role: str
    content: str

    def as_history_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ChatLaunchOptions:
    target: str = "the_creator"
    user_id: str = "the_creator"
    session_type: str = "safe"
    session_key: str | None = None
    port: int = 8000
    auto_start_gateway: bool = True
    initial_message: str | None = None
    exit_after_initial: bool = False
    show_startup_greeting: bool = True

    def resolved_session_type(self) -> str:
        return normalize_session_type(self.session_type)

    def resolved_session_key(self) -> str:
        key = (self.session_key or "").strip()
        if key:
            return key
        return f"cli:{self.target}:{self.user_id}"
