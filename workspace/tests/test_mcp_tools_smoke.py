"""Pin the contract: tools_server.py uses module-level Sentinel funcs, not Sentinel methods.
Regression guard for a bug that was previously documented in CLAUDE.md and has since been fixed.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_SERVER = REPO_ROOT / "workspace" / "sci_fi_dashboard" / "mcp_servers" / "tools_server.py"


def test_tools_server_does_not_use_sentinel_method_form():
    src = TOOLS_SERVER.read_text(encoding="utf-8")
    assert "Sentinel().agent_read_file" not in src, (
        "tools_server.py regressed: must call module-level agent_read_file/_sentinel, "
        "not the (nonexistent) Sentinel.agent_read_file method."
    )


def test_tools_server_uses_module_level_sentinel_helpers():
    src = TOOLS_SERVER.read_text(encoding="utf-8")
    assert "_sentinel.check_access" in src
    assert "agent_write_file" in src
