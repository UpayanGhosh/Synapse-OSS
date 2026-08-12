# Phase 15: Auth Persistence + Baileys 7.x — Research

**Researched:** 2026-04-22
**Domain:** Node.js WhatsApp bridge — Baileys auth file persistence + major-version upgrade (6.7.21 → 7.x)
**Confidence:** HIGH (OpenClaw reference code read directly, current Synapse bridge source read directly, npm registry queried) / MEDIUM (Baileys 7.x "stable" interpretation — no non-RC exists yet)

## Summary

Phase 15 bundles two bridge-layer changes that share the same regression surface: (1) port OpenClaw's per-authDir `enqueueSaveCreds` atomic queue + `maybeRestoreCredsFromBackup` single-file-backup logic into Synapse's `baileys-bridge/index.js`, and (2) upgrade `@whiskeysockets/baileys` from `^6.7.21` to the current 7.x tag. Both sit in the same ~24 KB CommonJS bridge file and both break the auth path if done wrong.

Three context-altering findings the planner must internalize before decomposing:

1. **There is no non-RC Baileys 7.x.** The npm `latest` dist-tag as of 2025-11-21 is `7.0.0-rc.9`. OpenClaw pins exactly `7.0.0-rc.9`. The 6.x line has been explicitly end-of-lifed — the `6.7.21` release notes read *"Hotfix to fix issue in pairing. Move to 7.0.0-rc.6 as soon as possible."* [VERIFIED: npm view @whiskeysockets/baileys dist-tags returned `{ latest: '7.0.0-rc.9' }`; npm view time shows 6.7.21 published 2025-11-06, 7.0.0-rc.9 published 2025-11-21]. BAIL-01 says *"latest stable 7.x"* — the planner must either (a) accept `7.0.0-rc.9` as de facto stable (OpenClaw does), or (b) ask the user to loosen the constraint. Anything in the 6.x line is a regression.

2. **The current "atomic" wrapper is broken.** `baileys-bridge/index.js:251-254` calls `saveCreds()` (which internally does an atomic write via Baileys' `useMultiFileAuthState`) AND then redundantly calls a custom `atomicSaveCreds(state.creds)` that writes the same file again via `write-file-atomic`. Worse, the "backup" is an `fs.cpSync(AUTH_DIR, AUTH_BAK_DIR, {recursive: true, force: true})` — a full recursive directory copy on every creds.update [VERIFIED from direct read of `baileys-bridge/index.js` lines 107-120]. There is no per-authDir queue, no corruption-detection-before-backup, no serialization against `creds.update` bursts. The current "auth_state.bak" contains 38 pre-key files + sessions + app-state-sync — gigabytes over a session's life, copied repeatedly.

3. **Phase 14 healthState enum already exists and matches Baileys 6.x codes only.** `workspace/sci_fi_dashboard/channels/supervisor.py:38` defines `NONRETRYABLE_CODES = {"401", "403", "440"}` (loggedOut, forbidden, connectionReplaced). Baileys 7.x does NOT change the `DisconnectReason` enum numerically (same HTTP-style status codes — 401, 403, 408, 411, 428, 440, 500, 503, 515) but introduces a new **LID-mapping error surface** for auth-state that lacks the new `lid-mapping`, `device-list`, `tctoken` keys [VERIFIED from Baileys migration guide text extraction]. The enum itself is stable; what changes is the auth-state schema.

**Primary recommendation:** Split into TWO waves internally. **Wave A** (auth-persistence-only, stays on 6.7.21): implement `enqueueSaveCreds` Map-keyed-by-authDir queue + single-file `creds.json.bak` rotation + `maybeRestoreCredsFromBackup` at bridge boot — ship as its own validation surface. **Wave B** (pin 7.0.0-rc.9, rename `.bak` file to match OpenClaw convention, validate pairing + media + groups). Bundling is risk-justified in the roadmap, but keeping the two migrations serial within the phase contains regression surface. The dependency is one-way: the atomic queue must land BEFORE the 7.x upgrade so corrupt-creds recovery is provable before the Baileys surface shifts underneath.

## User Constraints (from CONTEXT.md)

No CONTEXT.md exists for Phase 15 yet (standalone research run — discuss-phase was not executed). Upstream constraints come from:

- `.planning/ROADMAP.md` Phase 15 block (5 success criteria)
- `.planning/REQUIREMENTS.md` AUTH-V31-01..03 + BAIL-01..04 (7 REQ-IDs)
- Roadmap dependency: Phase 13 (structured logs) + Phase 14 (healthState enum, reconnect policy) must be exploited, not duplicated
- Research-focus checklist provided at spawn

### Locked Decisions
- **OpenClaw port target**: `extensions/whatsapp/src/session.ts:37-95` enqueueSaveCreds + `auth-store.ts:36-65` maybeRestoreCredsFromBackup (single-file `creds.json.bak`, not timestamped rotation).
- **Bundling**: both atomic-queue and Baileys 7.x upgrade ship in the same phase per roadmap (shared regression risk, both in bridge/auth surface).
- **Scope fence**: multi-account isolation deferred to Phase 18; per-authDir queue must be designed so Phase 18 can extend it with zero refactor (the `Map<authDir, Promise>` already generalizes).

### Claude's Discretion
- Whether "latest stable 7.x" maps to `7.0.0-rc.9` or blocks until a non-RC tag exists (recommendation below: accept rc.9).
- Backup rotation strategy: single `.bak` file (OpenClaw) vs numbered rotation (more recoverable but not in the reference code).
- Wave ordering inside the phase (recommended: atomic-queue first, Baileys upgrade second).
- Whether to keep the existing `./auth_state.bak` directory-copy layer as a belt-and-suspenders fallback during the transition (recommendation: delete it — the OpenClaw pattern supersedes).
- Node version bump strategy: Baileys 7.x requires Node `>=20.0.0`, bridge package.json currently says `>=18.0.0`. Planner picks coordination (CI bump, user docs, `synapse_start.sh` check).

### Deferred Ideas (OUT OF SCOPE)
- Multi-account authDir isolation (Phase 18 — `MULT-01..04`).
- `getMessage` store implementation for Baileys 7.x retry/poll-decryption (nice-to-have but not required by Phase 15 success criteria).
- Full history sync (`syncFullHistory: true`) — current `false` value is correct for the use case.
- Pairing-code login (currently QR-only — adding pairing-code is a separate UX decision).
- Protobuf `decodeAndHydrate()` migration work if the bridge doesn't directly call protobuf encode/decode (it doesn't — it uses `sendMessage` and `downloadMediaMessage` only).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUTH-V31-01 | Creds saved atomically via per-authDir queue — no concurrent writes can corrupt creds.json | OpenClaw `enqueueSaveCreds()` at session.ts:37-56 — `Map<string, Promise<void>>` keyed by authDir, chained `.then()` serializes saves; current Synapse has no queue (direct `sock.ev.on('creds.update', ...)` at index.js:265 races). |
| AUTH-V31-02 | Corrupt creds.json on boot falls back to most recent valid backup before forcing re-pair | OpenClaw `maybeRestoreCredsFromBackup()` at auth-store.ts:36-65 — read current creds.json, `JSON.parse()` test, if fails read `.bak`, validate JSON.parse, `fs.copyFileSync` to creds.json, chmod 600. Called before `useMultiFileAuthState()` in createWaSocket. |
| AUTH-V31-03 | Backup only written when current creds.json parses as valid JSON (never clobber good backup with corrupt data) | OpenClaw `safeSaveCreds()` at session.ts:58-95 — reads current creds.json, `JSON.parse()` validates before `fs.copyFileSync(credsPath, backupPath)`. Current Synapse `atomicSaveCreds` at index.js:107-120 copies whole directory with `fs.cpSync` without validation — can clobber good backup with torn writes. |
| BAIL-01 | package.json pinned to latest stable 7.x | npm registry: `latest` dist-tag = `7.0.0-rc.9` (published 2025-11-21); OpenClaw pins exact `7.0.0-rc.9`. No non-RC 7.x exists. |
| BAIL-02 | QR pairing + multi-device login end-to-end validated on 7.x | Baileys 7.x keeps `useMultiFileAuthState` API stable but requires auth-state schema to support new keys (`lid-mapping`, `device-list`, `tctoken`) — fresh pair always safe; re-using old creds may fail if schema missing. `printQRInTerminal` still supported. Migration guide: https://baileys.wiki/docs/migration/to-v7.0.0 |
| BAIL-03 | Media send + receive validated on 7.x (image, audio OGG Opus, PDF, voice) | Baileys 7.x `sendMessage` media-payload shape unchanged — `{ image: Buffer, caption }`, `{ audio: Buffer, ptt: true, mimetype: 'audio/ogg; codecs=opus' }`, `{ document: Buffer, mimetype, fileName, caption }`, `{ video: Buffer, caption, mimetype, gifPlayback? }` all identical to 6.x per AnyMediaMessageContent type in both 6.x and 7.x. OpenClaw's send-api.ts:41-65 uses this shape against 7.0.0-rc.9 successfully. |
| BAIL-04 | Group metadata + inbound routing on 7.x | Key 7.x change: `GroupMetadata.owner` (LID) vs `ownerPn` (phone), `Contact.id + phoneNumber + lid` fields replace `Contact.jid/lid`. `groupMetadata()` API call unchanged. `messages.upsert` emits `MessageKey.remoteJidAlt` (for DMs) and `MessageKey.participantAlt` (for groups) for PN↔LID mapping. Current bridge reads `msg.key.remoteJid` and `msg.key.participant` — these still exist but may be LIDs now; `remoteJidAlt`/`participantAlt` give the PN counterpart. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@whiskeysockets/baileys` | `7.0.0-rc.9` | WhatsApp Web protocol client | [VERIFIED: npm dist-tag `latest` = `7.0.0-rc.9`, published 2025-11-21]. This IS the current stable despite the "-rc" suffix — the maintainers have explicitly directed all users off 6.x [CITED: 6.7.21 release notes "Move to 7.0.0-rc.6 as soon as possible"]. OpenClaw (the reference codebase for all v3.1 work) pins this exact version. |
| `write-file-atomic` | `^5.0.1` (already installed) | Torn-write-safe file write | [VERIFIED in package-lock.json]. Used by Synapse today. Baileys' internal `useMultiFileAuthState` already uses atomic writes — this is belt-and-suspenders. OpenClaw uses `fsSync.copyFileSync` for backup (non-atomic; good enough because backup is already-validated JSON). |
| Node.js | `>=20.0.0` | Runtime | [VERIFIED: `npm view @whiskeysockets/baileys@7.0.0-rc.9 engines` returned `{ node: '>=20.0.0' }`]. Current bridge `package.json` says `>=18.0.0` — MUST bump. Dev host runs Node v22.18.0 [VERIFIED: `node --version`]. |
| `pino` | `^8.21.0` (current) → can stay | Bridge structured logger | Baileys 7.x lists `pino: ^9.6` as a transitive dep but the bridge can continue using `pino@8.x` at top level; transitive resolution picks the right one per package. OpenClaw migration doesn't require pino bump. |
| `express`, `node-cache`, `qrcode-terminal` | current pins | Unchanged | Not affected by Baileys upgrade. |

### Supporting (no new deps needed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `p-queue` | (transitive via Baileys 7.x) | Promise queue primitive | Baileys 7.x now bundles `p-queue` and `async-mutex`. The OpenClaw `enqueueSaveCreds` pattern uses a naked `Map<string, Promise>` — no need for `p-queue` at the bridge layer. Keep custom chain. |
| `async-mutex` | (transitive via Baileys 7.x) | Would also work for per-authDir lock | Alternative to the Promise-chain pattern. Heavier. Stick with the OpenClaw pattern — zero new top-level dep. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `7.0.0-rc.9` | Stay on `6.7.21` | Rejected — explicit EOL notice from maintainer, no security patches going forward. Blocks BAIL-01..04. |
| `7.0.0-rc.9` | Pin a Baileys fork or `baileys@6.17.16` orphan | `6.17.16` exists on npm (published 2025-11-21 same day as rc.9) but is NOT tagged `latest` and NOT in git tags [VERIFIED: `git ls-remote` tags missing `6.17.16`] — appears to be a superseded variant. Do NOT use. |
| `Map<authDir, Promise>` | `async-mutex.Semaphore(1)` per authDir | OpenClaw's pattern is 15 lines, no new dep, proven. Mutex requires import + Mutex-per-key map that amounts to same data structure. Keep Promise-chain. |
| Single `creds.json.bak` (OpenClaw) | Numbered backup rotation (`creds.json.bak.1`, `.2`, ...) | Rotation gives more recovery depth but (a) OpenClaw's pattern is the reference, (b) corrupt-creds scenarios either fix on first backup attempt or indicate a fundamental auth-state rot that rotation won't save, (c) adds complexity. Stay with `.bak`. |
| Full-directory `fs.cpSync` backup (current Synapse) | Single-file `creds.json.bak` (OpenClaw) | Current approach copies 100+ files (pre-keys, sessions, app-state-sync) on every creds.update — pathological I/O amplification. OpenClaw's single-file `.bak` is correct: `creds.json` is the only file that MUST survive corruption; pre-keys + sessions auto-regenerate from server on reconnect. Switch. |
| `markOnlineOnConnect: false` (current) | `true` | Keep `false` — CLAUDE.md gotcha says phone push notifications require `false` and current behavior is correct. Baileys 7.x docs agree. |

**Installation:**
```bash
# From baileys-bridge/
npm install @whiskeysockets/baileys@7.0.0-rc.9
# (optional — verify no extraneous top-level deps added by 7.x)
npm prune
```

**Version verification:**
```bash
# Before committing, confirm the pin is still current:
npm view @whiskeysockets/baileys@7.0.0-rc.9 version
# and check that 'latest' hasn't advanced:
npm view @whiskeysockets/baileys dist-tags
```

## Architecture Patterns

### Recommended Bridge File Changes (targeted, not structural)

```
baileys-bridge/
├── index.js                       # edit in place (no new files)
│   ├── +30 lines: enqueueSaveCreds Map + safeSaveCreds
│   ├── ~10 lines: replace atomicSaveCredsWrapper with enqueue call
│   ├── +40 lines: maybeRestoreCredsFromBackup called before useMultiFileAuthState
│   ├── ~5 lines: drop redundant atomicSaveCreds + auth_state.bak dir-copy
│   └── ~2 lines: package version bump (reference only — edit is in package.json)
├── package.json                   # baileys → 7.0.0-rc.9; engines.node → >=20.0.0
├── package-lock.json              # regenerated by npm install
├── auth_state/                    # unchanged
├── auth_state.bak/                # REMOVED (replaced by creds.json.bak single file inside auth_state/)
└── test/                          # NEW — see Validation Architecture below
    └── creds_queue.test.js         # Node-level unit test for enqueueSaveCreds
