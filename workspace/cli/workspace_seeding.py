"""
workspace_seeding.py — Agent workspace seeding and state machine for Synapse-OSS.

Seeds Markdown guidance files into the agent workspace on first run and
maintains a workspace-state.json file that tracks bootstrapSeededAt and
setupCompletedAt timestamps.  This prevents re-triggering the bootstrapping
ritual on subsequent onboard runs.

Template files:
  INSTRUCTIONS.md, AGENTS.md, SOUL.md, CORE.md, CODE.md, IDENTITY.md, USER.md,
  TOOLS.md, MEMORY.md, HEARTBEAT.md, BOOTSTRAP.md. INSTRUCTIONS.md, CORE.md,
  and AGENTS.md are loaded from single canonical shipping sources in
  sci_fi_dashboard/agent_workspace/.

Exports:
  write_file_if_missing()     Exclusive-create a file; returns True if written
  ensure_agent_workspace()    Main entry point — seeds workspace, updates state
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Template file list (order matters for display; BOOTSTRAP.md written last)
# ---------------------------------------------------------------------------

_TEMPLATE_FILES: list[str] = [
    "INSTRUCTIONS.md",
    "AGENTS.md",
    "SOUL.md",
    "CORE.md",
    "CODE.md",
    "IDENTITY.md",
    "USER.md",
    "TOOLS.md",
    "MEMORY.md",
    "HEARTBEAT.md",
    "BOOTSTRAP.md",  # must be last — conditional seeding
]

# Legacy-workspace indicators — if any exist, mark setupCompletedAt immediately.
_LEGACY_INDICATORS: list[str] = [".git", "MEMORY.md", "memory"]

# ---------------------------------------------------------------------------
# State file helpers
# ---------------------------------------------------------------------------

_STATE_FILENAME = "workspace-state.json"
_STATE_DIR = ".synapse"


def _state_file_path(workspace_dir: Path) -> Path:
    """Return the path to workspace-state.json inside the workspace."""
    return workspace_dir / _STATE_DIR / _STATE_FILENAME


def _load_workspace_state(workspace_dir: Path) -> dict:
    """Load workspace state from disk.

    Returns an empty dict on FileNotFoundError or JSON parse errors.
    """
    state_path = _state_file_path(workspace_dir)
    try:
        with open(state_path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_workspace_state(workspace_dir: Path, state: dict) -> None:
    """Atomically write the workspace state dict to disk.

    Uses tempfile.mkstemp + os.fdopen + os.replace pattern (same as
    PairingStore._save() and write_config()) for crash-safe writes.
    No os.chmod — workspace-state.json stores only timestamps, not secrets.
    """
    state_path = _state_file_path(workspace_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(state_path.parent),
        suffix=".tmp",
        prefix=_STATE_FILENAME + ".",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp_path, str(state_path))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# write_file_if_missing
# ---------------------------------------------------------------------------


def write_file_if_missing(path: Path, content: str) -> bool:
    """Write content to path using exclusive-create mode ("x").

    If the file already exists, does nothing and returns False.
    Returns True if the file was newly written.

    Directories up to path.parent are created if they don't exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8") as fh:
            fh.write(content)
        return True
    except FileExistsError:
        return False


# ---------------------------------------------------------------------------
# Template loader
# ---------------------------------------------------------------------------


def _load_template(filename: str) -> str:
    """Load a runtime workspace template."""
    if filename in {"INSTRUCTIONS.md", "CORE.md", "AGENTS.md"}:
        canonical_path = Path(__file__).parents[1] / "sci_fi_dashboard" / "agent_workspace" / filename
        return canonical_path.read_text(encoding="utf-8")
    template_dir = Path(__file__).parent / "templates"
    template_path = template_dir / filename
    return template_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ensure_agent_workspace — main entry point
# ---------------------------------------------------------------------------


def ensure_agent_workspace(
    workspace_dir: Path,
    ensure_bootstrap_files: bool = True,
) -> dict:
    """Create and seed the agent workspace directory.

    State machine:
      1. If setupCompletedAt already set → skip all seeding, return state.
      2. If legacy indicators (.git, MEMORY.md, memory/) exist in workspace_dir
         → set setupCompletedAt without writing any template files.
      3. Otherwise:
         a. If bootstrapSeededAt is NOT set → seed all 7 templates via
            write_file_if_missing(); set bootstrapSeededAt.
         b. If bootstrapSeededAt IS set and BOOTSTRAP.md no longer exists
            → set setupCompletedAt (agent completed bootstrap ritual).
      4. Save and return updated state dict.

    Args:
        workspace_dir:          Target directory to seed.
        ensure_bootstrap_files: If False, skip file seeding (state only).

    Returns:
        The updated state dict (keys: bootstrapSeededAt, setupCompletedAt).
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)

    state = _load_workspace_state(workspace_dir)

    # --- Step 1: Already fully set up ---
    if state.get("setupCompletedAt"):
        return state

    # --- Step 2: Legacy workspace detection ---
    for indicator in _LEGACY_INDICATORS:
        if (workspace_dir / indicator).exists():
            state["setupCompletedAt"] = _utcnow()
            _save_workspace_state(workspace_dir, state)
            return state

    bootstrap_seeded = state.get("bootstrapSeededAt")

    # --- Step 3b: Bootstrap ritual complete (BOOTSTRAP.md deleted by agent) ---
    if bootstrap_seeded and not (workspace_dir / "BOOTSTRAP.md").exists():
        state["setupCompletedAt"] = _utcnow()
        _save_workspace_state(workspace_dir, state)
        return state

    # --- Step 3a: First time — seed all templates ---
    if not bootstrap_seeded and ensure_bootstrap_files:
        for filename in _TEMPLATE_FILES:
            try:
                content = _load_template(filename)
            except (FileNotFoundError, OSError):
                # If template file is missing, skip gracefully
                continue
            write_file_if_missing(workspace_dir / filename, content)

        state["bootstrapSeededAt"] = _utcnow()
        _save_workspace_state(workspace_dir, state)

    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    """Return current UTC time as ISO 8601 string (no microseconds)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
