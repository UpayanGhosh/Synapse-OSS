'use strict';
const path = require('node:path');

// Wave 0 skeleton. Implementations arrive in Plan 02 (15-02). Tests fail RED here.
// Path resolvers are trivially implementable now — both Wave 1 plans need them.

function resolveWebCredsPath(authDir) {
  return path.join(authDir, 'creds.json');
}

function resolveWebCredsBackupPath(authDir) {
  return path.join(authDir, 'creds.json.bak');
}

function readCredsJsonRaw(_filePath) {
  throw new Error('NOT_IMPLEMENTED_WAVE_1');
}

function maybeRestoreCredsFromBackup(_authDir) {
  throw new Error('NOT_IMPLEMENTED_WAVE_1');
}

module.exports = {
  resolveWebCredsPath,
  resolveWebCredsBackupPath,
  readCredsJsonRaw,
  maybeRestoreCredsFromBackup,
};
