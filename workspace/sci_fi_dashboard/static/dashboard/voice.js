/**
 * SynapseVoice — Browser-side voice module for Synapse dashboard
 *
 * Exposes window.SynapseVoice with:
 *   startVoice(ws)     — initialise VAD + AudioContext, begin mic capture
 *   stopVoice()        — tear down VAD, flush playback queue, release mic
 *   handleWSMessage(e) — route inbound binary (MP3) and JSON voice.* events
 *   getState()         — read-only snapshot of internal state
 *
 * CDN dependencies (must be loaded before this file):
 *   onnxruntime-web  1.22.0   https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/ort.wasm.min.js
 *   vad-web          0.0.29   https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/bundle.min.js
 *
 * Protocol (matches ws_server.py voice.* handlers):
 *   Outbound JSON  — voice.start, voice.stop, voice.barge_in (all have type:"req")
 *   Outbound binary — ArrayBuffer containing a PCM-16 mono WAV (16 kHz)
 *   Inbound JSON   — {type:"event", event:"voice.transcription", payload:{text}}
 *                    {type:"event", event:"voice.tts_done", payload:{}}
 *   Inbound binary — MP3 audio chunks for AudioContext playback
 */

'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const voiceState = {
  isActive: false,         // VAD running and mic open
  isAISpeaking: false,     // at least one MP3 chunk received, not yet tts_done
  vad: null,               // MicVAD instance
  audioCtx: null,          // AudioContext for TTS playback
  ws: null,                // reference to the existing dashboard WebSocket
  activeSources: [],       // AudioBufferSourceNode[] — cleared on barge-in
  nextStartTime: 0,        // scheduled playback cursor (seconds)
};

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

/**
 * Returns a short unique ID suitable for WS request frames.
 * @returns {string}
 */
function uid() {
  return 'v-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

/**
 * Encode a Float32Array (16 kHz, mono) to a standard RIFF/WAV ArrayBuffer.
 * Uses PCM-16 little-endian format — accepted by Groq Whisper and all STT APIs.
 *
 * @param {Float32Array} samples  Raw audio samples from Silero VAD (16 kHz)
 * @param {number}       sampleRate  Typically 16000
 * @returns {ArrayBuffer}  Valid 44-byte WAV header + PCM-16 body
 */
function float32ToWav(samples, sampleRate) {
  const numChannels = 1;
  const bitsPerSample = 16;
  const byteRate = sampleRate * numChannels * (bitsPerSample / 8);
  const blockAlign = numChannels * (bitsPerSample / 8);
  const dataBytes = samples.length * 2; // 2 bytes per PCM-16 sample
  const bufferLength = 44 + dataBytes;

  const buffer = new ArrayBuffer(bufferLength);
  const view = new DataView(buffer);

  /** Write a 4-char ASCII string into the DataView at `offset`. */
  function writeString(dv, offset, str) {
    for (let i = 0; i < str.length; i++) {
      dv.setUint8(offset + i, str.charCodeAt(i));
    }
  }

  // RIFF chunk descriptor
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataBytes, true);   // ChunkSize
  writeString(view, 8, 'WAVE');

  // fmt sub-chunk
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);              // Subchunk1Size (PCM = 16)
  view.setUint16(20, 1, true);               // AudioFormat   (PCM = 1)
  view.setUint16(22, numChannels, true);     // NumChannels
  view.setUint32(24, sampleRate, true);      // SampleRate
  view.setUint32(28, byteRate, true);        // ByteRate
  view.setUint16(32, blockAlign, true);      // BlockAlign
  view.setUint16(34, bitsPerSample, true);   // BitsPerSample

  // data sub-chunk
  writeString(view, 36, 'data');
  view.setUint32(40, dataBytes, true);       // Subchunk2Size

  // PCM-16 samples — clamp to [-1, 1] before scaling
  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }

  return buffer;
}

// ---------------------------------------------------------------------------
// Playback helpers
// ---------------------------------------------------------------------------

/**
 * Stop all active AudioBufferSourceNodes immediately (barge-in or cleanup).
 * Clears `onended` before calling stop() to avoid stale callback races.
 */
function stopAllTTSPlayback() {
  const sources = voiceState.activeSources.slice();
  voiceState.activeSources = [];
  voiceState.nextStartTime = 0;

  for (const src of sources) {
    src.onended = null; // prevent stale removal callback
    try {
      src.stop();
    } catch (_e) {
      // source may already have ended — safe to ignore
    }
  }

  voiceState.isAISpeaking = false;
  console.log('[SynapseVoice] TTS playback stopped, activeSources cleared');
}

