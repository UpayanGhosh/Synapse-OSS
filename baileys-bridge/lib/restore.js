'use strict';
// Ported verbatim from D:/Shorty/openclaw/extensions/whatsapp/src/auth-store.ts:21-65
// CommonJS for Synapse bridge (OpenClaw is TypeScript/ESM — structure preserved).

const fsSync = require('node:fs');
const path = require('node:path');

// ---- Path helpers (single source of truth — reused by creds_queue.js) ----
function resolveWebCredsPath(authDir) {
  return path.join(authDir, 'creds.json');
}

function resolveWebCredsBackupPath(authDir) {
  return path.join(authDir, 'creds.json.bak');
}

// ---- Raw reader with size + existence guards (AUTH-V31-02) ----
function readCredsJsonRaw(filePath) {
  try {
    if (!fsSync.existsSync(filePath)) return null;
    const stats = fsSync.statSync(filePath);
    if (!stats.isFile() || stats.size <= 1) return null; // AUTH-V31-02 size guard
    return fsSync.readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
}

// ---- Boot-time backup restoration (AUTH-V31-02) ----
// SYNCHRONOUS — must run BEFORE useMultiFileAuthState(authDir) is called (wiring in Plan 03).
// Outer try/catch swallows ALL errors: silent fall-through is safer than crashing at boot.
// Worst case: user re-scans QR. Best case: session restored transparently.
function maybeRestoreCredsFromBackup(authDir) {
  try {
    const credsPath = resolveWebCredsPath(authDir);
    const backupPath = resolveWebCredsBackupPath(authDir);

    const raw = readCredsJsonRaw(credsPath);
    // Gate 1: if creds exist and parse successfully, nothing to restore (common path)
    if (raw) {
      try { JSON.parse(raw); return; } catch { /* corrupt — fall through to restore */ }
    }

    // creds.json missing, effectively-empty, or corrupt — attempt backup restoration
    const backupRaw = readCredsJsonRaw(backupPath);
    if (!backupRaw) {
      return; // no backup available — fall through to fresh-pair
    }

    JSON.parse(backupRaw); // Gate 2: validate backup before using it — never restore garbage
    fsSync.copyFileSync(backupPath, credsPath);
    try { fsSync.chmodSync(credsPath, 0o600); } catch {} // best-effort; swallowed on Windows
    console.warn('[BRIDGE] Restored corrupted creds.json from backup:', credsPath);
  } catch {
    // ignore — worst case, user re-scans QR (safer than crashing at boot)
  }
}

module.exports = {
  resolveWebCredsPath,
  resolveWebCredsBackupPath,
  readCredsJsonRaw,
  maybeRestoreCredsFromBackup,
};
