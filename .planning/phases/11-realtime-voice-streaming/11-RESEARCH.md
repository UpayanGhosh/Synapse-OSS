# Phase 11: Realtime Voice Streaming - Research

**Researched:** 2026-04-09
**Domain:** Browser VAD, WebSocket audio streaming, STT/TTS pipeline, barge-in interruption
**Confidence:** HIGH

## Summary

Phase 11 is the most complex phase in v3.0. It adds full-duplex voice conversation from the dashboard by wiring four discrete subsystems: browser-side VAD + mic capture, WebSocket audio transport, server-side Groq Whisper transcription, and streamed TTS audio playback with barge-in cancellation.

The key architectural insight is that Phase 11 does NOT build new audio infrastructure from scratch — it reuses and extends existing foundations from Phase 8 (TTS engine, edge-tts streaming, OGG transcode) and Phase 10 (WebSocket gateway at `ws://127.0.0.1:8000/ws`, `GatewayWebSocket` handler, existing `chat.send` method). Phase 11 adds: (1) a new `voice.start` / `voice.audio` / `voice.stop` WebSocket protocol on top of the existing WS server, (2) a `VoiceChannel` that registers in `ChannelRegistry` so the existing chat pipeline handles transcribed utterances, and (3) browser-side `@ricky0123/vad-web` (via CDN, no bundler) that detects speech boundaries and sends completed audio blobs to the server.

The Groq Whisper integration already exists in the codebase (`media/audio_transcriber.py`) as a file-based transcription helper. Phase 11 adapts this to accept in-memory bytes from the WebSocket (by writing to a temp file or using `io.BytesIO` wrapped in a multipart form upload). No new Groq SDK is needed. The key gap is that Groq Whisper is batch-only — it transcribes complete utterances, not streaming chunks — which is exactly what Silero VAD's `onSpeechEnd` event provides.

Barge-in is implemented as two signals: (a) when VAD fires `onSpeechStart` while TTS is playing, the browser sends a `voice.barge_in` WS message AND calls `AudioBufferSourceNode.stop()` immediately on all queued source nodes; (b) the server receives `voice.barge_in`, sets a cancellation flag on the active TTS stream task, and stops sending further audio chunks.

**Primary recommendation:** Reuse the existing `/ws` WebSocket endpoint with new voice-specific message types. Add a `VoiceChannel` that feeds transcribed text into the standard `TaskQueue`. Stream TTS back as binary WebSocket frames (MP3 chunks from `edge-tts.stream()` — no need to transcode to OGG for dashboard playback since the browser can decode MP3 natively).

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VOICE-01 | User can have real-time voice conversations via WebSocket from dashboard | Reuse existing `/ws` endpoint in `routes/websocket.py`. Add `voice.*` method handlers to `GatewayWebSocket`. Dashboard HTML adds a "Start Voice" button that initializes `@ricky0123/vad-web` |
| VOICE-02 | Silero VAD detects speech boundaries with conservative defaults | `@ricky0123/vad-web@0.0.29` via CDN. Default `positiveSpeechThreshold: 0.3`, `redemptionMs: 1400` (conservative), `preSpeechPadMs: 800`. `onSpeechEnd` fires with `Float32Array` at 16kHz |
| VOICE-03 | Groq Whisper handles streaming transcription | Existing `transcribe_audio()` in `media/audio_transcriber.py`. Adapt to accept bytes via in-memory WAV encoding (`wave` stdlib module). Encode `Float32Array→PCM16→WAV` client-side before sending, or send raw Float32 bytes and encode server-side |
| VOICE-04 | TTS response streams back as audio chunks | `edge-tts` `communicate.stream()` yields `{"type": "audio", "data": bytes}` MP3 chunks. Server sends these as binary WebSocket frames. Browser queues them into `AudioContext` via `decodeAudioData()` + scheduled `AudioBufferSourceNode` chain |
| VOICE-05 | Barge-in cancels current TTS playback | VAD `onSpeechStart` → browser calls `AudioBufferSourceNode.stop()` on all active nodes + sends `voice.barge_in` WS message → server sets `asyncio.Event` to cancel TTS streaming loop |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| @ricky0123/vad-web | 0.0.29 | Browser-side Silero VAD via ONNX Runtime Web | Only production-ready browser VAD library; 16kHz Float32Array output maps directly to Whisper input; CDN-loadable, no bundler |
| onnxruntime-web | 1.22.0 | WASM runtime for Silero VAD model | Required peer dependency of vad-web; CDN-loadable |
| edge-tts | 7.2.8 | TTS synthesis with streaming | Already in Phase 8 stack; `stream()` async generator yields MP3 chunks ideal for WS streaming |
| groq (via existing transcribe_audio) | — | Whisper transcription | `media/audio_transcriber.py` already exists; no new client needed |
| wave (Python stdlib) | stdlib | Encode Float32→PCM16 WAV for Groq | Zero dependency; builds valid WAV header accepted by Groq |
| AudioContext (Web API) | browser native | Browser audio playback of TTS chunks | Native API; decodes MP3 chunks via `decodeAudioData()`; no library needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| AudioWorklet (Web API) | browser native | Alternative to ScriptProcessor for mic capture | Only needed if building custom VAD pipeline — @ricky0123/vad-web handles this internally |
| MediaRecorder (Web API) | browser native | Alternative audio capture format | Only if Float32Array path proves difficult — MediaRecorder produces WebM/Opus but VAD gives Float32 directly |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| @ricky0123/vad-web | webrtcvad (Python server-side) | Server-side VAD requires sending all mic audio continuously over WebSocket; vad-web fires only completed speech segments, reducing bandwidth 90% |
| @ricky0123/vad-web | MediaRecorder + time-based chunks | Time-based chunking produces incomplete utterances, increasing Whisper WER significantly; VAD boundary detection is more accurate |
| edge-tts stream() for WS | edge-tts save() then serve file | File-based approach adds 2-5s latency before first audio byte reaches browser; streaming yields first chunk in ~300ms |
| Binary WS frames for audio | Base64-encoded JSON | Binary frames reduce bandwidth 33% and eliminate encode/decode overhead; critical for streaming audio |
| Existing `/ws` endpoint | New `/voice` WebSocket endpoint | Separate endpoint creates auth duplication; extending existing `GatewayWebSocket` with `voice.*` methods is simpler and reuses token auth |

