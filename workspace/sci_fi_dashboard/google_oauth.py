"""
google_oauth.py — Google Antigravity / Gemini CLI OAuth flow for Synapse-OSS.

Mirrors OpenClaw's extensions/google/oauth.* in Python. Provides the OAuth
bootstrap that lets a logged-in Google account hit the CodeAssist endpoint
(``cloudcode-pa.googleapis.com``) — the same backend Google's Antigravity IDE
and the official Gemini CLI use.

Public API:
    - GoogleAntigravityCredentials  : dataclass with access/refresh/expires/project_id/email/tier
    - login_pkce(headless=False)    : full OAuth flow, returns credentials
    - load_credentials()            : read from disk, returns None if missing
    - save_credentials(creds)       : atomic write
    - delete_credentials()          : wipe state file
    - refresh_access_token(creds)   : exchange refresh_token for new access_token
    - extract_gemini_cli_credentials() : find OAuth client_id/secret in local Gemini CLI install
    - resolve_oauth_client_config() : env var first, then extracted, else raise

State file location:
    $SYNAPSE_HOME/state/google-oauth.json (default ~/.synapse/state/google-oauth.json)

Important:
    No OAuth client_id or client_secret is hardcoded in this repo. We either
    read them from the user's locally installed @google/gemini-cli npm package
    or accept GEMINI_CLI_OAUTH_CLIENT_ID / _SECRET env vars. This is a
    third-party integration with no official Google endorsement.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

_logger = logging.getLogger(__name__)

# OAuth endpoints (public Google IDs)
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
USERINFO_URL = "https://www.googleapis.com/oauth2/v1/userinfo?alt=json"
REDIRECT_HOST = "localhost"
REDIRECT_PORT = 8085
REDIRECT_PATH = "/oauth2callback"
REDIRECT_URI = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}{REDIRECT_PATH}"

# CodeAssist endpoints — try in order on first contact
CODE_ASSIST_ENDPOINT_PROD = "https://cloudcode-pa.googleapis.com"
CODE_ASSIST_ENDPOINT_DAILY = "https://daily-cloudcode-pa.sandbox.googleapis.com"
CODE_ASSIST_ENDPOINT_AUTOPUSH = "https://autopush-cloudcode-pa.sandbox.googleapis.com"
LOAD_CODE_ASSIST_ENDPOINTS = (
    CODE_ASSIST_ENDPOINT_PROD,
    CODE_ASSIST_ENDPOINT_DAILY,
    CODE_ASSIST_ENDPOINT_AUTOPUSH,
)

# OAuth scopes — same set Gemini CLI requests
SCOPES = (
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
)

# Tier identifiers returned by loadCodeAssist
TIER_FREE = "free-tier"
TIER_LEGACY = "legacy-tier"
TIER_STANDARD = "standard-tier"

# Env-var names for the OAuth client config — we check both Synapse-prefixed
# names and the upstream Gemini CLI ones for users who already have them set.
CLIENT_ID_KEYS = ("SYNAPSE_GEMINI_OAUTH_CLIENT_ID", "GEMINI_CLI_OAUTH_CLIENT_ID")
CLIENT_SECRET_KEYS = ("SYNAPSE_GEMINI_OAUTH_CLIENT_SECRET", "GEMINI_CLI_OAUTH_CLIENT_SECRET")

# How many seconds before expiry we treat the access token as stale
TOKEN_REFRESH_LEEWAY_SEC = 5 * 60

DEFAULT_HTTP_TIMEOUT_SEC = 15.0
OAUTH_CALLBACK_TIMEOUT_SEC = 5 * 60
USER_AGENT = "synapse-oss-google-oauth/1.0"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OAuthCallbackBindError(RuntimeError):
    """Raised when the localhost OAuth callback server cannot bind to the port."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class GoogleAntigravityCredentials:
    """OAuth credentials for the Google Antigravity / Gemini CLI integration.

    Attributes:
        access_token:  Bearer token for CodeAssist API requests.
        refresh_token: Long-lived token used to mint new access tokens.
        expires_at:    Unix epoch seconds when access_token expires.
        project_id:    Google Cloud project ID (auto-discovered or user-supplied).
        email:         The Google account email tied to this token.
        tier:          One of TIER_FREE, TIER_LEGACY, TIER_STANDARD (or empty).
    """

    access_token: str
    refresh_token: str
    expires_at: float
    project_id: str
    email: str = ""
    tier: str = ""

    def is_expired(self, *, leeway_sec: float = TOKEN_REFRESH_LEEWAY_SEC) -> bool:
        return time.time() + leeway_sec >= self.expires_at


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _state_dir() -> Path:
    """Resolve the directory holding google-oauth.json.

    Honors SYNAPSE_HOME env var; defaults to ~/.synapse. Always returns
    ``<root>/state``, creating it if missing.
    """
    root_env = os.environ.get("SYNAPSE_HOME", "").strip()
    root = Path(root_env) if root_env else Path.home() / ".synapse"
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    return state


