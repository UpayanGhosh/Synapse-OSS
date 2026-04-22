'use strict';
const test = require('node:test');
const assert = require('node:assert');

// In Wave 0, index.js has no extractPayload export.
// Plan 05 (15-05) Task 1 adds:
//   if (require.main !== module) module.exports = { extractPayload };
// wrapped in a require.main !== module guard so index.js still runs standalone.
// Until then, extractPayload is undefined and every test fails RED.
let extractPayload;
try {
  ({ extractPayload } = require('../index.js'));
} catch {
  // index.js may throw on startup (missing env, Baileys connect attempt) — RED state
}

test('PN sender leaves user_id_alt null on DM (BAIL-04 6.x shape)', async () => {
  if (!extractPayload) throw new Error('NOT_IMPLEMENTED: extractPayload not exported from index.js (Wave 0 RED)');
  const msg = {
    key: { remoteJid: '1234567890@s.whatsapp.net', fromMe: false, id: 'M1' },
    message: { conversation: 'hi' },
    messageTimestamp: 100,
  };
  const p = await extractPayload(msg);
  assert.equal(p.user_id, '1234567890@s.whatsapp.net');
  assert.equal(p.user_id_alt, null);
  assert.equal(p.is_group, false);
});

test('LID peer populates user_id_alt on DM (BAIL-04 7.x shape)', async () => {
  if (!extractPayload) throw new Error('NOT_IMPLEMENTED: extractPayload not exported from index.js (Wave 0 RED)');
  const msg = {
    key: {
      remoteJid: '1234567890@lid',
      remoteJidAlt: '919876543210@s.whatsapp.net',
      fromMe: false,
      id: 'M2',
    },
    message: { conversation: 'hi' },
    messageTimestamp: 200,
  };
  const p = await extractPayload(msg);
  assert.equal(p.user_id, '1234567890@lid');
  assert.equal(p.user_id_alt, '919876543210@s.whatsapp.net');
  assert.equal(p.is_group, false);
});

test('LID participant populates user_id_alt in group (BAIL-04)', async () => {
  if (!extractPayload) throw new Error('NOT_IMPLEMENTED: extractPayload not exported from index.js (Wave 0 RED)');
  const msg = {
    key: {
      remoteJid: 'GROUP@g.us',
      participant: '1234567890@lid',
      participantAlt: '919876543210@s.whatsapp.net',
      fromMe: false,
      id: 'M3',
    },
    message: { conversation: 'gm' },
    messageTimestamp: 300,
  };
  const p = await extractPayload(msg);
  assert.equal(p.user_id, '1234567890@lid');
  assert.equal(p.user_id_alt, '919876543210@s.whatsapp.net');
  assert.equal(p.is_group, true);
});

test('PN participant leaves user_id_alt null in group (BAIL-04 6.x shape)', async () => {
  if (!extractPayload) throw new Error('NOT_IMPLEMENTED: extractPayload not exported from index.js (Wave 0 RED)');
  const msg = {
    key: {
      remoteJid: 'GROUP@g.us',
      participant: '1234567890@s.whatsapp.net',
      fromMe: false,
      id: 'M4',
    },
    message: { conversation: 'gm' },
    messageTimestamp: 400,
  };
  const p = await extractPayload(msg);
  assert.equal(p.user_id, '1234567890@s.whatsapp.net');
  assert.equal(p.user_id_alt, null);
  assert.equal(p.is_group, true);
});
