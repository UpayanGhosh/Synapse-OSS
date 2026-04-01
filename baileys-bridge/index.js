'use strict';

// baileys-bridge/index.js
// CommonJS Node.js Express + Baileys WhatsApp bridge microservice for Synapse-OSS.
// Exposes REST endpoints for outbound messages, media, reactions, group management,
// session control (logout/relink), and connection monitoring.
// Node.js 18+ required (uses built-in global fetch, not node-fetch npm).

const express = require('express');
const NodeCache = require('node-cache');
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
} = require('@whiskeysockets/baileys');
const writeFileAtomic = require('write-file-atomic');
const pino = require('pino');
const qrcodeTerminal = require('qrcode-terminal');
const path = require('path');
const fs = require('fs');

// ---------------------------------------------------------------------------
// Configuration from environment
// ---------------------------------------------------------------------------
const PORT = parseInt(process.env.BRIDGE_PORT || '5010', 10);
const PYTHON_WEBHOOK_URL =
  process.env.PYTHON_WEBHOOK_URL ||
  'http://127.0.0.1:8000/channels/whatsapp/webhook';
const PYTHON_STATE_WEBHOOK_URL =
  process.env.PYTHON_STATE_WEBHOOK_URL ||
  PYTHON_WEBHOOK_URL.replace('/webhook', '/connection-state');
const MEDIA_CACHE_DIR = path.resolve(process.env.MEDIA_CACHE_DIR || './media_cache');
const MEDIA_CACHE_TTL_MS = parseInt(process.env.MEDIA_CACHE_TTL_MINUTES || '60', 10) * 60 * 1000;
const AUTH_DIR = path.resolve('./auth_state');
const AUTH_BAK_DIR = path.resolve('./auth_state.bak');
const AUTH_META_FILE = path.join(AUTH_DIR, 'meta.json');

// ---------------------------------------------------------------------------
// Group metadata cache — prevents WhatsApp spam detection (WA-05)
// stdTTL: 300s (5 min); useClones: false avoids deep-copy overhead
// ---------------------------------------------------------------------------
const groupCache = new NodeCache({ stdTTL: 300, useClones: false });

// ---------------------------------------------------------------------------
// Media cache dir setup + hourly cleanup
// ---------------------------------------------------------------------------
fs.mkdirSync(MEDIA_CACHE_DIR, { recursive: true });

setInterval(() => {
  try {
    const now = Date.now();
    for (const file of fs.readdirSync(MEDIA_CACHE_DIR)) {
      const filePath = path.join(MEDIA_CACHE_DIR, file);
      const stat = fs.statSync(filePath);
      if (now - stat.mtimeMs > MEDIA_CACHE_TTL_MS) {
        fs.rmSync(filePath, { force: true });
      }
    }
  } catch (err) {
    console.warn('[BRIDGE] Media cache cleanup error (non-fatal):', err.message);
  }
}, 60 * 60 * 1000); // every hour

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------
/** @type {import('@whiskeysockets/baileys').WASocket | null} */
let sock = null;
let baileysVersion = null; // fetched once; reused on reconnects
let qrData = null;
let connectionState = 'disconnected';
let connectedSince = null;       // ISO string — when session last connected
let authTimestamp = null;         // ISO string — when account was first authenticated
let restartCount = 0;
let lastDisconnectReason = null;

// Load persisted authTimestamp from meta.json if it exists
try {
  if (fs.existsSync(AUTH_META_FILE)) {
    const meta = JSON.parse(fs.readFileSync(AUTH_META_FILE, 'utf8'));
    authTimestamp = meta.authTimestamp || null;
  }
} catch (_) {}

// ---------------------------------------------------------------------------
// notifyStateChange — fire-and-forget POST to Python connection-state webhook
// ---------------------------------------------------------------------------
function notifyStateChange(state) {
  fetch(PYTHON_STATE_WEBHOOK_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      connectionState: state,
      connectedSince,
      authTimestamp,
      pid: process.pid,
      restartCount,
      lastDisconnectReason,
    }),
    signal: AbortSignal.timeout(3000),
  }).catch(() => {}); // fire-and-forget — never crash on webhook failure
}

// ---------------------------------------------------------------------------
// atomicSaveCreds — WA-04: write auth state atomically to survive SIGKILL
// ---------------------------------------------------------------------------
async function atomicSaveCreds(creds) {
  fs.mkdirSync(AUTH_DIR, { recursive: true });
  const credsPath = path.join(AUTH_DIR, 'creds.json');
  await writeFileAtomic(credsPath, JSON.stringify(creds, null, 2));

  // Rolling backup
  try {
    fs.cpSync(AUTH_DIR, AUTH_BAK_DIR, { recursive: true, force: true });
  } catch (err) {
    console.warn('[BRIDGE] auth_state backup failed (non-fatal):', err.message);
  }
}

