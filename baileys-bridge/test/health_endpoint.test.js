'use strict';
/**
 * Phase 16 BRIDGE-01 — RED test stubs for /health endpoint augmentation.
 *
 * The bridge index.js currently returns 8 fields. Phase 16 requires 4 new fields:
 *   - last_inbound_at (ISO8601 string | null)
 *   - last_outbound_at (ISO8601 string | null)
 *   - uptime_ms (integer)
 *   - bridge_version (string from package.json)
 *
 * Plan 01 Task 1 adds:
 *   1. `START_BRIDGE_SOCKET !== 'false'` guard around sock startup so tests can require index.js
 *   2. module.exports = { app, __testTriggerInbound, __testTriggerOutbound } for test-only access
 *   3. The 4 new fields injected into GET /health response
 *
 * Wave 0: all 4 tests FAIL RED (fields missing or file cannot be imported safely).
 */

const test = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const path = require('node:path');

// Guard: prevent index.js from opening a real Baileys socket during test import.
// Plan 01 Task 1 wraps startSocket() behind `if (process.env.START_BRIDGE_SOCKET !== 'false')`.
process.env.START_BRIDGE_SOCKET = 'false';
process.env.BRIDGE_PORT = '0';   // let Node pick a free port

// The require below will throw RED in Wave 0 because:
//   (a) index.js starts startSocket() unconditionally (no START_BRIDGE_SOCKET guard yet)
//   (b) module.exports = { app, ... } does not yet exist
// Plan 01 Task 1 fixes both.
const bridgeModule = require('../index.js');

function requestHealth(app) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(app);
    server.listen(0, () => {
      const { port } = server.address();
      http.get(`http://127.0.0.1:${port}/health`, (res) => {
        let body = '';
        res.on('data', (c) => { body += c; });
        res.on('end', () => {
          server.close();
          try { resolve({ status: res.statusCode, body: JSON.parse(body) }); }
          catch (e) { reject(e); }
        });
      }).on('error', (e) => { server.close(); reject(e); });
    });
  });
}

test('GET /health returns 4 new Phase 16 fields (BRIDGE-01)', async () => {
  const { app } = bridgeModule;
  assert.ok(app, 'index.js must export { app } for tests');
  const { status, body } = await requestHealth(app);
  assert.equal(status, 200);
  assert.ok('last_inbound_at' in body, 'last_inbound_at missing from /health');
  assert.ok('last_outbound_at' in body, 'last_outbound_at missing from /health');
  assert.ok('uptime_ms' in body, 'uptime_ms missing from /health');
  assert.ok('bridge_version' in body, 'bridge_version missing from /health');
});

test('last_inbound_at updates when messages.upsert fires (BRIDGE-01)', async () => {
  const { app, __testTriggerInbound } = bridgeModule;
  assert.ok(__testTriggerInbound, 'index.js must export __testTriggerInbound for tests');
  // Before trigger: last_inbound_at may be null
  // After trigger: last_inbound_at is a valid ISO8601 string
  __testTriggerInbound();
  const { body } = await requestHealth(app);
  assert.notEqual(body.last_inbound_at, null, 'last_inbound_at should be set after inbound event');
  // Must be ISO8601 parseable
  const t = Date.parse(body.last_inbound_at);
  assert.ok(!Number.isNaN(t), `last_inbound_at=${body.last_inbound_at} is not valid ISO8601`);
  assert.ok(Math.abs(Date.now() - t) < 5000, 'last_inbound_at must be recent (<5s)');
});

test('last_outbound_at updates when /send path succeeds (BRIDGE-01)', async () => {
  const { app, __testTriggerOutbound } = bridgeModule;
  assert.ok(__testTriggerOutbound, 'index.js must export __testTriggerOutbound for tests');
  __testTriggerOutbound();
  const { body } = await requestHealth(app);
  assert.notEqual(body.last_outbound_at, null, 'last_outbound_at should be set after outbound event');
  const t = Date.parse(body.last_outbound_at);
  assert.ok(!Number.isNaN(t), `last_outbound_at=${body.last_outbound_at} is not valid ISO8601`);
});

test('bridge_version matches package.json version (BRIDGE-01)', async () => {
  const { app } = bridgeModule;
  const pkg = require('../package.json');
  const { body } = await requestHealth(app);
  assert.equal(body.bridge_version, pkg.version,
    `bridge_version=${body.bridge_version} does not match package.json version=${pkg.version}`);
});
