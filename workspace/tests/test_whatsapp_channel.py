"""
Tests for Phase 4 WhatsApp Baileys Bridge (WA-01 through WA-08).

RED phase state:
  WA-01/03/04/05/07: File-system checks — FAIL until Plan 04-02 ships baileys-bridge/.
  WA-02/06/08:       Import-guarded — SKIP (WA_AVAILABLE=False) until Plan 04-03 ships
                     WhatsAppChannel. Will FAIL until Plan 04-03 turns them GREEN.

Import guard:
  Until 04-03 ships sci_fi_dashboard/channels/whatsapp.py, WA_AVAILABLE=False and
  all tests are skipped. This mirrors the pattern from test_llm_router.py and
  test_channels.py — single guard, clean RED state, one-line removal when the
  module ships.
"""

import asyncio
import importlib.util
import json
import sys
import unittest.mock
from pathlib import Path

import pytest

# Ensure workspace/ is on the import path regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Conditional import: RED phase guard for whatsapp channel
#
# Until Plan 04-03 creates sci_fi_dashboard/channels/whatsapp.py,
# WA_AVAILABLE=False and all WhatsAppChannel-dependent tests are skipped.
# ---------------------------------------------------------------------------
WA_AVAILABLE = importlib.util.find_spec("sci_fi_dashboard.channels.whatsapp") is not None

pytestmark = pytest.mark.skipif(
    not WA_AVAILABLE,
    reason="WhatsAppChannel not implemented yet (Phase 04-03)",
)

if WA_AVAILABLE:
    from sci_fi_dashboard.channels.whatsapp import WhatsAppChannel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BRIDGE_DIR = Path(__file__).resolve().parent.parent.parent / "baileys-bridge"


def _make_mock_process(returncode_after_start=None):
    """
    Create an AsyncMock process that simulates a running Node.js bridge subprocess.

    Args:
        returncode_after_start: If not None, the process will 'exit' with this code
                                after a single asyncio.sleep(0) cycle (crash simulation).
                                If None, process runs indefinitely (returncode stays None).
    """
    mock_proc = unittest.mock.MagicMock()
    mock_proc.pid = 12345
    mock_proc.terminate = unittest.mock.MagicMock()

    if returncode_after_start is None:
        # Running forever — returncode stays None
        mock_proc.returncode = None

        async def wait_forever():
            # Simulate a long-running process by sleeping a large amount
            await asyncio.sleep(9999)
            return 0

        mock_proc.wait = wait_forever
    else:
        # Process exits immediately with given returncode
        mock_proc.returncode = returncode_after_start

        async def wait_exits():
            await asyncio.sleep(0)
            return returncode_after_start

        mock_proc.wait = wait_exits

    return mock_proc


# ---------------------------------------------------------------------------
# WA-01: Bridge files exist at baileys-bridge/index.js and package.json
# ---------------------------------------------------------------------------


def test_bridge_files_exist():
    """WA-01: baileys-bridge/index.js and package.json must exist before integration."""
    assert (_BRIDGE_DIR / "index.js").exists(), (
        "baileys-bridge/index.js missing — Plan 04-02 must create it"
    )
    assert (_BRIDGE_DIR / "package.json").exists(), (
        "baileys-bridge/package.json missing — Plan 04-02 must create it"
    )


# ---------------------------------------------------------------------------
# WA-02: WhatsAppChannel.start() tracks subprocess PID
# ---------------------------------------------------------------------------


async def test_start_tracks_pid(monkeypatch):
    """WA-02: After start(), channel._bridge_pid must equal the mock subprocess PID."""
    mock_proc = _make_mock_process(returncode_after_start=None)

    async def mock_create_subprocess(*args, **kwargs):
        return mock_proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_create_subprocess)

    channel = WhatsAppChannel(bridge_port=5010, python_webhook_url="http://localhost:8000")

    # start() runs the supervisor loop; cancel it after first iteration
    start_task = asyncio.create_task(channel.start())
    # Yield to allow start() to spawn the subprocess and record the PID
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert channel._bridge_pid == mock_proc.pid, (
        f"Expected _bridge_pid={mock_proc.pid}, got {channel._bridge_pid}"
    )

    start_task.cancel()
    try:
        await start_task
    except (asyncio.CancelledError, Exception):
        pass


# ---------------------------------------------------------------------------
# WA-03: All required HTTP endpoints defined in index.js source
# ---------------------------------------------------------------------------