**Installation:**
```bash
# Python (edge-tts already in Phase 8, wave is stdlib)
pip install edge-tts  # already installed
# No new Python packages needed for Phase 11

# Browser (CDN — no npm needed, dashboard is vanilla JS)
# In dashboard HTML:
# <script src="https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/ort.wasm.min.js"></script>
# <script src="https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/bundle.min.js"></script>
```

## Architecture Patterns

### Recommended Project Structure
```
workspace/sci_fi_dashboard/
├── channels/
│   └── voice_channel.py       # NEW: VoiceChannel — receives transcribed text, sends TTS chunks
├── gateway/
│   ├── ws_server.py           # EXTEND: add voice.* method handlers + binary frame support
│   └── voice_session.py       # NEW: VoiceSession per-connection state (active_tts_task, cancel_event)
├── routes/
│   └── websocket.py           # UNCHANGED: /ws endpoint already exists
└── media/
    └── audio_transcriber.py   # EXTEND: add transcribe_bytes() wrapping existing transcribe_audio()

# Dashboard (Phase 10 dependency)
workspace/sci_fi_dashboard/static/
└── dashboard/
    └── voice.js               # NEW: VAD init, WS audio protocol, AudioContext playback queue, barge-in
```

### Pattern 1: VAD Browser Side — Speech Segment Capture
**What:** `@ricky0123/vad-web` detects speech boundaries entirely in the browser using ONNX Runtime WASM. Fires `onSpeechEnd` with a `Float32Array` (16kHz) only when a complete utterance is detected. Browser encodes to WAV and sends via binary WebSocket frame.
**When to use:** Always — this is the VAD entry point.
**Example:**
```javascript
// Source: https://github.com/ricky0123/vad + docs.vad.ricky0123.com
const myvad = await vad.MicVAD.new({
  positiveSpeechThreshold: 0.3,  // conservative default
  negativeSpeechThreshold: 0.25,
  redemptionMs: 700,              // 700ms silence before speech ends (requirement: 700ms)
  preSpeechPadMs: 300,            // prepend 300ms before speech start
  minSpeechMs: 400,               // ignore clips < 400ms (reduces misfires)
  onSpeechStart: () => {
    // Barge-in: cancel TTS playback immediately
    if (voiceState.isAISpeaking) {
      stopAllTTSPlayback();
      ws.send(JSON.stringify({ type: "req", id: uid(), method: "voice.barge_in", params: {} }));
    }
  },
  onSpeechEnd: (audio) => {
    // audio: Float32Array at 16000 Hz
    const wavBytes = float32ToWav(audio, 16000);
    ws.send(wavBytes);  // binary frame — server reads as bytes
  },
  baseAssetPath: "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/",
  onnxWASMBasePath: "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/",
});
myvad.start();
```

