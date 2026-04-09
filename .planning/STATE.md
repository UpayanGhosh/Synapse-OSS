---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: OpenClaw Feature Harvest
status: in_progress
last_updated: "2026-04-09T14:10:11Z"
progress:
  total_phases: 12
  completed_phases: 9
  total_plans: 47
  completed_plans: 44
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-08)

**Core value:** An AI that knows you deeply, grows with you continuously, and reaches out to you first — on your machine, under your full control.
**Current focus:** Phase 6 — LLM Provider Expansion (v3.0 first phase, ready to plan)

## Current Position

Phase: 10 of 12 (Cron Wiring + Web Control Panel) — Complete (all 4 plans done)
Plan: 4 of 4 complete in current phase
Status: In progress
Last activity: 2026-04-09 — Phase 10 Plan 04 complete (29 tests across 3 files: test_cron_wiring.py, test_loopback_middleware.py, test_cron_routes.py)

Progress: [████████░░] 96% (44/47 plans complete)

## Milestone Map

| Milestone | Target | Status | Description |
|-----------|--------|--------|-------------|
| v1.0 | 2026-03-03 | COMPLETE | OSS independence — all OpenClaw deps removed |
| v2.0 | 2026-04-08 | COMPLETE | The Adaptive Core — skills, self-mod, subagents, browser |
| v3.0 | 2026 | CURRENT | OpenClaw Feature Harvest — providers, skills library, TTS, image gen, cron v2, dashboard, voice |
| v4.0 | Future | Planned | The Jarvis Threshold |

## Accumulated Context

### Decisions

- v3.0 phases numbered 6-11 (continuous from v2.0 which ended at Phase 5)
- Phase 10 combines CRON + DASH (9 requirements) — tightly coupled; dashboard panels require TTS/image gen SSE events from Phases 8-9
- Phase 11 (Realtime Voice) is last — highest complexity, depends on Phase 8 TTS chain and Phase 10 dashboard WebSocket
- gpt-image-1 target for Phase 9 (DALL-E 3 deprecated May 12, 2026 — time-sensitive)
- litellm budget-fallback bug (GitHub #10052) patched in Phase 6 — critical correctness dependency for all LLM-reliant phases
- BackgroundTask pattern used for all media outputs (TTS, image gen) — never inline await in persona_chat()
- Vault hemisphere isolation enforced at every cloud-API dispatch point across Phases 8-9
- [06-01] DeepSeek placed in Major Cloud (US) group — USD pricing, globally accessible; not Chinese Providers
- [06-01] deepseek/deepseek-chat chosen as validation model; deepseek-reasoner excluded (special response format not yet handled)
- [06-01] together_ai key renamed to togetherai in synapse.json.example to match _KEY_MAP contract (was silently dropping Together AI keys)
- [06-01] budget_usd/budget_duration documented on openai entry as canonical example for PROV-02 budget enforcement
- [06-02] BudgetExceededError import-guarded for older litellm version compatibility — placeholder class never matches real exceptions so except clause is inert on old versions
- [06-02] Budget check uses token count as USD proxy (1M tokens ~$1) — safety net, not billing system; avoids per-model pricing tables that change frequently
- [06-02] get_provider_spend() is non-fatal (returns zeros on error) so DB issues never block LLM calls
- [06-02] Fallback uses model_mappings.get(role).get('fallback') NOT self._router.model_list to avoid litellm Router internal coupling
- [Phase 07-bundled-skills-library]: cloud_safe defaults to True — all existing skills are cloud_safe by default; only new bundled cloud-API skills need to explicitly set False
- [Phase 07-bundled-skills-library]: synapse.* namespace reserved for bundled skills; user skills shadowing them trigger startup WARNING (not error) — both load but user is informed
- [Phase 06-llm-provider-expansion]: BudgetExceededError must be raised with (current_cost, max_budget, message) signature matching litellm.exceptions.BudgetExceededError — production code was passing a single string and was fixed
- [Phase 06-llm-provider-expansion]: qianfan is an intentional _KEY_MAP divergence — provider_steps only, not in llm_router._KEY_MAP; encoded as _PS_ONLY_KEYS in test for documentation
- [Phase 08-tts-voice-output]: /send-voice is a separate dedicated endpoint (not a flag on /send) — keeps PTT logic isolated, no risk of breaking existing text/media send
- [Phase 08-tts-voice-output]: PTT voice note requires three fields: audio buffer + ptt: true + mimetype: 'audio/ogg; codecs=opus' — all three required for WhatsApp earphone icon rendering
- [Phase 09-image-generation]: IMAGE placed first in traffic cop prompt; negative examples prevent false-positive classification of 'draw up a plan', 'create a document'
- [Phase 09-image-generation]: IMAGE branch uses early return placeholder — Plan 03 replaces with BackgroundTask dispatch; STRATEGY_TO_ROLE unchanged
- [Phase 08-tts-voice-output]: edge-tts is default TTS provider — zero credentials, works out-of-the-box without tts config in synapse.json
- [Phase 08-tts-voice-output]: ElevenLabs API key read from SynapseConfig.providers directly (not os.environ) to avoid init-time ordering dependency with LLMRouter
- [Phase 08-tts-voice-output]: Terminal punctuation gate (. ! ? ) ] }) makes TTS and auto-continue mutually exclusive — auto-continue fires for non-terminal replies (cut-off), TTS fires for terminal replies (complete)
- [Phase 08-tts-voice-output]: Patch path for TTSEngine tests is synapse_config.SynapseConfig.load (deferred local import inside synthesize()), not sci_fi_dashboard.tts.engine.SynapseConfig
- [Phase 09-image-generation]: gpt-image-1 always returns b64_json — never URL, response_format param omitted; openai and fal-client are lazy-imported inside provider functions to keep them optional
- [Phase 09-image-generation]: ImageGenEngine API key validation in engine helpers (_generate_openai/_generate_fal), not in provider functions — provider functions are pure and testable
- [Phase 09-image-generation]: IMAGE branch Vault block is defense-in-depth; spicy sessions caught at outer vault routing (line 622) before reaching IMAGE — IMAGE Vault check guards future bypass paths
- [Phase 09-image-generation]: save_media_buffer() wrapped in asyncio.to_thread() — synchronous file I/O (os.open, os.replace, os.chmod) must not block the event loop
- [Phase 09-image-generation]: channel_id hardcoded to 'whatsapp' inside _generate_and_send_image() — persona_chat() has no channel_id scope; matches continue_conversation() default at pipeline_helpers.py:151
- [Phase 11-realtime-voice-streaming/11-02]: redemptionMs set to 700ms per VOICE-02 requirement (plan overrides research default of 1400ms)
- [Phase 11-realtime-voice-streaming/11-02]: ws.binaryType forced to arraybuffer in startVoice() — eliminates Blob conversion overhead for streaming MP3 chunks
- [Phase 11-realtime-voice-streaming/11-02]: Barge-in guard re-checks isAISpeaking in scheduleAudioChunk after async decodeAudioData — prevents playing decoded chunk if barge-in fired during decode
- [Phase 11-realtime-voice-streaming/11-02]: Transcription exposed as CustomEvent("synapse:transcription") on window — zero DOM coupling from voice.js
- [Phase 11-realtime-voice-streaming/11-02]: handleWSMessage is passive — dashboard's existing ws.onmessage delegates to it; voice.js never patches global WS

