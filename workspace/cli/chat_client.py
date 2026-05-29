from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from cli.chat_types import ChatLaunchOptions, ChatTurn


def _config_gateway_token() -> str:
    try:
        from synapse_config import SynapseConfig, gateway_token

        return (gateway_token(SynapseConfig.load()) or "").strip()
    except Exception:
        return ""


def _gateway_token_candidates() -> list[str]:
    tokens: list[str] = []
    for token in (os.environ.get("SYNAPSE_GATEWAY_TOKEN", "").strip(), _config_gateway_token()):
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _headers_for_token(token: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if token:
        headers["x-api-key"] = token
    return headers


def gateway_headers() -> dict[str, str]:
    env_token = os.environ.get("SYNAPSE_GATEWAY_TOKEN", "").strip()
    if env_token:
        return _headers_for_token(env_token)
    config_token = _config_gateway_token()
    return _headers_for_token(config_token) if config_token else {}


def _is_gateway_auth_failure(response: httpx.Response) -> bool:
    if int(response.status_code) != 401:
        return False
    lowered = response.text.lower()
    return "invalid api key" in lowered or "unauthorized" in lowered


def _gateway_auth_error(response: httpx.Response) -> RuntimeError:
    return RuntimeError(
        "Gateway authentication failed: "
        f"HTTP {response.status_code}: {response.text}. "
        "This is the Synapse gateway token, not the LLM provider key. "
        "Run /status and ensure SYNAPSE_GATEWAY_TOKEN matches synapse.json gateway.token, "
        "or restart the gateway after re-onboarding."
    )


@dataclass(frozen=True)
class ChatReply:
    reply: str
    model: str = ""
    raw: dict | None = None


class ChatClient:
    def __init__(self, base_url: str, timeout_sec: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    def probe_health(self) -> tuple[bool, str]:
        try:
            response = httpx.get(
                f"{self.base_url}/health",
                headers=gateway_headers(),
                timeout=min(self.timeout_sec, 5.0),
            )
            if int(response.status_code) >= 400:
                return False, f"HTTP {response.status_code}"
            body = response.json()
            status = str(body.get("status", "unknown"))
            return status in {"ok", "degraded"}, status
        except Exception as exc:
            return False, str(exc)

    def get_style_policy(self, session_key: str) -> tuple[bool, dict | str]:
        try:
            header_candidates = [gateway_headers()]
            for token in _gateway_token_candidates():
                headers = _headers_for_token(token)
                if headers not in header_candidates:
                    header_candidates.append(headers)

            response = None
            url = f"{self.base_url}/api/sessions/{quote(session_key, safe='')}/style"
            for headers in header_candidates:
                response = httpx.get(
                    url,
                    headers=headers,
                    timeout=min(self.timeout_sec, 5.0),
                )
                if not _is_gateway_auth_failure(response):
                    break
            assert response is not None  # noqa: S101
            if int(response.status_code) >= 400:
                return False, f"HTTP {response.status_code}"
            body = response.json()
            return True, body if isinstance(body, dict) else {}
        except Exception as exc:
            return False, str(exc)

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
        header_candidates = [gateway_headers()]
        for token in _gateway_token_candidates():
            headers = _headers_for_token(token)
            if headers not in header_candidates:
                header_candidates.append(headers)

        response = None
        for headers in header_candidates:
            response = httpx.post(
                f"{self.base_url}/chat/{options.target}",
                json=payload,
                headers=headers,
                timeout=self.timeout_sec,
            )
            if not _is_gateway_auth_failure(response):
                break

        assert response is not None  # noqa: S101
        if int(response.status_code) >= 400:
            if _is_gateway_auth_failure(response):
                raise _gateway_auth_error(response)
            raise RuntimeError(f"Gateway chat failed: HTTP {response.status_code}: {response.text}")
        body = response.json()
        return ChatReply(
            reply=str(body.get("reply", "")),
            model=str(body.get("model", "")),
            raw=body,
        )
