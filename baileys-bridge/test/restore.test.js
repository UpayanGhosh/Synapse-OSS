'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { createTmpAuthDir, cleanup } = require('./helpers/tmp_auth_dir.js');
const { writeValidCreds, writeCorruptCreds, writeValidBackup } = require('./helpers/corrupt_fixtures.js');
const { maybeRestoreCredsFromBackup, readCredsJsonRaw, resolveWebCredsPath } = require('../lib/restore.js');

// Wave 0 RED stubs — readCredsJsonRaw and maybeRestoreCredsFromBackup throw NOT_IMPLEMENTED_WAVE_1.
// Plan 02 (15-02) implements the real logic; these tests turn GREEN there.

test('corrupt creds.json restored from valid .bak (AUTH-V31-02)', () => {
  const dir = createTmpAuthDir();
  try {
    writeCorruptCreds(dir);
    writeValidBackup(dir, { noiseKey: 'good' });
    maybeRestoreCredsFromBackup(dir);
    const restored = JSON.parse(fs.readFileSync(path.join(dir, 'creds.json'), 'utf-8'));
    assert.equal(restored.noiseKey, 'good');
  } finally {
    cleanup(dir);
  }
});

test('missing creds.json restored from valid .bak (AUTH-V31-02)', () => {
  const dir = createTmpAuthDir();
  try {
    writeValidBackup(dir, { noiseKey: 'from-bak' });
    maybeRestoreCredsFromBackup(dir);
    const restored = JSON.parse(fs.readFileSync(path.join(dir, 'creds.json'), 'utf-8'));
    assert.equal(restored.noiseKey, 'from-bak');
  } finally {
    cleanup(dir);
  }
});

test('valid creds.json not overwritten by .bak (AUTH-V31-02)', () => {
  const dir = createTmpAuthDir();
  try {
    writeValidCreds(dir, { k: 'NEW' });
    writeValidBackup(dir, { k: 'OLD' });
    maybeRestoreCredsFromBackup(dir);
    const creds = JSON.parse(fs.readFileSync(path.join(dir, 'creds.json'), 'utf-8'));
    assert.equal(creds.k, 'NEW', 'valid creds should not be overwritten');
  } finally {
    cleanup(dir);
  }
});

test('corrupt creds + missing .bak returns silently (AUTH-V31-02)', () => {
  const dir = createTmpAuthDir();
  try {
    writeCorruptCreds(dir);
    // no backup — should not throw
    assert.doesNotThrow(() => maybeRestoreCredsFromBackup(dir));
    // creds.json left as-is (still corrupt)
    const raw = fs.readFileSync(path.join(dir, 'creds.json'), 'utf-8');
    assert.equal(raw, '{truncated-JSON');
  } finally {
    cleanup(dir);
  }
});

test('readCredsJsonRaw size guard (AUTH-V31-02)', () => {
  const dir = createTmpAuthDir();
  try {
    const p = path.join(dir, 'creds.json');
    // 0-byte file → null
    fs.writeFileSync(p, '');
    assert.equal(readCredsJsonRaw(p), null);
    // 1-byte file → null
    fs.writeFileSync(p, ' ');
    assert.equal(readCredsJsonRaw(p), null);
    // 2-byte file → non-null string
    fs.writeFileSync(p, '{}');
    assert.notEqual(readCredsJsonRaw(p), null);
  } finally {
    cleanup(dir);
  }
});