### Pattern 2: Float32Array → WAV Encoding (Browser)
**What:** Encode 16kHz mono Float32 samples to a WAV byte buffer with a proper PCM16 header, ready for Groq Whisper ingestion. Pure JavaScript, no libraries.
**When to use:** In the `onSpeechEnd` callback before sending over WebSocket.
**Example:**
```javascript
// Source: MDN Web Audio API docs + Groq STT format requirements
function float32ToWav(samples, sampleRate) {
  const numChannels = 1;
  const bitsPerSample = 16;
  const bytesPerSample = bitsPerSample / 8;
  const blockAlign = numChannels * bytesPerSample;
  const byteRate = sampleRate * blockAlign;
  const dataSize = samples.length * bytesPerSample;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  // RIFF header
  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);       // PCM chunk size
  view.setUint16(20, 1, true);        // PCM format
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeString(view, 36, 'data');
  view.setUint32(40, dataSize, true);

  // PCM16 samples
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
  }
  return buffer;
}
function writeString(view, offset, str) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}
```

### Pattern 3: VoiceSession State Machine (Server)
**What:** Per-WebSocket connection state object tracking whether TTS is active, storing the active TTS task, and providing a cancellation event for barge-in.
**When to use:** Created when `voice.start` is received; destroyed on `voice.stop` or disconnect.
**Example:**
```python
# workspace/sci_fi_dashboard/gateway/voice_session.py
import asyncio
from dataclasses import dataclass, field

@dataclass
class VoiceSession:
    conn_id: str
    active_tts_task: asyncio.Task | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    is_ai_speaking: bool = False

    def request_cancel(self) -> None:
        """Signal active TTS stream to stop (barge-in or new utterance)."""
        self.cancel_event.set()

    def reset_cancel(self) -> None:
        """Clear cancel event after TTS task completes or is cancelled."""
        self.cancel_event.clear()
        self.active_tts_task = None
        self.is_ai_speaking = False
```

### Pattern 4: Server WebSocket Voice Protocol Extension
**What:** Extend `GatewayWebSocket._dispatch()` in `ws_server.py` to handle binary frames (WAV bytes) and new text-frame methods: `voice.start`, `voice.stop`, `voice.barge_in`. Binary frames bypass JSON dispatch and go directly to transcription.
**When to use:** When client sends a binary WebSocket message (the WAV audio blob) or a `voice.*` JSON method.
**Example:**
```python
# In GatewayWebSocket.handle() — extend the receive loop to handle binary:
async def handle(self, websocket: WebSocket) -> None:
    # ... existing handshake ...
    while True:
        message = await websocket.receive()  # use receive() not receive_text()
        if message["type"] == "websocket.receive":
            if "bytes" in message and message["bytes"]:
                # Binary frame = audio WAV blob from VAD
                await self._handle_voice_audio(websocket, message["bytes"], conn_id)
            elif "text" in message and message["text"]:
                raw = message["text"]
                # ... existing JSON dispatch ...
```

### Pattern 5: Transcription — Groq Whisper from Bytes
**What:** Extend `audio_transcriber.py` with `transcribe_bytes()` that wraps the existing file-based helper by writing bytes to a temp WAV file, calling the existing `transcribe_audio()`, then deleting the temp file.
**When to use:** When binary audio frame arrives on WebSocket.
**Example:**
```python
# workspace/sci_fi_dashboard/media/audio_transcriber.py — new function
import tempfile
from pathlib import Path

async def transcribe_bytes(wav_bytes: bytes, language: str = "en") -> str:
    """Transcribe WAV bytes using existing transcribe_audio() helper."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp_path = Path(f.name)
    try:
        return await transcribe_audio(tmp_path, language=language)
    finally:
        tmp_path.unlink(missing_ok=True)
```

### Pattern 6: TTS Streaming Back via WebSocket Binary Frames
**What:** Use `edge-tts` `communicate.stream()` async generator to yield MP3 audio chunks and send each chunk as a binary WebSocket frame as soon as it arrives. Check `cancel_event` before each send to support barge-in.
**When to use:** After transcription returns text, before injecting into chat pipeline; OR as a second path where the TTS reply streams directly to the voice WebSocket after `persona_chat()` returns.
**Example:**
```python
# In GatewayWebSocket — TTS streaming task
async def _stream_tts_to_ws(
    websocket: WebSocket,
    text: str,
    voice: str,
    session: VoiceSession,
) -> None:
    """Stream edge-tts MP3 chunks as binary WS frames."""
    import edge_tts
    session.is_ai_speaking = True
    session.reset_cancel()
    communicate = edge_tts.Communicate(text, voice)
    try:
        async for chunk in communicate.stream():
            if session.cancel_event.is_set():
                break  # barge-in or new utterance: stop streaming
            if chunk["type"] == "audio":
                await websocket.send_bytes(chunk["data"])
        # Signal end of TTS
        await websocket.send_json({"type": "event", "event": "voice.tts_done"})
    except Exception as exc:
        logger.error("[VoiceWS] TTS stream error: %s", exc)
    finally:
        session.is_ai_speaking = False
        session.active_tts_task = None
```