def test_bridge_endpoints_defined():
    """WA-03: index.js must declare POST /send, POST /typing, POST /seen, GET /health, GET /qr."""
    index_js = _BRIDGE_DIR / "index.js"
    assert index_js.exists(), "baileys-bridge/index.js missing — cannot check endpoints"
    src = index_js.read_text()
    required_endpoints = [
        ("post", "/send"),
        ("post", "/typing"),
        ("post", "/seen"),
        ("get", "/health"),
        ("get", "/qr"),
    ]
    for verb, path in required_endpoints:
        found = (
            f"app.{verb}('{path}'" in src
            or f'app.{verb}("{path}"' in src
        )
        assert found, f"Bridge index.js missing endpoint: {verb.upper()} {path}"


# ---------------------------------------------------------------------------
# WA-04: write-file-atomic listed as a dependency in package.json
# ---------------------------------------------------------------------------


def test_atomic_write_dep_present():
    """WA-04: package.json must include write-file-atomic in dependencies."""
    pkg_path = _BRIDGE_DIR / "package.json"
    assert pkg_path.exists(), "baileys-bridge/package.json missing — cannot check dependencies"
    pkg = json.loads(pkg_path.read_text())
    assert "write-file-atomic" in pkg.get("dependencies", {}), (
        "write-file-atomic missing from baileys-bridge/package.json dependencies"
    )


# ---------------------------------------------------------------------------
# WA-05: cachedGroupMetadata enabled in index.js
# ---------------------------------------------------------------------------


def test_cached_group_metadata_enabled():
    """WA-05: index.js must use cachedGroupMetadata for group message performance."""
    index_js = _BRIDGE_DIR / "index.js"
    assert index_js.exists(), "baileys-bridge/index.js missing — cannot check cachedGroupMetadata"
    src = index_js.read_text()
    assert "cachedGroupMetadata" in src, (
        "cachedGroupMetadata not found in index.js — required for group message performance (WA-05)"
    )


# ---------------------------------------------------------------------------
# WA-06: Supervisor loop restarts bridge on crash
# ---------------------------------------------------------------------------


async def test_supervisor_restarts_on_crash(monkeypatch):
    """WA-06: supervisor loop must restart the bridge subprocess after an unexpected exit."""
    call_count = 0
    crash_proc = _make_mock_process(returncode_after_start=1)  # exits immediately

    # Second process runs until cancelled
    running_proc = _make_mock_process(returncode_after_start=None)

    async def mock_create_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return crash_proc
        return running_proc

    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_create_subprocess)

    channel = WhatsAppChannel(bridge_port=5010, python_webhook_url="http://localhost:8000")

    start_task = asyncio.create_task(channel.start())

    # Allow supervisor to detect the crash and attempt restart
    # First iteration: spawn, detect exit, trigger restart
    for _ in range(10):
        await asyncio.sleep(0)

    start_task.cancel()
    try:
        await start_task
    except (asyncio.CancelledError, Exception):
        pass

    assert call_count >= 2, (
        f"Expected subprocess to be spawned at least 2 times (crash + restart), "
        f"got {call_count} — supervisor loop not restarting on crash (WA-06)"
    )


# ---------------------------------------------------------------------------
# WA-07: GET /qr endpoint defined in bridge (also verified by WA-03, isolated here)
# ---------------------------------------------------------------------------


def test_qr_endpoint_routed():
    """WA-07: GET /qr endpoint must be defined for QR code pairing flow."""
    index_js = _BRIDGE_DIR / "index.js"
    assert index_js.exists(), "baileys-bridge/index.js missing — cannot check /qr endpoint"
    src = index_js.read_text()
    assert "app.get('/qr'" in src or 'app.get("/qr"' in src, (
        "GET /qr endpoint not found in index.js — required for WhatsApp QR pairing (WA-07)"
    )


# ---------------------------------------------------------------------------
# WA-08: Missing Node.js raises RuntimeError with clear message
# ---------------------------------------------------------------------------


async def test_nodejs_missing_raises_clear_error(monkeypatch):
    """WA-08: If Node.js is not on PATH, start() must raise RuntimeError mentioning 'Node.js'."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)  # simulate node not on PATH

    channel = WhatsAppChannel(bridge_port=5010, python_webhook_url="http://localhost:8000")

    with pytest.raises(RuntimeError, match="Node.js"):
        await channel.start()