/**
 * Decode an MP3 ArrayBuffer and schedule it in the AudioContext playback queue.
 * Uses a scheduled-start chain so consecutive chunks play gaplessly.
 *
 * @param {ArrayBuffer} arrayBuffer  MP3 bytes from a binary WS frame
 */
function scheduleAudioChunk(arrayBuffer) {
  const audioCtx = voiceState.audioCtx;
  if (!audioCtx || audioCtx.state === 'closed') {
    console.log('[SynapseVoice] scheduleAudioChunk: AudioContext unavailable, skipping chunk');
    return;
  }

  // decodeAudioData is Promise-based in modern browsers; callback form also supported.
  audioCtx.decodeAudioData(arrayBuffer).then((audioBuffer) => {
    // Re-check state — barge-in may have fired while we were decoding
    if (!voiceState.isAISpeaking) {
      return;
    }

    const source = audioCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioCtx.destination);

    const startAt = Math.max(audioCtx.currentTime, voiceState.nextStartTime);
    source.start(startAt);
    voiceState.nextStartTime = startAt + audioBuffer.duration;

    voiceState.activeSources.push(source);

    source.onended = () => {
      const idx = voiceState.activeSources.indexOf(source);
      if (idx !== -1) {
        voiceState.activeSources.splice(idx, 1);
      }
    };
  }).catch((err) => {
    // Pitfall 7: MP3 frame boundary issues — silently discard corrupt chunks
    console.log('[SynapseVoice] decodeAudioData failed (possibly truncated chunk), skipping:', err.message);
  });
}

// ---------------------------------------------------------------------------
// WebSocket message handler
// ---------------------------------------------------------------------------

/**
 * Route an inbound WebSocket message event to the voice subsystem.
 * The dashboard's existing `ws.onmessage` handler should call this when
 * `voiceState.isActive` is true.
 *
 * @param {MessageEvent} event
 */
function handleWSMessage(event) {
  if (event.data instanceof ArrayBuffer) {
    // Binary frame = MP3 audio chunk from TTS streamer
    voiceState.isAISpeaking = true;
    scheduleAudioChunk(event.data);
    return;
  }

  if (event.data instanceof Blob) {
    // Fallback: some browsers may still deliver Blob even with binaryType="arraybuffer"
    event.data.arrayBuffer().then((ab) => {
      voiceState.isAISpeaking = true;
      scheduleAudioChunk(ab);
    });
    return;
  }

  // Text (JSON) frame
  if (typeof event.data === 'string') {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (_e) {
      return; // not JSON — not our concern
    }

    if (msg.type !== 'event') return;

    switch (msg.event) {
      case 'voice.tts_done':
        voiceState.isAISpeaking = false;
        console.log('[SynapseVoice] TTS stream complete (voice.tts_done)');
        break;

      case 'voice.transcription':
        console.log('[SynapseVoice] Transcription received:', msg.payload && msg.payload.text);
        // Dispatch a custom DOM event so the dashboard UI can display the text
        window.dispatchEvent(new CustomEvent('synapse:transcription', {
          detail: { text: (msg.payload && msg.payload.text) || '' },
        }));
        break;

      default:
        // Not a voice event — let the dashboard's normal handler process it
        break;
    }
  }
}

// ---------------------------------------------------------------------------
// Core API
// ---------------------------------------------------------------------------

/**
 * Initialize VAD, AudioContext, and begin mic capture.
 * MUST be called from a user-gesture context (button click) so that
 * AudioContext.resume() is allowed by the browser.
 *
 * @param {WebSocket} ws  The existing dashboard WebSocket connection
 * @returns {Promise<boolean>}  true on success, false on failure
 */