- [Phase 10-cron-wiring/10-01]: session_key added as explicit Optional field to ChatRequest — persona_chat already uses getattr fallback, field just makes it type-safe
- [Phase 10-cron-wiring/10-01]: timeout_seconds passed via **kwargs in execute_fn — CronPayload.timeout_seconds flows through to asyncio.wait_for without leaking into ChatRequest
- [Phase 10-cron-wiring/10-01]: All three SSE emitter calls use lazy try-import inside try/except — emitter optional, cron never blocked by dashboard unavailability
- [Phase 10-cron-wiring/10-01]: old cron_service.py file retained — only api_gateway.py import replaced; tests referencing old file not broken
- [Phase 10-cron-wiring-web-control-panel]: LoopbackOnlyMiddleware registered after BodySizeLimitMiddleware — Starlette LIFO order means it runs before body-size check
- [Phase 10-cron-wiring-web-control-panel]: routes/cron.py serializes jobs as plain dicts — cron_service.py stores jobs as JSON dicts loaded from file
- [Phase 10-cron-wiring-web-control-panel/10-03]: Dashboard memory stats fetched from /persona/status (not /persona/summary which doesn't exist) — response has memory_db field with documents/atomic_facts/entity_links
- [Phase 10-cron-wiring-web-control-panel/10-03]: Routing decisions panel driven by llm.route SSE event (not pipeline.run_done) — llm.route carries role+model in current codebase; pipeline.run_done added as forward-compat fallback
- [Phase 10-cron-wiring-web-control-panel/10-03]: formatSchedule() handles both CronSchedule objects (cron/service.py) and legacy schedule strings (cron_service.py) for dual-format compatibility
- [Phase 10-cron-wiring-web-control-panel/10-04]: SSE emission tests patch sci_fi_dashboard.pipeline_emitter.get_emitter (not cron.service.get_emitter) — lazy import inside _execute_job() means the source module is the correct patch target
- [Phase 10-cron-wiring-web-control-panel/10-04]: LoopbackOnlyMiddleware tests use direct dispatch() calls with mock request.client.host — TestClient uses 'testclient' hostname not '127.0.0.1', bypassing the loopback check
- [Phase 10-cron-wiring-web-control-panel/10-04]: _require_gateway_auth patched via synapse_config.SynapseConfig.load — lazy import inside function body means patch must target the source module, not the middleware module

### Pending Todos

- Phase 2 (v2.0): 02-06-PLAN.md integration tests still pending
- Merge develop → main for v2.0 release

### Blockers/Concerns

None active.

## Session Continuity

Last session: 2026-04-09 (Phase 10 Plan 04 execution)
Stopped at: Completed 10-04-PLAN.md — 29 tests for all Phase 10 requirements (CRON-01-04, DASH-01, DASH-02, DASH-04, DASH-05)
Resume file: None
Next step: Phase 11 — Realtime Voice Streaming
