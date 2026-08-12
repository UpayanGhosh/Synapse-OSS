---
phase: 15
plan: 1
subsystem: baileys-bridge
tags: [auth, creds-queue, wave-1, AUTH-V31-01, AUTH-V31-03]
dependency_graph:
  requires: [15-00]
  provides: [creds_queue_implementation]
  affects: [baileys-bridge/lib/creds_queue.js]
tech_stack:
  added: []
  patterns: [per-authDir Promise-chain queue, JSON.parse-gated backup, tail-guard Map cleanup]
key_files:
  created: []
  modified:
    - baileys-bridge/lib/creds_queue.js
decisions:
  - "_readRaw() duplicated from restore.js (not imported) to avoid a forward dependency on the Plan 02 readCredsJsonRaw implementation — avoids breaking Plan 01 tests in isolation. Plan 02 can optionally refactor to import from restore.js."
  - "safeSaveCreds re-throws on save failure so the queue outer .catch() produces a distinct console.warn log. This matches OpenClaw behavior where two different log severities surface (error inside safeSaveCreds, warn on queue chain)."
  - "__peekQueueSize added to exports (not in original Wave 0 stub interface) per plan task spec — allows test_queue_cleans_map_entry to assert Map size === 0 after drain."
metrics:
  duration: "< 5 minutes"
  completed: "2026-04-22"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 15 Plan 01: creds_queue.js Implementation Summary

Full implementation of `baileys-bridge/lib/creds_queue.js`, replacing the Wave 0 NOT_IMPLEMENTED stub.
PORT: verbatim from `D:/Shorty/openclaw/extensions/whatsapp/src/session.ts:37-95` + `:197-221`, adapted to CommonJS with `console.warn/error` replacing pino logger.

## Result

```
# tests 5 / # pass 5 / # fail 0
```

AUTH-V31-01 and AUTH-V31-03 are now GREEN at unit level. Integration wiring into `index.js` remains in Plan 03.

## What Was Built

`baileys-bridge/lib/creds_queue.js` — 112 lines

Key constructs:

- `const credsSaveQueues = new Map()` — module-level per-authDir queue (AUTH-V31-01)
- `JSON.parse(raw)` gate in `safeSaveCreds` backup phase (AUTH-V31-03)
- `fsSync.copyFileSync(credsPath, backupPath)` runs BEFORE `saveCreds()` — backup reflects pre-save known-good state
- `fsSync.chmodSync(path, 0o600)` best-effort on both creds.json and .bak (T-15-03, silently no-ops on Windows)
- `.catch()` on queue chain swallows re-thrown save errors — subsequent saves still run (AUTH-V31-01 error isolation)
- `.finally()` tail-guard deletes Map entry only when no newer save is queued (T-15-06, prevents memory growth)

## Port Provenance

Ported verbatim from:
- `D:/Shorty/openclaw/extensions/whatsapp/src/session.ts` lines 37-95 (`enqueueSaveCreds` + `safeSaveCreds`)
- `D:/Shorty/openclaw/extensions/whatsapp/src/session.ts` lines 197-221 (`waitForCredsSaveQueueWithTimeout`)

Adaptations from TypeScript original:
1. CommonJS (`require`/`module.exports`) instead of ESM
2. `console.warn/error` instead of `getChildLogger({module: 'session'})` pino calls
3. `_readRaw()` bootstrap helper (Plan 02 will implement `readCredsJsonRaw` in `restore.js`; this avoids a forward dep)
4. `__peekQueueSize()` export added for test-only Map-size introspection

## Tests Verified

| Test | ID | Result |
|------|----|--------|
| 10 concurrent enqueueSaveCreds calls serialize writes | AUTH-V31-01 | PASS |
| queue cleans Map entry after flush | AUTH-V31-01 | PASS |
| save error does not cancel chain | AUTH-V31-01 | PASS |
| corrupt creds.json preserves existing .bak | AUTH-V31-03 | PASS |
| valid creds.json updates .bak | AUTH-V31-03 | PASS |

Full suite baseline: 18 tests / 5 pass / 13 fail (restore 5 + send_shapes 4 + extract_payload 4 remain RED — planned for Plans 02-04).

## Threat Mitigations Applied

| Threat ID | Category | Status |
|-----------|----------|--------|
| T-15-01 | Tampering — concurrent creds.update interleave | MITIGATED (Promise-chain queue) |
| T-15-02a | Tampering — corrupt creds.json clobbers valid .bak | MITIGATED (JSON.parse gate) |
| T-15-03 | Information Disclosure — file permissions | MITIGATED (chmod 600 best-effort) |
| T-15-06 | DoS — unbounded Map growth | MITIGATED (tail-guard .finally()) |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `baileys-bridge/lib/creds_queue.js` exists and contains `const credsSaveQueues = new Map()`
- Commit `d33f2e6` exists: `feat(p15-01): implement creds_queue.js — AUTH-V31-01 + AUTH-V31-03 GREEN`
- All 5 tests pass; full suite count matches expected baseline
