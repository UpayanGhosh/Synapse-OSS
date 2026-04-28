import base64
import json
import time

import httpx
import pytest

from sci_fi_dashboard.openai_codex_oauth import (
    OpenAICodexCredentials,
    OpenAICodexDeviceCode,
    _decode_jwt_payload,
    delete_credentials,
    extract_identity,
    get_active_credentials,
    import_codex_cli_credentials,
    load_credentials,
    poll_device_code,
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


def test_get_active_credentials_never_refreshes_by_expiry(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path))
    creds = OpenAICodexCredentials(
        access_token="expired-access",
        refresh_token="refresh",
        expires_at=time.time() - 3600,
        email="",
        account_id="acct-123",
        profile_name="default",
    )
    save_credentials(creds)

    def _refresh_must_not_run(*args, **kwargs):
        raise AssertionError("Codex credentials refresh only after an auth error")

    monkeypatch.setattr(
        "sci_fi_dashboard.openai_codex_oauth.refresh_access_token",
        _refresh_must_not_run,
    )

    assert get_active_credentials(refresh_if_needed=True) == creds


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


def test_poll_device_code_tolerates_transient_unknown_device_authorization():
    fake = _FakeSyncClient(
        [
            httpx.Response(
                403,
                json={"error": "Device authorization is unknown. Please try again."},
            ),
            httpx.Response(
                200,
                json={
                    "authorization_code": "auth-code-1",
                    "code_verifier": "verifier-1",
                },
            ),
        ]
    )
    sleeps = []
    code = OpenAICodexDeviceCode(
        device_auth_id="device-1",
        user_code="ABCD-EFGH",
        verification_uri="https://auth.openai.com/codex/device",
        expires_in=900,
        interval=1,
    )

    authorization_code, code_verifier = poll_device_code(
        code,
        http_client=fake,
        sleep_fn=lambda seconds: sleeps.append(seconds),
    )

    assert authorization_code == "auth-code-1"
    assert code_verifier == "verifier-1"
    assert sleeps == [1]


def test_poll_device_code_unknown_device_authorization_repeated_raises_helpful_error():
    fake = _FakeSyncClient(
        [
            httpx.Response(
                403,
                json={"error": "Device authorization is unknown. Please try again."},
            ),
            httpx.Response(
                403,
                json={"error": "Device authorization is unknown. Please try again."},
            ),
            httpx.Response(
                403,
                json={"error": "Device authorization is unknown. Please try again."},
            ),
            httpx.Response(
                403,
                json={"error": "Device authorization is unknown. Please try again."},
            ),
        ]
    )
    sleeps = []
    code = OpenAICodexDeviceCode(
        device_auth_id="device-1",
        user_code="ABCD-EFGH",
        verification_uri="https://auth.openai.com/codex/device",
        expires_in=900,
        interval=1,
    )

    with pytest.raises(RuntimeError, match="Device Code Authorization for Codex"):
        poll_device_code(
            code,
            http_client=fake,
            sleep_fn=lambda seconds: sleeps.append(seconds),
        )

    assert sleeps == [1, 1, 1]


def test_request_device_code_cloudflare_html_is_sanitized():
    fake = _FakeSyncClient(
        [
            httpx.Response(
                403,
                text=(
                    "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
                    "<body>cloudflare challenge-platform</body></html>"
                ),
            )
        ]
    )

    with pytest.raises(RuntimeError, match="Cloudflare challenge blocked OpenAI OAuth request"):
        request_device_code(http_client=fake)


def test_import_codex_cli_credentials_reads_local_auth_json(tmp_path, monkeypatch):
    now = int(time.time())
    access = _jwt(
        {
            "exp": now + 3600,
            "https://api.openai.com/profile.email": "me@example.com",
            "chatgpt_account_user_id": "acct-jwt",
        }
    )
    codex_home = tmp_path / ".codex"
    codex_home.mkdir(parents=True)
    (codex_home / "auth.json").write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": access,
                    "refresh_token": "refresh-123",
                    "account_id": "acct-file",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("SYNAPSE_HOME", str(tmp_path / ".synapse"))
    creds = import_codex_cli_credentials()

    assert creds is not None
    assert creds.access_token == access
    assert creds.refresh_token == "refresh-123"
    # Identity from JWT should win over file-level account_id.
    assert creds.account_id == "acct-jwt"
    assert creds.email == "me@example.com"
    saved = load_credentials()
    assert saved is not None
    assert saved.access_token == access
