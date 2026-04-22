'use strict';
const test = require('node:test');
const assert = require('node:assert');

// lib/send_payload.js does not exist in Wave 0 — module-not-found IS the RED state.
// Plan 06 (15-06) Task 1 creates it. Until then every test throws and fails RED.
let buildSendPayload;
try {
  ({ buildSendPayload } = require('../lib/send_payload.js'));
} catch {
  // RED state — Plan 06 creates this module
}

test('image payload includes mimetype (BAIL-03)', () => {
  if (!buildSendPayload) throw new Error('NOT_IMPLEMENTED: lib/send_payload.js missing (Wave 0 RED state)');
  const buf = Buffer.from([0xFF, 0xD8]);
  const result = buildSendPayload('image', buf, { caption: 'hi', mimetype: 'image/jpeg' });
  assert.deepEqual(result, { image: buf, caption: 'hi', mimetype: 'image/jpeg' });
});

test('voice note uses ptt:true + audio/ogg;codecs=opus (BAIL-03)', () => {
  if (!buildSendPayload) throw new Error('NOT_IMPLEMENTED: lib/send_payload.js missing (Wave 0 RED state)');
  const buf = Buffer.from([0x4F, 0x67, 0x67, 0x53]);
  const result = buildSendPayload('voice', buf, {});
  assert.deepEqual(result, { audio: buf, ptt: true, mimetype: 'audio/ogg; codecs=opus' });
});

test('document payload has fileName + mimetype (BAIL-03)', () => {
  if (!buildSendPayload) throw new Error('NOT_IMPLEMENTED: lib/send_payload.js missing (Wave 0 RED state)');
  const buf = Buffer.from([0x25, 0x50]);
  const result = buildSendPayload('document', buf, { fileName: 'report.pdf', caption: 'Q3', mimetype: 'application/pdf' });
  assert.deepEqual(result, { document: buf, fileName: 'report.pdf', caption: 'Q3', mimetype: 'application/pdf' });
});

test('video payload includes caption (BAIL-03)', () => {
  if (!buildSendPayload) throw new Error('NOT_IMPLEMENTED: lib/send_payload.js missing (Wave 0 RED state)');
  const buf = Buffer.from([0x00, 0x00]);
  const result = buildSendPayload('video', buf, { caption: 'clip', mimetype: 'video/mp4' });
  assert.deepEqual(result, { video: buf, caption: 'clip', mimetype: 'video/mp4' });
});
