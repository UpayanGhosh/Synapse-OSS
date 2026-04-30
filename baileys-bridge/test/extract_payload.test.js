'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { extractPayload, isAllowedOutboundMediaUrl } = require('../index.js');

test('PN sender leaves user_id_alt null on DM (BAIL-04 6.x shape)', async () => {
  const msg = {
    key: { remoteJid: '1234567890@s.whatsapp.net', fromMe: false, id: 'M1' },
    message: { conversation: 'hi' },
    messageTimestamp: 100,
  };
  const p = await extractPayload(msg);
  assert.equal(p.user_id, '1234567890@s.whatsapp.net');
  assert.equal(p.user_id_alt, null);
  assert.equal(p.is_group, false);
  assert.equal(p.text, 'hi');
});

test('LID peer populates user_id_alt on DM (BAIL-04 7.x shape)', async () => {
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
  assert.equal(p.chat_id, 'GROUP@g.us');
});

test('PN participant leaves user_id_alt null in group (BAIL-04 6.x shape)', async () => {
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

// Reaction path — exercises the second user_id_alt emission (index.js reaction branch)
test('LID sender reaction carries user_id_alt (BAIL-04 reaction path)', async () => {
  const msg = {
    key: {
      remoteJid: 'GROUP@g.us',
      participant: '111@lid',
      participantAlt: '919999999999@s.whatsapp.net',
      fromMe: false,
      id: 'M5',
    },
    message: {
      reactionMessage: { text: '👍', key: { remoteJid: 'GROUP@g.us', id: 'ORIG' } },
    },
    messageTimestamp: 500,
  };
  const p = await extractPayload(msg);
  assert.equal(p.type, 'reaction');
  assert.equal(p.user_id, '111@lid');
  assert.equal(p.user_id_alt, '919999999999@s.whatsapp.net');
  assert.equal(p.reaction_emoji, '👍');
});

// Edge case: no alt fields present on either branch → both null
test('no alt JIDs present → user_id_alt null on both DM and group (BAIL-04)', async () => {
  const dmMsg = {
    key: { remoteJid: '555@s.whatsapp.net', fromMe: false, id: 'M6' },
    message: { conversation: 'hey' },
    messageTimestamp: 600,
  };
  const dm = await extractPayload(dmMsg);
  assert.equal(dm.user_id_alt, null);

  const grpMsg = {
    key: { remoteJid: 'GRP@g.us', participant: '555@s.whatsapp.net', fromMe: false, id: 'M7' },
    message: { conversation: 'hey' },
    messageTimestamp: 700,
  };
  const grp = await extractPayload(grpMsg);
  assert.equal(grp.user_id_alt, null);
});

test('malformed messages without remoteJid are ignored safely', async () => {
  const msg = {
    key: { fromMe: false, id: 'BAD1' },
    message: { conversation: 'missing jid' },
    messageTimestamp: 800,
  };

  const p = await extractPayload(msg);

  assert.equal(p, null);
});

test('outbound media URL guard rejects private and non-http targets', () => {
  assert.equal(isAllowedOutboundMediaUrl('https://example.com/image.png'), true);
  assert.equal(isAllowedOutboundMediaUrl('http://127.0.0.1:8000/private.png'), false);
  assert.equal(isAllowedOutboundMediaUrl('http://10.0.0.4/private.png'), false);
  assert.equal(isAllowedOutboundMediaUrl('file:///C:/secret.txt'), false);
  assert.equal(isAllowedOutboundMediaUrl('not a url'), false);
});
