---
phase: 15
slug: auth-persistence-baileys-7x
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-22
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Node: `node:test` (built-in, Node 18+); Python: pytest 7.4.0 + pytest-asyncio 0.23+ (existing) |
| **Config file** | `baileys-bridge/package.json` → `scripts.test`; `workspace/pytest.ini` (existing) |
| **Quick run command** | `cd baileys-bridge && npm test && cd ../workspace && pytest tests/test_bridge_auth.py -x` |
| **Full suite command** | `cd baileys-bridge && npm test && cd ../workspace && pytest tests/ -v` |
| **Estimated runtime** | ~45 seconds (Node unit 2-5s + Python unit+integration 15-30s) plus manual smoke (5-10 min) |

---

## Sampling Rate

- **After every task commit:** Quick run command (~5s)
- **After every plan wave:** Full suite command (~45s)
- **Before `/gsd-verify-work`:** Full suite green + manual `15-MANUAL-VALIDATION.md` sign-off (BAIL-02 + BAIL-03 + BAIL-04) PASS
- **Max feedback latency:** 45 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 15-00-01 | 00 | 0 | all | T-15-W0-01 | Test scaffolding only | scaffold | `cd baileys-bridge && node -e "require('./lib/creds_queue.js')"` | ⚠️ Wave 0 creates | ⬜ |
| 15-00-02 | 00 | 0 | AUTH-V31-01..03 + BAIL-03 + BAIL-04 | T-15-W0-01 | RED stubs — tests fail by design (18 total) | unit stubs (RED) | `cd baileys-bridge && npm test` (exit non-zero; ≥18 failures) | ⚠️ Wave 0 creates | ⬜ |
| 15-00-02b | 00 | 0 | BAIL-01 | T-15-W0-01 | RED stub for version pin | unit stub (RED) | `cd workspace && pytest tests/test_bridge_auth.py::test_baileys_version_pin -v` (fails) | ⚠️ Wave 0 creates | ⬜ |
| 15-00-03 | 00 | 0 | BAIL-02/03/04 | — | Manual validation scaffold | doc | `test -f .planning/phases/15-auth-persistence-baileys-7x/15-MANUAL-VALIDATION.md` | ⚠️ Wave 0 creates | ⬜ |
| 15-01-01 | 01 | 1 | AUTH-V31-01 | T-15-01 | Per-authDir serial queue | unit | `cd baileys-bridge && node --test test/creds_queue.test.js -t "serialize writes"` | ✅ W0 | ⬜ |
| 15-01-02 | 01 | 1 | AUTH-V31-03 | T-15-02a | JSON.parse gate + chmod 600 (write-side) | unit | `cd baileys-bridge && node --test test/creds_queue.test.js -t "corrupt creds.json preserves"` | ✅ W0 | ⬜ |
| 15-01-03 | 01 | 1 | AUTH-V31-01 | T-15-06 | Error isolation in chain | unit | `cd baileys-bridge && node --test test/creds_queue.test.js -t "save error does not cancel"` | ✅ W0 | ⬜ |
| 15-02-01 | 02 | 1 | AUTH-V31-02 | T-15-02b | Parse-before-restore guard (boot-side) | unit | `cd baileys-bridge && node --test test/restore.test.js -t "restore from valid backup"` | ✅ W0 | ⬜ |
| 15-02-02 | 02 | 1 | AUTH-V31-02 | T-15-02b | No-op when creds valid (boot-side) | unit | `cd baileys-bridge && node --test test/restore.test.js -t "no restore when creds valid"` | ✅ W0 | ⬜ |
| 15-02-03 | 02 | 1 | AUTH-V31-03 | T-15-07 | readCredsJsonRaw size guard | unit | `cd baileys-bridge && node --test test/restore.test.js -t "readCredsJsonRaw size guard"` | ✅ W0 | ⬜ |
| 15-03-01 | 03 | 2 | AUTH-V31-01..03 | T-15-01/02c/03 | Queue+restore wired in startSocket (wiring-side) | integration | `cd workspace && pytest tests/test_bridge_auth.py::test_corruption_recovery_no_qr -v` | ✅ W0 | ⬜ |
| 15-03-02 | 03 | 2 | AUTH-V31-01..03 | T-15-02c | Legacy double-write removed + Wave 1 Node tests still GREEN | grep+unit | `! grep -n "atomicSaveCredsWrapper\|AUTH_BAK_DIR" baileys-bridge/index.js && cd baileys-bridge && node --test test/ 2>&1 \| tail -3` | ✅ W0 | ⬜ |
| 15-04-01 | 04 | 3 | BAIL-01 | T-15-04 | Exact version pin (no caret) | unit | `cd workspace && pytest tests/test_bridge_auth.py::test_baileys_version_pin -v` | ✅ W0 | ⬜ |
| 15-04-02 | 04 | 3 | BAIL-01 | T-15-04 | Node 20+ engines gate | unit | `cd workspace && pytest tests/test_bridge_auth.py::test_node_engine_requirement -v` | ✅ W0 | ⬜ |
| 15-04-03 | 04 | 3 | BAIL-01 | T-15-04 | npm audit + lockfile committed | grep | `test -f baileys-bridge/package-lock.json && grep -c "7.0.0-rc.9" baileys-bridge/package-lock.json` | ✅ W0 | ⬜ |
| 15-04-04 | 04 | 3 | BAIL-02 | T-15-14 | QR pairing on 7.x (operator walkthrough — formal sign-off deferred to Plan 06 Task 3) | manual | See `15-MANUAL-VALIDATION.md` § BAIL-02 (walkthrough only; Plan 04 Task 2 does NOT edit MANUAL-VALIDATION.md) | ✅ W0 | ⬜ |
| 15-05-01 | 05 | 4 | BAIL-04 | T-15-15 | user_id_alt surfaced on LID sender | unit | `cd baileys-bridge && node --test test/extract_payload.test.js -t "LID participant populates"` | ✅ W0 | ⬜ |
| 15-05-02 | 05 | 4 | BAIL-04 | T-15-15 | user_id_alt null on PN sender (no regression) | unit | `cd baileys-bridge && node --test test/extract_payload.test.js -t "PN sender leaves user_id_alt null"` | ✅ W0 | ⬜ |
| 15-05-03 | 05 | 4 | BAIL-04 | T-15-16 | user_id_alt registered in Phase 13 PII allowlist | unit | `cd workspace && python -c "from sci_fi_dashboard.observability.formatter import _SENSITIVE_FIELDS; assert 'user_id_alt' in _SENSITIVE_FIELDS"` | ✅ W0 | ⬜ |
| 15-05-04 | 05 | 4 | BAIL-04 | T-15-17 | GET /groups/:jid includes ownerPn key | integration | `cd workspace && WAVE_15_LIVE_BRIDGE_7X=1 WAVE_15_TEST_GROUP_JID=<jid> pytest tests/test_bridge_auth.py::test_group_metadata_shape -v` | ✅ W0 | ⬜ |
| 15-06-01 | 06 | 5 | BAIL-03 | T-15-19 | Media payload shapes stable (image/audio/voice/video/document) | unit | `cd baileys-bridge && node --test test/send_shapes.test.js` | ✅ W0 | ⬜ |
| 15-06-02 | 06 | 5 | BAIL-03 | T-15-19 | buildSendPayload wired into POST /send + /send-voice | grep | `grep -c "buildSendPayload" baileys-bridge/index.js` (≥3) | ✅ (after Task 2) | ⬜ |
| 15-06-03 | 06 | 5 | BAIL-02/03/04 | T-15-20 | Operator manual sign-off PASS matrix (BAIL-02/03/04) — Plan 06 Task 3 writes Sign-Off rows | manual | See `15-MANUAL-VALIDATION.md` § Sign-Off (3 PASS rows) | ✅ W0 | ⬜ |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · ✅ manual-passed*

