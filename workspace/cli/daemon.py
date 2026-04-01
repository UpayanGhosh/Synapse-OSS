"""
daemon.py — GatewayService ABC and platform-specific daemon installers.

Provides install/uninstall/restart/status for the Synapse gateway as a
persistent background service on macOS (launchd), Linux (systemd user unit),
and Windows (schtasks / Startup folder).

Exports:
  InstallOpts             — dataclass for daemon install parameters
  GatewayService          — ABC defining the install/manage interface
  LaunchdService          — macOS launchd backend
  SystemdUserService      — Linux systemd --user backend
  WindowsTaskService      — Windows schtasks / Startup folder backend
  resolve_gateway_service()   — Returns the correct backend for sys.platform
  build_gateway_install_plan()— Constructs InstallOpts from SynapseConfig
"""

from __future__ import annotations

import os
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# InstallOpts
# ---------------------------------------------------------------------------


@dataclass
class InstallOpts:
    """Parameters for installing the gateway as a daemon.

    Attributes:
        exec_path: Full path to the Python / uvicorn executable.
        args:      Command-line arguments (includes --host derived from bind mode).
        env:       Environment variables to set for the daemon process.
        log_dir:   Directory where stdout/stderr logs are written.
    """

    exec_path: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    log_dir: Path = field(default_factory=lambda: Path.home() / ".synapse" / "logs")


# ---------------------------------------------------------------------------
# GatewayService ABC
# ---------------------------------------------------------------------------


class GatewayService(ABC):
    """Abstract base class for platform-specific gateway daemon management."""

    @abstractmethod
    def install(self, opts: InstallOpts) -> None:
        """Install and start the gateway service."""

    @abstractmethod
    def uninstall(self) -> None:
        """Stop and remove the gateway service."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the running service without removing it."""

    @abstractmethod
    def restart(self) -> None:
        """Restart the service."""

    @abstractmethod
    def is_loaded(self) -> bool:
        """Return True if the service is currently active/running."""

    @abstractmethod
    def read_command(self) -> list[str]:
        """Return the command list that was installed for diagnostic display."""


# ---------------------------------------------------------------------------
# LaunchdService — macOS
# ---------------------------------------------------------------------------

_LAUNCHD_LABEL = "ai.synapse.gateway"
_LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{program_args}    </array>
    <key>EnvironmentVariables</key>
    <dict>
{env_vars}    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/gateway.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/gateway.stderr.log</string>
</dict>
</plist>
"""


class LaunchdService(GatewayService):
    """macOS launchd backend — installs a LaunchAgent plist."""

    @property
    def _plist_path(self) -> Path:
        return (
            Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL}.plist"
        )

    def _build_plist(self, opts: InstallOpts) -> str:
        args = [opts.exec_path] + opts.args
        program_args = "".join(
            f"        <string>{_xml_escape(a)}</string>\n" for a in args
        )
        env_vars = "".join(
            f"        <key>{_xml_escape(k)}</key>\n"
            f"        <string>{_xml_escape(v)}</string>\n"
            for k, v in opts.env.items()
        )
        return _LAUNCHD_PLIST_TEMPLATE.format(
            label=_LAUNCHD_LABEL,
            program_args=program_args,
            env_vars=env_vars,
            log_dir=str(opts.log_dir),
        )

    def install(self, opts: InstallOpts) -> None:
        opts.log_dir.mkdir(parents=True, exist_ok=True)
        self._plist_path.parent.mkdir(parents=True, exist_ok=True)
        self._plist_path.write_text(self._build_plist(opts), encoding="utf-8")
        subprocess.run(
            ["launchctl", "load", str(self._plist_path)],
            check=False,
        )

    def uninstall(self) -> None:
        subprocess.run(
            ["launchctl", "unload", str(self._plist_path)],
            check=False,
        )
        with _suppress_oserror():
            self._plist_path.unlink()

    def stop(self) -> None:
        subprocess.run(
            ["launchctl", "stop", _LAUNCHD_LABEL],
            check=False,
        )

    def restart(self) -> None:
        subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{_LAUNCHD_LABEL}"],
            check=False,
        )

    def is_loaded(self) -> bool:
        result = subprocess.run(
            ["launchctl", "list", _LAUNCHD_LABEL],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def read_command(self) -> list[str]:
        if not self._plist_path.exists():
            return []
        import xml.etree.ElementTree as ET  # noqa: PLC0415

        try:
            tree = ET.parse(str(self._plist_path))
            root = tree.getroot()
            # Find ProgramArguments array
            dict_elem = root.find("dict")
            if dict_elem is None:
                return []
            keys = list(dict_elem)
            for i, elem in enumerate(keys):
                if elem.tag == "key" and elem.text == "ProgramArguments":
                    arr = keys[i + 1]
                    return [s.text or "" for s in arr.findall("string")]
        except Exception:  # noqa: BLE001
            pass
        return []


# ---------------------------------------------------------------------------
# SystemdUserService — Linux
# ---------------------------------------------------------------------------

_SYSTEMD_UNIT_NAME = "synapse-gateway.service"
_SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=Synapse-OSS AI Gateway
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_path} {args}
Restart=on-failure
RestartSec=5
{env_lines}
StandardOutput=append:{log_dir}/gateway.stdout.log
StandardError=append:{log_dir}/gateway.stderr.log

[Install]
WantedBy=default.target
"""


