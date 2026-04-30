from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from cli.workspace_seeding import ensure_agent_workspace
from synapse_config import resolve_data_root

PRODUCT_DIRS: tuple[str, ...] = (
    ".venv",
    "bin",
    "runtime",
    "workspace",
    "logs",
    "state",
    "bridges",
    "bridges/baileys",
    "skills",
)


def ensure_product_home(data_root: Path | None = None) -> dict[str, object]:
    """Create or repair the standalone Synapse product home.

    User-owned files under workspace/config/state are preserved. Managed launchers
    are repaired on every run because they are generated from this installed code.
    """
    root = (data_root or resolve_data_root()).expanduser().resolve()
    created: list[str] = []

    for rel in PRODUCT_DIRS:
        path = root / rel
        existed = path.exists()
        path.mkdir(parents=True, exist_ok=True)
        if not existed:
            created.append(rel)

    seeding_state = ensure_agent_workspace(root / "workspace", ensure_bootstrap_files=True)
    _write_managed_launchers(root)
    _copy_managed_bridge_assets(root)

    return {
        "data_root": str(root),
        "created": created,
        "workspace_state": seeding_state,
    }


def baileys_bridge_dir(data_root: Path | None = None) -> Path:
    root = (data_root or resolve_data_root()).expanduser().resolve()
    return root / "bridges" / "baileys"


def whatsapp_state_dir(data_root: Path | None = None) -> Path:
    root = (data_root or resolve_data_root()).expanduser().resolve()
    return root / "state" / "whatsapp"


def _write_managed_launchers(root: Path) -> None:
    bin_dir = root / "bin"
    _write_text(bin_dir / "synapse-gateway.bat", _windows_gateway_launcher())
    sh_path = bin_dir / "synapse-gateway.sh"
    _write_text(sh_path, _posix_gateway_launcher())
    try:
        sh_path.chmod(sh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def _copy_managed_bridge_assets(root: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "sci_fi_dashboard" / "runtime_assets" / "baileys-bridge"
    target = baileys_bridge_dir(root)
    if not source.exists():
        return
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        if {"node_modules", "auth_state", "media_cache", "test", "tests"}.intersection(rel.parts):
            continue
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _windows_gateway_launcher() -> str:
    return "\n".join(
        [
            "@echo off",
            "setlocal",
            "set PYTHONUTF8=1",
            "set PYTHONIOENCODING=utf-8",
            'set "SYNAPSE_HOME=%~dp0.."',
            'set "PYTHON=%SYNAPSE_HOME%\\.venv\\Scripts\\python.exe"',
            'if not exist "%PYTHON%" (',
            "  echo Synapse Python runtime missing. Run: synapse install",
            "  exit /b 1",
            ")",
            '"%PYTHON%" -X utf8 -m uvicorn sci_fi_dashboard.api_gateway:app --host 127.0.0.1 --port 8000 --workers 1',
            "",
        ]
    )


def _posix_gateway_launcher() -> str:
    return "\n".join(
        [
            "#!/usr/bin/env sh",
            "set -eu",
            "export PYTHONUTF8=1",
            "export PYTHONIOENCODING=utf-8",
            'SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"',
            'export SYNAPSE_HOME="$(dirname "$SCRIPT_DIR")"',
            'PYTHON="$SYNAPSE_HOME/.venv/bin/python"',
            'if [ ! -x "$PYTHON" ]; then',
            '  echo "Synapse Python runtime missing. Run: synapse install" >&2',
            "  exit 1",
            "fi",
            'exec "$PYTHON" -X utf8 -m uvicorn sci_fi_dashboard.api_gateway:app --host 127.0.0.1 --port 8000 --workers 1',
            "",
        ]
    )


def product_home_from_env() -> Path:
    raw = os.environ.get("SYNAPSE_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".synapse"