### Threat ID Nomenclature (per M-2 revision)

`T-15-02` is split across three plans to disambiguate which trust boundary each mitigation addresses:

- **T-15-02a** (Plan 01, `baileys-bridge/lib/creds_queue.js::safeSaveCreds`) — write-side JSON.parse gate that prevents corrupt creds.json from clobbering a valid creds.json.bak during `copyFileSync`.
- **T-15-02b** (Plan 02, `baileys-bridge/lib/restore.js::maybeRestoreCredsFromBackup`) — boot-side two-gate parse (current creds + backup) that silently falls through on corruption.
- **T-15-02c** (Plan 03, `baileys-bridge/index.js::startSocket`) — wiring-side ordering constraint that calls `maybeRestoreCredsFromBackup(AUTH_DIR)` BEFORE `useMultiFileAuthState(AUTH_DIR)`.

All three must hold for AUTH-V31-02 end-to-end. Phase 13 PII allowlist addition (T-15-16, Plan 05) is a distinct concern.

---

## Wave 0 Requirements (from Plan 00)

- [x] `baileys-bridge/test/` directory scaffolded with `helpers/` + `fixtures/`
- [x] `baileys-bridge/test/helpers/tmp_auth_dir.js` + `corrupt_fixtures.js`
- [x] `baileys-bridge/test/fixtures/test_voice.ogg` (synthetic OGG, ≤5KB, valid OggS header)
- [x] `baileys-bridge/package.json` — `scripts.test: "node --test test/*.test.js"` added (NO dep bump in Wave 0)
- [x] `baileys-bridge/lib/creds_queue.js` + `lib/restore.js` stubs (throw NOT_IMPLEMENTED_WAVE_1)
- [x] `baileys-bridge/test/creds_queue.test.js` + `restore.test.js` + `send_shapes.test.js` + `extract_payload.test.js` (RED stubs — 15 Node tests fail + 1 file-level RED: 5+5+4+4)
- [x] `workspace/tests/test_bridge_auth.py` (RED stubs for BAIL-01 pins; skipif guards for live-bridge tests)
- [x] `.planning/phases/15-auth-persistence-baileys-7x/15-MANUAL-VALIDATION.md` (scaffold with BAIL-02 + BAIL-03 matrix + BAIL-04 + Sign-Off table)

