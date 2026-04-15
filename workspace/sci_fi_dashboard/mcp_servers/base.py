"""Base utilities for Synapse MCP servers."""

import logging
import os
import sys

_DIR = os.path.dirname(os.path.abspath(__file__))
_DASHBOARD = os.path.abspath(os.path.join(_DIR, ".."))
_WORKSPACE = os.path.abspath(os.path.join(_DASHBOARD, ".."))
for p in (_DASHBOARD, _WORKSPACE):
    if p not in sys.path:
        sys.path.insert(0, p)

logger = logging.getLogger("synapse.mcp")

# ── Shared MCP auth token (optional, from SYNAPSE_GATEWAY_TOKEN) ─────
_MCP_AUTH_TOKEN: str | None = os.environ.get("SYNAPSE_GATEWAY_TOKEN")


def check_mcp_auth(arguments: dict) -> str | None:
    """Return an error string if MCP auth fails, or None if OK.

    If SYNAPSE_GATEWAY_TOKEN is not set, auth is skipped (open mode).
    When set, callers must pass ``auth_token`` in their arguments dict.
    """
    if not _MCP_AUTH_TOKEN:
        return None  # no token configured — allow (backward-compatible)
    provided = arguments.get("auth_token") or ""
    if not provided or provided != _MCP_AUTH_TOKEN:
        return "auth_token missing or invalid"
    return None


def setup_logging():
    """Configure logging to stderr (stdout reserved for MCP stdio transport)."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