class SystemdUserService(GatewayService):
    """Linux systemd --user backend."""

    @property
    def _unit_path(self) -> Path:
        return (
            Path.home()
            / ".config"
            / "systemd"
            / "user"
            / _SYSTEMD_UNIT_NAME
        )

    def _build_unit(self, opts: InstallOpts) -> str:
        args_str = " ".join(opts.args)
        env_lines = "\n".join(
            f"Environment={k}={v}" for k, v in opts.env.items()
        )
        return _SYSTEMD_UNIT_TEMPLATE.format(
            exec_path=opts.exec_path,
            args=args_str,
            env_lines=env_lines,
            log_dir=str(opts.log_dir),
        )

    def _systemctl_available(self) -> bool:
        result = subprocess.run(
            ["systemctl", "--user", "status"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        # Return code 0 or 3 (not running) are both "available"
        return result.returncode in (0, 1, 3)

    def install(self, opts: InstallOpts) -> None:
        if not self._systemctl_available():
            return  # container / minimal environment — skip gracefully

        opts.log_dir.mkdir(parents=True, exist_ok=True)
        self._unit_path.parent.mkdir(parents=True, exist_ok=True)
        self._unit_path.write_text(self._build_unit(opts), encoding="utf-8")

        # Enable linger so the user unit survives logout (nice-to-have; skip if unavailable)
        try:
            subprocess.run(
                ["loginctl", "enable-linger", str(os.getuid())],
                check=True,
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            print(
                "Warning: loginctl not available — linger not enabled. "
                "The service may stop after logout on some systems."
            )

        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
        )
        subprocess.run(
            ["systemctl", "--user", "enable", "--now", _SYSTEMD_UNIT_NAME],
            check=False,
        )

    def uninstall(self) -> None:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", _SYSTEMD_UNIT_NAME],
            check=False,
        )
        with _suppress_oserror():
            self._unit_path.unlink()
        subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            check=False,
        )

    def stop(self) -> None:
        subprocess.run(
            ["systemctl", "--user", "stop", _SYSTEMD_UNIT_NAME],
            check=False,
        )

    def restart(self) -> None:
        subprocess.run(
            ["systemctl", "--user", "restart", _SYSTEMD_UNIT_NAME],
            check=False,
        )

    def is_loaded(self) -> bool:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", _SYSTEMD_UNIT_NAME],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def read_command(self) -> list[str]:
        if not self._unit_path.exists():
            return []
        for line in self._unit_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("ExecStart="):
                return line[len("ExecStart="):].split()
        return []


# ---------------------------------------------------------------------------
# WindowsTaskService — Windows
# ---------------------------------------------------------------------------

_WINDOWS_TASK_NAME = "Synapse Gateway"