// ---------------------------------------------------------------------------
// forwardToFastAPI — POST inbound event payload to Python webhook
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
// MIME → extension helper
// ---------------------------------------------------------------------------
const MIME_EXT = {
  'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif',
  'video/mp4': 'mp4', 'video/3gpp': '3gp',
  'audio/ogg': 'ogg', 'audio/mpeg': 'mp3', 'audio/mp4': 'm4a',
  'application/pdf': 'pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': 'xlsx',
};

function mimeToExt(mime) {
  return MIME_EXT[mime] || 'bin';
}

// ---------------------------------------------------------------------------
// extractPayload — normalise a Baileys message into the Synapse channel schema
// Handles text, media (image/video/audio/document/sticker), and reactions
// ---------------------------------------------------------------------------
async function extractPayload(msg) {
  const isGroup = msg.key.remoteJid.endsWith('@g.us');
  const userId = isGroup
    ? (msg.key.participant || msg.pushName || msg.key.remoteJid)
    : msg.key.remoteJid;

  // Detect message type
  const msgContent = msg.message || {};
  const text =
    msgContent.conversation ||
    msgContent.extendedTextMessage?.text ||
    msgContent.imageMessage?.caption ||
    msgContent.videoMessage?.caption ||
    msgContent.documentMessage?.caption ||
    '';

  // Reaction detection
  if (msgContent.reactionMessage) {
    return {
      type: 'reaction',
      channel_id: 'whatsapp',
      user_id: userId,
      chat_id: msg.key.remoteJid,
      message_id: msg.key.id,
      reaction_emoji: msgContent.reactionMessage.text || '',
      reacted_to_id: msgContent.reactionMessage.key?.id || '',
      timestamp: msg.messageTimestamp ? Number(msg.messageTimestamp) : Math.floor(Date.now() / 1000),
    };
  }

  const payload = {
    type: 'message',
    channel_id: 'whatsapp',
    user_id: userId,
    chat_id: msg.key.remoteJid,
    text,
    message_id: msg.key.id,
    is_group: isGroup,
    timestamp: msg.messageTimestamp ? Number(msg.messageTimestamp) : Math.floor(Date.now() / 1000),
    raw: msg,
  };

  // Media detection and download
  const mediaTypes = {
    imageMessage: { type: 'image', mime: msgContent.imageMessage?.mimetype },
    videoMessage: { type: 'video', mime: msgContent.videoMessage?.mimetype },
    audioMessage: { type: 'audio', mime: msgContent.audioMessage?.mimetype },
    documentMessage: { type: 'document', mime: msgContent.documentMessage?.mimetype },
    stickerMessage: { type: 'sticker', mime: msgContent.stickerMessage?.mimetype || 'image/webp' },
  };

  for (const [msgKey, meta] of Object.entries(mediaTypes)) {
    if (msgContent[msgKey]) {
      try {
        const buffer = await downloadMediaMessage(msg, 'buffer', {});
        const ext = mimeToExt(meta.mime || '');
        const fileName = `${msg.key.id}.${ext}`;
        const filePath = path.join(MEDIA_CACHE_DIR, fileName);
        fs.writeFileSync(filePath, buffer);
        payload.mediaType = meta.type;
        payload.mediaUrl = `http://127.0.0.1:${PORT}/media/${fileName}`;
        payload.mediaMimeType = meta.mime || '';
        payload.mediaCaption = text;
      } catch (err) {
        console.warn('[BRIDGE] Media download failed (non-fatal):', err.message);
      }
      break;
    }
  }

  return payload;
}

