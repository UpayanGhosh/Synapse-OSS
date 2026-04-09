---
phase: 08-tts-voice-output
plan: "03"
subsystem: tts-pipeline
tags: [tts, pipeline, background-task, media-store, whatsapp, testing]
dependency_graph:
  requires:
    - phase: 08-01
      provides: TTSEngine (tts/engine.py) and mp3_to_ogg_opus (tts/convert.py)
    - phase: 08-02
      provides: WhatsAppChannel.send_voice_note() and /send-voice bridge endpoint
  provides:
    - _send_voice_note background task (pipeline_helpers.py)
    - TTS Step 7 gate in process_message_pipeline
    - /media/tts_outbound StaticFiles mount (api_gateway.py)
    - test_tts.py — 31 tests covering full TTS stack
  affects:
    - process_message_pipeline() — now dispatches TTS as fire-and-forget after text reply
    - api_gateway.py — new static file mount for OGG delivery
    - Phase 11 (Realtime Voice) — inherits TTS chain established here
tech_stack:
  added: []
  patterns:
    - "TTS dispatched as asyncio.create_task() — fire-and-forget, never blocks pipeline"
    - "Terminal punctuation gate (. ! ? ) ] }) — TTS and auto-continue are mutually exclusive"
    - "All TTS failures are exception-isolated in _send_voice_note — text delivery is never affected"
    - "Deferred imports inside _send_voice_note — graceful degradation when TTS deps absent"
    - "sys.modules stubbing in integration tests — avoids importing heavy deps (pyarrow/lancedb)"
key_files:
  created:
    - workspace/tests/test_tts.py
  modified:
    - workspace/sci_fi_dashboard/pipeline_helpers.py
    - workspace/sci_fi_dashboard/api_gateway.py
decisions:
  - "Terminal punctuation gate used for TTS/auto-continue mutual exclusivity — auto-continue fires when reply lacks terminal punct (cut-off), TTS fires when it has it (complete sentence)"
  - "TTS is WhatsApp-only in this phase — process_message_pipeline is WhatsApp-bound; channel abstraction deferred"
  - "_send_voice_note uses deferred imports (from sci_fi_dashboard.tts import TTSEngine inside the function) to avoid circular import and allow graceful degradation"
  - "Integration tests use sys.modules stubbing to avoid pyarrow/lancedb import chain — realistic wiring tests without requiring optional heavy deps"
  - "Patch path for TTSEngine.synthesize tests is synapse_config.SynapseConfig.load (not sci_fi_dashboard.tts.engine.SynapseConfig) because SynapseConfig is deferred-imported inside synthesize()"
metrics:
  duration_minutes: 10
  completed_date: "2026-04-09"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 2
---

# Phase 08 Plan 03: TTS Pipeline Integration and Tests Summary

**One-liner:** TTS wired into message pipeline as fire-and-forget background task with terminal-punctuation gate, OGG media served via static mount, 31 unit+integration tests covering full stack.

## What Was Built

The TTS pipeline integration connects all Phase 8 components into the live message flow. After every text reply, `process_message_pipeline()` checks three conditions (Step 7): reply is non-empty, TTS is enabled in config, and the reply ends with terminal punctuation. When all three hold, `_send_voice_note()` fires as a background task — calling `TTSEngine.synthesize()`, saving the OGG file to the media store, building a local URL, and delivering via `WhatsAppChannel.send_voice_note()`.

The FastAPI app gains a new `/media/tts_outbound` static file mount that serves the generated OGG files. The Baileys bridge fetches audio from this URL when delivering PTT voice notes.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Wire TTS dispatch into pipeline and add media mount | 19ba471 | pipeline_helpers.py, api_gateway.py |
| 2 | Write unit and integration tests for TTS | efb5afb | tests/test_tts.py |

## Architecture

```
process_message_pipeline()
  ├── Steps 1-6: session, persona_chat, transcript save (unchanged)
  └── Step 7: TTS voice note (fire-and-forget)
        ├── Guard: reply is empty → skip
        ├── Guard: tts.enabled=False → skip
        ├── Guard: reply does NOT end with terminal punct → skip (auto-continue territory)
        └── asyncio.create_task(_send_voice_note(reply, chat_id))
              ├── TTSEngine().synthesize(reply)  [from 08-01]
              │     → OGG Opus bytes | None
              ├── save_media_buffer(ogg_bytes, subdir="tts_outbound")
              │     → ~/.synapse/state/media/tts_outbound/{uuid}.ogg
              ├── audio_url = "http://127.0.0.1:8000/media/tts_outbound/{filename}"
              └── WhatsAppChannel.send_voice_note(chat_id, audio_url)  [from 08-02]
                    → POST /send-voice → Baileys → WhatsApp PTT

api_gateway.py
  └── /media/tts_outbound → StaticFiles(~/.synapse/state/media/tts_outbound/)
```