*ESM migration scaffolding: deferred to Plan 04 (Wave 3) — empirical decision there per 15-RESEARCH.md Pitfall 4.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| QR pairing + multi-device login on Baileys 7.x | BAIL-02 | Requires a real phone with WhatsApp installed — cannot mock the 6-panel pairing handshake | `15-MANUAL-VALIDATION.md` § BAIL-02 (reset authDir, start bridge, scan QR, assert `/health` shows `connected`). Plan 04 Task 2 is a walkthrough checkpoint (no file edit); Plan 06 Task 3 records the formal PASS row. |
| Send image/voice/PDF/video on 7.x | BAIL-03 | Requires real WhatsApp destination to confirm delivered receipt (double grey tick) | `15-MANUAL-VALIDATION.md` § BAIL-03 (5-row curl matrix with mediaUrl/audioUrl). Plan 06 Task 3 sign-off. |
| Group metadata + round-trip reply on 7.x | BAIL-04 | Requires a group with ≥ 3 members (bot + 2 others) and a second device | `15-MANUAL-VALIDATION.md` § BAIL-04 (`GET /groups/:jid`; inbound from second device; reply via POST /send). Plan 06 Task 3 sign-off. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or explicit manual-validation gate (BAIL-02/03/04 sign-off rows in 15-MANUAL-VALIDATION.md, written by Plan 06 Task 3)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (manual checkpoints bracketed by automated tasks on either side)
- [x] Wave 0 (Plan 00) covers all MISSING test-file references before Wave 1 can start — including `extract_payload.test.js` (4 RED stubs for BAIL-04 per B-1 fix)
- [x] No watch-mode flags (`--watch`) anywhere — `node:test` runs once, pytest runs once
- [x] Feedback latency < 45s
- [x] `nyquist_compliant: true` set in frontmatter (flipped by Plan 00 Task 3)

**Approval:** Wave 0 complete — 2026-04-22