### Pattern 7: Browser TTS Playback Queue (AudioContext)
**What:** Browser receives binary WebSocket frames (MP3 chunks). Each chunk is decoded via `audioCtx.decodeAudioData()` and scheduled to play at the next available time slot using `AudioBufferSourceNode`. Barge-in calls `stop()` on all active source nodes and clears the playback queue.
**When to use:** Always — this is the only correct approach for streaming audio chunks in the browser without audible gaps.
**Example:**
```javascript
// Source: MDN AudioBufferSourceNode docs
const audioCtx = new AudioContext();
let nextStartTime = 0;
let activeSources = [];

function scheduleAudioChunk(arrayBuffer) {
  audioCtx.decodeAudioData(arrayBuffer, (audioBuffer) => {
    const source = audioCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(audioCtx.destination);

    const startAt = Math.max(audioCtx.currentTime, nextStartTime);
    source.start(startAt);
    nextStartTime = startAt + audioBuffer.duration;
    activeSources.push(source);

    source.onended = () => {
      activeSources = activeSources.filter(s => s !== source);
    };
  });
}

function stopAllTTSPlayback() {
  // Barge-in: stop all queued and active source nodes
  activeSources.forEach(src => {
    src.onended = null;  // prevent stale callback firing
    try { src.stop(); } catch(e) {}
  });
  activeSources = [];
  nextStartTime = 0;
}

// WebSocket binary handler
ws.onmessage = (event) => {
  if (event.data instanceof ArrayBuffer) {
    scheduleAudioChunk(event.data);
  } else {
    const msg = JSON.parse(event.data);
    if (msg.event === "voice.tts_done") {
      // TTS stream complete — ready for next utterance
      voiceState.isAISpeaking = false;
    }
  }
};
```

### Pattern 8: VoiceChannel Registration
**What:** A `VoiceChannel` class registered in `ChannelRegistry` at gateway startup. Its `send()` method does nothing (TTS goes directly via WebSocket to the voice session, not through channel adapters). Its role is to give the chat pipeline a valid `channel_id` so `persona_chat()` can run with `channel_id="voice"`.
**When to use:** One `VoiceChannel` instance registered at startup alongside WhatsApp/Telegram.
**Example:**
```python
# workspace/sci_fi_dashboard/channels/voice_channel.py
from .base import BaseChannel, ChannelMessage

class VoiceChannel(BaseChannel):
    channel_id = "voice"

    async def start(self) -> None:
        pass  # No polling loop; messages arrive via WebSocket

    async def stop(self) -> None:
        pass

    async def send(self, chat_id: str, text: str, **kwargs) -> bool:
        # TTS delivery happens in GatewayWebSocket._stream_tts_to_ws()
        # not through the channel adapter
        return True
```

### Anti-Patterns to Avoid
- **Sending raw Float32Array bytes without WAV header:** Groq Whisper rejects raw PCM without a valid RIFF/WAV container. Always wrap in WAV header before upload.
- **Using `receive_text()` instead of `receive()` for binary WS messages:** Starlette's `receive_text()` will raise on binary frames. Use `receive()` and check the message type.
- **Awaiting TTS inside the WebSocket receive loop:** TTS streaming takes 1-5 seconds. Always dispatch as `asyncio.create_task()` so the receive loop can still process `voice.barge_in` while TTS is streaming.
- **Not clearing `onended` handler before calling `stop()`:** A stopped `AudioBufferSourceNode` still fires `onended`. If this callback resets `isAISpeaking = false` or adjusts `nextStartTime`, it will corrupt playback state after barge-in.
- **Using `decodeAudioData` on an incomplete chunk:** Edge-TTS MP3 chunks may be incomplete MP3 frames. Browser `decodeAudioData` is lenient with MP3 but may fail on the final partial chunk. Wrap in `try/catch` and discard decode errors silently.
- **Serving VAD WASM files from loopback HTTP (not HTTPS):** `@ricky0123/vad-web` uses `AudioWorklet`, which requires a secure context (HTTPS) OR `localhost` specifically. Loopback `127.0.0.1` satisfies this. If the dashboard is served from a non-localhost origin, HTTPS is required.
- **Not registering `voice` in `channels/ids.py`:** `is_valid_channel_id("voice")` will return `False` and `resolve_channel_id()` won't recognize it. Add `"voice"` to `CHANNEL_ORDER` and `ChannelId` Literal.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Browser voice activity detection | Custom WebRTC/AudioWorklet VAD | `@ricky0123/vad-web` | Silero VAD model is ONNX-optimized for speech; hand-rolled energy threshold VAD produces 30%+ false positive rate |
| Groq Whisper client | Custom multipart HTTP client | Existing `transcribe_audio()` + new `transcribe_bytes()` wrapper | Auth, retry, and error handling already tested in codebase |
| Audio chunk scheduling | Custom timer-based playback | `AudioContext` + `AudioBufferSourceNode.start(time)` scheduling | Scheduled start times prevent gaps and clicks; timer-based approach produces audible glitches |
| TTS streaming | Custom synthesis engine | `edge-tts.communicate.stream()` | Already in Phase 8 stack; `stream()` yields MP3 chunks — exactly what WS binary frames need |
| Float32→PCM16 conversion | Audio codec library | 5-line DataView loop (Pattern 2) | Standard audio engineering formula; no library needed |

