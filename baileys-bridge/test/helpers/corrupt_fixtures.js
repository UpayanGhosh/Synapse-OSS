'use strict';
const fs = require('node:fs');
const path = require('node:path');

/**
 * Writes a valid JSON creds.json to the given auth directory.
 * @param {string} dir - path to auth directory
 * @param {object} obj - creds object to serialise (default has noiseKey + counter)
 */
function writeValidCreds(dir, obj = { noiseKey: 'test', counter: 0 }) {
  fs.writeFileSync(path.join(dir, 'creds.json'), JSON.stringify(obj));
}

/**
 * Writes a deliberately corrupt (non-parseable) creds.json to the given auth directory.
 * @param {string} dir - path to auth directory
 */
function writeCorruptCreds(dir) {
  fs.writeFileSync(path.join(dir, 'creds.json'), '{truncated-JSON');
}

/**
 * Writes a valid JSON creds.json.bak to the given auth directory.
 * @param {string} dir - path to auth directory
 * @param {object} obj - backup object to serialise
 */
function writeValidBackup(dir, obj = { noiseKey: 'protected' }) {
  fs.writeFileSync(path.join(dir, 'creds.json.bak'), JSON.stringify(obj));
}

/**
 * Writes a deliberately corrupt (non-parseable) creds.json.bak to the given auth directory.
 * @param {string} dir - path to auth directory
 */
function writeCorruptBackup(dir) {
  fs.writeFileSync(path.join(dir, 'creds.json.bak'), '{truncated-JSON');
}

module.exports = { writeValidCreds, writeCorruptCreds, writeValidBackup, writeCorruptBackup };