```

**Rationale for minimal restructure:** the bridge is a single ~670-line CommonJS file intentionally kept monolithic so the Python side only needs to understand one endpoint contract. Phase 15 preserves this. Test file lives under `baileys-bridge/test/` to avoid mixing into the python `workspace/tests/` suite.

### Pattern 1: Per-authDir Promise-Chain Queue (the enqueueSaveCreds port)

**What:** A module-level `Map<string, Promise<void>>` keyed by `authDir`. Each call to `enqueueSaveCreds` reads the previous promise, appends a new `.then(() => safeSaveCreds(...))`, and stores the new promise back. Promises chained via `.then()` execute sequentially by the JavaScript runtime's own semantics — zero lock needed.

**When to use:** Every `sock.ev.on('creds.update', ...)` callback. Also every explicit graceful-shutdown flush.

**Example (OpenClaw source, session.ts:37-56):**
```javascript
// Source: D:/Shorty/openclaw/extensions/whatsapp/src/session.ts:37-95 (verbatim)
const credsSaveQueues = new Map();
const CREDS_SAVE_FLUSH_TIMEOUT_MS = 15_000;

function enqueueSaveCreds(authDir, saveCreds, logger) {
  const prev = credsSaveQueues.get(authDir) ?? Promise.resolve();
  const next = prev
    .then(() => safeSaveCreds(authDir, saveCreds, logger))
    .catch((err) => {
      logger.warn({ error: String(err) }, "WhatsApp creds save queue error");
    })
    .finally(() => {
      if (credsSaveQueues.get(authDir) === next) credsSaveQueues.delete(authDir);
    });
  credsSaveQueues.set(authDir, next);
}

async function safeSaveCreds(authDir, saveCreds, logger) {
  try {
    // Best-effort backup so we can recover after abrupt restarts.
    // Important: don't clobber a good backup with a corrupted/truncated creds.json.
    const credsPath = resolveWebCredsPath(authDir);
    const backupPath = resolveWebCredsBackupPath(authDir);
    const raw = readCredsJsonRaw(credsPath);
    if (raw) {
      try {
        JSON.parse(raw);  // validate BEFORE overwriting backup
        fsSync.copyFileSync(credsPath, backupPath);
        try { fsSync.chmodSync(backupPath, 0o600); } catch {}
      } catch {
        // keep existing backup — don't clobber with corrupt data
      }
    }
  } catch {
    // ignore backup failures — never block the real save
  }
  try {
    await Promise.resolve(saveCreds());
    try { fsSync.chmodSync(resolveWebCredsPath(authDir), 0o600); } catch {}
  } catch (err) {
    logger.warn({ error: String(err) }, "failed saving WhatsApp creds");
  }
}
```

**Key invariants:**
1. **Backup-before-save**: validation + `copyFileSync` to `.bak` runs BEFORE the new `saveCreds()`, using the OLD good creds.json that's currently on disk.
2. **JSON.parse gate**: `JSON.parse(raw)` must throw-or-succeed — if it throws, the catch swallows and keeps the existing backup untouched. This is AUTH-V31-03.
3. **Error isolation**: the outer `.catch()` on the queue entry ensures one failed save doesn't cancel the chain — subsequent saves still execute.
4. **Self-cleaning map**: `.finally()` deletes the Map entry only if it's still the tail (`credsSaveQueues.get(authDir) === next`) — prevents leaking stale keys while still allowing new saves to chain correctly.

**Wiring point in Synapse bridge:**
```javascript
// baileys-bridge/index.js — replace lines 251-265
const sessionLogger = pino({ level: 'info' }).child({ module: 'web-session' });

sock.ev.on('creds.update', () => enqueueSaveCreds(AUTH_DIR, saveCreds, sessionLogger));

// DELETE the atomicSaveCreds function (lines 107-120) and atomicSaveCredsWrapper (lines 251-254).
// DELETE AUTH_BAK_DIR constant (line 37) — new model uses AUTH_DIR/creds.json.bak single file.
// DELETE auth_state.bak/ directory wipe in /logout (line 518) — replace with `creds.json.bak` unlink.
```

### Pattern 2: Single-File Backup Restoration (the maybeRestoreCredsFromBackup port)

**What:** At bridge startup (before `useMultiFileAuthState`), check creds.json. If missing or unparseable, look at `creds.json.bak`, validate that, and copy it into place.

**When to use:** Exactly once per bridge start, inside `startSocket()`, before the `useMultiFileAuthState(AUTH_DIR)` call.

**Example (OpenClaw source, auth-store.ts:36-65):**
```javascript
// Source: D:/Shorty/openclaw/extensions/whatsapp/src/auth-store.ts:36-65 (verbatim)
function maybeRestoreCredsFromBackup(authDir) {
  try {
    const credsPath = path.join(authDir, 'creds.json');
    const backupPath = path.join(authDir, 'creds.json.bak');
    const raw = readCredsJsonRaw(credsPath);
    if (raw) {
      JSON.parse(raw);           // validate parseable — throws on corrupt
      return;                     // creds are fine, nothing to restore
    }
    const backupRaw = readCredsJsonRaw(backupPath);
    if (!backupRaw) {
      return;                     // no backup available — fall through to re-pair
    }
    JSON.parse(backupRaw);         // validate backup before using it
    fsSync.copyFileSync(backupPath, credsPath);
    try { fsSync.chmodSync(credsPath, 0o600); } catch {}
    // NOTE: in Synapse, replace OpenClaw's `getChildLogger` with pino:
    // log.warn({ credsPath }, 'restored corrupted WhatsApp creds.json from backup');
  } catch {
    // ignore — worst case, user re-scans QR
  }
}

