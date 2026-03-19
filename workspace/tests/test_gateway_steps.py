"""
test_gateway_steps.py — Unit tests for workspace/cli/gateway_steps.py

Tests:
  - QuickStart path generates a 48-char hex token when none exists
  - QuickStart path keeps an existing token
  - Non-interactive path reads env vars correctly
  - configure_gateway() returns a flat dict (no nested "auth" sub-dict)
"""

import pytest

# ---------------------------------------------------------------------------
# Availability guard — skip if gateway_steps not installed
# ---------------------------------------------------------------------------

try:
    from cli.gateway_steps import configure_gateway

    GATEWAY_STEPS_AVAILABLE = True
except ImportError:
    GATEWAY_STEPS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not GATEWAY_STEPS_AVAILABLE,
    reason="cli.gateway_steps not available",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_48_hex(token: str) -> bool:
    """Return True if token is a 48-character lowercase hex string."""
    return len(token) == 48 and all(c in "0123456789abcdef" for c in token)


# ===========================================================================
# QuickStart path — token auto-generation
# ===========================================================================


def test_quickstart_generates_48_char_hex_token_when_none_exists():
    """QuickStart with no existing token must auto-generate a 48-char hex token."""
    result = configure_gateway(flow="quickstart", existing_gateway={}, non_interactive=False)

    assert "token" in result, "Result must contain 'token' key"
    token = result["token"]
    assert token is not None, "Token should not be None in QuickStart mode (no auth disabled)"
    assert _is_48_hex(token), f"Expected 48-char hex token, got: {token!r} (len={len(token)})"


def test_quickstart_keeps_existing_token():
    """QuickStart with an existing token must preserve it (not overwrite)."""
    existing_token = "a" * 48  # valid 48-char hex-like string
    existing_gateway = {"token": existing_token}

    result = configure_gateway(flow="quickstart", existing_gateway=existing_gateway, non_interactive=False)

    assert result["token"] == existing_token, (
        f"QuickStart should keep existing token, got: {result['token']!r}"
    )


# ===========================================================================
# Non-interactive path — env var passthrough
# ===========================================================================


def test_non_interactive_reads_port_from_env(monkeypatch):
    """Non-interactive mode must read SYNAPSE_GATEWAY_PORT env var."""
    monkeypatch.setenv("SYNAPSE_GATEWAY_PORT", "9000")
    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)

    result = configure_gateway(flow="advanced", existing_gateway={}, non_interactive=True)

    assert result["port"] == 9000, f"Expected port 9000, got {result['port']}"


def test_non_interactive_reads_bind_from_env(monkeypatch):
    """Non-interactive mode must read SYNAPSE_GATEWAY_BIND env var."""
    monkeypatch.setenv("SYNAPSE_GATEWAY_BIND", "lan")
    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)

    result = configure_gateway(flow="advanced", existing_gateway={}, non_interactive=True)

    assert result["bind"] == "lan", f"Expected bind=lan, got {result['bind']}"


def test_non_interactive_reads_token_from_env(monkeypatch):
    """Non-interactive mode must use SYNAPSE_GATEWAY_TOKEN when set."""
    my_token = "b" * 48
    monkeypatch.setenv("SYNAPSE_GATEWAY_TOKEN", my_token)
    monkeypatch.setenv("SYNAPSE_GATEWAY_AUTH_MODE", "token")

    result = configure_gateway(flow="advanced", existing_gateway={}, non_interactive=True)

    assert result["token"] == my_token, f"Expected token from env, got: {result['token']!r}"


def test_non_interactive_generates_token_when_env_missing(monkeypatch):
    """Non-interactive with no SYNAPSE_GATEWAY_TOKEN must auto-generate a 48-char token."""
    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)
    monkeypatch.setenv("SYNAPSE_GATEWAY_AUTH_MODE", "token")

    result = configure_gateway(flow="advanced", existing_gateway={}, non_interactive=True)

    token = result.get("token")
    assert token is not None
    assert _is_48_hex(token), f"Expected 48-char hex token, got: {token!r}"


def test_non_interactive_disabled_auth_sets_token_none(monkeypatch):
    """Non-interactive with SYNAPSE_GATEWAY_AUTH_MODE=disabled must set token=None."""
    monkeypatch.setenv("SYNAPSE_GATEWAY_AUTH_MODE", "disabled")
    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)

    result = configure_gateway(flow="advanced", existing_gateway={}, non_interactive=True)

    assert result["token"] is None, f"Expected token=None with disabled auth, got: {result['token']!r}"


def test_non_interactive_invalid_port_falls_back_to_default(monkeypatch):
    """Non-interactive with invalid port value should fall back to 8000."""
    monkeypatch.setenv("SYNAPSE_GATEWAY_PORT", "not-a-number")
    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)

    result = configure_gateway(flow="advanced", existing_gateway={}, non_interactive=True)

    assert result["port"] == 8000, f"Expected default port 8000, got {result['port']}"


# ===========================================================================
# Return shape — flat dict (no nested "auth" sub-dict)
# ===========================================================================


def test_configure_gateway_returns_flat_dict():
    """configure_gateway() must return a flat dict with no nested 'auth' key."""
    result = configure_gateway(flow="quickstart", existing_gateway={}, non_interactive=False)

    assert isinstance(result, dict), "Result must be a dict"
    assert "auth" not in result, (
        f"Result must be flat (no nested 'auth' key), got keys: {list(result.keys())}"
    )
    # Required top-level keys
    assert "port" in result, "Result must contain 'port'"
    assert "bind" in result, "Result must contain 'bind'"
    assert "token" in result, "Result must contain 'token'"


def test_configure_gateway_non_interactive_flat_dict(monkeypatch):
    """configure_gateway() in non-interactive mode also returns a flat dict."""
    monkeypatch.delenv("SYNAPSE_GATEWAY_TOKEN", raising=False)

    result = configure_gateway(flow="advanced", existing_gateway={}, non_interactive=True)

    assert isinstance(result, dict)
    assert "auth" not in result
    assert "port" in result
    assert "bind" in result
    assert "token" in result
