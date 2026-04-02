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


def setup_logging():
    """Configure logging to stderr (stdout reserved for MCP stdio transport)."""
    logging.basicConfig(
        level=logging.INFO,
        format="[%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
