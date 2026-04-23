"""Phase 15 bridge auth tests.

Wave 0: test_baileys_version_pin and test_node_engine_requirement are RED
(package.json still has ^6.7.21 and >=18.0.0 — Plan 04 bumps these to 7.0.0-rc.9 / >=20.0.0).

Others are skipped until:
- test_qr_endpoint_returns_string: live 7.x bridge available (WAVE_15_LIVE_BRIDGE_7X env var)
- test_group_metadata_shape: live 7.x bridge available (WAVE_15_LIVE_BRIDGE_7X env var)
"""
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
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


# ---------------------------------------------------------------------------
# Synthetic plausibly-shaped creds — NEVER real noise keys.
# All values generated per-test via hashlib so no real creds are ever committed.
# ---------------------------------------------------------------------------
def _synthetic_creds(seed: int = 1) -> dict:
    import hashlib
    def h(s: str) -> str:
        return hashlib.sha256(f'{s}-{seed}'.encode()).hexdigest()
    return {
        'noiseKey': {'private': h('noise-priv'), 'public': h('noise-pub')},
        'pairingEphemeralKeyPair': {'private': h('pair-priv'), 'public': h('pair-pub')},
        'signedIdentityKey': {'private': h('sid-priv'), 'public': h('sid-pub')},
        'signedPreKey': {
            'keyPair': {'private': h('spk-priv'), 'public': h('spk-pub')},
            'signature': h('spk-sig'),
            'keyId': 1,
        },
        'registrationId': 12345,
        'advSecretKey': h('adv'),
        'nextPreKeyId': 1,
        'firstUnuploadedPreKeyId': 1,
        'accountSyncCounter': 0,
        'accountSettings': {'unarchiveChats': False},
        'deviceId': h('dev')[:22],
        'phoneId': h('phone')[:36],
        'identityId': h('id')[:16],
        'registered': False,
        'backupToken': h('bt')[:20],
        'registration': {},
        'pairingCode': None,
    }


