'use strict';
// Baileys 7.x AnyMediaMessageContent shape builder.
// Pure function — no I/O, no Baileys dep.

const DEFAULT_VOICE_MIMETYPE = 'audio/ogg; codecs=opus';
const DEFAULT_STICKER_MIMETYPE = 'image/webp';

/**
 * @param {string} mediaType — 'text' | 'image' | 'audio' | 'video' | 'document' | 'sticker' | 'voice'
 * @param {Buffer|null} buffer — binary content, null for text.
 * @param {object} [opts={}] — { text, caption, mimetype, fileName, gifPlayback, ptt }
 * @returns {object}
 * @throws {TypeError} if mediaType invalid or buffer missing when required.
 */
function buildSendPayload(mediaType, buffer, opts = {}) {
  if (typeof mediaType !== 'string' || !mediaType) {
    throw new TypeError('buildSendPayload: mediaType must be a non-empty string');
  }

  if (mediaType === 'text') {
    if (typeof opts.text !== 'string') {
      throw new TypeError('buildSendPayload: text requires opts.text string');
    }
    return { text: opts.text };
  }

  if (!Buffer.isBuffer(buffer)) {
    throw new TypeError(`buildSendPayload: ${mediaType} requires a Buffer (got ${typeof buffer})`);
  }

  if (mediaType === 'voice') {
    return { audio: buffer, ptt: true, mimetype: DEFAULT_VOICE_MIMETYPE };
  }

  if (mediaType === 'image') {
    const out = { image: buffer };
    if (opts.caption) out.caption = opts.caption;
    if (opts.mimetype) out.mimetype = opts.mimetype;
    return out;
  }

  if (mediaType === 'audio') {
    const out = { audio: buffer };
    if (opts.mimetype) out.mimetype = opts.mimetype;
    if (opts.ptt === true) out.ptt = true;
    return out;
  }

  if (mediaType === 'video') {
    const out = { video: buffer };
    if (opts.caption) out.caption = opts.caption;
    if (opts.mimetype) out.mimetype = opts.mimetype;
    if (opts.gifPlayback === true) out.gifPlayback = true;
    return out;
  }

  if (mediaType === 'document') {
    const out = { document: buffer };
    if (opts.fileName) out.fileName = opts.fileName;
    if (opts.caption) out.caption = opts.caption;
    if (opts.mimetype) out.mimetype = opts.mimetype;
    return out;
  }

  if (mediaType === 'sticker') {
    return { sticker: buffer, mimetype: opts.mimetype || DEFAULT_STICKER_MIMETYPE };
  }

  throw new TypeError(`buildSendPayload: unknown mediaType "${mediaType}"`);
}

module.exports = { buildSendPayload, DEFAULT_VOICE_MIMETYPE, DEFAULT_STICKER_MIMETYPE };
