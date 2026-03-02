'use strict';

// baileys-bridge/index.js
// CommonJS Node.js Express + Baileys WhatsApp bridge microservice for Synapse-OSS.
// Exposes REST endpoints for outbound messages; forwards inbound messages to Python webhook.
// Node.js 18+ required (uses built-in global fetch, not node-fetch npm).

const express = require('express');
const NodeCache = require('node-cache');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
} = require('@whiskeysockets/baileys');
const writeFileAtomic = require('write-file-atomic');
const qrcode = require('qrcode-terminal');
const pino = require('pino');
const path = require('path');
const fs = require('fs');

// ---------------------------------------------------------------------------
// Configuration from environment
// ---------------------------------------------------------------------------
const PORT = parseInt(process.env.BRIDGE_PORT || '5010', 10);
const PYTHON_WEBHOOK_URL =
  process.env.PYTHON_WEBHOOK_URL ||
  'http://127.0.0.1:8000/channels/whatsapp/webhook';

// ---------------------------------------------------------------------------
// Group metadata cache — prevents WhatsApp spam detection (WA-05)
// stdTTL: 300s (5 min); useClones: false avoids deep-copy overhead
// ---------------------------------------------------------------------------
const groupCache = new NodeCache({ stdTTL: 300, useClones: false });

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------
/** @type {import('@whiskeysockets/baileys').WASocket | null} */
let sock = null;
let qrData = null;
let connectionState = 'disconnected'; // 'disconnected' | 'awaiting_qr' | 'connected' | 'reconnecting' | 'logged_out'

// ---------------------------------------------------------------------------
// atomicSaveCreds — WA-04: write auth state atomically to survive SIGKILL
// ---------------------------------------------------------------------------
async function atomicSaveCreds(creds) {
  const authDir = path.resolve('./auth_state');
  const bakDir = path.resolve('./auth_state.bak');

  // Write creds JSON atomically (tmp + rename)
  const credsPath = path.join(authDir, 'creds.json');
  await writeFileAtomic(credsPath, JSON.stringify(creds, null, 2));

  // Rolling backup: copy auth_state/ → auth_state.bak/ after each successful write
  try {
    fs.cpSync(authDir, bakDir, { recursive: true, force: true });
  } catch (err) {
    console.warn('[BRIDGE] auth_state backup failed (non-fatal):', err.message);
  }
}

// ---------------------------------------------------------------------------
// forwardToFastAPI — POST inbound message payload to Python webhook
// Uses Node 18+ built-in global fetch(); no node-fetch npm needed (WA-08)
// ---------------------------------------------------------------------------
async function forwardToFastAPI(payload) {
  try {
    const res = await fetch(PYTHON_WEBHOOK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) {
      console.error('[BRIDGE] Webhook POST failed:', res.status);
    }
  } catch (err) {
    console.error('[BRIDGE] Webhook POST error:', err.message);
  }
}

// ---------------------------------------------------------------------------
// extractPayload — normalise a Baileys message into the Synapse channel schema
// ---------------------------------------------------------------------------
function extractPayload(msg) {
  const isGroup = msg.key.remoteJid.endsWith('@g.us');
  const userId = isGroup
    ? (msg.key.participant || msg.pushName || msg.key.remoteJid)
    : msg.key.remoteJid;
  const text =
    msg.message?.conversation ||
    msg.message?.extendedTextMessage?.text ||
    msg.message?.imageMessage?.caption ||
    msg.message?.videoMessage?.caption ||
    '';

  return {
    channel_id: 'whatsapp',
    user_id: userId,
    chat_id: msg.key.remoteJid,
    text,
    message_id: msg.key.id,
    is_group: isGroup,
    timestamp: msg.messageTimestamp
      ? Number(msg.messageTimestamp)
      : Math.floor(Date.now() / 1000),
    raw: msg,
  };
}

