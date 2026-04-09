---
phase: 08-tts-voice-output
verified: 2026-04-09T14:30:00Z
status: passed
score: 11/11 must-haves verified
re_verification: false
---

# Phase 8: TTS Voice Output Verification Report

**Phase Goal:** Users receive voice replies as playable WhatsApp voice notes. edge-tts is the zero-cost default (400+ voices, no API key). ElevenLabs is available for premium opt-in. TTS never blocks the chat pipeline.
**Verified:** 2026-04-09T14:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                           | Status     | Evidence                                                                                                                       |
|----|-------------------------------------------------------------------------------------------------|------------|--------------------------------------------------------------------------------------------------------------------------------|
| 1  | TTSEngine.synthesize(text) returns OGG Opus bytes for any input under 400 chars                 | VERIFIED   | `engine.py` line 53 guards on MAX_TTS_CHARS=400; pipeline: EdgeTTS→MP3→ffmpeg→OGG Opus via `mp3_to_ogg_opus()`               |
| 2  | edge-tts is the default provider when no tts.provider is configured                             | VERIFIED   | `engine.py` line 71: `tts_cfg.get("provider", "edge-tts")`; `EdgeTTSProvider` used when provider absent or unrecognised       |
| 3  | ElevenLabs provider works when tts.provider is 'elevenlabs' and API key is available            | VERIFIED   | `engine.py` lines 77–85: explicit "elevenlabs" branch reads api_key from `cfg.providers.elevenlabs.api_key`; key required     |
| 4  | synapse.json tts.voice key controls which voice is used for synthesis                           | VERIFIED   | `engine.py` line 72: `voice = tts_cfg.get("voice", "en-US-AriaNeural")` passed to both providers                              |
| 5  | ffmpeg absence is detected gracefully with a clear error log, not a crash                       | VERIFIED   | `convert.py` lines 65–71: separate `FileNotFoundError` catch logs actionable install instructions, returns `b""`              |
| 6  | Baileys bridge /send-voice endpoint sends audio with ptt: true and mimetype audio/ogg;codecs=opus | VERIFIED | `baileys-bridge/index.js` lines 445–449: `audio: buffer, ptt: true, mimetype: 'audio/ogg; codecs=opus'` — all three fields present |
| 7  | WhatsAppChannel.send_voice_note() POSTs to bridge /send-voice endpoint                         | VERIFIED   | `whatsapp.py` lines 420–431: posts to `http://127.0.0.1:{port}/send-voice` with `{jid, audioUrl}`; returns bool               |
| 8  | TTS synthesis fires as a background task and never blocks the chat pipeline                     | VERIFIED   | `pipeline_helpers.py` line 507: `asyncio.create_task(_send_voice_note(...))` fire-and-forget; `_background_tasks` set used    |
| 9  | TTS and auto-continue are mutually exclusive (terminal punctuation gate)                        | VERIFIED   | `pipeline_helpers.py` lines 502–506: TTS fires only when reply ends with `.!?"')]}`; auto-continue fires for all other endings |
| 10 | OGG audio files are saved to media store and served via local URL for bridge fetch              | VERIFIED   | `pipeline_helpers.py` lines 253–260: `save_media_buffer(..., subdir="tts_outbound")`; URL built as `http://127.0.0.1:8000/media/tts_outbound/{name}` |
| 11 | Tests verify TTSEngine, mp3_to_ogg_opus, and pipeline integration                              | VERIFIED   | `test_tts.py`: 31 tests across 6 classes (696 lines); covers config, EdgeTTS, ElevenLabs, MP3→OGG, TTSEngine, pipeline gates  |

**Score:** 11/11 truths verified

---

### Required Artifacts

