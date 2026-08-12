---
phase: 15
plan: 4
status: complete
wave: 3
---

## Plan 04 — Baileys 7.x Upgrade + BAIL-02 Manual Sign-Off

### ESM Decision: Option B — CommonJS retained
`require('@whiskeysockets/baileys')` resolves on Node 22 with `typeof b.default === 'function'`.
No ESM conversion applied. Bridge stays `'use strict'` CommonJS.

### npm audit findings
3 criticals in `libsignal/node_modules/protobufjs@6.8.8` (upstream vendored copy inside `@whiskeysockets/libsignal-node`).
Pre-existing upstream issue — not addressable by this project. Documented in DEPENDENCIES.md. No exploitable surface in bridge usage.

### Changes
- `baileys-bridge/package.json`: Baileys pinned to exact `7.0.0-rc.9`, `write-file-atomic` removed, `engines.node` = `>=20.0.0`
- `baileys-bridge/package-lock.json`: regenerated, 2 entries for `7.0.0-rc.9` with integrity hashes
- `baileys-bridge/index.js`: Node 20+ runtime guard at top (exits 1 with clear message on Node < 20)
- `synapse_start.sh` + `synapse_start.bat`: Node version check before bridge start
- `HOW_TO_RUN.md`: Node.js 20+ documented in Troubleshooting section
- `DEPENDENCIES.md`: "Baileys 7.x Upgrade (Phase 15)" section added

### Test Results
- Node unit tests: 10 pass, 8 fail (8 RED stubs — unchanged)
- `test_baileys_version_pin`: PASSED (flipped from RED)
- `test_node_engine_requirement`: PASSED (flipped from RED)
- `test_corruption_recovery_no_qr`: PASSED (still GREEN after bump)

### BAIL-02 Manual Pairing Sign-Off
**Status: PASSED** — operator confirmed on 2026-04-23

- QR displayed within ~15s of `node index.js`
- QR scanned on WhatsApp → Linked Devices → Link a device
- `[BRIDGE] Connection closed (code=515)` — expected Meta Coexistence transient (RESEARCH.md Pitfall 6), auto-recovered
- `[BRIDGE] Connected to WhatsApp` logged
- `GET /health` returned `{"status":"ok","connectionState":"connected","restartCount":0}`
- Webhook POST errors expected — Python gateway not running during manual test
- `authTimestamp: "2026-04-23T14:06:44.004Z"` (valid ISO 8601)

**Wave 4 (Plans 05, 06) unblocked.**