function readCredsJsonRaw(filePath) {
  try {
    if (!fsSync.existsSync(filePath)) return null;
    const stats = fsSync.statSync(filePath);
    if (!stats.isFile() || stats.size <= 1) return null;   // guards empty / truncated files
    return fsSync.readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
}
```

**Wiring point in Synapse bridge:**
```javascript
// baileys-bridge/index.js — inside startSocket(), BEFORE useMultiFileAuthState
async function startSocket() {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  maybeRestoreCredsFromBackup(AUTH_DIR);   // NEW — AUTH-V31-02
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  // ... rest unchanged
}
```

**Critical sequencing:** this MUST run before `useMultiFileAuthState(AUTH_DIR)` because that call reads creds.json into memory. If restoration is needed, it has to happen on disk first.

### Pattern 3: Graceful Flush on Shutdown

**What:** On bridge SIGTERM / process exit, await all pending enqueued saves with a timeout so we don't hang on stalled I/O.

**When to use:** In any shutdown handler. OpenClaw exports `waitForCredsSaveQueueWithTimeout(authDir, timeoutMs)` for this.

**Example (OpenClaw session.ts:197-221):**
```javascript
function waitForCredsSaveQueue(authDir) {
  if (authDir) return credsSaveQueues.get(authDir) ?? Promise.resolve();
  return Promise.all(credsSaveQueues.values()).then(() => {});
}

async function waitForCredsSaveQueueWithTimeout(authDir, timeoutMs = 15_000) {
  let flushTimeout;
  await Promise.race([
    waitForCredsSaveQueue(authDir),
    new Promise((resolve) => { flushTimeout = setTimeout(resolve, timeoutMs); }),
  ]).finally(() => { if (flushTimeout) clearTimeout(flushTimeout); });
}
```

**Wiring point:** Synapse bridge currently has no SIGTERM handler — the Python WhatsAppChannel sends SIGTERM → SIGKILL with 5s gap. Phase 15 adds:
```javascript
process.on('SIGTERM', async () => {
  await waitForCredsSaveQueueWithTimeout(AUTH_DIR, 5000);
  process.exit(0);
});
```
This is BONUS (not in success criteria) but closes a data-loss window. Planner may choose to defer.

### Pattern 4: Fresh Start Semantics

Baileys 7.x keeps `useMultiFileAuthState(authDir)` returning `{ state, saveCreds }`. The state includes `creds` (the sensitive bit — noise key, identity key, registrationId, signed-pre-key, etc.) and `keys` (pre-keys, sessions, sender-keys, app-state-sync-keys). Only `creds.json` is unrecoverable if corrupted — the others regenerate from the server.

**File-survival matrix:**
| File | Category | Corruption recovery |
|------|----------|---------------------|
| `creds.json` | Identity root | MUST be backed up — covered by `creds.json.bak` |
| `pre-key-N.json` | Pre-computed Signal keys (consumed per-session) | Regenerates on reconnect — safe to lose |
| `session-<jid>.json` | Per-peer Signal session state | Regenerates on next message from peer |
| `sender-key-<group>.json` | Group Signal key | Regenerates on next message in group |
| `app-state-sync-key-<id>.json` | WhatsApp app-state sync | Re-fetched from server |
| `app-state-sync-version-*.json` | Sync cursors | Rebuilt from scratch if lost |
| `meta.json` | Synapse-specific (authTimestamp) | Already separate file, needs no backup |

**Implication:** the queue only needs to serialize writes to `creds.json`. Pre-keys etc. are individual files; `useMultiFileAuthState` writes each independently and tornness of one file is harmless. The `.bak` strategy targets exactly one file.

### Anti-Patterns to Avoid
- **Directory-level `fs.cpSync(AUTH_DIR, AUTH_BAK_DIR, {recursive: true})` backup** (current Synapse behavior). Quadratic I/O amplification on every creds.update. Replace with single-file `creds.json.bak` per OpenClaw.
- **Double-writing creds.json**: current `atomicSaveCredsWrapper` runs Baileys' internal save AND a custom `writeFileAtomic(credsPath, JSON.stringify(creds))`. The second write is racy against future creds mutations in-flight. Delete it; trust `saveCreds()`.
- **Backing up unvalidated creds**: copying a freshly-corrupted `creds.json` over a good `.bak` is the worst outcome. Always `JSON.parse` before `fs.copyFileSync`.
- **Skipping restoration on "empty" creds.json**: Baileys writes `{}` to creds.json on fresh install. `stats.size <= 1` guard in `readCredsJsonRaw` correctly treats truly-empty files as missing, not corrupted. Don't remove this guard.
- **Global mutex on all auth ops**: a single global lock would serialize writes across all authDirs — fine for single-account (Phase 15) but kills Phase 18 multi-account parallelism. The per-authDir Map is the forward-compatible shape.
- **Assuming `saveCreds()` is synchronous**: it's async. `await` it. The OpenClaw pattern uses `await Promise.resolve(saveCreds())` defensively.
- **Emitting QR during corruption-recovery simulation**: success criterion 2 explicitly requires *no new QR emission* — restoration must happen before `makeWASocket` is called, otherwise Baileys sees empty creds and initiates pairing.
- **Opening the queue to arbitrary callers**: `enqueueSaveCreds` is only called from `sock.ev.on('creds.update', ...)`. Don't expose a REST endpoint that dispatches enqueue — that becomes a DoS vector.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-authDir mutex | `async-mutex.Semaphore(1)` + custom Map management | `Map<string, Promise>` + chained `.then()` (OpenClaw pattern) | 15 lines, zero deps, cancellation-safe, already proven in OpenClaw production. |
| Atomic file write | Custom `writeFileSync + rename` dance | Baileys' internal `useMultiFileAuthState` (already atomic) OR `write-file-atomic` (already installed) | Baileys' built-in write is atomic. The queue serializes the HIGH-LEVEL intent; the low-level write is handled by Baileys. |
| Backup rotation | Numbered backup files + mtime sorting | Single `creds.json.bak` per OpenClaw | Rotation solves a problem that doesn't exist — corruption is either write-torn (latest save failed, backup valid) or structural (replay of older creds won't help either way). One snapshot suffices. |
| JSON corruption detection | Schema validation / partial recovery / auto-repair | `JSON.parse()` inside try/catch | Baileys creds schema is deeply nested protobuf-shaped — attempting repair risks corrupting crypto material. Binary valid-or-invalid is the only correct test. |
| Windows path quoting | Hand-rolled `path.join` with separators | `node:path` module (already imported) | Already handled. Keep. |
| Process shutdown sequencing | Custom signal handlers + timeouts | `waitForCredsSaveQueueWithTimeout` (optional) + existing Python SIGTERM / SIGKILL from WhatsAppChannel | The Python supervisor already has a 5s SIGTERM→SIGKILL window. Node-side graceful flush is additive hygiene, not required. |
| WhatsApp binary protocol parsing | Custom noise-protocol / protobuf work | Baileys primitives (`sendMessage`, `downloadMediaMessage`, `groupMetadata`, `messages.upsert`) | Bridge already uses these. Don't regress by touching internals. |
| PTT voice-note encoding | ffmpeg re-encode pipelines | Pass OGG Opus buffer directly with `audio/ogg; codecs=opus` mimetype + `ptt: true` | OpenClaw send-api.ts:48 does exactly this. Current bridge /send-voice endpoint at index.js:445-449 does it too. Keep. |

**Key insight:** this phase is almost pure porting work. The reference code (OpenClaw) is ~130 lines across two TypeScript files. Converting them to CommonJS JavaScript and wiring into the existing bridge loses nothing semantic. Resist the urge to "improve" the algorithm — the point is parity with a proven pattern.

## Runtime State Inventory

**Trigger:** Phase 15 is part migration (Baileys upgrade) + part refactor (auth path). Full inventory required.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | `baileys-bridge/auth_state/creds.json` (6,650 bytes, current personal account); 38 pre-key-*.json + session files + 7 app-state-sync-key-*.json; meta.json (authTimestamp). `baileys-bridge/auth_state.bak/` is a legacy full-directory copy containing duplicate creds.json + all subordinate files. | Code edit: migrate to single `creds.json.bak` inside `auth_state/`. Data migration: delete `auth_state.bak/` directory once new flow is proven (keep during transition). Nothing in the creds binary format changes — Baileys 7.x can read 6.7.21-written creds.json. |
| **Live service config** | None. Bridge config is entirely in `baileys-bridge/index.js` env vars + `package.json`. No external service (n8n / Datadog / Tailscale) knows about the WhatsApp bridge by name. | None. |
| **OS-registered state** | None. Bridge is a Node subprocess spawned by the Python `WhatsAppChannel` via `asyncio.create_subprocess_exec` — no systemd unit, no Windows Task Scheduler entry, no launchd plist. The Python side manages lifecycle. | None. |
| **Secrets and env vars** | `WHATSAPP_BRIDGE_TOKEN` (currently unused in bridge? — verify; present in CLAUDE.md env list). `SYNAPSE_GATEWAY_TOKEN` (gateway only, not bridge). No credentials ship in package.json. `PYTHON_WEBHOOK_URL`, `PYTHON_STATE_WEBHOOK_URL`, `MEDIA_CACHE_DIR`, `MEDIA_CACHE_TTL_MINUTES`, `BRIDGE_PORT` — all config, not secrets. | Verify `WHATSAPP_BRIDGE_TOKEN` usage: `grep -rn "WHATSAPP_BRIDGE_TOKEN" D:/Shorty/Synapse-OSS` confirms it's not referenced in `baileys-bridge/` (only in Python side for TelegramChannel / stub auth). No rename needed. |
| **Build artifacts / installed packages** | `baileys-bridge/node_modules/@whiskeysockets/baileys/` (6.7.21 cached files). `baileys-bridge/package-lock.json` pins 6.7.21 transitive graph. | Reinstall required: `rm -rf baileys-bridge/node_modules baileys-bridge/package-lock.json && cd baileys-bridge && npm install` AFTER package.json is updated to 7.0.0-rc.9. Verify with `npm ls @whiskeysockets/baileys`. |

**The canonical question (after every file is updated, what runtime systems still have the old string cached?):** For Phase 15, the answer is:
1. An already-running bridge subprocess holds a copy of 6.7.21 in memory — killing and respawning it handles this (existing `WhatsAppChannel.stop() / start()` flow).
2. `auth_state.bak/` directory will linger on disk until first run with new code — must be explicitly removed (either by migration script at bridge boot, or by deleting during code edit).
3. No database, no OS service, no secret key embeds "6.7.21" or "auth_state.bak". Safe.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Bridge runtime | ✓ | v22.18.0 [VERIFIED: `node --version`] | — |
| npm | Install Baileys 7.x | ✓ | 10.9.3 [VERIFIED] | — |
| Python 3.11+ | Synapse gateway | ✓ | 3.13.6 (per Phase 13 research) | — |
| pytest + pytest-asyncio | Integration tests | ✓ | pytest>=7.4.0, pytest-asyncio>=0.23.0 | — |
| `httpx` (Python side) | Gateway → bridge HTTP | ✓ | Already in requirements.txt | — |
| A WhatsApp account + a second phone for pairing | Manual validation of BAIL-02/03/04 | Unknown to this session | — | None — required for manual smoke tests. Planner must flag as manual-only prerequisite. |
| A group chat with ≥ 3 members (user + 2 others) | Manual BAIL-04 group smoke | Unknown | — | None — required for group metadata + round-trip test. |
| `ffmpeg` (for generating test OGG Opus fixture) | Test fixture preparation | ✓ likely (Synapse has audio pipeline) | verify with `ffmpeg -version` | If absent, use a static pre-recorded `test_voice.ogg` fixture checked into `baileys-bridge/test/fixtures/` (synthetic, 1-second silence, ~2 KB). |
| `jq` CLI | Potential JSON log assertions | Unknown | — | Use Node `JSON.parse` in test asserts instead. |

**Missing dependencies with no fallback:**
- Live WhatsApp phone pairing is inherently manual. Planner must carve out a `15-MANUAL-VALIDATION.md` sibling doc.

**Missing dependencies with fallback:**
- If `ffmpeg` is unavailable, ship a committed synthetic OGG Opus fixture.
- If `jq` is unavailable, use in-test JSON parsers.

## Common Pitfalls

### Pitfall 1: Writing backup BEFORE validating current creds.json
**What goes wrong:** A partially-written creds.json (e.g., process killed mid-write) gets copied to creds.json.bak, clobbering the last known good state.
**Why it happens:** The naive implementation does `fs.copyFileSync(creds, bak); saveCreds();` — copying the soon-to-be-overwritten file without checking it.
**How to avoid:** OpenClaw's `safeSaveCreds` structure — `JSON.parse(raw)` BEFORE `fs.copyFileSync`. If parse fails, skip backup and keep the existing (older, valid) `.bak`. This is AUTH-V31-03 encoded in the algorithm.
**Warning signs:** After a hard crash, creds.json.bak is freshly-timestamped but unparseable; on restart, `maybeRestoreCredsFromBackup` can't help.

### Pitfall 2: Race between `creds.update` burst and `saveCreds()` mutation of `state.creds`
**What goes wrong:** Baileys can emit multiple `creds.update` events in rapid succession (during LID-mapping bootstrap in 7.x especially). Without serialization, two concurrent `saveCreds()` calls can interleave their writes mid-JSON-serialization, producing truncated output.
**Why it happens:** Node fs operations are sync or promise-returning; there's no file-level lock. Baileys' internal state object is mutated from the same thread, but Promise microtasks can interleave around `fs.writeFile`.
**How to avoid:** The enqueueSaveCreds Map + Promise chain — guarantees at-most-one `saveCreds` in flight per authDir at any time.
**Warning signs:** creds.json file size oscillates; `JSON.parse` fails on some freshly-written files; phantom "Unexpected end of JSON input" errors on restart.

### Pitfall 3: Baileys 7.x requires Node ≥ 20 but bridge package.json says ≥ 18
**What goes wrong:** A user on Node 18 upgrades Synapse, `npm install` silently succeeds (npm only warns), bridge crashes at runtime with obscure `SyntaxError` or `TypeError` from ESM-only transitive modules.
**Why it happens:** Baileys 7.x uses `p-queue@9` which requires Node 20 ESM features; `@whiskeysockets/baileys` itself declares `engines: { node: ">=20.0.0" }` but npm `engines` is advisory by default.
**How to avoid:**
1. Bump `baileys-bridge/package.json` → `engines.node: ">=20.0.0"`.
2. Add a runtime check in `index.js` top: `if (parseInt(process.versions.node) < 20) { console.error('[BRIDGE] Node 20+ required for Baileys 7.x'); process.exit(1); }`.
3. Update `synapse_start.sh` + `synapse_start.bat` + `HOW_TO_RUN.md` to reflect new minimum.
**Warning signs:** Cryptic import errors on bridge start, `SyntaxError: Unexpected token` in transitive modules.

### Pitfall 4: Baileys 7.x ESM migration ripple
**What goes wrong:** Baileys 6.8+ moved to ESM. The Synapse bridge is CommonJS (`'use strict'; const { ... } = require(...);`). `require('@whiskeysockets/baileys')` on an ESM-only package fails.
**Why it happens:** Node's `require()` can't load ESM synchronously by default (requires Node 22.12+ `--experimental-require-module` or explicit `await import()`).
**How to avoid:** Two options:
- **Option A (recommended):** Convert `baileys-bridge/index.js` to ESM. Add `"type": "module"` to package.json, rename to `index.mjs` OR keep `.js` with the type flag, change `require(...)` to `import ... from ...`, change `module.exports =` to `export default` (bridge has no exports so this is a non-issue). ~20 lines of syntax edits.
- **Option B:** Use dynamic `await import('@whiskeysockets/baileys')` at top of `startSocket()`. Works but awkward — top-level `await` requires ESM anyway or Node 22.12+.
- **Option C (DISCOURAGED):** Stay on CommonJS and rely on `require('@whiskeysockets/baileys')` working in modern Node. Baileys 7.x exports both via conditional exports; Node 22 supports `require(esm)` under `--experimental-require-module`. Fragile. Don't bet on this.
**Warning signs:** `Error [ERR_REQUIRE_ESM]: require() of ES Module`.
**Verification step for planner:** Before picking an approach, run in sandbox: `cd baileys-bridge && npm install @whiskeysockets/baileys@7.0.0-rc.9 && node -e "const b = require('@whiskeysockets/baileys'); console.log(typeof b.default);"`. If it errors, commit to Option A.

### Pitfall 5: LID-mapping breaks existing creds.json schema
**What goes wrong:** Baileys 7.x requires the auth state to support `lid-mapping`, `device-list`, and `tctoken` keys. Creds.json written by 6.7.21 lacks these. On first connect with 7.x, Baileys expects them and may reject or re-pair.
**Why it happens:** Per the migration guide: *"This system requires the auth state to support the lid-mapping, device-list, and tctoken keys. Look at the SignalDataTypeMap to see what needs change in your application. Make sure you have updated your authentication state."*
**How to avoid:** Three approaches:
- **Accept that upgrade = re-pair** and document this. Simplest. User scans QR once.
- **Write a creds migration** that populates empty `lid-mapping: {}`, `device-list: []`, `tctoken: null` stubs before first 7.x boot. Risky — might not match expected schema.
- **Validate on first boot** — try connecting, catch the failure, log clearly, prompt for re-pair.
**Recommendation:** Accept re-pair. Document in `15-MANUAL-VALIDATION.md`. The restoration-from-backup test for AUTH-V31-02 must still pass with a fresh 7.x-era creds.json, not a 6.7.21-era one.
**Warning signs:** First connect after upgrade fails with cryptic `Error: missing key` or `undefined is not iterable` in Signal store.

### Pitfall 6: `DisconnectReason` enum values unchanged, but semantics drift
**What goes wrong:** Phase 14's `NONRETRYABLE_CODES = {"401", "403", "440"}` maps to loggedOut / forbidden / connectionReplaced. These numeric values are the same in Baileys 7.x. BUT in 7.x, code 440 (connectionReplaced) now fires during Meta Coexistence handshake in some flows — a healthy transition, not a conflict. Halting reconnect on 440 may be over-eager.
**Why it happens:** WhatsApp protocol evolution. Baileys 7.x adds full Meta Coexistence support (pairing a WA Business App alongside linked devices). Handshake phases can briefly show 440.
**How to avoid:** Monitor the first pairing on 7.x with verbose logs. If false-positive 440s appear, add a grace period: only treat 440 as non-retryable after the connection has been `open` at least once. Update supervisor.py's NONRETRYABLE_CODES with a note.
**Warning signs:** After 7.x upgrade, bridge hits `healthState=conflict` on initial pair and never recovers without a `reset_stop_reconnect()` call.
**Recommendation for Phase 15:** Leave NONRETRYABLE_CODES alone, add one integration test that provokes a pairing flow on 7.x and asserts final healthState is `connected`. If it fails, the planner adds a grace period.

### Pitfall 7: `useMultiFileAuthState` rewrites ALL files on first call
**What goes wrong:** On bridge start, `useMultiFileAuthState(AUTH_DIR)` reads every `.json` in the dir and may rewrite them with reformatted content. A `creds.json` that was restored from backup milliseconds ago might be the first one rewritten, potentially re-triggering a `creds.update` event and kicking off the queue.
**Why it happens:** Baileys' auth reader loads into memory, and any internal migration (e.g., adding the new 7.x keys to in-memory state) causes `state.creds` to diverge from disk, firing `creds.update` on the next socket tick.
**How to avoid:** This is expected and HARMLESS — the queue ensures only one write runs at a time, and a rewrite of valid-to-valid creds can't corrupt. But the AUTH-V31-02 test must assert "no QR emission during recovery", which means the test must wait for connection to `open` without seeing a QR event, NOT just check that the queue ran once. Use event-based assertions, not timer-based.
**Warning signs:** Test for AUTH-V31-02 passes on fast CI but flakes on slow Windows hosts because the QR check fires before connection stabilizes.

### Pitfall 8: `messages.upsert` inbound routing breaks on LID-only senders
**What goes wrong:** On 7.x, a group participant may have `msg.key.participant = "1234567890@lid"` (a LID) instead of a PN. Current Synapse bridge's `extractPayload` at index.js:162 does:
```javascript
const userId = isGroup ? (msg.key.participant || msg.pushName || msg.key.remoteJid) : msg.key.remoteJid;
```
If `msg.key.participant` is an `@lid` JID, it's returned as-is, and downstream Python code (which assumes `@s.whatsapp.net` JIDs for user_id) may mis-match in allowlists, pairing, echo tracker, etc.
**Why it happens:** The 7.x LID migration anonymizes phone numbers in large groups. Code that expects `@s.whatsapp.net` breaks.
**How to avoid:** Surface both in the payload:
```javascript
const userId = isGroup ? (msg.key.participant || msg.pushName || msg.key.remoteJid) : msg.key.remoteJid;
const userIdAlt = isGroup ? (msg.key.participantAlt || null) : (msg.key.remoteJidAlt || null);
payload.user_id = userId;
payload.user_id_alt = userIdAlt;   // NEW — PN if userId is LID, LID if userId is PN
```
The Python `OutboundTracker` + `PairingStore` can then match on either. Alternatively, only emit the PN when available (fallback to LID). Planner picks.
**Warning signs:** After 7.x upgrade, group messages get `user_id` like `1234567890@lid` in logs; access control rules matched on `@s.whatsapp.net` no longer fire.

### Pitfall 9: Group metadata owner type flips from PN to LID
**What goes wrong:** `sock.groupMetadata(jid)` returns a `GroupMetadata` object where `owner` is now a LID. Current Synapse bridge exposes the raw result via `GET /groups/:jid` and cache; any Python code reading `meta.owner` assuming `@s.whatsapp.net` breaks.
**Why it happens:** 7.x LID migration applies to the metadata schema too.
**How to avoid:** Baileys 7.x adds `ownerPn`, `descOwnerPn` alongside `owner`, `descOwner`. The bridge can transparently include both in the `/groups/:jid` response without changing the endpoint contract (additive).
**Warning signs:** Group-admin checks on the Python side stop matching the user's PN.

### Pitfall 10: `downloadMediaMessage` API unchanged but transitive re-encoding drops audio metadata
**What goes wrong:** On 7.x, inbound voice notes download successfully but may lack duration/waveform metadata that the current `extractPayload` expects (via `msgContent.audioMessage.seconds`).
**Why it happens:** 7.x has a new `music-metadata@11.7.0` dep that changes how audio metadata is extracted.
**How to avoid:** The current bridge doesn't READ `audioMessage.seconds` anywhere (verified by grep on index.js). It just downloads the buffer and forwards it to Python. Forward-compatible.
**Warning signs:** Voice-note transcription pipeline misses duration hints. Not a Phase 15 concern.

### Pitfall 11: `cachedGroupMetadata: async (jid) => groupCache.get(jid)` signature unchanged, but return shape wider
**What goes wrong:** Synapse's current `cachedGroupMetadata` at index.js:261 returns whatever `node-cache` has stored, populated by `sock.groupMetadata(event.id)`. On 7.x, the stored object has more fields (`ownerPn`, LID-shaped participants). Cached-too-long returns stale shape after server rotation.
**Why it happens:** `node-cache` TTL is 300s (5 min) — short enough that staleness is bounded.
**How to avoid:** No change needed. Keep TTL. Just know that after a 7.x-era write, cache entries have new fields.

### Pitfall 12: Deleting `auth_state.bak/` during Phase 15 breaks rollback
**What goes wrong:** If the 7.x upgrade goes sideways and the team wants to roll back to 6.7.21, having deleted `auth_state.bak/` means no fast recovery path.
**Why it happens:** Premature cleanup.
**How to avoid:** Phase 15 keeps `auth_state.bak/` on disk (rename it to `auth_state.bak.legacy/` as a marker) for at least one release cycle. Delete in Phase 16 or later.
**Warning signs:** Rollback to 6.7.21 requires re-pair because the old backup system is gone.

## Code Examples

### Complete enqueueSaveCreds integration (port to index.js)

```javascript
// Source: synthesized from D:/Shorty/openclaw/extensions/whatsapp/src/session.ts:37-95
//         and D:/Shorty/openclaw/extensions/whatsapp/src/auth-store.ts:36-65
//         adapted for Synapse baileys-bridge CommonJS (or ESM per Pitfall 4 decision)

const fsSync = require('node:fs');
const path = require('node:path');

// ---- Module-level queue state ----
const credsSaveQueues = new Map();  // authDir → Promise<void>
const CREDS_SAVE_FLUSH_TIMEOUT_MS = 15_000;

// ---- Path helpers ----
function resolveWebCredsPath(authDir) {
  return path.join(authDir, 'creds.json');
}
function resolveWebCredsBackupPath(authDir) {
  return path.join(authDir, 'creds.json.bak');
}

// ---- Raw reader with size + existence guards ----
function readCredsJsonRaw(filePath) {
  try {
    if (!fsSync.existsSync(filePath)) return null;
    const stats = fsSync.statSync(filePath);
    if (!stats.isFile() || stats.size <= 1) return null;
    return fsSync.readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
}

// ---- Boot-time backup restoration (AUTH-V31-02) ----
function maybeRestoreCredsFromBackup(authDir) {
  try {
    const credsPath = resolveWebCredsPath(authDir);
    const backupPath = resolveWebCredsBackupPath(authDir);
    const raw = readCredsJsonRaw(credsPath);
    if (raw) {
      JSON.parse(raw);
      return;  // creds valid, no restore needed
    }
    const backupRaw = readCredsJsonRaw(backupPath);
    if (!backupRaw) return;  // nothing to restore

    JSON.parse(backupRaw);  // validate backup parseable
    fsSync.copyFileSync(backupPath, credsPath);
    try { fsSync.chmodSync(credsPath, 0o600); } catch {}
    console.warn('[BRIDGE] Restored corrupted creds.json from backup:', credsPath);
  } catch {
    // ignore — fall through to fresh-pair flow
  }
}

// ---- Write-side: pre-validate creds before clobbering backup (AUTH-V31-03) ----
async function safeSaveCreds(authDir, saveCreds) {
  try {
    const credsPath = resolveWebCredsPath(authDir);
    const backupPath = resolveWebCredsBackupPath(authDir);
    const raw = readCredsJsonRaw(credsPath);
    if (raw) {
      try {
        JSON.parse(raw);
        fsSync.copyFileSync(credsPath, backupPath);
        try { fsSync.chmodSync(backupPath, 0o600); } catch {}
      } catch {
        // current creds.json is corrupt — keep the existing (older, valid) .bak
      }
    }
  } catch {
    // backup failures are non-fatal
  }
  try {
    await Promise.resolve(saveCreds());
    try { fsSync.chmodSync(resolveWebCredsPath(authDir), 0o600); } catch {}
  } catch (err) {
    console.error('[BRIDGE] failed saving WhatsApp creds:', err.message);
  }
}

// ---- Queue enqueue (AUTH-V31-01) ----
function enqueueSaveCreds(authDir, saveCreds) {
  const prev = credsSaveQueues.get(authDir) ?? Promise.resolve();
  const next = prev
    .then(() => safeSaveCreds(authDir, saveCreds))
    .catch((err) => {
      console.warn('[BRIDGE] creds save queue error:', err && err.message);
    })
    .finally(() => {
      if (credsSaveQueues.get(authDir) === next) credsSaveQueues.delete(authDir);
    });
  credsSaveQueues.set(authDir, next);
}

// ---- Graceful flush for shutdown (optional, bonus) ----
async function waitForCredsSaveQueueWithTimeout(authDir, timeoutMs = CREDS_SAVE_FLUSH_TIMEOUT_MS) {
  let flushTimeout;
  await Promise.race([
    (credsSaveQueues.get(authDir) ?? Promise.resolve()),
    new Promise((resolve) => { flushTimeout = setTimeout(resolve, timeoutMs); }),
  ]).finally(() => { if (flushTimeout) clearTimeout(flushTimeout); });
}

// ---- Wiring inside startSocket() ----
async function startSocket() {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  maybeRestoreCredsFromBackup(AUTH_DIR);               // NEW — before auth state load
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  // ... baileysVersion fetch unchanged ...
  sock = makeWASocket({ /* ...unchanged config... */ });

  // REPLACES old atomicSaveCredsWrapper (delete lines 251-254 + 265):
  sock.ev.on('creds.update', () => enqueueSaveCreds(AUTH_DIR, saveCreds));
  // ... rest of startSocket unchanged ...
}
```

### Stress test script (unit-level AUTH-V31-01 validation)

```javascript
// Source: synthesized — mirrors expected Phase 15 Wave 0 test
// File: baileys-bridge/test/creds_queue.test.js
// Run with: cd baileys-bridge && node --test test/creds_queue.test.js

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

// Import the queue implementation (assumes exports added to index.js)
const { enqueueSaveCreds, maybeRestoreCredsFromBackup } = require('../lib/creds_queue.js');

test('10 concurrent enqueueSaveCreds calls serialize writes (AUTH-V31-01)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-creds-'));
  const credsPath = path.join(dir, 'creds.json');
  fs.writeFileSync(credsPath, JSON.stringify({ counter: 0 }));

  let writeCount = 0;
  const writes = [];
  const saveCreds = async () => {
    writeCount += 1;
    const currentRaw = fs.readFileSync(credsPath, 'utf-8');
    const current = JSON.parse(currentRaw);  // MUST parse — AUTH-V31-01 invariant
    writes.push(current.counter);
    await new Promise((r) => setTimeout(r, Math.random() * 5));  // simulate I/O jitter
    fs.writeFileSync(credsPath, JSON.stringify({ counter: current.counter + 1 }));
  };

  // Fire 10 concurrent enqueues
  for (let i = 0; i < 10; i++) enqueueSaveCreds(dir, saveCreds);

  // Wait for all to settle
  await new Promise((r) => setTimeout(r, 500));

  assert.equal(writeCount, 10, 'all 10 saves executed');
  // Sequential counter — proves no interleaving
  assert.deepEqual(writes.sort((a, b) => a - b), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  const finalRaw = fs.readFileSync(credsPath, 'utf-8');
  JSON.parse(finalRaw);  // still parseable
  fs.rmSync(dir, { recursive: true });
});