def _state_file() -> Path:
    return _state_dir() / "google-oauth.json"


def save_credentials(creds: GoogleAntigravityCredentials) -> Path:
    """Atomic write of credentials to ~/.synapse/state/google-oauth.json."""
    target = _state_file()
    tmp = target.with_suffix(".tmp")
    payload = asdict(creds)
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    with contextlib.suppress(OSError):
        os.chmod(target, 0o600)
    return target


def load_credentials() -> GoogleAntigravityCredentials | None:
    """Read credentials from disk; return None if missing or unparseable."""
    target = _state_file()
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _logger.warning("google-oauth.json unreadable: %s", exc)
        return None
    try:
        return GoogleAntigravityCredentials(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=float(data["expires_at"]),
            project_id=str(data["project_id"]),
            email=str(data.get("email", "")),
            tier=str(data.get("tier", "")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        _logger.warning("google-oauth.json schema mismatch: %s", exc)
        return None


def delete_credentials() -> bool:
    target = _state_file()
    if target.exists():
        target.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# OAuth client_id / client_secret discovery
# ---------------------------------------------------------------------------

_CLIENT_ID_RE = re.compile(r"OAUTH_CLIENT_ID\s*=\s*['\"]([^'\"]+)['\"]")
_CLIENT_SECRET_RE = re.compile(r"OAUTH_CLIENT_SECRET\s*=\s*['\"]([^'\"]+)['\"]")
_FALLBACK_CLIENT_ID_RE = re.compile(r"(\d+-[a-z0-9]+\.apps\.googleusercontent\.com)")
_FALLBACK_CLIENT_SECRET_RE = re.compile(r"(GOCSPX-[A-Za-z0-9_-]+)")


def _parse_credentials_from_text(text: str) -> tuple[str, str] | None:
    cid = _CLIENT_ID_RE.search(text) or _FALLBACK_CLIENT_ID_RE.search(text)
    cs = _CLIENT_SECRET_RE.search(text) or _FALLBACK_CLIENT_SECRET_RE.search(text)
    if cid and cs:
        return cid.group(1), cs.group(1)
    return None


def _try_read_credentials(path: Path) -> tuple[str, str] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    return _parse_credentials_from_text(text)


def _gemini_cli_root_candidates(gemini_path: Path) -> list[Path]:
    """Resolve possible @google/gemini-cli install dirs from a `gemini` binary path."""
    try:
        resolved = gemini_path.resolve()
    except OSError:
        resolved = gemini_path

    bin_dir = gemini_path.parent
    candidates = [
        resolved.parent.parent,
        resolved.parent / "node_modules" / "@google" / "gemini-cli",
        bin_dir / "node_modules" / "@google" / "gemini-cli",
        bin_dir.parent / "node_modules" / "@google" / "gemini-cli",
        bin_dir.parent / "lib" / "node_modules" / "@google" / "gemini-cli",
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for cand in candidates:
        sub_search = [
            cand,
            cand / "node_modules" / "@google" / "gemini-cli",
            cand / "lib" / "node_modules" / "@google" / "gemini-cli",
        ]
        for sub in sub_search:
            if not sub.exists():
                continue
            if not (
                (sub / "package.json").exists()
                or (sub / "node_modules" / "@google" / "gemini-cli-core").exists()
            ):
                continue
            key = str(sub).lower() if sys.platform == "win32" else str(sub)
            if key in seen:
                continue
            seen.add(key)
            out.append(sub)
    return out


def _read_credentials_from_known_paths(cli_dir: Path) -> tuple[str, str] | None:
    candidates = [
        cli_dir
        / "node_modules"
        / "@google"
        / "gemini-cli-core"
        / "dist"
        / "src"
        / "code_assist"
        / "oauth2.js",
        cli_dir
        / "node_modules"
        / "@google"
        / "gemini-cli-core"
        / "dist"
        / "code_assist"
        / "oauth2.js",
    ]
    for path in candidates:
        if path.exists():
            creds = _try_read_credentials(path)
            if creds:
                return creds
    return None


def _read_credentials_from_bundle(cli_dir: Path) -> tuple[str, str] | None:
    bundle = cli_dir / "bundle"
    if not bundle.is_dir():
        return None
    try:
        for entry in bundle.iterdir():
            if entry.is_file() and entry.suffix == ".js":
                creds = _try_read_credentials(entry)
                if creds:
                    return creds
    except OSError:
        pass
    return None


def _find_credentials_in_tree(root: Path, depth: int) -> tuple[str, str] | None:
    if depth <= 0 or not root.is_dir():
        return None
    try:
        for entry in root.iterdir():
            if entry.is_file() and entry.name == "oauth2.js":
                creds = _try_read_credentials(entry)
                if creds:
                    return creds
            elif entry.is_dir() and not entry.name.startswith("."):
                inner = _find_credentials_in_tree(entry, depth - 1)
                if inner:
                    return inner
    except OSError:
        pass
    return None


def extract_gemini_cli_credentials() -> tuple[str, str] | None:
    """Locate OAuth client_id/secret from the user's installed Gemini CLI.

    Returns (client_id, client_secret) or None if not found. Mirrors OpenClaw's
    extraction logic — walks node_modules trees and regex-scrapes oauth2.js.
    """
    gemini_bin = shutil.which("gemini")
    if not gemini_bin:
        return None
    gemini_path = Path(gemini_bin)

    for cli_dir in _gemini_cli_root_candidates(gemini_path):
        creds = _read_credentials_from_known_paths(cli_dir)
        if creds:
            return creds
        creds = _read_credentials_from_bundle(cli_dir)
        if creds:
            return creds
        creds = _find_credentials_in_tree(cli_dir, depth=10)
        if creds:
            return creds
    return None


def _env_first(keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


def resolve_oauth_client_config() -> tuple[str, str | None]:
    """Resolve OAuth client_id / client_secret.

    Order:
      1. Env vars (SYNAPSE_GEMINI_OAUTH_CLIENT_ID/_SECRET or GEMINI_CLI_*).
      2. Auto-extracted from local @google/gemini-cli install.
      3. Raise RuntimeError with install hint.
    """
    env_id = _env_first(CLIENT_ID_KEYS)
    env_secret = _env_first(CLIENT_SECRET_KEYS)
    if env_id:
        return env_id, env_secret

    extracted = extract_gemini_cli_credentials()
    if extracted:
        return extracted

    raise RuntimeError(
        "Google OAuth client config not found. Either install Gemini CLI "
        "(`npm install -g @google/gemini-cli`) or set "
        "SYNAPSE_GEMINI_OAUTH_CLIENT_ID and SYNAPSE_GEMINI_OAUTH_CLIENT_SECRET."
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _is_wsl2() -> bool:
    """True when running under Windows Subsystem for Linux (WSL2).

    WSL2's localhost cannot reliably receive an OAuth callback from a Windows
    browser, so we fall back to manual code-paste flow.
    """
    try:
        with open("/proc/version", encoding="utf-8", errors="ignore") as fh:
            content = fh.read()
        return "microsoft" in content.lower() or "WSL" in content
    except (OSError, FileNotFoundError):
        return False


# ---------------------------------------------------------------------------
# Public callback-input parser
# ---------------------------------------------------------------------------


def parse_oauth_callback_input(pasted: str, *, expected_state: str) -> tuple[str, str]:
    """Parse a pasted OAuth callback URL or bare 'code=...&state=...' fragment.

    Returns (code, state). Raises RuntimeError with a *helpful* message if the
    pasted text cannot yield both a code and a state, OR if the state mismatches
    the expected_state.

    Accepts:
      - Full redirect URL: http://localhost:8085/oauth2callback?code=X&state=Y
      - Bare query string: code=X&state=Y
      - Bare query with leading ?: ?code=X&state=Y

    Helpful errors:
      - empty input → "Paste the redirect URL from your browser. It starts with http://localhost:8085."
      - missing code → "The pasted URL is missing the 'code' parameter. Paste the FULL URL, not just the code value."
      - missing state → "The pasted URL is missing the 'state' parameter. Paste the FULL URL."
      - state mismatch → "OAuth state mismatch — please retry the login flow from the start."
    """
    stripped = pasted.strip()
    if not stripped:
        raise RuntimeError(
            f"Paste the redirect URL from your browser. It starts with http://{REDIRECT_HOST}:{REDIRECT_PORT}."
        )

    # Normalise: bare query strings (with or without leading '?') → parseable URL
    if not stripped.startswith("http://") and not stripped.startswith("https://"):
        stripped = f"http://{REDIRECT_HOST}:{REDIRECT_PORT}{REDIRECT_PATH}?" + stripped.lstrip("?")

    parsed = urlparse(stripped)
    query = parse_qs(parsed.query)

    code = (query.get("code", [None])[0] or "").strip()
    state = (query.get("state", [None])[0] or "").strip()

    if not code:
        raise RuntimeError(
            "The pasted URL is missing the 'code' parameter. "
            "Paste the FULL URL, not just the code value."
        )
    if not state:
        raise RuntimeError(
            "The pasted URL is missing the 'state' parameter. Paste the FULL URL."
        )
    if state != expected_state:
        raise RuntimeError("OAuth state mismatch — please retry the login flow from the start.")

    return code, state


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def _generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_hex(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _generate_state() -> str:
    return secrets.token_hex(32)


def _build_auth_url(client_id: str, challenge: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Localhost callback server
# ---------------------------------------------------------------------------


class _CallbackResult:
    """Mutable shared slot for the callback handler to deliver its result."""

    __slots__ = ("code", "error", "state")

    def __init__(self) -> None:
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None


def _build_callback_handler(result: _CallbackResult, expected_state: str, done: threading.Event):
    class Handler(BaseHTTPRequestHandler):
        # Silence default logging — we don't want stdout noise in the wizard.
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != REDIRECT_PATH:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Not found")
                return

            query = parse_qs(parsed.query)
            error = query.get("error", [None])[0]
            code = (query.get("code", [None])[0] or "").strip()
            state = (query.get("state", [None])[0] or "").strip()

            if error:
                result.error = f"OAuth error: {error}"
                self._send_html(400, "Authentication failed", error)
                done.set()
                return
            if not code or not state:
                result.error = "Missing OAuth code or state"
                self._send_html(400, "Authentication failed", "missing parameters")
                done.set()
                return
            if state != expected_state:
                result.error = "OAuth state mismatch"
                self._send_html(400, "Authentication failed", "state mismatch")
                done.set()
                return

            result.code = code
            result.state = state
            self._send_html(
                200,
                "Synapse Google OAuth complete",
                "You can close this window and return to the Synapse onboarding wizard.",
            )
            done.set()

        def _send_html(self, status: int, title: str, body: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = (
                f"<!doctype html><html><head><meta charset='utf-8'/>"
                f"<title>{title}</title></head><body style='font-family: sans-serif; "
                f"max-width: 480px; margin: 4rem auto; line-height: 1.5;'>"
                f"<h2>{title}</h2><p>{body}</p></body></html>"
            )
            self.wfile.write(html.encode("utf-8"))

    return Handler


def _wait_for_callback(expected_state: str, *, timeout_sec: float) -> tuple[str, str]:
    """Bind localhost:8085 and block until the OAuth callback hits us.

    Returns (code, state). Raises RuntimeError on error/timeout.
    """
    result = _CallbackResult()
    done = threading.Event()
    handler_cls = _build_callback_handler(result, expected_state, done)
    try:
        server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), handler_cls)
    except OSError as exc:
        raise OAuthCallbackBindError(
            f"Cannot bind {REDIRECT_HOST}:{REDIRECT_PORT} for OAuth callback: {exc}"
        ) from exc

    serving = threading.Thread(target=server.serve_forever, name="google-oauth-cb", daemon=True)
    serving.start()
    try:
        if not done.wait(timeout=timeout_sec):
            raise RuntimeError("OAuth callback timeout")
    finally:
        server.shutdown()
        server.server_close()

    if result.error or not result.code or not result.state:
        raise RuntimeError(result.error or "OAuth callback returned no code")
    return result.code, result.state


# ---------------------------------------------------------------------------
# Token endpoint calls
# ---------------------------------------------------------------------------


def _exchange_code_for_tokens(
    client_id: str,
    client_secret: str | None,
    code: str,
    verifier: str,
    *,
    http_client: httpx.Client | None = None,
) -> dict:
    body = {
        "client_id": client_id,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
        "code_verifier": verifier,
    }
    if client_secret:
        body["client_secret"] = client_secret

    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    client = http_client or httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SEC)
    try:
        resp = client.post(TOKEN_URL, data=body, headers=headers)
    finally:
        if http_client is None:
            client.close()
    if resp.status_code >= 400:
        raise RuntimeError(f"Token exchange failed: HTTP {resp.status_code} {resp.text}")
    data = resp.json()
    if "refresh_token" not in data or "access_token" not in data:
        raise RuntimeError("Token exchange did not return refresh_token + access_token")
    return data


def refresh_access_token(
    creds: GoogleAntigravityCredentials,
    *,
    http_client: httpx.Client | None = None,
) -> GoogleAntigravityCredentials:
    """Exchange the stored refresh_token for a fresh access_token.

    Returns a NEW credentials object (does not mutate or persist). Caller is
    responsible for save_credentials() if persistence is desired.
    """
    client_id, client_secret = resolve_oauth_client_config()
    body = {
        "client_id": client_id,
        "refresh_token": creds.refresh_token,
        "grant_type": "refresh_token",
    }
    if client_secret:
        body["client_secret"] = client_secret

    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    client = http_client or httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SEC)
    try:
        resp = client.post(TOKEN_URL, data=body, headers=headers)
    finally:
        if http_client is None:
            client.close()
    if resp.status_code >= 400:
        raise RuntimeError(f"Token refresh failed: HTTP {resp.status_code} {resp.text}")
    data = resp.json()
    if "access_token" not in data:
        raise RuntimeError("Refresh response missing access_token")
    new_expires = time.time() + float(data.get("expires_in", 3600)) - TOKEN_REFRESH_LEEWAY_SEC
    return GoogleAntigravityCredentials(
        access_token=str(data["access_token"]),
        refresh_token=str(data.get("refresh_token", creds.refresh_token)),
        expires_at=new_expires,
        project_id=creds.project_id,
        email=creds.email,
        tier=creds.tier,
    )


# ---------------------------------------------------------------------------
# Identity + project resolution (loadCodeAssist / onboardUser)
# ---------------------------------------------------------------------------


_LOAD_CODE_ASSIST_METADATA = {
    "ideType": "IDE_UNSPECIFIED",
    "platform": "PLATFORM_UNSPECIFIED",
    "pluginType": "GEMINI",
}


def _fetch_user_email(access_token: str, http_client: httpx.Client) -> str:
    try:
        resp = http_client.get(
            USERINFO_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": USER_AGENT,
            },
        )
        if resp.status_code == 200:
            return str(resp.json().get("email", ""))
    except (httpx.HTTPError, ValueError):
        pass
    return ""


def _is_vpc_sc_violation(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    error = payload.get("error")
    if not isinstance(error, dict):
        return False
    details = error.get("details")
    if not isinstance(details, list):
        return False
    return any(
        isinstance(item, dict) and item.get("reason") == "SECURITY_POLICY_VIOLATED"
        for item in details
    )


def _try_load_code_assist(
    access_token: str,
    http_client: httpx.Client,
) -> tuple[str, dict, Exception | None]:
    """Hit each loadCodeAssist endpoint in order. Return (active_endpoint, data, error)."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Client-Metadata": json.dumps(_LOAD_CODE_ASSIST_METADATA),
    }
    env_project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or os.environ.get("GOOGLE_CLOUD_PROJECT_ID", "").strip()
    )
    body: dict = {
        "metadata": {**_LOAD_CODE_ASSIST_METADATA},
    }
    if env_project:
        body["cloudaicompanionProject"] = env_project
        body["metadata"]["duetProject"] = env_project

    last_err: Exception | None = None
    for endpoint in LOAD_CODE_ASSIST_ENDPOINTS:
        try:
            resp = http_client.post(
                f"{endpoint}/v1internal:loadCodeAssist",
                headers=headers,
                content=json.dumps(body),
            )
        except httpx.HTTPError as exc:
            last_err = exc
            continue

        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            if _is_vpc_sc_violation(payload):
                return endpoint, {"currentTier": {"id": TIER_STANDARD}}, None
            last_err = RuntimeError(
                f"loadCodeAssist failed at {endpoint}: HTTP {resp.status_code} {resp.text}"
            )
            continue

        try:
            return endpoint, resp.json(), None
        except ValueError as exc:
            last_err = exc
    return CODE_ASSIST_ENDPOINT_PROD, {}, last_err


def _onboard_user(
    endpoint: str,
    access_token: str,
    tier_id: str,
    http_client: httpx.Client,
) -> str:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "Client-Metadata": json.dumps(_LOAD_CODE_ASSIST_METADATA),
    }
    env_project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or os.environ.get("GOOGLE_CLOUD_PROJECT_ID", "").strip()
    )
    body: dict = {
        "tierId": tier_id,
        "metadata": {**_LOAD_CODE_ASSIST_METADATA},
    }
    if tier_id != TIER_FREE and env_project:
        body["cloudaicompanionProject"] = env_project
        body["metadata"]["duetProject"] = env_project

    resp = http_client.post(
        f"{endpoint}/v1internal:onboardUser",
        headers=headers,
        content=json.dumps(body),
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"onboardUser failed: HTTP {resp.status_code} {resp.text}")
    lro = resp.json()

    if not lro.get("done") and lro.get("name"):
        for _ in range(24):
            time.sleep(5)
            poll = http_client.get(f"{endpoint}/v1internal/{lro['name']}", headers=headers)
            if poll.status_code >= 400:
                continue
            try:
                lro = poll.json()
            except ValueError:
                continue
            if lro.get("done"):
                break
        else:
            raise RuntimeError("onboardUser polling timed out")

    project = (lro.get("response") or {}).get("cloudaicompanionProject") or {}
    project_id = project.get("id")
    if isinstance(project_id, str) and project_id:
        return project_id
    if env_project:
        return env_project
    raise RuntimeError(
        "Could not provision a Google Cloud project. "
        "Set GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_PROJECT_ID."
    )


def _discover_project_and_tier(
    access_token: str,
    http_client: httpx.Client,
) -> tuple[str, str]:
    """Return (project_id, tier_id) by walking loadCodeAssist + onboardUser if needed."""
    endpoint, data, load_err = _try_load_code_assist(access_token, http_client)
    env_project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or os.environ.get("GOOGLE_CLOUD_PROJECT_ID", "").strip()
    )
    has_data = bool(
        data.get("currentTier") or data.get("cloudaicompanionProject") or data.get("allowedTiers")
    )
    if not has_data and load_err:
        if env_project:
            return env_project, ""
        raise load_err

    current_tier = data.get("currentTier") or {}
    if current_tier:
        project = data.get("cloudaicompanionProject")
        if isinstance(project, str) and project:
            return project, str(current_tier.get("id", ""))
        if isinstance(project, dict) and project.get("id"):
            return str(project["id"]), str(current_tier.get("id", ""))
        if env_project:
            return env_project, str(current_tier.get("id", ""))
        raise RuntimeError(
            "Account has a tier set but no project ID. "
            "Set GOOGLE_CLOUD_PROJECT or GOOGLE_CLOUD_PROJECT_ID."
        )

    allowed = data.get("allowedTiers") or []
    default_tier = next((t for t in allowed if t.get("isDefault")), None)
    tier_id = (default_tier or {}).get("id") or TIER_FREE

    if tier_id != TIER_FREE and not env_project:
        raise RuntimeError(
            "This account is on a paid tier and requires GOOGLE_CLOUD_PROJECT or "
            "GOOGLE_CLOUD_PROJECT_ID."
        )
    project_id = _onboard_user(endpoint, access_token, tier_id, http_client)
    return project_id, tier_id


# ---------------------------------------------------------------------------
# Top-level OAuth orchestration
# ---------------------------------------------------------------------------


def login_pkce(
    *,
    headless: bool = False,
    open_browser: bool = True,
    auth_url_sink=None,
    code_input=None,
) -> GoogleAntigravityCredentials:
    """Run the full OAuth login: build URL, capture callback, exchange + discover project.

    Args:
        headless:        If True, skip the localhost callback server and ask the
                         caller (via ``code_input``) to paste the redirect URL
                         manually. Useful for SSH/WSL2/remote setups.
        open_browser:    If True (default), call ``webbrowser.open`` on the auth URL.
        auth_url_sink:   Optional callable that receives the auth URL string —
                         used by the wizard to also print the URL.
        code_input:      Required when ``headless=True``: callable returning the
                         redirect URL the user pasted from their browser.

    Returns:
        Saved-and-loaded ``GoogleAntigravityCredentials``. The caller usually
        passes this straight to ``save_credentials()``; this function does NOT
        persist on its own.
    """
    client_id, client_secret = resolve_oauth_client_config()
    verifier, challenge = _generate_pkce()
    state = _generate_state()
    auth_url = _build_auth_url(client_id, challenge, state)

    # WSL2: localhost callback from a Windows browser cannot reach WSL2's network
    # stack reliably — automatically promote to headless/manual-paste mode.
    effective_headless = headless
    if not headless and _is_wsl2():
        _logger.warning(
            "WSL2 detected: the localhost OAuth callback server cannot receive "
            "the redirect from a Windows browser. Switching to headless (manual "
            "code-paste) mode automatically."
        )
        effective_headless = True
        if code_input is None:
            raise RuntimeError(
                "WSL2 detected; pass headless=True with a code_input callback"
            )

    if auth_url_sink is not None:
        with contextlib.suppress(Exception):  # noqa: BLE001
            auth_url_sink(auth_url)

    if open_browser and not effective_headless:
        with contextlib.suppress(webbrowser.Error):
            webbrowser.open(auth_url, new=1, autoraise=True)

    if effective_headless:
        if code_input is None:
            raise RuntimeError("headless=True requires code_input callback")
        pasted = code_input(auth_url).strip()
        code, _ = parse_oauth_callback_input(pasted, expected_state=state)
    else:
        try:
            code, _ = _wait_for_callback(state, timeout_sec=OAUTH_CALLBACK_TIMEOUT_SEC)
        except OAuthCallbackBindError as bind_err:
            _logger.warning(
                "OAuth callback server failed to bind (port %d busy?): %s — "
                "falling back to manual code-paste mode.",
                REDIRECT_PORT,
                bind_err,
            )
            if code_input is None:
                raise OAuthCallbackBindError(
                    f"{bind_err}. Pass a code_input callback so the manual "
                    "paste fallback can be used."
                ) from bind_err
            pasted = code_input(auth_url).strip()
            code, _ = parse_oauth_callback_input(pasted, expected_state=state)

    with httpx.Client(timeout=DEFAULT_HTTP_TIMEOUT_SEC) as http_client:
        token_resp = _exchange_code_for_tokens(
            client_id, client_secret, code, verifier, http_client=http_client
        )
        access_token = str(token_resp["access_token"])
        refresh_token = str(token_resp["refresh_token"])
        expires_at = (
            time.time() + float(token_resp.get("expires_in", 3600)) - TOKEN_REFRESH_LEEWAY_SEC
        )
        email = _fetch_user_email(access_token, http_client)
        project_id, tier = _discover_project_and_tier(access_token, http_client)

    return GoogleAntigravityCredentials(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        project_id=project_id,
        email=email,
        tier=tier,
    )


# ---------------------------------------------------------------------------
# Convenience: load-or-refresh
# ---------------------------------------------------------------------------


def get_active_credentials(*, refresh_if_needed: bool = True) -> GoogleAntigravityCredentials | None:
    """Return current creds, refreshing the access token if it's about to expire.

    Returns None if no credentials are saved on disk. Persists refreshed creds
    automatically.
    """
    creds = load_credentials()
    if creds is None:
        return None
    if not refresh_if_needed or not creds.is_expired():
        return creds
    refreshed = refresh_access_token(creds)
    save_credentials(refreshed)
    return refreshed
