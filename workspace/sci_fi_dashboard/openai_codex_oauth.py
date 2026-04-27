"""OpenAI Codex OAuth helpers for ChatGPT subscription-backed inference.

State file:
    $SYNAPSE_HOME/state/openai-codex-oauth.json

This integration follows OpenClaw's OpenAI Codex device-code path. Synapse
stores OAuth access/refresh tokens locally and uses the access token as a
Bearer credential for the ChatGPT Codex backend.
"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

_logger = logging.getLogger(__name__)

OPENAI_AUTH_BASE = "https://auth.openai.com"
OPENAI_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_CODEX_DEVICE_VERIFY_URL = "https://auth.openai.com/codex/device"
OPENAI_CODEX_DEVICE_REDIRECT_URI = "https://auth.openai.com/deviceauth/callback"
TOKEN_REFRESH_LEEWAY_SEC = 5 * 60
DEFAULT_TIMEOUT_SEC = 15.0
DEVICE_TIMEOUT_SEC = 15 * 60


@dataclass(frozen=True)
class OpenAICodexIdentity:
    email: str
    account_id: str
    profile_name: str


@dataclass(frozen=True)
class OpenAICodexCredentials:
    access_token: str
    refresh_token: str
    expires_at: float
    email: str = ""
    account_id: str = ""
    profile_name: str = "default"

    def is_expired(self, *, leeway_sec: float = TOKEN_REFRESH_LEEWAY_SEC) -> bool:
        return time.time() + leeway_sec >= self.expires_at


@dataclass(frozen=True)
class OpenAICodexDeviceCode:
    device_auth_id: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


def _state_dir() -> Path:
    root_env = os.environ.get("SYNAPSE_HOME", "").strip()
    root = Path(root_env) if root_env else Path.home() / ".synapse"
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    return state


def _state_file() -> Path:
    return _state_dir() / "openai-codex-oauth.json"


def save_credentials(creds: OpenAICodexCredentials) -> Path:
    target = _state_file()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(creds), indent=2), encoding="utf-8")
    os.replace(tmp, target)
    with contextlib.suppress(OSError):
        os.chmod(target, 0o600)
    return target


def load_credentials() -> OpenAICodexCredentials | None:
    target = _state_file()
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return OpenAICodexCredentials(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=float(data["expires_at"]),
            email=str(data.get("email", "")),
            account_id=str(data.get("account_id", "")),
            profile_name=str(data.get("profile_name", "") or "default"),
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        _logger.warning("openai-codex-oauth.json unreadable: %s", exc)
        return None


def delete_credentials() -> bool:
    target = _state_file()
    if target.exists():
        target.unlink()
        return True
    return False


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload.encode("ascii"))
        parsed = json.loads(raw.decode("utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, OSError, json.JSONDecodeError):
        return {}


def _profile_name_for_subject(subject: str) -> str:
    encoded = base64.urlsafe_b64encode(subject.encode("utf-8")).decode("ascii").rstrip("=")
    return f"id-{encoded[:24]}"


def extract_identity(access_token: str) -> OpenAICodexIdentity:
    payload = _decode_jwt_payload(access_token)
    email = str(payload.get("https://api.openai.com/profile.email") or "")
    account_id = str(
        payload.get("chatgpt_account_user_id")
        or payload.get("chatgpt_user_id")
        or payload.get("user_id")
        or payload.get("sub")
        or ""
    )
    profile_name = email or _profile_name_for_subject(account_id or "default")
    return OpenAICodexIdentity(email=email, account_id=account_id, profile_name=profile_name)


def _expires_at_from_token_or_delta(access_token: str, expires_in: int | float | None) -> float:
    payload = _decode_jwt_payload(access_token)
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp > time.time():
        return float(exp)
    delta = float(expires_in or 3600)
    return time.time() + delta


def _json_error_code(resp: Any) -> str:
    with contextlib.suppress(ValueError, TypeError, json.JSONDecodeError):
        data = resp.json()
        if isinstance(data, dict):
            raw = data.get("error") or data.get("code")
            if isinstance(raw, dict):
                raw = raw.get("code") or raw.get("type")
            if isinstance(raw, str):
                return raw.strip().lower()
    return ""


def _error_detail(resp: Any) -> str:
    with contextlib.suppress(ValueError, TypeError, json.JSONDecodeError):
        data = resp.json()
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, str) and error.strip():
                return error.strip()
            if isinstance(error, dict):
                message = error.get("message")
                code = error.get("code")
                if isinstance(message, str) and message.strip():
                    return message.strip()
                if isinstance(code, str) and code.strip():
                    return code.strip()
            message = data.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
    text = getattr(resp, "text", "")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return "request failed"


def _ensure_success(resp: Any) -> None:
    status = int(getattr(resp, "status_code", 0))
    if status < 400:
        return
    detail = _error_detail(resp)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"OpenAI OAuth HTTP {status}: {detail}") from exc
    except RuntimeError as exc:
        # httpx.Response objects used in unit tests can lack a bound request.
        raise RuntimeError(f"OpenAI OAuth HTTP {status}: {detail}") from exc
    raise RuntimeError(f"OpenAI OAuth HTTP {status}: {detail}")


def request_device_code(*, http_client: Any | None = None) -> OpenAICodexDeviceCode:
    client = http_client or httpx
    resp = client.post(
        f"{OPENAI_AUTH_BASE}/api/accounts/deviceauth/usercode",
        json={"client_id": OPENAI_CODEX_CLIENT_ID},
        timeout=DEFAULT_TIMEOUT_SEC,
    )
    _ensure_success(resp)
    data = resp.json()
    return OpenAICodexDeviceCode(
        device_auth_id=str(data["device_auth_id"]),
        user_code=str(data["user_code"]),
        verification_uri=str(data.get("verification_uri") or OPENAI_CODEX_DEVICE_VERIFY_URL),
        expires_in=int(data.get("expires_in") or DEVICE_TIMEOUT_SEC),
        interval=max(1, int(data.get("interval") or 5)),
    )


def poll_device_code(
    code: OpenAICodexDeviceCode,
    *,
    http_client: Any | None = None,
    sleep_fn=time.sleep,
) -> tuple[str, str]:
    client = http_client or httpx
    wait_interval = max(1, int(code.interval))
    deadline = time.time() + min(float(code.expires_in), float(DEVICE_TIMEOUT_SEC))
    while time.time() < deadline:
        resp = client.post(
            f"{OPENAI_AUTH_BASE}/api/accounts/deviceauth/token",
            json={
                "client_id": OPENAI_CODEX_CLIENT_ID,
                "device_auth_id": code.device_auth_id,
                "user_code": code.user_code,
            },
            timeout=DEFAULT_TIMEOUT_SEC,
        )
        if resp.status_code == 200:
            data = resp.json()
            return str(data["authorization_code"]), str(data["code_verifier"])
        if resp.status_code in (403, 404):
            sleep_fn(wait_interval)
            continue
        if resp.status_code == 400:
            error_code = _json_error_code(resp)
            if error_code == "authorization_pending":
                sleep_fn(wait_interval)
                continue
            if error_code == "slow_down":
                wait_interval += 5
                sleep_fn(wait_interval)
                continue
        _ensure_success(resp)
    raise RuntimeError("OpenAI Codex device authorization timed out")


def exchange_authorization_code(
    authorization_code: str,
    code_verifier: str,
    *,
    http_client: Any | None = None,
) -> OpenAICodexCredentials:
    client = http_client or httpx
    resp = client.post(
        f"{OPENAI_AUTH_BASE}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "code": authorization_code,
            "redirect_uri": OPENAI_CODEX_DEVICE_REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=DEFAULT_TIMEOUT_SEC,
    )
    _ensure_success(resp)
    data = resp.json()
    access_token = str(data["access_token"])
    refresh_token = str(data["refresh_token"])
    identity = extract_identity(access_token)
    return OpenAICodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=_expires_at_from_token_or_delta(access_token, data.get("expires_in")),
        email=identity.email,
        account_id=identity.account_id,
        profile_name=identity.profile_name,
    )


def refresh_access_token(
    creds: OpenAICodexCredentials,
    *,
    http_client: Any | None = None,
) -> OpenAICodexCredentials:
    client = http_client or httpx
    resp = client.post(
        f"{OPENAI_AUTH_BASE}/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "refresh_token": creds.refresh_token,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=DEFAULT_TIMEOUT_SEC,
    )
    _ensure_success(resp)
    data = resp.json()
    access_token = str(data["access_token"])
    refresh_token = str(data.get("refresh_token") or creds.refresh_token)
    identity = extract_identity(access_token)
    return OpenAICodexCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=_expires_at_from_token_or_delta(access_token, data.get("expires_in")),
        email=identity.email or creds.email,
        account_id=identity.account_id or creds.account_id,
        profile_name=identity.profile_name or creds.profile_name,
    )


def login_device_code(
    *,
    open_browser: bool = True,
    code_sink=None,
    http_client: Any | None = None,
) -> OpenAICodexCredentials:
    code = request_device_code(http_client=http_client)
    if code_sink is not None:
        code_sink(code)
    if open_browser:
        webbrowser.open(code.verification_uri)
    authorization_code, code_verifier = poll_device_code(code, http_client=http_client)
    creds = exchange_authorization_code(
        authorization_code,
        code_verifier,
        http_client=http_client,
    )
    save_credentials(creds)
    return creds


def get_active_credentials(*, refresh_if_needed: bool = True) -> OpenAICodexCredentials | None:
    creds = load_credentials()
    if creds is None:
        return None
    if not refresh_if_needed or not creds.is_expired():
        return creds
    refreshed = refresh_access_token(creds)
    save_credentials(refreshed)
    return refreshed
