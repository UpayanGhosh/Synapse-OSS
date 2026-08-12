---
phase: 08-tts-voice-output
plan: "01"
subsystem: tts
tags: [tts, audio, voice, edge-tts, elevenlabs, ffmpeg, synapse-config]
dependency_graph:
  requires: []
  provides:
    - TTSEngine (sci_fi_dashboard/tts/engine.py)
    - mp3_to_ogg_opus (sci_fi_dashboard/tts/convert.py)
    - EdgeTTSProvider (sci_fi_dashboard/tts/providers/edge.py)
    - ElevenLabsProvider (sci_fi_dashboard/tts/providers/elevenlabs.py)
    - SynapseConfig.tts field (synapse_config.py)
  affects:
    - Any code that calls SynapseConfig.load() (tts field now present)
    - Phase 08-02 (voice note delivery) which imports TTSEngine
tech_stack:
  added:
    - edge-tts>=7.0.0 (Microsoft Edge neural TTS, zero credentials)
    - elevenlabs>=1.0.0 (ElevenLabs premium TTS SDK)
    - ffmpeg (system binary, documented in requirements.txt comment)
  patterns:
    - Deferred third-party imports inside methods for graceful ImportError handling
    - asyncio.create_subprocess_exec for non-blocking ffmpeg transcode
    - Hardcoded premade voice dict to avoid per-call ElevenLabs /voices API lookups
    - MAX_TTS_CHARS guard skips TTS on messages >400 chars
key_files:
  created:
    - workspace/sci_fi_dashboard/tts/__init__.py
    - workspace/sci_fi_dashboard/tts/engine.py
    - workspace/sci_fi_dashboard/tts/convert.py
    - workspace/sci_fi_dashboard/tts/providers/__init__.py
    - workspace/sci_fi_dashboard/tts/providers/edge.py
    - workspace/sci_fi_dashboard/tts/providers/elevenlabs.py
  modified:
    - workspace/synapse_config.py (tts dict field added)
    - requirements.txt (edge-tts, elevenlabs added; ffmpeg system dep commented)
decisions:
  - edge-tts default provider requires zero config — TTSEngine works out-of-the-box without synapse.json tts key
  - ElevenLabs API key read directly from SynapseConfig.providers (not os.environ) per Pitfall 5 in research doc
  - ffmpeg FileNotFoundError caught separately with clear actionable log message — graceful degradation not crash
  - image_gen field was already present in synapse_config.py from Phase 9 plan execution; tts field added after it
metrics:
  duration_minutes: 2
  completed_date: "2026-04-09"
  tasks_completed: 2
  tasks_total: 2
  files_created: 6
  files_modified: 2
---

# Phase 08 Plan 01: TTS Synthesis Engine Summary

**One-liner:** TTS synthesis engine with edge-tts default + ElevenLabs opt-in, producing OGG Opus bytes via async ffmpeg transcode.

## What Was Built

The `workspace/sci_fi_dashboard/tts/` package provides the audio generation core for Phase 8 TTS voice output. It accepts text and returns WhatsApp-compatible OGG Opus bytes through a two-stage pipeline: (1) synthesis via edge-tts or ElevenLabs, (2) transcoding from MP3 to OGG Opus via async ffmpeg subprocess.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create TTS providers and converter | 069d7f4 | tts/__init__.py, engine.py, convert.py, providers/edge.py, providers/elevenlabs.py, providers/__init__.py |
| 2 | Add TTS config to SynapseConfig and update requirements.txt | aec7af9 | synapse_config.py, requirements.txt |

## Architecture

```
TTSEngine.synthesize(text)
  ├── Guard: len(text) > 400 → return None
  ├── Load SynapseConfig.tts (provider, voice, enabled)
  ├── provider == "edge-tts" (default)
  │     └── EdgeTTSProvider.synthesize(text, voice)
  │           → edge_tts.Communicate(text, voice).save(tmp.mp3)
  │           → returns MP3 bytes
  ├── provider == "elevenlabs"
  │     → reads api_key from cfg.providers.elevenlabs.api_key
  │     └── ElevenLabsProvider.synthesize(text, voice, api_key)
  │           → resolve_voice_id("Rachel") → "21m00Tcm4TlvDq8ikWAM"
  │           → AsyncElevenLabs.text_to_speech.convert(...)
  │           → returns MP3 bytes
  └── mp3_to_ogg_opus(mp3_bytes)
        → asyncio.create_subprocess_exec("ffmpeg", ..., "-c:a", "libopus", ...)
        → returns OGG Opus bytes (WhatsApp PTT compatible)
```

## Key Design Decisions

1. **Deferred imports everywhere** — `edge_tts` and `elevenlabs` imports happen inside methods. Users without these packages installed get a clear error log, not an ImportError at startup.

2. **Hardcoded ElevenLabs voice dict** — 9 premade voices (Rachel, Josh, Sam, Bella, Adam, Elli, Arnold, Domi, Antoni) with their voice IDs. Pass-through for unknown names allows raw voice_id usage. Avoids 200ms+ /voices API call per synthesis.

3. **ffmpeg FileNotFoundError treated specially** — Separate catch for `FileNotFoundError` produces a clear, actionable message with install commands for apt/brew/winget. Other errors produce a generic error log. Both return `b""` for graceful degradation.

4. **ElevenLabs key from config, not os.environ** — Per Phase 8 research Pitfall 5: `_inject_provider_keys()` runs at LLMRouter init time, not TTS engine init. TTSEngine calls `SynapseConfig.load()` directly and reads `providers.elevenlabs.api_key`.

5. **SynapseConfig.tts added after image_gen** — synapse_config.py had already been extended with `image_gen` field by Phase 9 plan execution. The `tts` field was added after it, maintaining the chronological field ordering pattern.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Existing field] synapse_config.py already had image_gen field from Phase 9**
- **Found during:** Task 2
- **Issue:** The plan context showed the dataclass without `image_gen`, but Phase 9 plan execution had already added it. The `tts` field needed to be added after `image_gen`, not after `kg_extraction`.
- **Fix:** Added `tts` field and all three wiring points (init var, raw.get(), cls() kwarg) after the corresponding `image_gen` lines.
- **Files modified:** workspace/synapse_config.py
- **Impact:** Trivial — pattern identical, just different insertion point.

## Self-Check: PASSED

All 6 created files exist on disk. Both task commits (069d7f4, aec7af9) verified in git log.