@pytest.mark.asyncio
async def test_corruption_recovery_no_qr(tmp_path):
    """AUTH-V31-02 end-to-end: corrupt creds.json + valid bak + restart bridge -> no QR.

    Caveat: on Baileys 6.7.21 the 'connected' state may not be reached because
    synthetic creds are rejected by the WA server. The primary signal is the
    bridge's console.warn output including 'Restored corrupted creds.json from
    backup' — that proves maybeRestoreCredsFromBackup ran in the real boot path.
    """
    auth_dir = tmp_path / 'auth_state'
    auth_dir.mkdir()

    # 1. Write valid synthetic backup (the restore target)
    (auth_dir / 'creds.json.bak').write_text(json.dumps(_synthetic_creds(1)))
    # 2. Corrupt the current creds.json
    (auth_dir / 'creds.json').write_text('{truncated-JSON')

    env = {
        **os.environ,
        'SYNAPSE_AUTH_DIR': str(auth_dir),
        'BRIDGE_PORT': '5011',
        'PYTHON_WEBHOOK_URL': 'http://127.0.0.1:65535/never-reachable',
        'PYTHON_STATE_WEBHOOK_URL': 'http://127.0.0.1:65535/never-reachable',
    }

    proc = await asyncio.create_subprocess_exec(
        'node', 'index.js',
        cwd=str(BRIDGE_DIR),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []

    async def drain(stream, sink):
        while True:
            line = await stream.readline()
            if not line:
                return
            sink.append(line)

    stdout_task = asyncio.create_task(drain(proc.stdout, stdout_chunks))
    stderr_task = asyncio.create_task(drain(proc.stderr, stderr_chunks))

    try:
        # Poll /health for up to 30s; also check /qr returns 404 throughout
        deadline = time.monotonic() + 30.0
        qr_seen = False
        async with httpx.AsyncClient(timeout=2.0) as client:
            while time.monotonic() < deadline:
                try:
                    q = await client.get('http://127.0.0.1:5011/qr')
                    if q.status_code == 200:
                        qr_seen = True
                        break
                except httpx.RequestError:
                    pass
                await asyncio.sleep(1.0)

        # Yield briefly so drain tasks flush any remaining buffered lines.
        # Do NOT await the drain tasks — they block until EOF (process exit).
        # After 30s of polling, all startup output has been emitted.
        await asyncio.sleep(0.2)

        # Assert 1: QR was never emitted
        assert not qr_seen, (
            'AUTH-V31-02 FAIL: QR was emitted. '
            'Restoration did not prevent Baileys from seeing corrupt creds.'
        )
        # Assert 2: Restoration log line appeared in bridge output
        # console.warn() goes to stderr in Node.js; console.log() goes to stdout.
        all_stdout = b''.join(stdout_chunks).decode('utf-8', errors='replace')
        all_stderr = b''.join(stderr_chunks).decode('utf-8', errors='replace')
        all_output = all_stdout + all_stderr
        assert 'Restored corrupted creds.json from backup' in all_output, (
            f'AUTH-V31-02 FAIL: expected restoration log in stdout+stderr.\n'
            f'stdout:\n{all_stdout[:1000]}\nstderr:\n{all_stderr[:1000]}'
        )
        # Assert 3: No JSON-parse error from Baileys in stderr
        assert 'Unexpected end of JSON input' not in all_stderr
        assert 'Unexpected token' not in all_stderr
    finally:
        stdout_task.cancel()
        stderr_task.cancel()
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()


@pytest.mark.asyncio
async def test_bridge_legacy_bak_dir_renamed(tmp_path):
    """AUTH-V31 one-shot migration: auth_state.bak/ -> auth_state.bak.legacy/ on boot."""
    pytest.xfail(
        'migrateLegacyAuthStateBakDir resolves legacy path relative to cwd; '
        'testing requires SYNAPSE_LEGACY_BAK_DIR env override — defer to Phase 16'
    )


@pytest.mark.skipif('WAVE_15_LIVE_BRIDGE_7X' not in os.environ, reason='requires live 7.x bridge')
def test_qr_endpoint_returns_string():
    """BAIL-02: QR endpoint returns string on 7.x paired bridge."""
    pytest.skip('Wave 0 stub — requires live Baileys 7.x bridge')


@pytest.mark.skipif(
    'WAVE_15_LIVE_BRIDGE_7X' not in os.environ or 'WAVE_15_TEST_GROUP_JID' not in os.environ,
    reason='requires live 7.x paired bridge + group JID (set WAVE_15_LIVE_BRIDGE_7X=1 + WAVE_15_TEST_GROUP_JID=<jid>@g.us)',
)
@pytest.mark.asyncio
async def test_group_metadata_shape():
    """BAIL-04 (structural): GET /groups/:jid returns expected shape on 7.x.

    Pre-conditions (operator):
    1. Baileys bridge is running on port 5010 (default) — paired on 7.0.0-rc.9
    2. WAVE_15_LIVE_BRIDGE_7X=1 in env
    3. WAVE_15_TEST_GROUP_JID=<jid>@g.us — a group the paired account is a member of
    """
    group_jid = os.environ['WAVE_15_TEST_GROUP_JID']
    bridge_port = int(os.environ.get('BRIDGE_PORT', '5010'))
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f'http://127.0.0.1:{bridge_port}/groups/{group_jid}')
    assert r.status_code == 200, f'Bridge returned {r.status_code}: {r.text}'
    resp = r.json()

    assert 'id' in resp, 'missing id'
    assert 'subject' in resp, 'missing subject'
    assert 'participants' in resp, 'missing participants'
    assert isinstance(resp['participants'], list), 'participants not a list'
    assert 'owner' in resp, 'missing owner (null allowed)'
    assert 'ownerPn' in resp, 'missing ownerPn key (null allowed)'