**Key insight:** This phase is almost entirely integration work, not new components. The heavy lifting — VAD model inference, Whisper transcription, TTS synthesis — is fully handled by existing libraries. The code surface is smaller than it appears.

## Common Pitfalls

### Pitfall 1: AudioContext suspended on page load
**What goes wrong:** Chrome and Safari auto-suspend `AudioContext` until a user gesture occurs. First TTS chunk is decoded but `start()` calls are silently ignored. The voice session appears to work (no error) but produces no sound.
**Why it happens:** Browser autoplay policy. `AudioContext` state is `"suspended"` until `audioCtx.resume()` is called inside a user event handler.
**How to avoid:** Call `audioCtx.resume()` inside the "Start Voice" button click handler — the same gesture that calls `myvad.start()`. Verify `audioCtx.state === "running"` before scheduling chunks.
**Warning signs:** VAD fires, WS sends audio, server transcribes, TTS chunks arrive, but no audio plays. `audioCtx.state` is `"suspended"` in browser console.

### Pitfall 2: VAD ONNX model CDN CORS failure
**What goes wrong:** `@ricky0123/vad-web` tries to load `silero_vad_v5.onnx` from the `baseAssetPath` via `fetch()` inside an `AudioWorklet`. CDN CORS headers must allow this. If the dashboard is served from `http://127.0.0.1:8000`, the CDN request is cross-origin and requires CORS headers (jsDelivr provides these — confirmed).
**Why it happens:** AudioWorklet `fetch()` calls are subject to CORS. jsDelivr CDN includes `Access-Control-Allow-Origin: *`.
**How to avoid:** Use jsDelivr CDN URLs as shown (not unpkg, which has inconsistent CORS headers). Alternatively, serve ONNX model files from FastAPI static mount.
**Warning signs:** `Failed to fetch` error in console when VAD initializes. `MicVAD.new()` rejects its Promise.

### Pitfall 3: VAD `redemptionMs` too short — premature speech end detection
**What goes wrong:** VAD fires `onSpeechEnd` mid-sentence during a natural pause (e.g., "I want to... [0.5s pause] ...go to the store"). User receives a partial transcription.
**Why it happens:** Default `redemptionMs` in some older vad-web versions is 600ms. The requirement specifies 700ms.
**How to avoid:** Explicitly set `redemptionMs: 700` in MicVAD config. Add a 10-utterance test asserting no premature cutoffs.
**Warning signs:** Transcriptions cut off mid-sentence. WER spikes on multi-clause sentences.

### Pitfall 4: Starlette WebSocket `receive()` vs `receive_text()` for binary
**What goes wrong:** Existing `ws_server.py` uses `websocket.receive_text()` in the message loop. When the browser sends a binary WAV blob, `receive_text()` raises `WebSocketDisconnect` or a decode error.
**Why it happens:** Starlette's `receive_text()` only handles text frames. Binary frames are a different message type.
**How to avoid:** Change the main receive loop to use `websocket.receive()` (returns raw Starlette message dict). Check `message["type"]` and branch on `"bytes"` vs `"text"`. This is a required change to `ws_server.py`.
**Warning signs:** WebSocket disconnects immediately when browser sends first audio blob. Server log shows `WebSocketDisconnect` on the binary frame.

### Pitfall 5: Concurrent TTS stream + new utterance → double TTS
**What goes wrong:** User speaks while AI is mid-response. Server receives the new audio AND the barge-in signal, but the existing TTS `asyncio.Task` hasn't cancelled yet. Two TTS streams start concurrently, producing double audio.
**Why it happens:** Race condition between barge-in cancel event and new utterance processing. The new utterance arrives before the old TTS task observes the cancel event.
**How to avoid:** On `voice.barge_in` OR on any new audio blob, call `await session.active_tts_task` with `asyncio.wait_for(session.active_tts_task, timeout=0.5)` before starting a new TTS task. Use `asyncio.shield` pattern to prevent cascading cancellations.
**Warning signs:** Two overlapping TTS audio streams arrive simultaneously. Browser plays garbled audio.