| Artifact                                                     | Expected                                       | Status     | Details                                                                 |
|--------------------------------------------------------------|------------------------------------------------|------------|-------------------------------------------------------------------------|
| `workspace/sci_fi_dashboard/tts/__init__.py`                 | Re-exports TTSEngine, mp3_to_ogg_opus          | VERIFIED   | Lines 18–21: explicit re-exports; `__all__` defined                     |
| `workspace/sci_fi_dashboard/tts/engine.py`                   | TTSEngine with synthesize() returning OGG Opus | VERIFIED   | 107 lines; full dispatch logic, guards, logging — no stubs              |
| `workspace/sci_fi_dashboard/tts/convert.py`                  | mp3_to_ogg_opus() async transcode              | VERIFIED   | 84 lines; asyncio subprocess, ffmpeg args, error branches all present   |
| `workspace/sci_fi_dashboard/tts/providers/__init__.py`       | Re-exports EdgeTTSProvider, ElevenLabsProvider | VERIFIED   | 6 lines; explicit re-exports                                            |
| `workspace/sci_fi_dashboard/tts/providers/edge.py`           | EdgeTTSProvider.synthesize() → MP3 bytes       | VERIFIED   | 52 lines; deferred import, temp file pattern, error handling            |
| `workspace/sci_fi_dashboard/tts/providers/elevenlabs.py`     | ElevenLabsProvider.synthesize() → MP3 bytes   | VERIFIED   | 87 lines; 9-voice premade dict, resolve_voice_id(), async generator collection |
| `workspace/synapse_config.py`                                | tts dict field on SynapseConfig                | VERIFIED   | Line 108: `tts: dict = field(default_factory=dict)`; load() wired at lines 141, 165, 196 |
| `baileys-bridge/index.js`                                    | POST /send-voice with ptt: true                | VERIFIED   | Lines 427–455: complete endpoint, connection guard, jitter, fetch, PTT send |
| `workspace/sci_fi_dashboard/channels/whatsapp.py`            | send_voice_note() method                       | VERIFIED   | Lines 420–431: async method, httpx POST, bool return, error handling    |
| `workspace/sci_fi_dashboard/pipeline_helpers.py`             | _send_voice_note background task + Step 7 gate | VERIFIED   | Lines 241–269 (function) + 495–509 (Step 7 gate)                       |
| `workspace/sci_fi_dashboard/api_gateway.py`                  | Static mount at /media/tts_outbound            | VERIFIED   | Lines 364–369: `_tts_media_dir.mkdir(parents=True, exist_ok=True)` + mount |
| `workspace/tests/test_tts.py`                                | 80+ line test file covering full TTS stack     | VERIFIED   | 696 lines, 31 tests, 6 test classes                                     |
| `requirements.txt` (root)                                    | edge-tts>=7.0.0 and elevenlabs>=1.0.0          | VERIFIED   | Lines 65–66; plan said `workspace/requirements.txt` but root file is the correct monorepo location; ffmpeg documented at line 10 |

---

### Key Link Verification

| From                            | To                                       | Via                                            | Status  | Details                                                                                    |
|---------------------------------|------------------------------------------|------------------------------------------------|---------|--------------------------------------------------------------------------------------------|
| `tts/engine.py`                 | `tts/providers/edge.py`                  | `EdgeTTSProvider` dispatch on config           | WIRED   | Line 93: `EdgeTTSProvider().synthesize(text, voice)` in else-branch                        |
| `tts/engine.py`                 | `tts/convert.py`                         | `mp3_to_ogg_opus()` transcodes MP3→OGG         | WIRED   | Line 24 import + line 100: `ogg_bytes = await mp3_to_ogg_opus(mp3_bytes)`                 |
| `tts/engine.py`                 | `synapse_config.py`                      | `SynapseConfig.load().tts`                     | WIRED   | Lines 62–65: deferred import + `cfg = SynapseConfig.load(); tts_cfg: dict = cfg.tts`      |
| `channels/whatsapp.py`          | `baileys-bridge/index.js`                | HTTP POST to `/send-voice`                     | WIRED   | Line 425: `f"http://127.0.0.1:{self._port}/send-voice"` with `{"jid", "audioUrl"}` body   |
| `pipeline_helpers.py`           | `tts/engine.py`                          | `TTSEngine().synthesize()` in background task  | WIRED   | Lines 244, 247–248: deferred import + `engine.synthesize(reply)`                           |
| `pipeline_helpers.py`           | `media/store.py`                         | `save_media_buffer(..., subdir="tts_outbound")` | WIRED  | Lines 245, 253–257: deferred import + call with `content_type="audio/ogg"`                |
| `pipeline_helpers.py`           | `channels/whatsapp.py`                   | `send_voice_note(chat_id, audio_url)`          | WIRED   | Lines 263–265: registry lookup + `hasattr` guard + `await wa_channel.send_voice_note(...)` |
| `api_gateway.py`                | `tts_outbound` media store directory     | `StaticFiles` mount at `/media/tts_outbound`   | WIRED   | Lines 367–369: `_tts_media_dir` created + mounted                                          |

---

### Requirements Coverage

