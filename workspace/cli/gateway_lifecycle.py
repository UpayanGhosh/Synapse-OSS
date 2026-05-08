"""Start/stop helpers for the local Synapse gateway process."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any


def _is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _stop_process_tree(pid: int) -> None:
    if not _is_running(pid):
        return
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 and _is_running(pid):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
        return

    os.kill(pid, signal.SIGTERM)


def _runtime_env(data_root: Path, gateway: dict[str, Any]) -> dict[str, str]:
    runtime_tmp = data_root / "runtime" / "tmp"
    env = dict(os.environ)
    env.setdefault("SYNAPSE_HOME", str(data_root))
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("TEMP", str(runtime_tmp))
    env.setdefault("TMP", str(runtime_tmp))
    env.setdefault("TMPDIR", str(runtime_tmp))
    token = gateway.get("token")
    if token:
        env.setdefault("SYNAPSE_GATEWAY_TOKEN", str(token))
    return env


def _gateway_host(gateway: dict[str, Any]) -> str:
    env_host = os.environ.get("SYNAPSE_GATEWAY_HOST")
    if env_host:
        return env_host
    bind = gateway.get("bind", "loopback")
    return "127.0.0.1" if bind == "loopback" else "0.0.0.0"


def _gateway_port(gateway: dict[str, Any]) -> str:
    return os.environ.get("SYNAPSE_GATEWAY_PORT") or str(gateway.get("port", 8000))


def start_gateway(config: Any, popen_factory: Any = subprocess.Popen) -> tuple[bool, str]:
    """Start the gateway in the background.

    Returns:
        (started, message). ``started`` is False when an existing live pid was found.
    """

    data_root = Path(getattr(config, "data_root", Path.home() / ".synapse"))
    gateway = dict(getattr(config, "gateway", {}) or {})
    state_dir = data_root / "state"
    log_dir = data_root / "logs"
    pid_path = state_dir / "gateway.pid"
    log_path = log_dir / "gateway.log"

    if pid_path.exists():
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = 0
        if _is_running(pid):
            return False, f"Synapse gateway already running (pid {pid})."

    state_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    (data_root / "runtime" / "tmp").mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-X",
        "utf8",
        "-m",
        "uvicorn",
        "sci_fi_dashboard.api_gateway:app",
        "--host",
        _gateway_host(gateway),
        "--port",
        _gateway_port(gateway),
        "--workers",
        "1",
    ]
    kwargs: dict[str, Any] = {
        "cwd": str(data_root),
        "env": _runtime_env(data_root, gateway),
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True

    with log_path.open("ab") as log_handle:
        process = popen_factory(command, stdout=log_handle, stderr=log_handle, **kwargs)

    pid_path.write_text(str(process.pid), encoding="utf-8")
    return True, f"Synapse gateway started (pid {process.pid})."


def stop_gateway(config: Any) -> tuple[bool, str]:
    """Stop the background gateway process if a pid file exists."""

    data_root = Path(getattr(config, "data_root", Path.home() / ".synapse"))
    pid_path = data_root / "state" / "gateway.pid"
    if not pid_path.exists():
        return False, "Synapse gateway is not running."

    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        pid = 0
    if pid:
        _stop_process_tree(pid)
    pid_path.unlink(missing_ok=True)
    return True, "Synapse gateway stopped."