### Pitfall 6: `channels/ids.py` missing `"voice"` entry
**What goes wrong:** `MessageTask(channel_id="voice")` is created in `GatewayWebSocket._handle_voice_audio()`. If `"voice"` is not in `CHANNEL_ORDER` or `ChannelId` Literal, and there's any validation checking `is_valid_channel_id()`, the task is rejected.
**Why it happens:** `ids.py` has a closed set of channel IDs. Phase 11 adds a new channel.
**How to avoid:** Add `"voice"` to `CHANNEL_ORDER` tuple, `ChannelId` Literal, and register `VoiceChannel` in the gateway lifespan. Check `api_gateway.py` lifespan for where `WhatsAppChannel`, `TelegramChannel` etc. are registered.
**Warning signs:** TaskQueue rejects `MessageTask` with `channel_id="voice"`. No AI response generated.

### Pitfall 7: Edge-TTS MP3 chunk boundaries not aligned to MP3 frames
**What goes wrong:** `audioCtx.decodeAudioData(chunk)` fails for some chunks because they contain partial MP3 frames. Browser console shows `EncodingError: The encoded audio data was corrupted`.
**Why it happens:** `edge-tts stream()` yields chunks as they arrive from the Microsoft WebSocket — chunk boundaries are not aligned to MP3 frame boundaries.
**How to avoid:** Collect all audio chunks first (buffered streaming), then send the complete MP3 to the browser as one binary frame. Alternatively, send a single WebSocket binary message per utterance rather than per-chunk. The latency tradeoff is acceptable since the browser's first audio starts within ~1-2s of the complete reply being synthesized (still well within the 3s round-trip requirement).
**Warning signs:** `decodeAudioData` throws `EncodingError` on some chunks but not others. Audio playback is incomplete.

### Pitfall 8: Mic not released on tab close
**What goes wrong:** When the user closes the tab, the microphone stays active (browser mic indicator remains lit). VAD model keeps running. AudioWorklet keeps processing.
**Why it happens:** `myvad.destroy()` is not called on `beforeunload` / `visibilitychange`.
**How to avoid:** Register `window.addEventListener('beforeunload', () => { myvad.destroy(); ws.close(); })`. The success criterion explicitly checks for no dangling streams.
**Warning signs:** Browser mic indicator stays on after tab close. OS reports microphone still in use.

## Code Examples

Verified patterns from official sources:

### VAD Initialization (Browser, no bundler)
```html
<!-- Source: https://github.com/ricky0123/vad + docs.vad.ricky0123.com/user-guide/browser/ -->
<script src="https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/ort.wasm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/bundle.min.js"></script>
<script>
  let myvad = null;

  async function startVoice() {
    const audioCtx = new AudioContext();
    await audioCtx.resume();  // REQUIRED before first chunk

    myvad = await vad.MicVAD.new({
      redemptionMs: 700,
      positiveSpeechThreshold: 0.3,
      negativeSpeechThreshold: 0.25,
      preSpeechPadMs: 300,
      minSpeechMs: 400,
      onSpeechStart: () => {
        if (voiceState.isAISpeaking) {
          stopAllTTSPlayback();
          ws.send(JSON.stringify({ type: "req", id: uid(), method: "voice.barge_in", params: {} }));
        }
      },
      onSpeechEnd: (audio) => {
        const wav = float32ToWav(audio, 16000);
        ws.send(wav);  // binary frame
      },
      baseAssetPath: "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/",
      onnxWASMBasePath: "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/",
    });
    myvad.start();
  }

  window.addEventListener('beforeunload', () => {
    if (myvad) myvad.destroy();
    if (ws) ws.close();
  });
</script>
```

### Transcribe Bytes (Python, server-side)
```python
# Source: adaptation of existing workspace/sci_fi_dashboard/media/audio_transcriber.py
import tempfile
from pathlib import Path
from .audio_transcriber import transcribe_audio

async def transcribe_bytes(wav_bytes: bytes, language: str = "en") -> str:
    """Wrap transcribe_audio() for in-memory bytes from WebSocket."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp_path = Path(f.name)
    try:
        return await transcribe_audio(tmp_path, language=language)
    finally:
        tmp_path.unlink(missing_ok=True)
```

### TTS Streaming Task (Python)
```python
# Source: edge-tts stream() API — github.com/rany2/edge-tts/blob/master/src/edge_tts/communicate.py
import asyncio
import edge_tts
import logging
from starlette.websockets import WebSocket
from .voice_session import VoiceSession

logger = logging.getLogger(__name__)

async def stream_tts_to_ws(websocket: WebSocket, text: str, voice: str, session: VoiceSession) -> None:
    session.is_ai_speaking = True
    session.reset_cancel()
    communicate = edge_tts.Communicate(text, voice)
    full_audio = bytearray()
    try:
        async for chunk in communicate.stream():
            if session.cancel_event.is_set():
                break
            if chunk["type"] == "audio":
                full_audio.extend(chunk["data"])
        if not session.cancel_event.is_set() and full_audio:
            await websocket.send_bytes(bytes(full_audio))
            await websocket.send_json({"type": "event", "event": "voice.tts_done", "seq": 0})
    except Exception as exc:
        logger.error("[VoiceWS] TTS stream error: %s", exc)
    finally:
        session.is_ai_speaking = False
        session.active_tts_task = None
```
> **Note on chunking vs. buffering:** The implementation above collects all chunks then sends one binary frame to avoid MP3 frame boundary decoding errors (Pitfall 7). If the 3s round-trip budget is tight, switch to per-chunk streaming with `try/catch` around `decodeAudioData` in the browser.