// ---------------------------------------------------------------------------
// startSocket — create/recreate Baileys socket
// ---------------------------------------------------------------------------
async function startSocket() {
  fs.mkdirSync(AUTH_DIR, { recursive: true });

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  if (!baileysVersion) {
    try {
      const result = await fetchLatestBaileysVersion();
      baileysVersion = result.version;
    } catch (err) {
      console.warn('[BRIDGE] fetchLatestBaileysVersion failed, using fallback:', err.message);
      baileysVersion = [2, 3000, 1035194821];
    }
  }

  const atomicSaveCredsWrapper = async () => {
    await saveCreds();
    await atomicSaveCreds(state.creds);
  };

  sock = makeWASocket({
    version: baileysVersion,
    auth: state,
    logger: pino({ level: 'silent' }),
    browser: ['Synapse', 'Chrome', '1.0.0'],
    cachedGroupMetadata: async (jid) => groupCache.get(jid),
    markOnlineOnConnect: false,
  });

  sock.ev.on('creds.update', atomicSaveCredsWrapper);

  sock.ev.on('groups.update', async ([event]) => {
    try {
      const meta = await sock.groupMetadata(event.id);
      groupCache.set(event.id, meta);
    } catch (_) {}
  });

  sock.ev.on('group-participants.update', async (event) => {
    try {
      const meta = await sock.groupMetadata(event.id);
      groupCache.set(event.id, meta);
    } catch (_) {}
  });

  // Connection lifecycle
  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      qrData = qr;
      connectionState = 'awaiting_qr';
      console.log('[BRIDGE] QR ready — scan with WhatsApp');
      qrcodeTerminal.generate(qr, { small: true });
      notifyStateChange('awaiting_qr');
    }

    if (connection === 'open') {
      qrData = null;
      connectionState = 'connected';
      connectedSince = new Date().toISOString();
      restartCount = 0;

      // Persist authTimestamp on first successful connection
      if (!authTimestamp) {
        authTimestamp = connectedSince;
        try {
          fs.mkdirSync(AUTH_DIR, { recursive: true });
          fs.writeFileSync(AUTH_META_FILE, JSON.stringify({ authTimestamp }));
        } catch (_) {}
      }

      console.log('[BRIDGE] Connected to WhatsApp');
      notifyStateChange('connected');
    }

    if (connection === 'close') {
      const code = lastDisconnect?.error?.output?.statusCode;
      lastDisconnectReason = String(code || 'unknown');
      connectedSince = null;

      if (
        code === DisconnectReason.loggedOut ||
        code === DisconnectReason.forbidden
      ) {
        connectionState = 'logged_out';
        console.error('[BRIDGE] Session invalidated (code=%d) — manual QR re-scan required.', code);
        notifyStateChange('logged_out');
      } else {
        connectionState = 'reconnecting';
        restartCount++;
        console.warn('[BRIDGE] Connection closed (code=%d), restarting socket…', code);
        notifyStateChange('reconnecting');
        startSocket().catch((err) =>
          console.error('[BRIDGE] startSocket restart error:', err.message)
        );
      }
    }
  });

  // Delivery/read receipts
  sock.ev.on('message-receipt.update', (updates) => {
    for (const { key, receipt } of updates) {
      const status = receipt.readTimestamp ? 'read'
        : receipt.receiptTimestamp ? 'delivered'
        : 'sent';
      forwardToFastAPI({
        type: 'message_status',
        channel_id: 'whatsapp',
        message_id: key.id,
        chat_id: key.remoteJid,
        status,
        timestamp: Math.floor(Date.now() / 1000),
      });
    }
  });

  // Incoming typing indicators
  sock.ev.on('presence.update', ({ id, presences }) => {
    for (const [jid, presence] of Object.entries(presences)) {
      if (presence.lastKnownPresence === 'composing') {
        forwardToFastAPI({
          type: 'typing_indicator',
          channel_id: 'whatsapp',
          chat_id: id,
          user_id: jid,
          timestamp: Math.floor(Date.now() / 1000),
        });
      }
    }
  });

  // Inbound messages
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return;
    for (const msg of messages) {
      if (!msg.message || msg.key.fromMe) continue;
      const payload = await extractPayload(msg);
      await forwardToFastAPI(payload);
    }
  });
}

// ---------------------------------------------------------------------------
// Express HTTP server
// ---------------------------------------------------------------------------
const app = express();
app.use(express.json());

// Static media file serving
app.use('/media', express.static(MEDIA_CACHE_DIR));

// ---------------------------------------------------------------------------
// Messaging endpoints
// ---------------------------------------------------------------------------

