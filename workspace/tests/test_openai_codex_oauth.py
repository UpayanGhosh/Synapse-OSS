import base64
import json
import time

import httpx
import pytest

from sci_fi_dashboard.openai_codex_oauth import (
    OpenAICodexCredentials,
    _decode_jwt_payload,
    delete_credentials,
    extract_identity,
    load_credentials,
    refresh_access_token,
    request_device_code,
    save_credentials,
)


def _jwt(payload: dict) -> str:
    raw = json.dumps(payload).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return f"header.{body}.sig"


def test_save_load_delete_credentials_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    creds = OpenAICodexCredentials(
        access_token="access",
        refresh_token="refresh",
        expires_at=12345.0,
        email="me@example.com",
        account_id="user-123",
        profile_name="me@example.com",
    )

    target = save_credentials(creds)
    assert target == tmp_path / "state" / "openai-codex-oauth.json"
    assert load_credentials() == creds

    assert delete_credentials() is True
    assert load_credentials() is None


def test_decode_jwt_payload_handles_base64url_without_padding():
    payload = _decode_jwt_payload(_jwt({"chatgpt_account_user_id": "acct", "exp": 999}))
    assert payload["chatgpt_account_user_id"] == "acct"
    assert payload["exp"] == 999


def test_extract_identity_prefers_chatgpt_account_id_and_email():
    token = _jwt(
        {
            "https://api.openai.com/profile.email": "me@example.com",
            "chatgpt_account_user_id": "acct-123",
            "sub": "subject-ignored",
        }
    )

    identity = extract_identity(token)

    assert identity.email == "me@example.com"
    assert identity.account_id == "acct-123"
    assert identity.profile_name == "me@example.com"


def test_extract_identity_falls_back_to_subject_profile_name():
    token = _jwt({"sub": "subject-123"})

    identity = extract_identity(token)

    assert identity.email == ""
    assert identity.account_id == "subject-123"
    assert identity.profile_name.startswith("id-")


class _FakeSyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, *, json=None, data=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "data": data,
                "headers": headers or {},
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


def test_request_device_code_posts_openai_codex_client_id():
    fake = _FakeSyncClient(
        [
            httpx.Response(
                200,
                json={
                    "device_auth_id": "device-1",
                    "user_code": "ABCD-EFGH",
                    "expires_in": 900,
                    "interval": 1,
                    "verification_uri": "https://auth.openai.com/codex/device",
                },
            )
        ]
    )

    result = request_device_code(http_client=fake)

    assert result.device_auth_id == "device-1"
    assert result.user_code == "ABCD-EFGH"
    assert result.verification_uri == "https://auth.openai.com/codex/device"
    assert fake.calls[0]["url"].endswith("/api/accounts/deviceauth/usercode")
    assert fake.calls[0]["json"]["client_id"] == "app_EMoamEEZ73f0CkXaXp7hrann"


def test_refresh_access_token_exchange_persists_new_access_token():
    access = _jwt(
        {
            "exp": int(time.time()) + 3600,
            "https://api.openai.com/profile.email": "me@example.com",
            "chatgpt_account_user_id": "acct-123",
        }
    )
    old = OpenAICodexCredentials(
        access_token="old-access",
        refresh_token="old-refresh",
        expires_at=time.time() - 1,
        email="me@example.com",
        account_id="acct-123",
        profile_name="me@example.com",
    )
    fake = _FakeSyncClient(
        [
            httpx.Response(
                200,
                json={
                    "access_token": access,
                    "refresh_token": "new-refresh",
                    "expires_in": 3600,
                },
            )
        ]
    )

    refreshed = refresh_access_token(old, http_client=fake)

    assert refreshed.access_token == access
    assert refreshed.refresh_token == "new-refresh"
    assert refreshed.email == "me@example.com"
    assert refreshed.account_id == "acct-123"
    assert fake.calls[0]["url"].endswith("/oauth/token")
    assert fake.calls[0]["data"]["grant_type"] == "refresh_token"
    assert fake.calls[0]["data"]["refresh_token"] == "old-refresh"
