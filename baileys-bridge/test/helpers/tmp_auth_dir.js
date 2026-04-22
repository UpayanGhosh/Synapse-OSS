'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

/**
 * Creates a temporary auth directory for test isolation.
 * Returns the path created by fs.mkdtempSync.
 */
function createTmpAuthDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'synapse-creds-'));
}

/**
 * Removes the temporary auth directory created by createTmpAuthDir.
 * Safe to call even if the directory no longer exists.
 */
function cleanup(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    // ignore errors — directory may already be gone
  }
}

module.exports = { createTmpAuthDir, cleanup };