### WebSocket Receive Loop Patch (Python)
```python
# ws_server.py — replace receive_text() with receive() to support binary
# Source: Starlette WebSocket docs
while True:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        break
    if "bytes" in message and message["bytes"]:
        await self._handle_voice_audio(websocket, message["bytes"], conn_id, voice_session)
    elif "text" in message and message["text"]:
        raw = message["text"]
        if len(raw.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            await websocket.close(code=4002, reason="Payload exceeds max size")
            return
        req = parse_frame(raw)
        if req is None:
            continue
        seq[0] += 1
        response = await self._dispatch(req, voice_session)
        await websocket.send_json(response)
```

### Voice Channel Registration (Python)
```python
# channels/ids.py — add "voice" to CHANNEL_ORDER and ChannelId
CHANNEL_ORDER: tuple[str, ...] = (
    "whatsapp", "telegram", "discord", "slack", "cli", "websocket", "voice"
)
ChannelId = Literal["whatsapp", "telegram", "discord", "slack", "cli", "websocket", "voice"]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| WebRTC-based browser VAD (energy threshold) | ONNX-based Silero VAD in browser (@ricky0123/vad-web) | 2023-2024 | 90%+ reduction in false positives; production-quality boundary detection |
| ScriptProcessorNode for audio processing | AudioWorklet (used internally by vad-web) | Chrome 66 / 2018 (standard 2024) | Off-main-thread audio processing; no more main-thread jank |
| Streaming Whisper (incremental) | Batch Whisper on complete utterances (VAD-gated) | 2024 | Lower WER; streaming Whisper has higher hallucination rate on partial audio |
| OpenAI Realtime API (WebRTC) | Custom VAD + Groq Whisper + edge-tts pipeline | 2024-2025 | Zero external dependency for voice pipeline; no per-minute API cost for voice |
| MediaRecorder for audio capture | VAD library direct Float32Array | 2023+ | VAD gives 16kHz mono Float32 directly — ideal for Whisper; no format conversion needed |

**Deprecated/outdated:**
- `createScriptProcessor()`: Deprecated in all browsers; vad-web uses AudioWorklet internally — no need to interact with ScriptProcessor at all.
- Streaming Groq Whisper: Not available — Groq STT is batch-only. This is fine because Silero VAD gives complete utterances, not partial chunks.

## Open Questions

1. **MP3 chunk boundary decoding reliability**
   - What we know: `edge-tts stream()` yields MP3 chunks that may not align to MP3 frame boundaries. Browser `decodeAudioData` may fail on partial frames.
   - What's unclear: Whether Chrome's MP3 decoder is lenient enough to handle partial frames in practice.
   - Recommendation: Start with buffered approach (collect all chunks → send one binary frame). If 3s latency budget is tight, switch to per-chunk with browser-side error recovery.

2. **Dashboard HTML location (Phase 10 dependency)**
   - What we know: Phase 11 depends on Phase 10 which creates the dashboard. The dashboard HTML file location and structure are not yet known (Phase 10 not yet planned).
   - What's unclear: Whether the dashboard will be a single `index.html` or use FastAPI's StaticFiles mount with separate JS files.
   - Recommendation: Plan Phase 11 with `voice.js` as a separate file served via FastAPI StaticFiles. If Phase 10 uses inline scripts, adapt accordingly.

3. **TTS voice for voice channel vs. WhatsApp**
   - What we know: Phase 8 uses `synapse.json → tts.voice` globally. Phase 11 voice conversations should use the same voice.
   - What's unclear: Whether users will want a different voice for real-time dashboard conversations vs. WhatsApp voice notes.
   - Recommendation: Reuse `synapse.json → tts.voice` in Phase 11. Per-mode voice is a v3.1+ concern.

4. **Groq Whisper language auto-detection vs. hardcoded `en`**
   - What we know: The existing `transcribe_audio()` defaults to `language="auto"`. Groq docs say specifying language improves accuracy.
   - What's unclear: Whether users will speak in languages other than English in real-time voice sessions.
   - Recommendation: Default to `language="en"` for voice channel (lower latency, better accuracy). Expose as `voice.language` config in `synapse.json`.

## Validation Architecture

> nyquist_validation not configured in .planning/config.json — including based on test infrastructure presence.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `workspace/tests/pytest.ini` (exists) |
| Quick run command | `cd workspace && pytest tests/test_voice_*.py -v -x` |
| Full suite command | `cd workspace && pytest tests/ -v --tb=short` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VOICE-01 | WS `voice.start` accepted, `voice.stop` tears down session | unit | `pytest tests/test_voice_session.py -x` | Wave 0 |
| VOICE-02 | VAD `redemptionMs=700` does not cut speech mid-sentence | manual | Browser demo test: 10-utterance recording | Wave 0 (manual) |
| VOICE-03 | `transcribe_bytes()` returns text for valid WAV input | unit | `pytest tests/test_voice_transcription.py -x` | Wave 0 |
| VOICE-04 | TTS chunks arrive as binary WS frames, AudioContext plays them | integration | `pytest tests/test_voice_tts_stream.py -x` | Wave 0 |
| VOICE-05 | `voice.barge_in` cancels active TTS task within 500ms | unit | `pytest tests/test_voice_barge_in.py -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd workspace && pytest tests/test_voice_*.py -v -x`
- **Per wave merge:** `cd workspace && pytest tests/ -v --tb=short`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_voice_session.py` — VoiceSession state machine unit tests
- [ ] `tests/test_voice_transcription.py` — `transcribe_bytes()` unit tests with synthetic WAV
- [ ] `tests/test_voice_tts_stream.py` — TTS streaming task tests (mock edge-tts, mock WebSocket)
- [ ] `tests/test_voice_barge_in.py` — barge-in cancel event tests
- [ ] `tests/test_ws_server_binary.py` — WebSocket server binary frame handling tests
- [ ] `tests/conftest.py` — check if mock WebSocket fixture exists (it may need extension for binary)