test('corrupt creds.json restored from valid .bak (AUTH-V31-02)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-creds-'));
  const credsPath = path.join(dir, 'creds.json');
  const bakPath = path.join(dir, 'creds.json.bak');
  fs.writeFileSync(bakPath, JSON.stringify({ noiseKey: 'good' }));
  fs.writeFileSync(credsPath, '{truncated-JSON');  // corrupt

  maybeRestoreCredsFromBackup(dir);

  const raw = fs.readFileSync(credsPath, 'utf-8');
  const parsed = JSON.parse(raw);
  assert.equal(parsed.noiseKey, 'good');
  fs.rmSync(dir, { recursive: true });
});

test('corrupt creds.json does NOT clobber good .bak (AUTH-V31-03)', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-creds-'));
  const credsPath = path.join(dir, 'creds.json');
  const bakPath = path.join(dir, 'creds.json.bak');
  fs.writeFileSync(bakPath, JSON.stringify({ noiseKey: 'protected' }));
  fs.writeFileSync(credsPath, '{this-is-corrupt');

  const saveCreds = async () => { /* no-op — we're testing pre-save backup logic */ };
  enqueueSaveCreds(dir, saveCreds);
  await new Promise((r) => setTimeout(r, 50));

  const bakAfter = JSON.parse(fs.readFileSync(bakPath, 'utf-8'));
  assert.equal(bakAfter.noiseKey, 'protected', 'backup still has good data');
  fs.rmSync(dir, { recursive: true });
});
```

### OpenClaw sendMessage media shapes (verified for 7.x parity)

```javascript
// Source: D:/Shorty/openclaw/extensions/whatsapp/src/inbound/send-api.ts:41-65
// These shapes are identical to what Synapse bridge already sends.