async function startVoice(ws) {
  if (voiceState.isActive) {
    console.log('[SynapseVoice] startVoice called but already active — ignoring');
    return true;
  }

  // Guard: vad-web CDN script must be loaded
  if (typeof vad === 'undefined' || typeof vad.MicVAD === 'undefined') {
    console.log('[SynapseVoice] ERROR: @ricky0123/vad-web not loaded from CDN. Cannot start voice.');
    return false;
  }

  try {
    // Store WS reference and set binary type for zero-copy decode (Pitfall: default is "blob")
    voiceState.ws = ws;
    ws.binaryType = 'arraybuffer';

    // Create AudioContext — must happen inside user gesture
    const audioCtx = new AudioContext();
    await audioCtx.resume(); // unlock context (required after user-gesture gate)
    voiceState.audioCtx = audioCtx;

    // Notify server that a voice session is beginning
    ws.send(JSON.stringify({
      type: 'req',
      id: uid(),
      method: 'voice.start',
      params: {},
    }));

    // Initialise Silero VAD
    const myvad = await vad.MicVAD.new({
      positiveSpeechThreshold: 0.3,
      negativeSpeechThreshold: 0.25,
      redemptionMs: 700,       // VOICE-02: 700ms silence boundary before speech end fires
      preSpeechPadMs: 300,
      minSpeechMs: 400,
      baseAssetPath: 'https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/',
      onnxWASMBasePath: 'https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/',

      onSpeechStart: () => {
        console.log('[SynapseVoice] Speech started');
        if (voiceState.isAISpeaking) {
          // Barge-in: user spoke while AI was talking
          console.log('[SynapseVoice] Barge-in detected — stopping TTS and sending voice.barge_in');
          stopAllTTSPlayback();
          if (voiceState.ws && voiceState.ws.readyState === WebSocket.OPEN) {
            voiceState.ws.send(JSON.stringify({
              type: 'req',
              id: uid(),
              method: 'voice.barge_in',
              params: {},
            }));
          }
        }
      },

      onSpeechEnd: (audio) => {
        // audio: Float32Array at 16000 Hz — encode to WAV and ship over WS
        console.log('[SynapseVoice] Speech ended, encoding', audio.length, 'samples to WAV');
        const wavBuffer = float32ToWav(audio, 16000);
        if (voiceState.ws && voiceState.ws.readyState === WebSocket.OPEN) {
          voiceState.ws.send(wavBuffer);
        } else {
          console.log('[SynapseVoice] WebSocket not open — WAV dropped');
        }
      },
    });

    myvad.start();
    voiceState.vad = myvad;
    voiceState.isActive = true;

    console.log('[SynapseVoice] Voice started — VAD active, AudioContext running');
    return true;
  } catch (err) {
    console.log('[SynapseVoice] startVoice failed:', err);
    // Partial cleanup on error
    if (voiceState.audioCtx) {
      try { voiceState.audioCtx.close(); } catch (_e) {}
      voiceState.audioCtx = null;
    }
    voiceState.ws = null;
    return false;
  }
}

/**
 * Tear down VAD, stop all playback, close AudioContext, notify server.
 * Safe to call multiple times.
 */
function stopVoice() {
  if (!voiceState.isActive && !voiceState.vad) {
    console.log('[SynapseVoice] stopVoice called but not active — nothing to do');
    return;
  }

  console.log('[SynapseVoice] Stopping voice session...');

  // Destroy VAD (releases mic via getUserMedia stream)
  if (voiceState.vad) {
    try {
      voiceState.vad.destroy();
    } catch (err) {
      console.log('[SynapseVoice] vad.destroy() error (non-fatal):', err);
    }
    voiceState.vad = null;
  }

  // Stop any in-progress TTS playback
  stopAllTTSPlayback();

  // Close AudioContext
  if (voiceState.audioCtx && voiceState.audioCtx.state !== 'closed') {
    voiceState.audioCtx.close().catch((err) => {
      console.log('[SynapseVoice] AudioContext.close() error (non-fatal):', err);
    });
  }
  voiceState.audioCtx = null;

  // Notify server
  if (voiceState.ws && voiceState.ws.readyState === WebSocket.OPEN) {
    voiceState.ws.send(JSON.stringify({
      type: 'req',
      id: uid(),
      method: 'voice.stop',
      params: {},
    }));
  }

  // Reset state
  voiceState.ws = null;
  voiceState.isActive = false;
  voiceState.isAISpeaking = false;
  voiceState.nextStartTime = 0;
  voiceState.activeSources = [];

  console.log('[SynapseVoice] Voice session stopped');
}

// ---------------------------------------------------------------------------
// Tab close cleanup
// ---------------------------------------------------------------------------

window.addEventListener('beforeunload', () => {
  if (voiceState.isActive) {
    stopVoice();
  }
});

// ---------------------------------------------------------------------------
// Public API — exposed on window for dashboard HTML wiring
// ---------------------------------------------------------------------------

window.SynapseVoice = {
  startVoice,
  stopVoice,
  handleWSMessage,
  getState: () => ({ ...voiceState }),  // read-only shallow copy
};

console.log('[SynapseVoice] Module loaded — call SynapseVoice.startVoice(ws) from a button click handler');
