---
phase: 08-tts-voice-output
plan: 02
subsystem: channels
tags: [whatsapp, baileys, voice-note, ptt, ogg-opus, tts]

# Dependency graph
requires:
  - phase: 08-01
    provides: TTS audio file generation — OGG Opus files served over HTTP that /send-voice consumes
provides:
  - POST /send-voice endpoint in Baileys bridge — sends PTT voice notes with ptt:true and audio/ogg; codecs=opus
  - WhatsAppChannel.send_voice_note(chat_id, audio_url) — Python async method calling the bridge endpoint
affects:
  - 08-03 (api_gateway TTS dispatch — calls send_voice_note to deliver generated audio)
  - 11-realtime-voice (voice pipeline delivery layer)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PTT voice note delivery requires three fields: audio buffer + ptt: true + mimetype: audio/ogg; codecs=opus"
    - "Bridge fetch pattern: AbortSignal.timeout(30000) for audio URL fetching"
    - "send_voice_note follows identical structure to send_media — httpx.AsyncClient, 30s timeout, bool return"

key-files:
  created: []
  modified:
    - baileys-bridge/index.js
    - workspace/sci_fi_dashboard/channels/whatsapp.py

key-decisions:
  - "/send-voice is a separate dedicated endpoint (not a flag on /send) — keeps PTT logic isolated and backward compatible"
  - "30s timeout on both fetch (Node.js) and httpx (Python) — appropriate for audio file transfer through local network"
  - "No auth middleware needed on /send-voice — bridge has no token auth on any endpoint"

patterns-established:
  - "PTT Pattern: audio: buffer, ptt: true, mimetype: 'audio/ogg; codecs=opus' — all three required for WhatsApp earphone icon"

requirements-completed: [TTS-01]

# Metrics
duration: 8min
completed: 2026-04-09
---

# Phase 8 Plan 02: TTS Voice Note Delivery Infrastructure Summary

**PTT voice note delivery added via dedicated /send-voice bridge endpoint and WhatsAppChannel.send_voice_note() — audio/ogg; codecs=opus with ptt: true renders earphone icon and inline waveform in WhatsApp**

## Performance

- **Duration:** 8 min
- **Started:** 2026-04-09T13:09:00Z
- **Completed:** 2026-04-09T13:17:10Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added `POST /send-voice` endpoint to Baileys bridge (Node.js) — fetches audio from URL, sends with `ptt: true` and `mimetype: 'audio/ogg; codecs=opus'` for WhatsApp voice note rendering
- Added `WhatsAppChannel.send_voice_note(chat_id, audio_url)` Python async method that POSTs to the bridge `/send-voice` endpoint
- Both implementations use identical error handling, anti-spam jitter, and connection guard patterns as existing endpoints

## Task Commits

Each task was committed atomically:

1. **Task 1: Add /send-voice endpoint to Baileys bridge** - `6fad012` (feat)
2. **Task 2: Add send_voice_note() to WhatsAppChannel** - `c22a608` (feat)

**Plan metadata:** (final docs commit — TBD)

## Files Created/Modified
- `baileys-bridge/index.js` - Added POST /send-voice endpoint (30 lines) after /send, before /react
- `workspace/sci_fi_dashboard/channels/whatsapp.py` - Added send_voice_note() method (13 lines) after send_media()

## Decisions Made
- `/send-voice` as a separate endpoint (not extending `/send` with a flag) — keeps PTT logic isolated, no risk of breaking existing text/media send
- Both Node.js fetch and Python httpx use 30s timeout — audio files may be several hundred KB, local network transfer is fast but bridge-to-WhatsApp upload can take a moment
- No token auth added to `/send-voice` — bridge has no auth on any endpoint; consistent with all other bridge endpoints

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Voice note delivery infrastructure complete — `send_voice_note()` is ready for 08-03 (api_gateway TTS dispatch) to call
- The chain: TTS generates OGG Opus file (08-01) → api_gateway serves it via /tts/{file} → send_voice_note() delivers it via /send-voice → WhatsApp renders as PTT voice note

---
*Phase: 08-tts-voice-output*
*Completed: 2026-04-09*

## Self-Check: PASSED
- FOUND: baileys-bridge/index.js
- FOUND: workspace/sci_fi_dashboard/channels/whatsapp.py
- FOUND: .planning/phases/08-tts-voice-output/08-02-SUMMARY.md
- FOUND commit: 6fad012 (feat(08-02): add /send-voice PTT voice note endpoint)
- FOUND commit: c22a608 (feat(08-02): add send_voice_note() to WhatsAppChannel)