| Requirement | Source Plan(s) | Description                                                         | Status    | Evidence                                                                                   |
|-------------|----------------|---------------------------------------------------------------------|-----------|--------------------------------------------------------------------------------------------|
| TTS-01      | 08-02, 08-03   | User receives voice replies as playable WhatsApp voice notes (OGG)  | SATISFIED | Bridge /send-voice + send_voice_note() + pipeline dispatch chain fully wired               |
| TTS-02      | 08-01          | edge-tts is the default TTS provider (zero API key, 400+ voices)    | SATISFIED | `tts_cfg.get("provider", "edge-tts")` — EdgeTTSProvider used by default, no key needed    |
| TTS-03      | 08-01          | ElevenLabs is available as premium opt-in TTS provider              | SATISFIED | ElevenLabsProvider with 9-voice dict, api_key read from config, graceful no-key skip       |
| TTS-04      | 08-03          | TTS runs as BackgroundTask — never blocks the chat pipeline          | SATISFIED | `asyncio.create_task(_send_voice_note(...))` with done callback; pipeline returns before TTS completes |
| TTS-05      | 08-01          | User can configure preferred voice in synapse.json                  | SATISFIED | `tts_cfg.get("voice", "en-US-AriaNeural")` — voice passed to both EdgeTTS and ElevenLabs providers |

No orphaned requirements detected. All 5 TTS-* requirements are claimed by plans and verified in the codebase.

---

### Anti-Patterns Found

No anti-patterns detected across all phase 8 modified files:

- No TODO/FIXME/PLACEHOLDER comments in TTS package, pipeline, bridge, or channel files
- No stub implementations (all return paths carry real logic or graceful fallback `b""` / `None` with logging)
- No empty handlers or `console.log`-only implementations
- No `return {}` or `return []` standing in for unimplemented logic

---

### Human Verification Required

#### 1. WhatsApp Earphone Icon Rendering

**Test:** Send a message to a live Synapse instance with TTS enabled and ffmpeg installed. Observe the received message in WhatsApp.
**Expected:** Message appears with the microphone/earphone icon and an inline waveform (PTT format), not as a generic audio file attachment.
**Why human:** PTT rendering is determined by WhatsApp's client-side logic based on `ptt: true` and `mimetype: "audio/ogg; codecs=opus"`. The bridge sends the correct payload but actual UI rendering requires a live WhatsApp connection.

#### 2. Voice Audibility and Quality

**Test:** Play the received voice note in WhatsApp.
**Expected:** Clear speech in the configured voice (default: en-US-AriaNeural), no audio artifacts, appropriate duration for the text.
**Why human:** Audio quality depends on edge-tts network availability, ffmpeg libopus encoding quality, and WhatsApp's audio player. Cannot be verified programmatically.

#### 3. ElevenLabs Premium Voice Quality (Opt-in)

**Test:** Configure `tts.provider = "elevenlabs"` with a valid API key, send a message.
**Expected:** Voice note uses ElevenLabs voice quality, notably better than edge-tts.
**Why human:** Requires a live ElevenLabs API key and subjective audio quality assessment.

---

### Note: requirements.txt Path Deviation

The plan specified `workspace/requirements.txt` as the target file for edge-tts and elevenlabs dependencies. The implementation correctly placed them in the project-root `requirements.txt` (lines 65–66 with ffmpeg comment at line 10). This is the correct location — the workspace directory does not have its own requirements file. This is an acceptable deviation with no functional impact.

---

## Summary

Phase 8 goal is fully achieved. All three sub-plans delivered their artifacts and wiring:

- **Plan 01** (TTS Engine): `tts/` package with TTSEngine, EdgeTTSProvider, ElevenLabsProvider, and `mp3_to_ogg_opus()`. SynapseConfig extended with `tts` field.
- **Plan 02** (Delivery Infrastructure): Baileys bridge `/send-voice` endpoint and `WhatsAppChannel.send_voice_note()` method, both correctly implementing the PTT three-field requirement.
- **Plan 03** (Pipeline Integration): `_send_voice_note` background task wired into `process_message_pipeline` Step 7 with terminal-punctuation gate ensuring mutual exclusivity with auto-continue. FastAPI static mount serves OGG files. 31 tests (696 lines) covering the full stack.

The complete delivery chain is verified end-to-end:
```
reply text
  → Step 7 gate (terminal punct + enabled check)
    → asyncio.create_task(_send_voice_note)          [non-blocking]
        → TTSEngine.synthesize()
            → EdgeTTSProvider OR ElevenLabsProvider  → MP3 bytes
            → mp3_to_ogg_opus()                      → OGG Opus bytes
        → save_media_buffer(subdir="tts_outbound")
        → http://127.0.0.1:8000/media/tts_outbound/{file}
        → WhatsAppChannel.send_voice_note(chat_id, url)
            → POST /send-voice {jid, audioUrl}
                → Baileys sock.sendMessage({audio, ptt:true, mimetype})
                    → WhatsApp PTT voice note
```

---

_Verified: 2026-04-09T14:30:00Z_
_Verifier: Claude (gsd-verifier)_