// POST /send — outbound message (text or media)
app.post('/send', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid, text, mediaUrl, mediaType, caption } = req.body;
  if (!jid) {
    return res.status(400).json({ error: 'jid is required' });
  }

  try {
    await new Promise((r) => setTimeout(r, 1000 + Math.random() * 2000)); // anti-spam jitter

    let sentMsg;
    if (mediaUrl) {
      // Media send
      const mediaTypeKey = mediaType || 'image';
      const response = await fetch(mediaUrl, { signal: AbortSignal.timeout(30000) });
      if (!response.ok) {
        return res.status(400).json({ error: `Failed to fetch media from URL: ${response.status}` });
      }
      const buffer = Buffer.from(await response.arrayBuffer());
      const messageContent = { [mediaTypeKey]: buffer };
      if (caption) messageContent.caption = caption;
      sentMsg = await sock.sendMessage(jid, messageContent);
    } else if (text) {
      sentMsg = await sock.sendMessage(jid, { text });
    } else {
      return res.status(400).json({ error: 'text or mediaUrl is required' });
    }

    res.json({ ok: true, messageId: sentMsg?.key?.id || null });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /react — send emoji reaction to a message
app.post('/react', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid, messageId, reaction } = req.body;
  if (!jid || !messageId) {
    return res.status(400).json({ error: 'jid and messageId are required' });
  }
  try {
    await sock.sendMessage(jid, {
      react: { text: reaction || '', key: { remoteJid: jid, id: messageId } },
    });
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
    await sock.readMessages([{ remoteJid: jid, id: messageId, fromMe, participant }]);
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
// Session management endpoints
// ---------------------------------------------------------------------------

// POST /logout — deregister linked device + wipe auth_state
app.post('/logout', async (req, res) => {
  if (sock) {
    try { await sock.logout(); } catch (_) {}
  }
  fs.rmSync(AUTH_DIR, { recursive: true, force: true });
  fs.rmSync(AUTH_BAK_DIR, { recursive: true, force: true });
  connectionState = 'logged_out';
  qrData = null;
  connectedSince = null;
  authTimestamp = null;
  sock = null;
  notifyStateChange('logged_out');
  res.json({ ok: true, message: 'Logged out and session cleared' });
});

// POST /relink — wipe creds and restart socket for fresh QR
app.post('/relink', async (req, res) => {
  if (sock) {
    try { sock.end(undefined); } catch (_) {}
  }
  fs.rmSync(AUTH_DIR, { recursive: true, force: true });
  fs.rmSync(AUTH_BAK_DIR, { recursive: true, force: true });
  connectionState = 'disconnected';
  qrData = null;
  connectedSince = null;
  authTimestamp = null;
  sock = null;
  startSocket().catch((err) => console.error('[BRIDGE] relink error:', err.message));
  notifyStateChange('disconnected');
  res.json({ ok: true, message: 'Restarting socket — poll GET /qr for new QR' });
});

// ---------------------------------------------------------------------------
// Health and QR endpoints
// ---------------------------------------------------------------------------

// GET /health — bridge liveness + connection state + metrics
app.get('/health', (req, res) => {
  const uptimeSeconds = connectedSince
    ? (Date.now() - new Date(connectedSince).getTime()) / 1000
    : 0;
  res.json({
    status: connectionState === 'connected' ? 'ok' : 'degraded',
    connectionState,
    pid: process.pid,
    connectedSince,
    authTimestamp,
    uptimeSeconds: Math.floor(uptimeSeconds),
    restartCount,
    lastDisconnectReason,
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
// Group management endpoints
// ---------------------------------------------------------------------------

// POST /groups/create — { subject, participants: [jid, ...] }
app.post('/groups/create', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { subject, participants } = req.body;
  if (!subject || !Array.isArray(participants)) {
    return res.status(400).json({ error: 'subject and participants[] are required' });
  }
  try {
    const result = await sock.groupCreate(subject, participants);
    res.json({ ok: true, jid: result.gid || result.id, result });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /groups/invite — { jid, participants: [jid, ...] }
app.post('/groups/invite', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid, participants } = req.body;
  if (!jid || !Array.isArray(participants)) {
    return res.status(400).json({ error: 'jid and participants[] are required' });
  }
  try {
    await sock.groupParticipantsUpdate(jid, participants, 'add');
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /groups/leave — { jid }
app.post('/groups/leave', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid } = req.body;
  if (!jid) return res.status(400).json({ error: 'jid is required' });
  try {
    await sock.groupLeave(jid);
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// POST /groups/update — { jid, subject }
app.post('/groups/update', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid, subject } = req.body;
  if (!jid || !subject) return res.status(400).json({ error: 'jid and subject are required' });
  try {
    await sock.groupUpdateSubject(jid, subject);
    res.json({ ok: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// GET /groups/:jid — get group metadata (cache-first)
app.get('/groups/:jid', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid } = req.params;
  try {
    const cached = groupCache.get(jid);
    if (cached) return res.json(cached);
    const meta = await sock.groupMetadata(jid);
    groupCache.set(jid, meta);
    res.json(meta);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
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
