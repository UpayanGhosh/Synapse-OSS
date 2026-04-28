from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from cli.chat_types import ChatLaunchOptions, ChatTurn


def gateway_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    token = os.environ.get("SYNAPSE_GATEWAY_TOKEN", "")
    if not token:
        try:
            from synapse_config import SynapseConfig, gateway_token

            token = gateway_token(SynapseConfig.load())
        except Exception:
            token = ""
    if token:
        headers["x-api-key"] = token
    return headers


@dataclass(frozen=True)
class ChatReply:
    reply: str
    model: str = ""
    raw: dict | None = None


class ChatClient:
    def __init__(self, base_url: str, timeout_sec: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def send_turn(
        self,
        message: str,
        *,
        options: ChatLaunchOptions,
        history: list[ChatTurn],
    ) -> ChatReply:
        payload = {
            "message": message,
            "history": [turn.as_history_message() for turn in history],
            "user_id": options.user_id,
            "session_type": options.resolved_session_type(),
            "session_key": options.resolved_session_key(),
        }
        response = httpx.post(
            f"{self.base_url}/chat/{options.target}",
            json=payload,
            headers=gateway_headers(),
            timeout=self.timeout_sec,
        )
        if int(response.status_code) >= 400:
            raise RuntimeError(f"Gateway chat failed: HTTP {response.status_code}: {response.text}")
        body = response.json()
        return ChatReply(
            reply=str(body.get("reply", "")),
            model=str(body.get("model", "")),
            raw=body,
        )