// Image
{ image: buffer, caption: text || undefined, mimetype: mediaType }
// Audio (voice note)
{ audio: buffer, ptt: true, mimetype: mediaType }   // mediaType='audio/ogg; codecs=opus'
// Video
{ video: buffer, caption: text || undefined, mimetype: mediaType, ...(gifPlayback ? { gifPlayback: true } : {}) }
// Document (PDF)
{ document: buffer, fileName, caption: text || undefined, mimetype: mediaType }
// Reaction
{ react: { text: emoji, key: { remoteJid: jid, id: messageId, fromMe, participant } } }
// Text
{ text }
```

**Synapse bridge parity check:** current `/send` (line 414) uses `{ [mediaTypeKey]: buffer, caption }` — looser than OpenClaw (missing `mimetype`). For 7.x, being explicit about `mimetype` is safer. Add it to Synapse's `/send` handler during Phase 15 as a small correctness fix.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `writeFileAtomic(creds.json)` without coordination | Per-authDir Promise queue (OpenClaw pattern) | 2025 (OpenClaw production) | Torn-write protection + concurrent-write serialization, 15 lines, no new deps. |
| Full-directory backup (`fs.cpSync`) | Single-file `creds.json.bak` | 2025 | I/O down from O(N files) to O(1); recovery time down from dir-copy to file-copy; semantic correctness: only creds.json matters for recovery. |
| `useMultiFileAuthState` + fresh pair on corruption | `maybeRestoreCredsFromBackup` before `useMultiFileAuthState` | 2025 | Recovery without user intervention for torn-write scenarios. |
| Baileys 6.x CommonJS | Baileys 7.x ESM + LID-aware | September–November 2025 | ESM migration + LID-mapping schema + Meta Coexistence pairing support. Forced upgrade (6.x EOL per maintainer). |
| PN-only JIDs (`@s.whatsapp.net`) | Dual PN/LID with `remoteJidAlt` / `participantAlt` | 7.0.0 | Group participants now anonymized; LID is primary, PN secondary. Access-control code assuming `@s.whatsapp.net` breaks. |
| `onWhatsApp()` returns JIDs + LIDs | `onWhatsApp()` returns only JIDs; use `getLIDForPN` for mapping | 7.0.0 | Existing Synapse code doesn't call onWhatsApp → unaffected. Good. |
| ACK on successful message delivery | ACK suppressed (Meta was banning users for it) | 7.0.0 | Fewer bans, slightly reduced delivery observability. Current bridge's receipt forwarding at index.js:335 still works — the `message-receipt.update` event still fires; what changed is what Baileys sends TO the server. |

**Deprecated/outdated:**
- `isJidUser()` removed → use `isPnUser()` (Synapse doesn't call either — unaffected).
- proto.fromObject() removed → use proto.create() (Synapse doesn't call proto directly — unaffected).
- Baileys 6.x line — no further patches per maintainer; security-critical to upgrade.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `7.0.0-rc.9` qualifies as "latest stable 7.x" for BAIL-01 (per npm dist-tag + OpenClaw production usage + maintainer directive to move off 6.x) | Standard Stack, BAIL-01 | MEDIUM — user may interpret "stable" strictly and require waiting for a non-RC tag. Planner should surface this as a confirmation item in CONTEXT.md before committing. If user says no, the phase blocks until WhiskeySockets publishes 7.0.0 proper. |
| A2 | Baileys 7.x can read creds.json files written by 6.7.21 | Pitfall 5 | MEDIUM — migration guide implies schema extension (new keys added), not incompatibility, but fresh pair is always safe. Worst case: one-time re-pair on first 7.x boot. Document as known. |
| A3 | Phase 14's `NONRETRYABLE_CODES = {"401", "403", "440"}` remains correct under 7.x Meta Coexistence flows | Pitfall 6 | LOW-MEDIUM — 440 may fire during Coexistence handshake as a transient. Easy to mitigate post-facto with a grace period or by asserting "first connection open" before enabling non-retryable logic. |
| A4 | The Synapse bridge's `cachedGroupMetadata` contract is untouched by 7.x's LID additions | Pitfall 11 | LOW — cache is keyed by JID (unchanged), value is the raw `groupMetadata()` result (wider schema but additive). TTL is 5 minutes so stale-shape risk is bounded. |
| A5 | Converting bridge to ESM (Option A for Pitfall 4) is the right call vs. sticking with CommonJS + `--experimental-require-module` (Option C) | Pitfall 4 | MEDIUM — Option C works on Node 22 but is experimental. Option A is ~20 lines of `require→import` edits. Planner should run the verification step (`node -e "require('@whiskeysockets/baileys')"` on 7.0.0-rc.9 after install) to confirm which option is needed. |
| A6 | Removing `auth_state.bak/` directory in Phase 15 doesn't break a rollback to 6.7.21 | Pitfall 12 | LOW — operator could always re-pair. But the research mitigation (rename to `.legacy` rather than delete) is free. Planner adopts. |
| A7 | `ffmpeg` is available on dev host for generating OGG Opus test fixtures | Environment Availability | LOW — Synapse has a TTS pipeline so likely yes; if no, commit a ~2 KB synthetic fixture. |
| A8 | `/chat/{user}` synchronous persona endpoint isn't affected by Phase 15 (bridge-only change) | Pipeline Integration | LOW — the bridge upgrade is transparent to Python side; only `GET /channels/whatsapp/status.healthState` and inbound payload schema (user_id/user_id_alt) change. |
| A9 | Phase 13 structured logging (`get_child_logger`) is available for use in bridge → Python webhook POSTs | Observability | LOW — verified Phase 13's 13-05 wave is done per STATE.md; `observability/` package imports work. Bridge itself uses `console.*` (Node side, cannot use Python logger), but the Python connection-state webhook handler can log structured. |
| A10 | OpenClaw's enqueueSaveCreds + maybeRestoreCredsFromBackup pattern shape is stable and reflected correctly in the code examples above | Architecture Patterns | LOW — direct file read of session.ts + auth-store.ts verified. Code blocks quote verbatim. |

## Open Questions

1. **"Latest stable 7.x" interpretation (BAIL-01) — does user accept `7.0.0-rc.9` as "stable"?**
   - What we know: npm `latest` dist-tag = 7.0.0-rc.9; OpenClaw pins same; 6.x EOLed by maintainer.
   - What's unclear: whether user's definition of "stable" requires a non-RC tag.
   - Recommendation: surface as a confirm item in `/gsd-discuss-phase 15`. Provide fallback plan (delay phase until 7.0.0 drops) but recommend moving forward with rc.9 given the OpenClaw precedent.

2. **ESM conversion of the bridge — Option A or Option C (Pitfall 4)?**
   - What we know: Baileys 6.8+ is ESM-first; Node 22 supports `require(esm)` experimentally.
   - What's unclear: will `require('@whiskeysockets/baileys')` work on the user's Node version without the experimental flag? Needs empirical check.
   - Recommendation: run `npm install @whiskeysockets/baileys@7.0.0-rc.9 && node -e "const b = require('@whiskeysockets/baileys'); console.log(typeof b);"` in Wave 0. If errors, commit to Option A (ESM conversion) — this is ~20 lines of syntax edits.

3. **LID-migration re-pair expectation (BAIL-02 edge case)**
   - What we know: 7.x migration guide says auth state must support `lid-mapping`, `device-list`, `tctoken` keys.
   - What's unclear: does a 6.7.21-era creds.json work directly on first 7.x boot, or does it force a QR re-scan?
   - Recommendation: accept possible one-time re-pair. Document in `15-MANUAL-VALIDATION.md`. Test AUTH-V31-02's "no QR emission" assertion only against 7.x-era creds.json (created after the upgrade), not 6.7.21-era state.

4. **Should the per-authDir queue be generalized for Phase 18 multi-account now?**
   - What we know: the `Map<authDir, Promise>` shape already generalizes. Phase 15 has exactly one authDir.
   - What's unclear: should Phase 15 pre-build the multi-authDir plumbing (mux `enqueueSaveCreds(authDir, saveCreds)` across N accounts) even though it's single-account now?
   - Recommendation: yes — the API is already plural-compatible. No code cost, avoids rework in Phase 18.

5. **Graceful SIGTERM flush (Pitfall 3 mitigation) — in scope or defer?**
   - What we know: Python WhatsAppChannel uses SIGTERM → SIGKILL with 5s gap.
   - What's unclear: whether `waitForCredsSaveQueueWithTimeout` in the bridge's SIGTERM handler is worth the complexity for Phase 15 (not in success criteria).
   - Recommendation: include as one ~10-line addition — closes a small data-loss window, trivially testable.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (Python side) | pytest 7.4.0 + pytest-asyncio 0.23+ (`asyncio_mode = auto`) — covers integration tests that spawn bridge subprocess |
| Framework (Node side) | Node built-in `node:test` (no new dep) — covers unit tests for enqueueSaveCreds |
| Config file (Python) | `workspace/tests/pytest.ini` |
| Config file (Node) | none needed — `node --test baileys-bridge/test/*.test.js` |
| Quick run command | `cd baileys-bridge && node --test test/creds_queue.test.js && cd ../workspace && pytest tests/test_bridge_auth.py -x` |
| Full suite command | `cd workspace && pytest tests/ -v` |
| Estimated runtime | Node unit tests ~2s; Python integration ~20s |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUTH-V31-01 | 10 concurrent `enqueueSaveCreds` calls serialize; every intermediate creds.json parses | unit (Node) | `cd baileys-bridge && node --test test/creds_queue.test.js` | ❌ Wave 0 |
| AUTH-V31-01 | Queue auto-cleans Map entry after flush | unit (Node) | `node --test test/creds_queue.test.js -t queue_cleans_map_entry` | ❌ Wave 0 |
| AUTH-V31-01 | Queue error in one save doesn't cancel subsequent saves | unit (Node) | `node --test test/creds_queue.test.js -t save_error_does_not_cancel_chain` | ❌ Wave 0 |
| AUTH-V31-02 | Corrupt creds.json + valid backup → creds.json restored on boot | unit (Node) | `node --test test/restore.test.js -t restore_from_valid_backup` | ❌ Wave 0 |
| AUTH-V31-02 | Missing creds.json + valid backup → creds.json restored on boot | unit (Node) | `node --test test/restore.test.js -t restore_when_missing` | ❌ Wave 0 |
| AUTH-V31-02 | End-to-end: corrupt creds.json + restart bridge subprocess → no QR event emitted, connection `open` reached | integration (Python) | `cd workspace && pytest tests/test_bridge_auth.py::test_corruption_recovery_no_qr -x` | ❌ Wave 0 |
| AUTH-V31-03 | Corrupt current creds.json → backup is NOT overwritten | unit (Node) | `node --test test/creds_queue.test.js -t corrupt_creds_preserves_bak` | ❌ Wave 0 |
| AUTH-V31-03 | Valid current creds.json + saveCreds run → backup is updated | unit (Node) | `node --test test/creds_queue.test.js -t valid_creds_updates_bak` | ❌ Wave 0 |
| BAIL-01 | package.json pins `@whiskeysockets/baileys: 7.0.0-rc.9` | unit (Python) | `cd workspace && pytest tests/test_bridge_auth.py::test_baileys_version_pin -x` | ❌ Wave 0 |
| BAIL-01 | `package.json.engines.node` is `>=20.0.0` | unit (Python) | `cd workspace && pytest tests/test_bridge_auth.py::test_node_engine_requirement -x` | ❌ Wave 0 |
| BAIL-01 | Bridge start throws clear error on Node < 20 | integration (Python) | `cd workspace && pytest tests/test_bridge_auth.py::test_node_version_gate -x` (via env mock) | ❌ Wave 0 |
| BAIL-02 | QR pairing end-to-end on 7.x against fresh phone | manual | (see `15-MANUAL-VALIDATION.md`) | — |
| BAIL-02 | `/qr` endpoint returns QR string for unauthenticated state on 7.x | integration (Python) | `cd workspace && pytest tests/test_bridge_auth.py::test_qr_endpoint_returns_string -x` (after fresh auth wipe) | ❌ Wave 0 |
| BAIL-03 | `/send` with `{jid, mediaUrl, mediaType: 'image'}` — delivered receipt within 30s | manual (requires live WA) | `15-MANUAL-VALIDATION.md` | — |
| BAIL-03 | `/send-voice` with OGG Opus audio — delivered receipt, received as PTT voice note | manual | `15-MANUAL-VALIDATION.md` | — |
| BAIL-03 | `/send` with PDF document — delivered receipt, received with filename | manual | `15-MANUAL-VALIDATION.md` | — |
| BAIL-03 | Media payload shapes match Baileys 7.x AnyMediaMessageContent types | unit (Node) | `node --test test/send_shapes.test.js` (mock sock, assert payload shape) | ❌ Wave 0 |
| BAIL-04 | `GET /groups/:jid` returns `{id, subject, participants, owner, ownerPn?}` on 7.x | integration (Python + live bridge) | `cd workspace && pytest tests/test_bridge_auth.py::test_group_metadata_shape -x` (requires auth) | ❌ Wave 0 (manual with live account) |
| BAIL-04 | Inbound group message → payload has `user_id` (LID or PN) AND `user_id_alt` (the counterpart) | manual | `15-MANUAL-VALIDATION.md` + inspect logs | — |
| BAIL-04 | Round-trip reply in a group routes via `chat_id` correctly | manual | `15-MANUAL-VALIDATION.md` | — |

### Sampling Rate
- **Per task commit:** `cd baileys-bridge && node --test test/` (Node unit tests, <5s)
- **Per wave merge:** `cd baileys-bridge && node --test test/ && cd ../workspace && pytest tests/test_bridge_auth.py tests/test_supervisor_watchdog.py tests/test_echo_tracker.py -v` (Node + Python integration, <30s)
- **Phase gate:** Full Python suite green (`cd workspace && pytest tests/ -v`) + `15-MANUAL-VALIDATION.md` checklist signed off before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `baileys-bridge/test/creds_queue.test.js` — unit tests for `enqueueSaveCreds`, `safeSaveCreds`, queue Map cleanup, error isolation (AUTH-V31-01, AUTH-V31-03)
- [ ] `baileys-bridge/test/restore.test.js` — unit tests for `maybeRestoreCredsFromBackup`, `readCredsJsonRaw` guards (AUTH-V31-02)
- [ ] `baileys-bridge/test/send_shapes.test.js` — unit tests for media payload shapes (BAIL-03 partial automation)
- [ ] `baileys-bridge/lib/creds_queue.js` — extract exportable module from `index.js` so tests can import without spinning up Express (or alternatively, export from `index.js` with guard against double-listen)
- [ ] `baileys-bridge/test/fixtures/test_voice.ogg` — synthetic 1s OGG Opus for voice-note test, ~2 KB (if ffmpeg absent locally, commit the binary)
- [ ] `workspace/tests/test_bridge_auth.py` — Python integration tests: version-pin asserts, Node-engine gate, QR endpoint smoke, group metadata shape (AUTH-V31-02 end-to-end, BAIL-01, BAIL-02 partial, BAIL-04 partial)
- [ ] `.planning/phases/15-auth-persistence-baileys-7x/15-MANUAL-VALIDATION.md` — checklist for phone pairing, media send/recv, group round-trip (BAIL-02/03/04 manual portions)
- [ ] `workspace/tests/conftest.py` — add fixture `bridge_auth_tmp_dir` that creates a fresh `auth_state/` in a tmpdir for integration tests without clobbering the dev host's real creds

**Framework install:** none needed. Node built-in `node:test` is available on Node 20+; pytest + pytest-asyncio already in `requirements-dev.txt`.

## Pipeline Integration (observability hooks — from Phase 13)

Structured log events that Phase 15 emits. These use Phase 13's `get_child_logger` on the Python side (bridge-forwarded state webhooks); the bridge itself logs via `console.*` + pino (no Phase 13 integration since it's Node, not Python).

| Event | Emitter | Fields | Trigger |
|-------|---------|--------|---------|
| `bridge.creds.save.enqueued` | Bridge (console) → Python webhook optional | `authDir` (redacted hash), `queue_depth` | every `creds.update` |
| `bridge.creds.save.committed` | Bridge console | `authDir` (redacted), `duration_ms` | on safeSaveCreds completion |
| `bridge.creds.backup.written` | Bridge console | `authDir` (redacted), `bak_size_bytes` | each successful backup copy |
| `bridge.creds.backup.skipped` | Bridge console, `WARN` level | `authDir` (redacted), `reason: corrupt_current_creds` | when current creds.json fails JSON.parse |
| `bridge.creds.restored_from_backup` | Bridge console, `WARN` level | `authDir` (redacted), `creds_path` | on startup restoration |
| `bridge.creds.save.failed` | Bridge console, `ERROR` level | `authDir` (redacted), `error` | saveCreds throws |
| `wa.healthState.changed` | Python supervisor.py (already emits) | `prev_state`, `health_state`, `attempt`, `code` | Phase 14 existing — Phase 15 adds new close codes if any emerge on 7.x |

**Integration with Phase 14 healthState:** no new close codes expected (enum values unchanged). Phase 15 QA must verify behavior under:
- Successful pair on 7.x (healthState: stopped → reconnecting → connected)
- 401 loggedOut on 7.x (healthState → logged-out, stop_reconnect=true)
- 440 connectionReplaced during Meta Coexistence handshake (watch for false-positive non-retryable — see Pitfall 6)
- 515 restartRequired after pairing (existing WA-FIX-02 handling, unchanged)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | WhatsApp QR-pair / multi-device login is the authentication flow. `creds.json` contains Noise Protocol keys (identity + signed-pre-key + registrationId). Corruption = auth loss. |
| V3 Session Management | yes | `creds.json` + pre-keys + sessions constitute the WhatsApp session. The atomic queue protects session integrity against concurrent writes. |
| V4 Access Control | no | Phase 15 doesn't touch DmPolicy / allowlists (Phase 14 / 17 concern). |
| V5 Input Validation | yes (partial) | JSON.parse validation on creds + backup treats contents as untrusted bytes before any use. `readCredsJsonRaw` size guard (`size <= 1`) rejects obviously-empty files. |
| V6 Cryptography | yes — **never hand-roll** | Baileys handles all crypto (Signal Protocol, Noise Protocol, WhatsApp binary protocol). Phase 15 only moves bytes — never parses or transforms crypto material. Never touch the keys inside creds.json. |
| V7 Logging | yes | No raw JID, no phone number, no creds.json content ever logged. `authDir` path is local and non-sensitive. Backup path includes authDir which on multi-account setup carries accountId — treat as low-sensitivity. |
| V8 Data Protection | yes | `chmod 600` on creds.json + creds.json.bak (OpenClaw pattern, best-effort on Windows). File lives under `~/.synapse/` or `baileys-bridge/` which is user-local. |
| V14 Configuration | yes | `package.json` version pin is critical — floating versions allow supply-chain surprise. Pin exact: `"@whiskeysockets/baileys": "7.0.0-rc.9"` (no caret `^`). |

### Known Threat Patterns for Node.js + WhatsApp

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Race-condition file corruption | Tampering | Per-authDir Promise-chain queue — only one write in flight per authDir |
| Supply-chain compromise via npm | Tampering | Exact-version pin (no `^`) + verify integrity hash in `package-lock.json` during install |
| Torn write (SIGKILL during saveCreds) | Tampering | Baileys uses atomic writes internally (rename-based); plus OpenClaw's JSON-parse-before-backup guard |
| Backup clobbered by corrupt data | Tampering | `JSON.parse(raw)` gate on current creds before `copyFileSync` to backup (AUTH-V31-03) |
| Auth state exfiltration via log leak | Information Disclosure | Never log creds.json contents; log only paths + sizes + durations |
| Auth directory world-readable | Information Disclosure | `chmod 600` on creds.json + creds.json.bak (best-effort on Windows which doesn't support POSIX perms in same way — accept) |
| Malicious LID spoofing in groups | Tampering | 7.x `remoteJidAlt` / `participantAlt` gives ground-truth PN to cross-check. Not Phase 15 exploit surface but surface it for Phase 17's access module. |
| Rollback to vulnerable 6.x via package-lock manipulation | Tampering | Pinned version in package.json + lockfile + CI check that `npm ls @whiskeysockets/baileys` returns exactly `7.0.0-rc.9` |

## Project Constraints (from CLAUDE.md)

Direct extraction of directives from `D:/Shorty/Synapse-OSS/CLAUDE.md`:

1. **OSS hygiene (pre-push)**: `creds.json` must be in `.gitignore`; never commit real Baileys auth state; `auth_state/` and `auth_state.bak/` excluded by existing `baileys-bridge/.gitignore` (verified file exists). Phase 15 tests use tmpdirs.
2. **Code graph first**: planner should query `semantic_search_nodes_tool` for `WhatsAppChannel`, `enqueueSaveCreds`, `maybeRestoreCredsFromBackup`, `supervisor.py::NONRETRYABLE_CODES` before reading files, then Read full source for implementation.
3. **Python 3.11 / line-length 100 / ruff + black**: all Python test files in `workspace/tests/test_bridge_auth.py` must pass existing linters.
4. **asyncio throughout (no Redis/Celery)**: Node queue uses Promise chain, not external broker. Python integration tests use pytest-asyncio.
5. **Windows cp1252 gotcha**: bridge console output is ASCII (verified — uses `[BRIDGE]` tags). Keep.
6. **synapse.json wide blast radius (gotcha #7)**: Phase 15 does NOT touch synapse.json schema (auth state is bridge-local). No ripple.
7. **Dual Cognition / Traffic Cop timing (gotcha #8-10)**: Phase 15 does NOT touch the chat pipeline. No timing impact.
8. **MCP graph auto-updates on file changes**: regenerates automatically after Edit/Write; no manual rebuild.
9. **Node 18+ minimum (current)**: Phase 15 bumps to Node 20+ per Baileys 7.x engine requirement. Coordinate `synapse_start.sh`, `synapse_start.bat`, `HOW_TO_RUN.md`, `DEPENDENCIES.md`.
10. **No personal data in commits (OSS development workflow)**: existing `auth_state/` in `baileys-bridge/.gitignore` — verify before any git add.
11. **`markOnlineOnConnect: false`** (CLAUDE.md implicit via WhatsApp gotcha): keep false for push-notification delivery.

## Sources

### Primary (HIGH confidence — direct reads / registry)
- `D:/Shorty/openclaw/extensions/whatsapp/src/session.ts` — full file, lines 1-226 (enqueueSaveCreds + safeSaveCreds + createWaSocket + flush helpers)
- `D:/Shorty/openclaw/extensions/whatsapp/src/auth-store.ts` — full file, lines 1-234 (maybeRestoreCredsFromBackup + readCredsJsonRaw + webAuthExists + path helpers)
- `D:/Shorty/openclaw/extensions/whatsapp/src/creds-files.ts` — full file (path helpers — 20 lines)
- `D:/Shorty/openclaw/extensions/whatsapp/src/session.runtime.ts` — re-export surface for Baileys primitives
- `D:/Shorty/openclaw/extensions/whatsapp/src/session-errors.ts` — getStatusCode / formatError helpers
- `D:/Shorty/openclaw/extensions/whatsapp/src/reconnect.ts` — DEFAULT_RECONNECT_POLICY reference (2000ms/30000ms/1.8/0.25/12)
- `D:/Shorty/openclaw/extensions/whatsapp/src/inbound/send-api.ts` — media payload shapes for 7.x
- `D:/Shorty/openclaw/extensions/whatsapp/src/send.ts` — outbound flow (BAIL-03 parity reference)
- `D:/Shorty/openclaw/extensions/whatsapp/package.json` — pins `@whiskeysockets/baileys: 7.0.0-rc.9`
- `D:/Shorty/Synapse-OSS/baileys-bridge/index.js` — full file, 673 lines; current atomicSaveCreds + sock wiring
- `D:/Shorty/Synapse-OSS/baileys-bridge/package.json` — current pin `^6.7.21`, engines `>=18.0.0`
- `D:/Shorty/Synapse-OSS/baileys-bridge/package-lock.json` — pinned 6.7.21 lock with integrity hashes
- `D:/Shorty/Synapse-OSS/baileys-bridge/node_modules/@whiskeysockets/baileys/lib/Types/index.d.ts` — DisconnectReason enum (401/403/408/411/428/440/500/503/515)
- `D:/Shorty/Synapse-OSS/baileys-bridge/node_modules/@whiskeysockets/baileys/lib/Types/Message.d.ts` — AnyMediaMessageContent type (image/audio/video/document/sticker shapes, 6.x baseline)
- `D:/Shorty/Synapse-OSS/baileys-bridge/auth_state/` directory listing — confirmed 38 pre-key files + 7 app-state-sync-key files + creds.json (6650 bytes) + meta.json layout
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/channels/supervisor.py` — full file (Phase 14 output); NONRETRYABLE_CODES, healthState, ReconnectPolicy
- `D:/Shorty/Synapse-OSS/workspace/sci_fi_dashboard/channels/whatsapp.py` — lines 1-240; subprocess supervisor, reconnect loop wiring
- `D:/Shorty/Synapse-OSS/.planning/ROADMAP.md` — Phase 15 scope + success criteria (lines 156-166)
- `D:/Shorty/Synapse-OSS/.planning/REQUIREMENTS.md` — AUTH-V31-01..03 + BAIL-01..04 wording
- `D:/Shorty/Synapse-OSS/.planning/STATE.md` — v3.1 seed findings (OpenClaw patterns inventory)
- `D:/Shorty/Synapse-OSS/.planning/phases/13-structured-observability/13-RESEARCH.md` — observability surface Phase 15 emits into
- `D:/Shorty/Synapse-OSS/.planning/phases/14-supervisor-watchdog-echo-tracker/14-VALIDATION.md` — Phase 14 validation format template
- `D:/Shorty/Synapse-OSS/CLAUDE.md` — project-wide gotchas + OSS hygiene rules
- npm registry: `npm view @whiskeysockets/baileys dist-tags` → `{ latest: '7.0.0-rc.9' }`; `npm view @whiskeysockets/baileys versions` → full version list; `npm view @whiskeysockets/baileys@7.0.0-rc.9 engines dependencies` → `{ node: '>=20.0.0' }` + 10-dep graph; `npm view @whiskeysockets/baileys time` → publish dates including 7.0.0-rc.9 on 2025-11-21

### Secondary (MEDIUM confidence — web-verified single-source)
- Baileys 7.x migration guide — `https://baileys.wiki/docs/migration/to-v7.0.0` (via curl + text extraction): LIDs + Acks + Meta Coexistence + ESM + Protobufs breaking changes. Content extracted directly.
- Baileys `7.0.0-rc.9` README (via `npm view readme`): full `useMultiFileAuthState` API, `sendMessage` semantics, `cachedGroupMetadata` recommendation, `markOnlineOnConnect` behavior.
- GitHub releases (via `curl api.github.com/repos/WhiskeySockets/Baileys/releases`): `v7.0.0-rc.9` release candidate chain, `v6.7.21` EOL notice ("Move to 7.0.0-rc.6 as soon as possible"), `v7.0.0-rc.6` status + known issues list.

### Tertiary (LOW confidence — flagged for validation)
- Node 22's `--experimental-require-module` support for `require(esm)` on 7.x packages — needs empirical test before committing to CommonJS-retention plan (see Open Question 2).
- Whether 6.7.21-written creds.json can be read by 7.0.0-rc.9 without re-pair — guide implies schema extension (additive), but re-pair is the safe default. Assumption A2.
- Whether `node-cache@5.1.2` (current top-level dep) conflicts with 7.x's `@cacheable/node-cache@1.4.0` (transitive) — two different packages despite similar names. Likely coexist; verify after install.

## Metadata

**Confidence breakdown:**
- OpenClaw port source (enqueueSaveCreds + maybeRestoreCredsFromBackup): HIGH — files read directly and verbatim.
- Current Synapse bridge state (atomicSaveCreds wrapper + directory-copy backup): HIGH — direct file read.
- Baileys 7.x "stable" interpretation: MEDIUM — npm tag = rc.9, maintainer directives support use, but "stable" is a judgment call pending user confirmation.
- Baileys 7.x API changes (DisconnectReason enum, media payloads, LIDs): HIGH — verified from type definitions + migration guide.
- Node 20+ engine requirement: HIGH — verified via `npm view engines`.
- ESM migration requirement: HIGH — migration guide + dep graph confirm.
- Phase 14 healthState integration: HIGH — direct supervisor.py read.
- Phase 13 logging integration: HIGH — direct 13-RESEARCH.md read.
- Environment availability (Node, npm, ffmpeg): HIGH for Node/npm (measured); MEDIUM for ffmpeg (assumed, easily verified).

**Research date:** 2026-04-22
**Valid until:** 2026-05-22 (30-day window — Baileys 7.x is actively pre-release; if a 7.0.0 non-RC drops, re-verify BAIL-01 interpretation. Check `npm view @whiskeysockets/baileys dist-tags` at phase-start.)
