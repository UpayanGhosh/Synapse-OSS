"""
Shared .env file loader for OpenClaw.

Resolves the .env path using the following priority:
  1. OPENCLAW_ENV_PATH environment variable (explicit override)
  2. Project root .env  (OpenClaw-OSS/.env)
  3. Workspace root .env (OpenClaw-OSS/workspace/.env)
"""

import os
from pathlib import Path


def resolve_env_path(anchor: Path | None = None) -> str:
    """
    Return the path to the .env file to load.

    Parameters
    ----------
    anchor : Path, optional
        A file inside the project (typically ``Path(__file__)``).
        Used to derive project-root and workspace-root when
        ``OPENCLAW_ENV_PATH`` is not set.  If *None*, the workspace
        directory containing this module is used as the anchor.
    """
    explicit = os.environ.get("OPENCLAW_ENV_PATH")
    if explicit:
        return explicit

    if anchor is None:
        anchor = Path(__file__)

    resolved = anchor.resolve()

    # Walk upwards until we find a directory that contains a .env
    # Heuristic: project root is the first ancestor that is NOT
    # "workspace" or a sub-package inside workspace.
    # Concrete layout:
    #   OpenClaw-OSS/               ← project root
    #   OpenClaw-OSS/workspace/     ← workspace root
    #   OpenClaw-OSS/workspace/sci_fi_dashboard/  ← sub-package
    #
    # We try project root first, then workspace root.

    workspace_root = _find_workspace_root(resolved)
    project_root = workspace_root.parent if workspace_root else resolved.parent

    root_env = project_root / ".env"
    workspace_env = workspace_root / ".env" if workspace_root else root_env

    return str(root_env if root_env.exists() else workspace_env)


def _find_workspace_root(path: Path) -> Path | None:
    """Walk up from *path* and return the first directory named ``workspace``."""
    for parent in path.parents:
        if parent.name == "workspace":
            return parent
    return None


def load_env_file(anchor: Path | None = None) -> None:
    """
    Parse a .env file and inject its values into ``os.environ``.

    Handles comments (``#``), quoted values, and spaces around keys.
    """
    env_path = resolve_env_path(anchor)
    if not os.path.exists(env_path):
        return

    print(f"🌍 Loading .env from {env_path}")
    with open(env_path, "r") as f:
        for raw_line in f:
            line = raw_line.strip()
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                os.environ[key] = value
