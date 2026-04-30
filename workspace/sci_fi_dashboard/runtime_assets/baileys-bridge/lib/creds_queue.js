'use strict';
// Ported verbatim from D:/Shorty/openclaw/extensions/whatsapp/src/session.ts:37-95
// + waitForCredsSaveQueueWithTimeout from :197-221
// Synapse adaptation: CommonJS (bridge is CJS); console.warn/error instead of pino logger
// (lib/ is kept logger-less for testability — index.js can wrap in a future refactor).

const fsSync = require('node:fs');
const { resolveWebCredsPath, resolveWebCredsBackupPath } = require('./restore.js');

// ---- Module-level state (AUTH-V31-01: per-authDir queue) ----
// One Promise<void> chain per authDir — Node single-thread + microtask semantics
// guarantee at-most-one saveCreds in flight per authDir at any time.
const credsSaveQueues = new Map(); // authDir -> Promise<void>
const CREDS_SAVE_FLUSH_TIMEOUT_MS = 15_000;

// ---- Test-only helpers (__ prefix marks test-only contract) ----

/**
 * Clears the module-level Map. Call between tests to prevent state leakage.
 * TEST ONLY — do not call in production code.
 */
function __resetQueuesForTest() {
  credsSaveQueues.clear();
}

/**
 * Returns the number of active per-authDir queue entries.
 * TEST ONLY — lets tests assert the Map cleans up after draining.
 */
function __peekQueueSize() {
  return credsSaveQueues.size;
}

// ---- Internal raw reader ----
// Reads creds.json as a raw string. Returns null if the file is absent, empty,
// or unreadable. Plan 02 implements readCredsJsonRaw in restore.js; this bootstrap
// copy avoids a forward dependency that would break Plan 01 tests in isolation.
function _readRaw(filePath) {
  try {
    if (!fsSync.existsSync(filePath)) return null;
    const stats = fsSync.statSync(filePath);
    if (!stats.isFile() || stats.size <= 1) return null;
    return fsSync.readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
}

// ---- Write-side: pre-validate creds before clobbering backup (AUTH-V31-03) ----
// The JSON.parse gate runs BEFORE fs.copyFileSync. If creds.json is currently
// corrupt, the catch swallows and the existing (older, valid) .bak is preserved.
// If creds.json is valid, it is copied to .bak BEFORE saveCreds() runs, so the
// backup always reflects the last known-good state prior to the update.
async function safeSaveCreds(authDir, saveCreds) {
  // Backup phase — non-fatal; never block the real save
  try {
    const credsPath = resolveWebCredsPath(authDir);
    const backupPath = resolveWebCredsBackupPath(authDir);
    const raw = _readRaw(credsPath);
    if (raw) {
      try {
        JSON.parse(raw); // AUTH-V31-03 gate: throws on corrupt input
        fsSync.copyFileSync(credsPath, backupPath);
        try { fsSync.chmodSync(backupPath, 0o600); } catch { /* no-op on Windows */ }
      } catch {
        // current creds.json is corrupt — keep existing (older, valid) .bak untouched
      }
    }
  } catch {
    // backup phase failures are non-fatal; continue to the real save
  }

  // Save phase
  try {
    await Promise.resolve(saveCreds());
    try { fsSync.chmodSync(resolveWebCredsPath(authDir), 0o600); } catch { /* no-op on Windows */ }
  } catch (err) {
    // Log then re-throw so the queue's outer .catch() records it without breaking the chain.
    console.error('[BRIDGE] failed saving WhatsApp creds:', (err && err.message) || String(err));
    throw err;
  }
}

// ---- Queue enqueue (AUTH-V31-01: per-authDir Promise-chain serialization) ----
// Each new call appends to the tail of the existing chain for this authDir.
// The .catch() swallows re-thrown save errors so subsequent enqueued saves run.
// The .finally() removes the Map entry only when this promise is still the tail
// (tail guard: credsSaveQueues.get(authDir) === next).
function enqueueSaveCreds(authDir, saveCreds) {
  const prev = credsSaveQueues.get(authDir) ?? Promise.resolve();
  const next = prev
    .then(() => safeSaveCreds(authDir, saveCreds))
    .catch((err) => {
      console.warn('[BRIDGE] creds save queue error:', (err && err.message) || String(err));
    })
    .finally(() => {
      // Self-cleaning map: delete only when no newer save has been appended behind us.
      if (credsSaveQueues.get(authDir) === next) {
        credsSaveQueues.delete(authDir);
      }
    });
  credsSaveQueues.set(authDir, next);
}

// ---- Graceful flush with timeout (used by Plan 03 SIGTERM handler) ----
// Races the current queue promise against a timeout. The timeout resolves (not
// rejects) so that SIGTERM never hangs indefinitely even if a save is stuck.
async function waitForCredsSaveQueueWithTimeout(authDir, timeoutMs = CREDS_SAVE_FLUSH_TIMEOUT_MS) {
  let flushTimeout;
  try {
    await Promise.race([
      (credsSaveQueues.get(authDir) ?? Promise.resolve()),
      new Promise((resolve) => {
        flushTimeout = setTimeout(resolve, timeoutMs);
      }),
    ]);
  } finally {
    if (flushTimeout) clearTimeout(flushTimeout);
  }
}

module.exports = {
  enqueueSaveCreds,
  safeSaveCreds,
  waitForCredsSaveQueueWithTimeout,
  __resetQueuesForTest,
  __peekQueueSize,
  CREDS_SAVE_FLUSH_TIMEOUT_MS,
};