// ---------------------------------------------------------------------------
// startSocket — create/recreate Baileys socket (Express server is NOT restarted)
// ---------------------------------------------------------------------------
async function startSocket() {
  const authDir = path.resolve('./auth_state');
  fs.mkdirSync(authDir, { recursive: true });

  const { state, saveCreds } = await useMultiFileAuthState(authDir);

  // Atomic credentials wrapper: intercepts creds.update to use writeFileAtomic
  const atomicSaveCredsWrapper = async () => {
    // First let Baileys write through its default saveCreds so state is updated
    await saveCreds();
    // Then additionally write creds.json atomically and back up the directory
    await atomicSaveCreds(state.creds);
  };

  sock = makeWASocket({
    auth: state,
    logger: pino({ level: 'silent' }),
    printQRInTerminal: false,           // serve QR via GET /qr ourselves; qrcode-terminal below for convenience
    cachedGroupMetadata: async (jid) => groupCache.get(jid), // WA-05 anti-spam
    markOnlineOnConnect: false,         // reduce detection surface
  });

  // Persist credentials on every update
  sock.ev.on('creds.update', atomicSaveCredsWrapper);

  // Keep group metadata cache fresh (WA-05)
  sock.ev.on('groups.update', async ([event]) => {
    try {
      const meta = await sock.groupMetadata(event.id);
      groupCache.set(event.id, meta);
    } catch (_) { /* non-fatal */ }
  });

  sock.ev.on('group-participants.update', async (event) => {
    try {
      const meta = await sock.groupMetadata(event.id);
      groupCache.set(event.id, meta);
    } catch (_) { /* non-fatal */ }
  });

  // Handle connection lifecycle
  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      qrData = qr;
      connectionState = 'awaiting_qr';
      // Print to terminal for convenience; QR also available via GET /qr
      qrcode.generate(qr, { small: true });
      console.log('[BRIDGE] QR ready — scan with WhatsApp or call GET /qr');
    }

    if (connection === 'open') {
      qrData = null;
      connectionState = 'connected';
      console.log('[BRIDGE] Connected to WhatsApp');
    }

    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      // CRITICAL: do NOT reconnect on logout (401) or forbidden (403) — loops + risks ban
      if (
        code === DisconnectReason.loggedOut ||
        code === DisconnectReason.forbidden
      ) {
        connectionState = 'logged_out';
        console.error(
          '[BRIDGE] CRITICAL: Session invalidated (code=%d) — manual QR re-scan required. NOT reconnecting.',
          code
        );
      } else {
        // Transient disconnect — restart socket (not Express) to reconnect
        connectionState = 'reconnecting';
        console.warn('[BRIDGE] Connection closed (code=%d), restarting socket…', code);
        startSocket().catch((err) =>
          console.error('[BRIDGE] startSocket restart error:', err.message)
        );
      }
    }
  });

  // Forward inbound messages to Python
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return; // skip history sync
    for (const msg of messages) {
      if (!msg.message || msg.key.fromMe) continue; // skip own + empty
      const payload = extractPayload(msg);
      await forwardToFastAPI(payload);
    }
  });
}

// ---------------------------------------------------------------------------
// Express HTTP server
// ---------------------------------------------------------------------------
const app = express();
app.use(express.json());

// POST /send — outbound message with anti-spam jitter (1–3s)
app.post('/send', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid, text } = req.body;
  if (!jid || !text) {
    return res.status(400).json({ error: 'jid and text are required' });
  }
  try {
    // Anti-spam jitter: 1000–3000ms delay before each outbound send
    await new Promise((r) => setTimeout(r, 1000 + Math.random() * 2000));
    await sock.sendMessage(jid, { text });
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /typing — send composing presence
app.post('/typing', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid } = req.body;
  if (!jid) return res.status(400).json({ error: 'jid is required' });
  try {
    await sock.sendPresenceUpdate('composing', jid);
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /seen — mark messages as read
app.post('/seen', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid, messageId, fromMe = false, participant } = req.body;
  if (!jid || !messageId) {
    return res.status(400).json({ error: 'jid and messageId are required' });
  }
  try {
    await sock.readMessages([
      { remoteJid: jid, id: messageId, fromMe, participant },
    ]);
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /health — bridge liveness + connection state
app.get('/health', (req, res) => {
  res.json({
    status: connectionState === 'connected' ? 'ok' : 'degraded',
    connectionState,
    pid: process.pid,
  });
});

// GET /qr — serve raw QR string for onboarding wizard (WA-07)
app.get('/qr', (req, res) => {
  if (!qrData) {
    return res.status(404).json({
      error: 'No QR available — already authenticated or bridge not started',
    });
  }
  res.json({ qr: qrData });
});

// ---------------------------------------------------------------------------
// Start server then socket
// ---------------------------------------------------------------------------
app.listen(PORT, () => {
  console.log(`[BRIDGE] Express listening on port ${PORT}`);
  console.log(`[BRIDGE] Forwarding inbound messages to ${PYTHON_WEBHOOK_URL}`);
});

startSocket().catch((err) => {
  console.error('[BRIDGE] Fatal startup error:', err.message);
  process.exit(1);
});
