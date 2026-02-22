# sci_fi_dashboard/sbs/sentinel/tools.py

"""
AGENT TOOL WRAPPERS
====================
These are the ONLY file operations the agent should have access to.
Your agent framework (LangChain, custom, etc.) should register THESE
functions as tools, NOT raw file operations.
"""

from pathlib import Path
from .gateway import Sentinel, SentinelError

# Global sentinel instance (initialized once at app startup)
_sentinel: Sentinel = None

def init_sentinel(project_root: Path):
    global _sentinel
    _sentinel = Sentinel(project_root)

def agent_read_file(path: str, reason: str = "agent requested") -> str:
    """
    Tool: Read a file.
    The agent calls this instead of open().
    """
    if not _sentinel:
        raise RuntimeError("Sentinel not initialized")
    try:
        return _sentinel.safe_read(path, reason)
    except SentinelError as e:
        return f"[SENTINEL DENIED]: {str(e)}"

def agent_write_file(path: str, content: str, reason: str = "") -> str:
    """
    Tool: Write to a file.
    The agent calls this instead of open('w').
    """
    if not _sentinel:
        raise RuntimeError("Sentinel not initialized")
    try:
        _sentinel.safe_write(path, content, reason)
        return f"[SUCCESS]: Written to {path}"
    except SentinelError as e:
        return f"[SENTINEL DENIED]: {str(e)}"

def agent_delete_file(path: str, reason: str = "") -> str:
    """
    Tool: Delete a file.
    """
    if not _sentinel:
        raise RuntimeError("Sentinel not initialized")
    try:
        _sentinel.safe_delete(path, reason)
        return f"[SUCCESS]: Deleted {path}"
    except SentinelError as e:
        return f"[SENTINEL DENIED]: {str(e)}"

def agent_list_directory(path: str, reason: str = "") -> str:
    """
    Tool: List files in a directory.
    """
    if not _sentinel:
        raise RuntimeError("Sentinel not initialized")
    try:
        _sentinel.check_access(path, "list", reason)
        resolved = _sentinel._resolve_path(path)
        items = [str(p.name) for p in resolved.iterdir()]
        return "\\n".join(items)
    except SentinelError as e:
        return f"[SENTINEL DENIED]: {str(e)}"
