"""Phase 15 bridge auth tests.

Wave 0: test_baileys_version_pin and test_node_engine_requirement are RED
(package.json still has ^6.7.21 and >=18.0.0 — Plan 04 bumps these to 7.0.0-rc.9 / >=20.0.0).

Others are skipped until:
- test_corruption_recovery_no_qr: Plan 03 wires maybeRestoreCredsFromBackup into bridge
- test_qr_endpoint_returns_string: live 7.x bridge available (WAVE_15_LIVE_BRIDGE_7X env var)
- test_group_metadata_shape: live 7.x bridge available (WAVE_15_LIVE_BRIDGE_7X env var)
"""
import json
import os
from pathlib import Path

import pytest

BRIDGE_DIR = Path(__file__).resolve().parent.parent.parent / 'baileys-bridge'


def test_baileys_version_pin():
    """BAIL-01: Baileys must be pinned to exact 7.0.0-rc.9 (no caret)."""
    pkg = json.loads((BRIDGE_DIR / 'package.json').read_text())
    assert pkg['dependencies']['@whiskeysockets/baileys'] == '7.0.0-rc.9', \
        f"BAIL-01: expected '7.0.0-rc.9', got {pkg['dependencies']['@whiskeysockets/baileys']!r}"


def test_node_engine_requirement():
    """BAIL-01: engines.node must be >=20.0.0."""
    pkg = json.loads((BRIDGE_DIR / 'package.json').read_text())
    assert pkg.get('engines', {}).get('node') == '>=20.0.0', \
        f"BAIL-01: expected '>=20.0.0', got {pkg.get('engines', {}).get('node')!r}"


@pytest.mark.asyncio
async def test_corruption_recovery_no_qr(tmp_path):
    """AUTH-V31-02 end-to-end: corrupt creds + valid bak -> no QR.

    Wave 0 stub — skipped until Plan 03 wires maybeRestoreCredsFromBackup into bridge.
    """
    pytest.skip('Wave 0 stub — fills in after Plan 03 wires restore into bridge')


@pytest.mark.skipif('WAVE_15_LIVE_BRIDGE_7X' not in os.environ, reason='requires live 7.x bridge')
def test_qr_endpoint_returns_string():
    """BAIL-02: QR endpoint returns string on 7.x paired bridge."""
    pytest.skip('Wave 0 stub — requires live Baileys 7.x bridge')


@pytest.mark.skipif('WAVE_15_LIVE_BRIDGE_7X' not in os.environ, reason='requires live 7.x bridge')
def test_group_metadata_shape():
    """BAIL-04: GET /groups/:jid returns expected shape on 7.x."""
    pytest.skip('Wave 0 stub — requires live Baileys 7.x bridge')