## Test Coverage

31 tests across 5 classes:

| Class | Tests | What It Covers |
|-------|-------|----------------|
| TestTTSConfig | 2 | SynapseConfig.tts field, default empty dict |
| TestEdgeTTSProvider | 3 | bytes returned, exception handling, ImportError |
| TestElevenLabsProvider | 5 | voice resolution (9 premade + passthrough), synthesize, error |
| TestMP3ToOGGOpus | 3 | FileNotFoundError, nonzero exit, successful conversion |
| TestTTSEngine | 8 | long text skip, disabled, edge-tts dispatch, ElevenLabs dispatch, no API key, empty bytes from provider, empty bytes from converter |
| TestPipelineTTSIntegration | 10 | gate logic (. ! ? ) ) non-terminal skip, disabled skip, empty reply, _send_voice_note wiring, engine returns None, exception isolation |

## Key Design Decisions

1. **Terminal punctuation gate** — TTS fires when reply ends with `.`, `!`, `?`, `"`, `'`, `)`, `]`, `}`. These are complete-sentence signals. Auto-continue fires for all other endings (incomplete replies). The two are mutually exclusive by design.

2. **WhatsApp-only scope** — `process_message_pipeline()` is already WhatsApp-bound in this phase. The `chat_id` is always a WhatsApp JID. Cross-channel TTS is deferred to a future phase.

3. **Exception isolation** — `_send_voice_note` wraps the entire body in `try/except Exception: logger.exception(...)`. Any failure (TTS disabled, ffmpeg absent, bridge down) is logged silently without affecting text message delivery.

4. **Deferred imports in `_send_voice_note`** — `from sci_fi_dashboard.tts import TTSEngine` and `from sci_fi_dashboard.media.store import save_media_buffer` are inside the function body. This avoids circular import at module load time and allows graceful degradation when TTS packages are not installed.

5. **Patch path fix for tests** — `TTSEngine.synthesize()` uses `from synapse_config import SynapseConfig` as a deferred local import. The correct patch target is `synapse_config.SynapseConfig.load`, not `sci_fi_dashboard.tts.engine.SynapseConfig` (which doesn't exist at module level).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TTSEngine test patch path was `sci_fi_dashboard.tts.engine.SynapseConfig` (module-level attr that doesn't exist)**
- **Found during:** Task 2, first test run
- **Issue:** `SynapseConfig` is imported as a deferred local import inside `synthesize()` via `from synapse_config import SynapseConfig`. It is NOT a module-level attribute of `sci_fi_dashboard.tts.engine`. Patching `sci_fi_dashboard.tts.engine.SynapseConfig` raises `AttributeError`.
- **Fix:** Changed all TTSEngine test patches to target `synapse_config.SynapseConfig.load` directly — the actual lookup point.
- **Files modified:** workspace/tests/test_tts.py
- **Commit:** efb5afb (included in Task 2)

**2. [Rule 2 - Missing test robustness] Integration tests importing pipeline_helpers fail due to missing pyarrow**
- **Found during:** Task 2, test run with pipeline_helpers import
- **Issue:** `pipeline_helpers.py` imports `sci_fi_dashboard._deps` at module level, which transitively imports `lancedb_store.py`, which imports `pyarrow` (not installed in CI test environment).
- **Fix:** Used `sys.modules` stubbing in the three `_send_voice_note` integration tests to inject mock `_deps`, `conv_kg_extractor`, `session_ingest`, and `psutil` modules before importing `pipeline_helpers`. This gives realistic wiring tests without requiring the full deps stack.
- **Files modified:** workspace/tests/test_tts.py
- **Commit:** efb5afb (included in Task 2)

## Self-Check

- FOUND: workspace/sci_fi_dashboard/pipeline_helpers.py — contains `_send_voice_note` (line 241) and Step 7 TTS dispatch (line 507)
- FOUND: workspace/sci_fi_dashboard/api_gateway.py — contains `tts_outbound` static mount (line 369)
- FOUND: workspace/tests/test_tts.py — 31 tests, 696 lines
- FOUND commit: 19ba471 (feat(08-03): wire TTS dispatch into pipeline and add media mount)
- FOUND commit: efb5afb (test(08-03): add comprehensive TTS test suite)

## Self-Check: PASSED
