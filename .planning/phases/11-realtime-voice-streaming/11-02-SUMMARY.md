---
phase: 11-realtime-voice-streaming
plan: 02
subsystem: ui
tags: [vad-web, silero-vad, onnxruntime-web, web-audio-api, audiobuffersourcenode, websocket, wav-encoding, barge-in, voice, javascript]

# Dependency graph
requires:
  - phase: 11-realtime-voice-streaming/11-01
    provides: ws_server.py voice.* method handlers and binary frame protocol
  - phase: 10-cron-dash
    provides: WebSocket endpoint /ws and existing dashboard HTML

provides:
  - window.SynapseVoice browser module (startVoice, stopVoice, handleWSMessage, getState)
  - Silero VAD via @ricky0123/vad-web CDN with 700ms redemptionMs
  - float32ToWav: PCM-16 mono WAV encoder from Float32Array (16kHz)
  - AudioContext scheduled playback queue using AudioBufferSourceNode chain
  - Barge-in: stops all active sources + sends voice.barge_in WS message
  - Tab-close cleanup via beforeunload

affects:
  - dashboard HTML (Phase 10) — must add CDN script tags and wire button onclick to SynapseVoice.startVoice(ws)

# Tech tracking
tech-stack:
  added:
    - "@ricky0123/vad-web@0.0.29 (CDN) — Silero VAD in-browser via ONNX Runtime WASM"
    - "onnxruntime-web@1.22.0 (CDN) — required peer dependency for vad-web"
  patterns:
    - "Scheduled AudioBufferSourceNode chain — gapless TTS chunk playback without timer polling"
    - "ws.binaryType = arraybuffer — zero-copy binary frame handling for audio data"
    - "onended = null before stop() — prevents stale callback race on barge-in"
    - "CDN-guard pattern — typeof vad !== undefined check before initializing optional CDN lib"

key-files:
  created:
    - workspace/sci_fi_dashboard/static/dashboard/voice.js
  modified: []

key-decisions:
  - "redemptionMs set to 700ms per VOICE-02 requirement (plan specifies 700, research default is 1400 — plan wins)"
  - "ws.binaryType forced to arraybuffer in startVoice() — eliminates Blob conversion overhead for streaming MP3"
  - "handleWSMessage is passive — dashboard wires its own ws.onmessage and delegates to this; no patching of global WS"
  - "CustomEvent synapse:transcription dispatched on window for transcription text — zero DOM coupling from voice.js"
  - "decodeAudioData uses Promise path (not callback) — modern browsers; callback form noted as fallback in comments"
  - "Barge-in guard checks isAISpeaking in scheduleAudioChunk after decode completes — prevents playing decoded chunk if barge-in fired during async decode"

patterns-established:
  - "SynapseVoice module pattern: no DOM manipulation, pure API surface on window — dashboard HTML owns DOM"
  - "console.log prefix [SynapseVoice] on all log lines for grep-ability"

requirements-completed: [VOICE-01, VOICE-02, VOICE-04, VOICE-05]

# Metrics
duration: 8min
completed: 2026-04-09
---

# Phase 11 Plan 02: Browser-Side Voice Module Summary

**Silero VAD + AudioContext TTS playback + barge-in handler in a self-contained voice.js with window.SynapseVoice API**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-09T13:44:42Z
- **Completed:** 2026-04-09T13:52:00Z
- **Tasks:** 1 of 1
- **Files modified:** 1 (created)

## Accomplishments

- Self-contained 407-line `voice.js` module — no DOM dependencies, pure API surface
- Float32-to-WAV encoder (RIFF/PCM-16 mono, 44-byte header) ready for Groq Whisper on server
- Silero VAD initialized via `@ricky0123/vad-web` CDN with conservative 700ms redemptionMs (VOICE-02)
- AudioContext scheduled playback chain: gapless MP3 chunk queuing via `nextStartTime` cursor
- Barge-in: `stopAllTTSPlayback()` clears `onended` before `stop()` (prevents stale callback race), then sends `voice.barge_in` WS message
- `ws.binaryType = "arraybuffer"` set in `startVoice()` for zero-copy binary frame handling

## Task Commits

Each task was committed atomically:

1. **Task 1: Create voice.js — VAD + WAV encoder + WS voice protocol** - `9e3669a` (feat)

**Plan metadata:** (committed with docs below)

## Files Created/Modified

- `workspace/sci_fi_dashboard/static/dashboard/voice.js` — Complete browser-side voice module: VAD init, WAV encoding, AudioContext playback queue, barge-in, cleanup (407 lines)

## Decisions Made

- `redemptionMs: 700` per VOICE-02 (plan overrides research default of 1400ms)
- `ws.binaryType = "arraybuffer"` set in `startVoice()` — eliminates Blob-to-ArrayBuffer conversion on every incoming MP3 chunk
- Barge-in guard in `scheduleAudioChunk()` re-checks `isAISpeaking` after async `decodeAudioData` — handles the race where barge-in fires during decode
- Transcription exposed as `CustomEvent("synapse:transcription")` on `window` — dashboard can `addEventListener` without voice.js touching DOM
- `handleWSMessage` is passive — dashboard's existing `ws.onmessage` delegates to it; voice.js never patches global WS

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required beyond CDN scripts already specified in plan.

**Integration note:** To activate voice in the dashboard, the HTML must:
1. Add CDN scripts before `voice.js`:
   ```html
   <script src="https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/ort.wasm.min.js"></script>
   <script src="https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.29/dist/bundle.min.js"></script>
   <script src="/static/dashboard/voice.js"></script>
   ```
2. Wire "Start Voice" button: `SynapseVoice.startVoice(ws)` (must be in click handler)
3. Route inbound WS messages: `if (SynapseVoice.getState().isActive) SynapseVoice.handleWSMessage(event)`

## Next Phase Readiness

- Browser-side voice module complete — client half of full-duplex voice loop is ready
- Waiting on Phase 11 server-side (Plan 01: ws_server.py voice handlers + VoiceChannel + VoiceSession) to complete the loop
- Dashboard HTML integration (Phase 10) needs CDN script tags + button wiring added

---
*Phase: 11-realtime-voice-streaming*
*Completed: 2026-04-09*
