"""
test_daemon.py — Unit tests for workspace/cli/daemon.py

Tests:
  - build_gateway_install_plan() maps loopback → --host 127.0.0.1
  - build_gateway_install_plan() maps lan → --host 0.0.0.0
  - WindowsTaskService.install() falls back to Startup folder on TimeoutExpired
  - LaunchdService generates correct plist content
  - resolve_gateway_service() returns the correct class for the current platform
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability guard — skip if daemon module not installed
# ---------------------------------------------------------------------------

try:
    from cli.daemon import (
        InstallOpts,
        LaunchdService,
        WindowsTaskService,
        build_gateway_install_plan,
        resolve_gateway_service,
    )

    DAEMON_AVAILABLE = True
except ImportError:
    DAEMON_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not DAEMON_AVAILABLE,
    reason="cli.daemon not available",
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fake_config(bind: str = "loopback", port: int = 8000, token: str | None = None) -> object:
    """Return a minimal object that looks like SynapseConfig for daemon tests."""
    fake = MagicMock()
    fake.gateway = {"bind": bind, "port": port}
    if token:
        fake.gateway["token"] = token
    fake.data_root = Path("/tmp/synapse_test")
    return fake


# ===========================================================================
# build_gateway_install_plan — host mapping
# ===========================================================================


def test_build_gateway_plan_loopback_maps_to_127():
    """build_gateway_install_plan(): bind=loopback must produce --host 127.0.0.1."""
    config = _make_fake_config(bind="loopback")
    opts = build_gateway_install_plan(config)

    assert "--host" in opts.args
    host_idx = opts.args.index("--host")
    assert opts.args[host_idx + 1] == "127.0.0.1", (
        f"Expected --host 127.0.0.1 for loopback, got {opts.args[host_idx + 1]!r}"
    )


def test_build_gateway_plan_lan_maps_to_0000():
    """build_gateway_install_plan(): bind=lan must produce --host 0.0.0.0."""
    config = _make_fake_config(bind="lan")
    opts = build_gateway_install_plan(config)

    assert "--host" in opts.args
    host_idx = opts.args.index("--host")
    assert opts.args[host_idx + 1] == "0.0.0.0", (
        f"Expected --host 0.0.0.0 for lan, got {opts.args[host_idx + 1]!r}"
    )


def test_build_gateway_plan_auto_maps_to_0000():
    """build_gateway_install_plan(): bind=auto must produce --host 0.0.0.0."""
    config = _make_fake_config(bind="auto")
    opts = build_gateway_install_plan(config)

    host_idx = opts.args.index("--host")
    assert opts.args[host_idx + 1] == "0.0.0.0"


def test_build_gateway_plan_port_in_args():
    """build_gateway_install_plan(): --port flag must reflect config.gateway.port."""
    config = _make_fake_config(port=9000)
    opts = build_gateway_install_plan(config)

    assert "--port" in opts.args
    port_idx = opts.args.index("--port")
    assert opts.args[port_idx + 1] == "9000", (
        f"Expected --port 9000, got {opts.args[port_idx + 1]!r}"
    )


def test_build_gateway_plan_sets_token_env():
    """build_gateway_install_plan(): token must appear in opts.env."""
    config = _make_fake_config(token="my-secret-token")
    opts = build_gateway_install_plan(config)

    assert opts.env.get("SYNAPSE_GATEWAY_TOKEN") == "my-secret-token"


def test_build_gateway_plan_returns_install_opts():
    """build_gateway_install_plan() must return an InstallOpts instance."""
    config = _make_fake_config()
    opts = build_gateway_install_plan(config)

    assert isinstance(opts, InstallOpts)
    assert opts.exec_path  # non-empty string
    assert isinstance(opts.args, list)
    assert isinstance(opts.env, dict)


# ===========================================================================
# WindowsTaskService — schtasks fallback to Startup folder
# ===========================================================================


def test_windows_task_service_falls_back_on_timeout(tmp_path, monkeypatch):
    """WindowsTaskService.install(): TimeoutExpired from schtasks → Startup folder bat file."""
    svc = WindowsTaskService()

    # Redirect APPDATA so the bat file lands in tmp_path instead of real Startup folder
    monkeypatch.setenv(
        "APPDATA",
        str(tmp_path),
    )

    opts = InstallOpts(
        exec_path=sys.executable,
        args=["-m", "uvicorn", "sci_fi_dashboard.api_gateway:app", "--host", "127.0.0.1"],
        env={},
        log_dir=tmp_path / "logs",
    )

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="schtasks", timeout=10)):
        svc.install(opts)

    # After timeout, the bat file should exist in the Startup folder
    bat_path = svc._startup_bat_path
    assert bat_path.exists(), f"Startup bat file should exist at {bat_path} after TimeoutExpired"


def test_windows_task_service_schtasks_success(tmp_path, monkeypatch):
    """WindowsTaskService.install(): successful schtasks should NOT write bat file."""
    svc = WindowsTaskService()
    monkeypatch.setenv("APPDATA", str(tmp_path))

    opts = InstallOpts(
        exec_path=sys.executable,
        args=["-m", "uvicorn", "test:app"],
        env={},
        log_dir=tmp_path / "logs",
    )

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        svc.install(opts)

    bat_path = svc._startup_bat_path
    assert not bat_path.exists(), "Bat file should NOT be created when schtasks succeeds"


# ===========================================================================
# LaunchdService — plist content correctness
# ===========================================================================


def test_launchd_plist_contains_label():
    """LaunchdService._build_plist(): plist must contain the correct label string."""
    svc = LaunchdService()
    opts = InstallOpts(
        exec_path="/usr/bin/python3",
        args=["-m", "uvicorn", "sci_fi_dashboard.api_gateway:app", "--host", "127.0.0.1"],
        env={"SYNAPSE_HOME": "/home/user/.synapse"},
        log_dir=Path("/home/user/.synapse/logs"),
    )
    plist = svc._build_plist(opts)

    assert "ai.synapse.gateway" in plist, "Plist must contain the service label"
    assert "<string>ai.synapse.gateway</string>" in plist


def test_launchd_plist_contains_program_args():
    """LaunchdService._build_plist(): plist must list each arg as a separate <string> element."""
    svc = LaunchdService()
    opts = InstallOpts(
        exec_path="/usr/bin/python3",
        args=["-m", "uvicorn", "--host", "127.0.0.1"],
        env={},
        log_dir=Path("/tmp/logs"),
    )
    plist = svc._build_plist(opts)

    assert "<string>/usr/bin/python3</string>" in plist
    assert "<string>-m</string>" in plist
    assert "<string>uvicorn</string>" in plist
    assert "<string>127.0.0.1</string>" in plist


def test_launchd_plist_contains_env_vars():
    """LaunchdService._build_plist(): plist must include environment variable entries."""
    svc = LaunchdService()
    opts = InstallOpts(
        exec_path="/usr/bin/python3",
        args=[],
        env={"SYNAPSE_HOME": "/data", "SYNAPSE_GATEWAY_TOKEN": "mytoken"},
        log_dir=Path("/tmp/logs"),
    )
    plist = svc._build_plist(opts)

    assert "<key>SYNAPSE_HOME</key>" in plist
    assert "<string>/data</string>" in plist
    assert "<key>SYNAPSE_GATEWAY_TOKEN</key>" in plist
    assert "<string>mytoken</string>" in plist


def test_launchd_plist_has_run_at_load():
    """LaunchdService._build_plist(): plist must have RunAtLoad = true."""
    svc = LaunchdService()
    opts = InstallOpts(exec_path="/usr/bin/python3", args=[], env={}, log_dir=Path("/tmp/logs"))
    plist = svc._build_plist(opts)

    assert "<key>RunAtLoad</key>" in plist
    assert "<true/>" in plist


def test_launchd_plist_contains_log_paths():
    """LaunchdService._build_plist(): plist must reference stdout/stderr log paths."""
    svc = LaunchdService()
    log_dir = Path("/home/user/.synapse/logs")
    opts = InstallOpts(exec_path="/usr/bin/python3", args=[], env={}, log_dir=log_dir)
    plist = svc._build_plist(opts)

    assert "gateway.stdout.log" in plist
    assert "gateway.stderr.log" in plist
    assert str(log_dir) in plist


# ===========================================================================
# resolve_gateway_service — platform detection
# ===========================================================================


def test_resolve_gateway_service_darwin():
    """resolve_gateway_service() must return LaunchdService on darwin."""
    import cli.daemon as daemon_mod

    with patch.object(daemon_mod.sys, "platform", "darwin"):
        svc = daemon_mod.resolve_gateway_service()
    assert type(svc).__name__ == "LaunchdService", (
        f"Expected LaunchdService on darwin, got {type(svc).__name__}"
    )


def test_resolve_gateway_service_linux():
    """resolve_gateway_service() must return SystemdUserService on linux."""
    import cli.daemon as daemon_mod

    with patch.object(daemon_mod.sys, "platform", "linux"):
        svc = daemon_mod.resolve_gateway_service()
    assert type(svc).__name__ == "SystemdUserService", (
        f"Expected SystemdUserService on linux, got {type(svc).__name__}"
    )


def test_resolve_gateway_service_win32():
    """resolve_gateway_service() must return WindowsTaskService on win32."""
    import cli.daemon as daemon_mod

    with patch.object(daemon_mod.sys, "platform", "win32"):
        svc = daemon_mod.resolve_gateway_service()
    assert type(svc).__name__ == "WindowsTaskService", (
        f"Expected WindowsTaskService on win32, got {type(svc).__name__}"
    )


def test_resolve_gateway_service_unsupported_raises():
    """resolve_gateway_service() must raise NotImplementedError on unknown platforms."""
    with patch("sys.platform", "freebsd14"), pytest.raises(NotImplementedError):
        resolve_gateway_service()