## Sources

### Primary (HIGH confidence)
- `workspace/sci_fi_dashboard/gateway/ws_server.py` — existing WebSocket handler code; `receive_text()` limitation confirmed
- `workspace/sci_fi_dashboard/gateway/ws_protocol.py` — existing protocol types; no voice methods yet
- `workspace/sci_fi_dashboard/routes/websocket.py` — existing `/ws` endpoint
- `workspace/sci_fi_dashboard/channels/ids.py` — closed ChannelId set; `"voice"` not yet present
- `workspace/sci_fi_dashboard/media/audio_transcriber.py` — existing Groq Whisper integration
- Phase 8 RESEARCH.md — edge-tts streaming API, TTS architecture confirmed
- [github.com/ricky0123/vad](https://github.com/ricky0123/vad) — MicVAD API, CDN install, Float32Array output
- [docs.vad.ricky0123.com/user-guide/algorithm](https://docs.vad.ricky0123.com/user-guide/algorithm/) — VAD parameters (redemptionMs=1400 default, positiveSpeechThreshold=0.3, preSpeechPadMs=800)
- [github.com/rany2/edge-tts communicate.py](https://github.com/rany2/edge-tts/blob/master/src/edge_tts/communicate.py) — `stream()` async generator yields `{"type": "audio", "data": bytes}`
- [console.groq.com/docs/speech-to-text](https://console.groq.com/docs/speech-to-text) — Groq Whisper batch-only, WAV/OGG/MP3 accepted, 25MB limit

### Secondary (MEDIUM confidence)
- [MDN AudioBufferSourceNode](https://developer.mozilla.org/en-US/docs/Web/API/AudioBufferSourceNode) — `stop()` method, `onended` callback behavior
- [MDN AudioScheduledSourceNode stop()](https://developer.mozilla.org/en-US/docs/Web/API/AudioScheduledSourceNode/stop) — scheduling audio stop
- Medium: "Handling Interruptions in Speech-to-Speech Services" — barge-in patterns, chunked TTS for fast cancellation
- [npmjs.com @ricky0123/vad-web](https://www.npmjs.com/package/@ricky0123/vad-web) — version 0.0.29 confirmed

### Tertiary (LOW confidence)
- WebSearch: MP3 chunk boundary AudioContext decoding behavior — empirical reports, no official spec reference
- WebSearch: edge-tts stream() chunk alignment — implied from source inspection, not documented

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified from official sources; existing codebase confirms Groq and edge-tts integration patterns
- Architecture: HIGH — based on direct reading of existing `ws_server.py`, `ws_protocol.py`, `audio_transcriber.py` in codebase
- Pitfalls: HIGH — AudioContext suspend confirmed by MDN; binary frame handling confirmed by Starlette docs; VAD CORS documented in jsDelivr behavior

**Research date:** 2026-04-09
**Valid until:** 2026-05-09 (stable browser APIs and libraries; vad-web 0.0.29 unlikely to change API in 30 days)
