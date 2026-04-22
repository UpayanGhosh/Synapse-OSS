'use strict';
// Wave 0 skeleton. Implementations arrive in Plan 01 (15-01). Tests fail RED here.
const CREDS_SAVE_FLUSH_TIMEOUT_MS = 15000;

function enqueueSaveCreds(_authDir, _saveCreds) {
  throw new Error('NOT_IMPLEMENTED_WAVE_1');
}

async function safeSaveCreds(_authDir, _saveCreds) {
  throw new Error('NOT_IMPLEMENTED_WAVE_1');
}

async function waitForCredsSaveQueueWithTimeout(_authDir, _timeoutMs) {
  throw new Error('NOT_IMPLEMENTED_WAVE_1');
}

function __resetQueuesForTest() {
  /* stub — Wave 1 clears module-level Map here */
}

module.exports = {
  enqueueSaveCreds,
  safeSaveCreds,
  waitForCredsSaveQueueWithTimeout,
  __resetQueuesForTest,
  CREDS_SAVE_FLUSH_TIMEOUT_MS,
};
