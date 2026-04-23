'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { buildSendPayload } = require('../lib/send_payload.js');

test('image payload includes mimetype (BAIL-03)', () => {
  const buf = Buffer.from([0xFF, 0xD8, 0xFF, 0xE0]);
  const result = buildSendPayload('image', buf, { caption: 'hi', mimetype: 'image/jpeg' });
  assert.deepEqual(result, { image: buf, caption: 'hi', mimetype: 'image/jpeg' });
});

test('voice note uses ptt:true + audio/ogg;codecs=opus (BAIL-03)', () => {
  const buf = Buffer.from([0x4F, 0x67, 0x67, 0x53]);
  const result = buildSendPayload('voice', buf, {});
  assert.deepEqual(result, { audio: buf, ptt: true, mimetype: 'audio/ogg; codecs=opus' });
});

test('document payload has fileName + mimetype (BAIL-03)', () => {
  const buf = Buffer.from([0x25, 0x50, 0x44, 0x46]);
  const result = buildSendPayload('document', buf, {
    fileName: 'report.pdf',
    caption: 'Q3 numbers',
    mimetype: 'application/pdf',
  });
  assert.deepEqual(result, {
    document: buf,
    fileName: 'report.pdf',
    caption: 'Q3 numbers',
    mimetype: 'application/pdf',
  });
});

test('video payload includes caption + optional gifPlayback (BAIL-03)', () => {
  const buf = Buffer.from([0x00, 0x00, 0x00, 0x18, 0x66, 0x74, 0x79, 0x70]);
  const normal = buildSendPayload('video', buf, { caption: 'clip', mimetype: 'video/mp4' });
  assert.deepEqual(normal, { video: buf, caption: 'clip', mimetype: 'video/mp4' });

  const gif = buildSendPayload('video', buf, { caption: 'gif', mimetype: 'video/mp4', gifPlayback: true });
  assert.deepEqual(gif, { video: buf, caption: 'gif', mimetype: 'video/mp4', gifPlayback: true });
});

test('text payload (BAIL-03 regression)', () => {
  assert.deepEqual(buildSendPayload('text', null, { text: 'hi' }), { text: 'hi' });
});

test('sticker default mimetype (BAIL-03 regression)', () => {
  const buf = Buffer.from([0x52, 0x49, 0x46, 0x46]);
  assert.deepEqual(buildSendPayload('sticker', buf, {}), { sticker: buf, mimetype: 'image/webp' });
});

test('audio non-PTT carries mimetype (BAIL-03 regression)', () => {
  const buf = Buffer.from([0xFF, 0xFB, 0x90, 0x00]); // MP3 frame sync
  const result = buildSendPayload('audio', buf, { mimetype: 'audio/mpeg' });
  assert.deepEqual(result, { audio: buf, mimetype: 'audio/mpeg' });
  assert.strictEqual('ptt' in result, false, 'ptt must not be present for non-voice audio');
});

test('image without optional fields emits only image key (BAIL-03 regression)', () => {
  const buf = Buffer.from([0xFF, 0xD8]);
  const result = buildSendPayload('image', buf, {});
  assert.deepEqual(result, { image: buf });
});

test('invalid mediaType throws TypeError', () => {
  assert.throws(() => buildSendPayload('unknown', Buffer.alloc(0), {}), TypeError);
});
