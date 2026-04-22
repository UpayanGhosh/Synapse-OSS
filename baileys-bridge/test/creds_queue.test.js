'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { createTmpAuthDir, cleanup } = require('./helpers/tmp_auth_dir.js');
const { writeValidCreds, writeCorruptCreds, writeValidBackup } = require('./helpers/corrupt_fixtures.js');
const queue = require('../lib/creds_queue.js');

// Wave 0 RED stubs — all 5 tests FAIL because creds_queue.js throws NOT_IMPLEMENTED_WAVE_1.
// Plan 01 (15-01) implements the real logic; these tests turn GREEN there.

test('10 concurrent enqueueSaveCreds calls serialize writes (AUTH-V31-01)', async () => {
  const dir = createTmpAuthDir();
  try {
    queue.__resetQueuesForTest();
    writeValidCreds(dir, { counter: 0 });
    let writeCount = 0;
    const writes = [];
    const saveCredsMock = async () => {
      const cur = JSON.parse(fs.readFileSync(path.join(dir, 'creds.json'), 'utf-8'));
      writes.push(cur.counter);
      await new Promise((r) => setTimeout(r, Math.random() * 5));
      fs.writeFileSync(path.join(dir, 'creds.json'), JSON.stringify({ counter: cur.counter + 1 }));
      writeCount++;
    };
    for (let i = 0; i < 10; i++) queue.enqueueSaveCreds(dir, saveCredsMock);
    await queue.waitForCredsSaveQueueWithTimeout(dir, 10_000);
    assert.equal(writeCount, 10);
    assert.deepEqual(writes, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    JSON.parse(fs.readFileSync(path.join(dir, 'creds.json'), 'utf-8'));
  } finally {
    cleanup(dir);
  }
});

test('queue cleans Map entry after flush (AUTH-V31-01)', async () => {
  const dir = createTmpAuthDir();
  try {
    queue.__resetQueuesForTest();
    writeValidCreds(dir, { counter: 0 });
    let called = false;
    const saveCredsMock = async () => { called = true; };
    queue.enqueueSaveCreds(dir, saveCredsMock);
    await queue.waitForCredsSaveQueueWithTimeout(dir, 5000);
    assert.ok(called, 'saveCreds should have been called');
    // If __peekQueueSize is exported by Wave 1, assert 0; otherwise just assert no throw
    if (typeof queue.__peekQueueSize === 'function') {
      assert.equal(queue.__peekQueueSize(), 0);
    }
  } finally {
    cleanup(dir);
  }
});

test('save error does not cancel chain (AUTH-V31-01)', async () => {
  const dir = createTmpAuthDir();
  try {
    queue.__resetQueuesForTest();
    writeValidCreds(dir, { counter: 0 });
    const results = [];
    const save1 = async () => { results.push(1); };
    const save2 = async () => { throw new Error('boom'); };
    const save3 = async () => { results.push(3); };
    queue.enqueueSaveCreds(dir, save1);
    queue.enqueueSaveCreds(dir, save2);
    queue.enqueueSaveCreds(dir, save3);
    await queue.waitForCredsSaveQueueWithTimeout(dir, 5000);
    assert.deepEqual(results, [1, 3]);
  } finally {
    cleanup(dir);
  }
});

test('corrupt creds.json preserves existing .bak (AUTH-V31-03)', async () => {
  const dir = createTmpAuthDir();
  try {
    queue.__resetQueuesForTest();
    writeCorruptCreds(dir);
    writeValidBackup(dir, { noiseKey: 'protected-bak' });
    const bakBefore = fs.readFileSync(path.join(dir, 'creds.json.bak'), 'utf-8');
    let called = false;
    const saveCredsMock = async () => { called = true; };
    queue.enqueueSaveCreds(dir, saveCredsMock);
    await queue.waitForCredsSaveQueueWithTimeout(dir, 5000);
    const bakAfter = fs.readFileSync(path.join(dir, 'creds.json.bak'), 'utf-8');
    assert.equal(bakBefore, bakAfter, 'corrupt creds must not clobber valid backup');
  } finally {
    cleanup(dir);
  }
});

test('valid creds.json updates .bak (AUTH-V31-03)', async () => {
  const dir = createTmpAuthDir();
  try {
    queue.__resetQueuesForTest();
    writeValidCreds(dir, { noiseKey: 'new-creds' });
    writeValidBackup(dir, { noiseKey: 'old-bak' });
    const saveCredsMock = async () => { /* no-op */ };
    queue.enqueueSaveCreds(dir, saveCredsMock);
    await queue.waitForCredsSaveQueueWithTimeout(dir, 5000);
    const bak = JSON.parse(fs.readFileSync(path.join(dir, 'creds.json.bak'), 'utf-8'));
    assert.equal(bak.noiseKey, 'new-creds', 'backup should be updated to pre-save creds content');
  } finally {
    cleanup(dir);
  }
});
