---
phase: 15
plan: 3
status: complete
wave: 2
---

## Plan 03 — Wire index.js + Integration Test

**All Wave 1 tests still GREEN:** 10 pass / 8 fail (8 = 4 extract_payload + 4 send_shapes RED stubs, as expected)

**Python integration test:** `test_corruption_recovery_no_qr` PASSED (30.78s)

### Changes

**baileys-bridge/index.js** (681 lines, +8 from 673)
- Removed: `write-file-atomic` require, `AUTH_BAK_DIR`, `atomicSaveCreds()`, `atomicSaveCredsWrapper`
- Added: `enqueueSaveCreds` + `maybeRestoreCredsFromBackup` imports from `./lib/`
- Added: `SYNAPSE_AUTH_DIR` env override (backward-compatible, default `./auth_state`)
- Added: `migrateLegacyAuthStateBakDir()` — one-shot boot rename of `auth_state.bak/` → `auth_state.bak.legacy/`
- Wired: `maybeRestoreCredsFromBackup(AUTH_DIR)` before `useMultiFileAuthState` in `startSocket()`
- Wired: `sock.ev.on('creds.update', () => enqueueSaveCreds(AUTH_DIR, saveCreds))`
- Updated: `/logout` + `/relink` clean `auth_state.bak.legacy` (not `AUTH_BAK_DIR`)
- Added: SIGTERM handler — `sock.end()` before queue flush (closes creds.update race window)

**workspace/tests/test_bridge_auth.py** (185 lines)
- `test_corruption_recovery_no_qr`: full implementation — spawns bridge with synthetic corrupt creds, asserts no QR + restoration log in output + no JSON parse errors
- `test_bridge_legacy_bak_dir_renamed`: xfail (cwd-relative legacy path requires Phase 16 env override)

### AUTH-V31 Status
- AUTH-V31-01: GREEN (creds_queue.js unit tests, 5/5)
- AUTH-V31-02: GREEN (restore.js unit tests 5/5 + integration test 1/1)
- AUTH-V31-03: GREEN (creds_queue.js backup-guard unit tests, 2/2)

### SIGTERM Note
INCLUDED. Handler nulls `sock` before snapshotting queue to close the race window where `creds.update` could fire after queue snapshot but before `process.exit`.

### test_bridge_legacy_bak_dir_renamed Note
XFAIL. `migrateLegacyAuthStateBakDir()` resolves the legacy path relative to cwd — a `SYNAPSE_LEGACY_BAK_DIR` env override is needed to test this in isolation. Deferred to Phase 16.