class WindowsTaskService(GatewayService):
    """Windows Task Scheduler backend with Startup folder fallback."""

    @property
    def _startup_bat_path(self) -> Path:
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        return (
            Path(appdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
            / "synapse_gateway.bat"
        )

    def _build_bat_content(self, opts: InstallOpts) -> str:
        args_str = " ".join(opts.args)
        env_lines = "\n".join(f"SET {k}={v}" for k, v in opts.env.items())
        return (
            "@echo off\n"
            f"{env_lines}\n"
            f'START "" "{opts.exec_path}" {args_str}\n'
        )

    def _schtasks_command(self, opts: InstallOpts) -> list[str]:
        args_str = " ".join(opts.args)
        full_cmd = f'"{opts.exec_path}" {args_str}'
        return [
            "schtasks",
            "/Create",
            "/TN",
            _WINDOWS_TASK_NAME,
            "/TR",
            full_cmd,
            "/SC",
            "ONLOGON",
            "/F",  # Force overwrite if exists
        ]

    @staticmethod
    def _is_admin() -> bool:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def install(self, opts: InstallOpts) -> None:
        opts.log_dir.mkdir(parents=True, exist_ok=True)
        if self._is_admin():
            try:
                result = subprocess.run(
                    self._schtasks_command(opts),
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                if result.returncode == 0:
                    print(
                        f"Synapse Gateway registered as Windows scheduled task '{_WINDOWS_TASK_NAME}'."
                    )
                    return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass  # fall through to Startup folder

        # Non-admin or schtasks failed: write .bat to Startup folder
        bat_path = self._startup_bat_path
        bat_path.parent.mkdir(parents=True, exist_ok=True)
        bat_path.write_text(self._build_bat_content(opts), encoding="utf-8")
        print(f"Synapse Gateway startup script written to Startup folder: {bat_path}")

    def uninstall(self) -> None:
        # Remove scheduled task
        subprocess.run(
            ["schtasks", "/Delete", "/TN", _WINDOWS_TASK_NAME, "/F"],
            capture_output=True,
            check=False,
        )
        # Also remove Startup bat if it exists
        with _suppress_oserror():
            self._startup_bat_path.unlink()

    def stop(self) -> None:
        subprocess.run(
            ["schtasks", "/End", "/TN", _WINDOWS_TASK_NAME],
            capture_output=True,
            check=False,
        )

    def restart(self) -> None:
        self.stop()
        subprocess.run(
            ["schtasks", "/Run", "/TN", _WINDOWS_TASK_NAME],
            capture_output=True,
            check=False,
        )

    def is_loaded(self) -> bool:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", _WINDOWS_TASK_NAME],
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def read_command(self) -> list[str]:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", _WINDOWS_TASK_NAME, "/FO", "LIST", "/V"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            if "Task To Run" in line or "Run As User" not in line and ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2 and "Task To Run" in parts[0]:
                    return parts[1].strip().split()
        return []


# ---------------------------------------------------------------------------
# resolve_gateway_service
# ---------------------------------------------------------------------------


def resolve_gateway_service() -> GatewayService:
    """Return the correct GatewayService backend for the current platform.

    Returns:
        LaunchdService()       on macOS (sys.platform == "darwin")
        SystemdUserService()   on Linux (sys.platform == "linux")
        WindowsTaskService()   on Windows (sys.platform == "win32")

    Raises:
        NotImplementedError: On unsupported platforms.
    """
    if sys.platform == "darwin":
        return LaunchdService()
    if sys.platform == "linux":
        return SystemdUserService()
    if sys.platform == "win32":
        return WindowsTaskService()
    raise NotImplementedError(
        f"No GatewayService implementation for platform {sys.platform!r}."
        " Supported: darwin, linux, win32."
    )


# ---------------------------------------------------------------------------
# build_gateway_install_plan
# ---------------------------------------------------------------------------


def build_gateway_install_plan(config: object) -> InstallOpts:
    """Build an InstallOpts from a SynapseConfig instance.

    Maps gateway.bind to the uvicorn --host flag:
      "loopback" -> --host 127.0.0.1
      "lan" / "auto" -> --host 0.0.0.0
      (anything else defaults to 127.0.0.1)

    Args:
        config: SynapseConfig instance (typed as object to avoid circular import).

    Returns:
        InstallOpts ready to pass to GatewayService.install().
    """
    # Resolve Python interpreter path
    exec_path = sys.executable

    gateway: dict = getattr(config, "gateway", {})
    data_root: Path = getattr(config, "data_root", Path.home() / ".synapse")

    port: int = int(gateway.get("port", 8000))
    bind: str = gateway.get("bind", "loopback")

    # Map bind mode to --host flag
    host = "127.0.0.1" if bind == "loopback" else "0.0.0.0"

    log_dir = data_root / "logs"

    # Build uvicorn args
    # Use -m uvicorn so it works regardless of uvicorn being on PATH
    args: list[str] = [
        "-m",
        "uvicorn",
        "sci_fi_dashboard.api_gateway:app",
        "--host",
        host,
        "--port",
        str(port),
        "--workers",
        "1",
    ]

    # Collect env vars from config
    env: dict[str, str] = {}
    token = gateway.get("token")
    if token:
        env["SYNAPSE_GATEWAY_TOKEN"] = token
    synapse_home = os.environ.get("SYNAPSE_HOME", str(data_root))
    env["SYNAPSE_HOME"] = synapse_home

    return InstallOpts(
        exec_path=exec_path,
        args=args,
        env=env,
        log_dir=log_dir,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _suppress_oserror():
    """Context manager that silently suppresses OSError."""
    import contextlib  # noqa: PLC0415

    return contextlib.suppress(OSError)


def _xml_escape(s: str) -> str:
    """Escape special characters for XML attribute / text content."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
