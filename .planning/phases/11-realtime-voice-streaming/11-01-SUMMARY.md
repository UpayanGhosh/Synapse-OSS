---
phase: 11-realtime-voice-streaming
plan: 01
subsystem: api
tags: [websocket, voice, audio, tts, edge-tts, groq-whisper, asyncio, dataclass]

# Dependency graph
requires:
  - phase: 08-tts-voice-output
    provides: "transcribe_audio() Groq Whisper wrapper and edge-tts TTS engine patterns"
  - phase: 07-bundled-skills-library
    provides: "BaseChannel ABC and ChannelRegistry for channel registration"
provides:
  - "VoiceSession dataclass with cancel_event, active_tts_task, request_cancel(), reset_cancel()"
  - "VoiceChannel(BaseChannel) adapter registered with channel_id='voice'"
  - "transcribe_bytes() helper for in-memory WAV bytes transcription via Groq Whisper"
  - "WebSocket binary frame handling with 5 MiB size guard"
  - "voice.start / voice.stop / voice.barge_in protocol dispatched in ws_server.py"
  - "TTS streaming as asyncio.Task via edge-tts buffered approach"
  - "VoiceSession cleanup on WebSocket disconnect"
affects:
  - phase: 11-realtime-voice-streaming (plan 02 — browser UI connects to this server backbone)

# Tech tracking
tech-stack:
  added: [edge-tts (already installed from Phase 8), asyncio.to_thread for blocking I/O, tempfile for in-memory bytes]
  patterns:
    - "VoiceSession state machine: create → active_tts_task → request_cancel() → reset_cancel()"
    - "Binary frame reception via websocket.receive() (replaces receive_text() loop)"
    - "asyncio.create_task() for TTS so receive loop remains responsive to barge-in"
    - "cancel_event checked per-chunk in streaming loop — cooperative cancellation"
    - "Buffered TTS: collect all chunks before send_bytes() (Research Pitfall 7)"

key-files:
  created:
    - workspace/sci_fi_dashboard/gateway/voice_session.py
    - workspace/sci_fi_dashboard/channels/voice_channel.py
  modified:
    - workspace/sci_fi_dashboard/channels/ids.py
    - workspace/sci_fi_dashboard/channels/__init__.py
    - workspace/sci_fi_dashboard/gateway/__init__.py
    - workspace/sci_fi_dashboard/gateway/ws_server.py
    - workspace/sci_fi_dashboard/media/audio_transcriber.py

key-decisions:
  - "voice.* methods routed BEFORE _dispatch() in receive loop — voice methods never reach standard JSON RPC handler table"
  - "_dispatch_voice() created as intermediate router for voice.start/stop/barge_in — keeps voice logic cleanly separated"
  - "transcribe_bytes() uses asyncio.to_thread() for both write and unlink — synchronous file I/O must not block event loop"
  - "Buffered TTS (collect all chunks) not streaming chunks — avoids partial audio on barge-in, gives client seekable blob"
  - "VoiceSession cleanup added to handle() finally block — prevents orphaned sessions/tasks on disconnect"
  - "persona_chat() called via lazy import inside _handle_voice_audio — avoids circular imports at module level"
  - "VoiceChannel.receive() raises NotImplementedError with explanation — documents architectural decision explicitly"

patterns-established:
  - "Binary frame handling: websocket.receive() returns dict with 'bytes' key; 'text' key for text frames"
  - "Voice barge-in: cancel_event.is_set() checked per-chunk, asyncio.CancelledError re-raised from TTS task"
  - "Voice session lifecycle: voice.start creates, binary frames use, voice.barge_in interrupts, voice.stop destroys"

requirements-completed: [VOICE-01, VOICE-02, VOICE-03, VOICE-05]

# Metrics
duration: 4min
completed: 2026-04-09
---

# Phase 11 Plan 01: Voice Infrastructure Summary

**Server-side voice WebSocket backbone: VoiceSession state machine, VoiceChannel adapter, binary frame reception with 5 MiB guard, voice.start/stop/barge_in protocol, transcribe_bytes() Groq wrapper, and buffered edge-tts streaming as asyncio.Task**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-09T13:44:46Z
- **Completed:** 2026-04-09T13:49:06Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- VoiceSession dataclass created with cancel/reset lifecycle — powers barge-in cancellation via asyncio.Event
- WebSocket server updated from receive_text() to receive() — handles both binary audio frames and text JSON frames
- transcribe_bytes() helper wraps existing transcribe_audio() for in-memory bytes without disk-path dependency
- voice.start/stop/barge_in protocol fully dispatched — routed before _dispatch() to keep voice separate from standard RPC
- _stream_tts_to_ws() streams edge-tts as buffered single binary frame with cooperative cancel_event check per chunk
- VoiceSession cleanup in handle() finally block prevents orphaned tasks on client disconnect

## Task Commits

Each task was committed atomically:

1. **Task 1: VoiceSession + VoiceChannel + channel IDs** - `4813ebf` (feat)
2. **Task 2: WebSocket binary frame handling + voice protocol + transcribe_bytes** - `9e533b7` (feat)

**Plan metadata:** (pending final docs commit)

## Files Created/Modified

- `workspace/sci_fi_dashboard/gateway/voice_session.py` - VoiceSession dataclass with cancel_event, active_tts_task, request_cancel(), reset_cancel()
- `workspace/sci_fi_dashboard/channels/voice_channel.py` - VoiceChannel(BaseChannel) with channel_id='voice', all 6 abstract methods implemented
- `workspace/sci_fi_dashboard/channels/ids.py` - Added 'voice' to CHANNEL_ORDER tuple and ChannelId Literal
- `workspace/sci_fi_dashboard/channels/__init__.py` - Import + export VoiceChannel
- `workspace/sci_fi_dashboard/gateway/__init__.py` - Import + export VoiceSession
- `workspace/sci_fi_dashboard/gateway/ws_server.py` - Binary frame handling, voice.* dispatch, _handle_voice_audio, _stream_tts_to_ws, session cleanup
- `workspace/sci_fi_dashboard/media/audio_transcriber.py` - Added transcribe_bytes() with asyncio.to_thread() for blocking I/O

## Decisions Made

- voice.* methods routed before _dispatch() — keeps voice protocol separate from standard JSON RPC handler table; _dispatch() is unchanged
- _dispatch_voice() intermediate router created — clean separation, voice.* never sees chat.send handler table
- Buffered TTS (collect all chunks, send one binary frame) — avoids partial audio artifacts on barge-in; matches Research Pitfall 7 guidance
- asyncio.to_thread() for temp file write+unlink in transcribe_bytes() — synchronous file I/O must not block the event loop
- persona_chat() lazy-imported inside _handle_voice_audio — circular import prevention at module level
- VoiceChannel.receive() raises NotImplementedError — makes architectural decision explicit rather than silently swallowing input

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. edge-tts was already installed from Phase 8.

## Next Phase Readiness

- Server-side voice backbone is complete. Plan 02 (browser voice UI) can connect to:
  - `ws://localhost:8000/ws` with voice.start then binary WAV frames
  - voice.transcription events carry transcript back to UI
  - Binary frames from server carry TTS audio
  - voice.barge_in cancels mid-stream AI speech
- No blockers. All verification checks pass.

---
*Phase: 11-realtime-voice-streaming*
*Completed: 2026-04-09*
