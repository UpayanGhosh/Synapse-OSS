# Project Research Summary

**Project:** Synapse-OSS v3.0 — OpenClaw Feature Harvest
**Domain:** Self-hosted personal AI middleware (FastAPI + litellm + asyncio)
**Researched:** 2026-04-08
**Confidence:** HIGH

## Executive Summary

Synapse v3.0 is not a greenfield build — it is a capability harvest onto an already mature v2.0 foundation. The research makes clear that the vast majority of required infrastructure (litellm routing, skills framework, CronService, SSE pipeline emitter, Baileys audio bridge, MemoryEngine) is already present and production-ready. What v3.0 adds is configuration exposure, content modules (10 bundled skills as SKILL.md directories), and three new capability chains (TTS voice output, image generation, and realtime voice streaming). The highest-leverage work is enabling features that are 70-80% built but not yet wired or documented.

The recommended approach is additive and dependency-ordered: start with zero-risk config work (provider routing), layer on content work (skills library), then build the two independent media output chains (TTS, image gen) before tackling operational visibility (dashboard + cron wiring), and defer the highest-complexity feature (realtime voice streaming) to the final phase. Every phase delivers immediate user-visible value while setting up the next. The architecture pattern is consistent throughout: provider ABC with lifespan-gated init, BackgroundTask delivery for all media outputs, and additive-only changes to high-fanout files like `synapse_config.py` and `api_gateway.py`.

The key risks cluster around three areas: (1) litellm's budget/rate-limit fallback is silently broken and must be manually patched in Phase 1; (2) TTS and image generation will serialize the chat pipeline if not correctly dispatched as BackgroundTasks; and (3) the Vault hemisphere isolation contract must be enforced explicitly in every new cloud-API-calling feature. None of these are blockers — they are known pitfalls with clear mitigation patterns documented in the research.

---

## Key Findings

### Recommended Stack

The v2.0 stack (FastAPI, litellm, SQLite+sqlite-vec, LanceDB, FlashRank, asyncio) requires no changes. All v3.0 capabilities are delivered by a small set of additive dependencies.

Two packages belong in `requirements.txt` (core): `croniter>=6.2.2` (already imported in `cron/schedule.py` but undeclared) and `sse-starlette>=2.0.0` (SSE endpoint for dashboard). Everything else is optional and feature-gated in `requirements-optional.txt`.

**Core technologies added:**
- `croniter>=6.2.2`: cron expression parsing — already imported, just undeclared; add to requirements.txt immediately
- `sse-starlette>=2.0.0`: W3C-compliant SSE endpoint wrapper for FastAPI; handles client disconnect and reconnect automatically
- `edge-tts>=7.2.8`: zero-cost async TTS via Microsoft Edge neural voices; 400+ voices, no API key required
- `elevenlabs>=2.42.0`: premium TTS, opt-in only; use `eleven_flash_v2_5` model for ~300ms latency at 50% cost reduction
- `pydub>=0.25.1`: MP3-to-OGG-Opus conversion for WhatsApp voice notes; requires system `ffmpeg` binary
- `fal-client>=0.13.2`: Flux image generation via fal.ai; all methods have `_async` suffix for asyncio compatibility
- `faster-whisper>=1.2.1`: local realtime transcription; CPU INT8 path safe for 8GB RAM hosts (no CUDA required)
- `sounddevice>=0.5.5`: cross-platform mic capture; Windows wheels bundle PortAudio; cleaner than PyAudio on Windows

**Critical version constraint:** DALL-E 2 and DALL-E 3 are deprecated by OpenAI on May 12, 2026. Use `gpt-image-1` via the `openai` SDK (already a transitive litellm dep — no new pip install needed).

**What NOT to add:** raw `anthropic` or `openai` SDKs for LLM calls (litellm is the abstraction layer — adding raw SDKs creates duplicate auth paths), APScheduler/Celery/Redis (CronService is already asyncio-native and complete), React+Vite frontend (zero build toolchain is a hard self-hosted constraint), WebRTC infrastructure (single-user tool; WebSocket streaming is the right scope), DALL-E 2/3 (deprecated May 2026).

### Expected Features

The feature research produces a clear four-tier priority definition that maps directly to implementation complexity and user-visible value.

**Must have (table stakes — launch blockers):**
- Multi-provider routing (OpenAI native, Anthropic, DeepSeek, Mistral, Together.ai) — users switching from ChatGPT/Claude expect these as day-one options; config-only work, no code changes to gateway
- 10 bundled skills (weather, notes, reminders, web-search, translate, summarize, calculator, news, unit-convert, timer) — OpenClaw ships 53; users comparing products expect useful defaults; 7 of 10 are LOW complexity with no new infrastructure
- TTS voice replies on WhatsApp — voice input already works; voice output is the natural table-stakes complement; OGG+Opus format required
- Image generation ("draw me X") — frontier AI companions are expected to have this; time-sensitive due to DALL-E 3 deprecation

**Should have (competitive differentiators):**
- Cron context file injection (IsolatedContextBuilder) — makes proactive cron agents actually useful rather than amnesiac
- Persona-aware TTS voice selection — voice adapts to relationship role (partner vs. creator); uses free edge-tts voices
- Provider cost tracking per role — litellm Router already logs usage; aggregate in SQLite by role+provider, expose on dashboard
- Real-time dashboard panels (cron manager, channel health, model routing log) — makes the system observable

**Defer to v3.1+:**
- Full React/SPA dashboard rewrite — npm/build toolchain complexity with zero functional benefit for a single-user tool; HTMX + vanilla JS is correct
- Always-on local Whisper for streaming — faster-whisper large-v3 needs 3-4GB VRAM; unusable on 8GB hosts under load; use Groq Whisper API as default
- ElevenLabs as the only TTS option — at $0.30/1k chars, 50 msgs/day = ~$3/day; edge-tts free default is the right call
- Midjourney integration — no public API; Discord bot workarounds violate ToS and break unpredictably
- WebRTC for voice chat — requires STUN/TURN, signaling server, NAT traversal; architectural overkill for a local personal tool
- Real-time collaborative sessions — architecture is per-user by design; multi-user requires full auth rethink; explicitly out of scope

### Architecture Approach

The v3.0 architecture is additive layering on the existing v2.0 pipeline. No existing components need to be rewritten. The pattern is: new capability modules (`tts/`, `image_gen/`, `voice/`) expose provider ABCs, a router selects the active backend, routers are initialized in the FastAPI lifespan block (same pattern as SkillSystem), and invoked from `persona_chat()` as BackgroundTasks after the text reply is already dispatched. All media output follows the existing auto-continue pattern.

**Major components (new — build from scratch):**
1. `tts/` module — `TTSProvider` ABC, `EdgeTTSProvider`, `ElevenLabsProvider`, `TTSRouter`; wire into `persona_chat()` as BackgroundTask
2. `image_gen/` module — `ImageProvider` ABC, `DALLEProvider` (`gpt-image-1`), optional `FalProvider`, `ImageRouter`; image intent detection in `persona_chat()`; dispatch as BackgroundTask
3. `voice/` module — `VoiceSessionManager`, `Transcriber` (reuses existing Groq Whisper path), `VAD` (Silero recommended); registered as a standard `BaseChannel`
4. `skills/bundled/` — 10 SKILL.md directories; first-boot copy to `~/.synapse/skills/`; uses existing SkillLoader with zero new Python infrastructure
5. Dashboard panel modules — vanilla JS ES modules extending `static/dashboard/`; new `.js` panel files for cron, skills, providers, voice; no bundler required

**Modified components (extend only, not rewrite):**
- `_deps.py`: add `tts_router`, `image_router` singletons (2 new lines, same pattern as `skill_registry`)
- `api_gateway.py` lifespan: init TTSRouter, ImageRouter (same 20-line pattern as SkillSystem init)
- `persona_chat()`: post-LLM BackgroundTask hooks for TTS and image intent (~10 lines each)
- `synapse_config.py`: add optional `tts`, `image_gen`, `voice` config sections as dataclass fields with `None` defaults; zero internal type imports
- `CronService`: wire `execute_fn` to `persona_chat()` (the infrastructure is complete; only the wiring is missing)
- `llm_router.py` `_KEY_MAP`: add `deepseek` entry (2 lines)

**Immutable (do not touch):** `gateway/` flood/dedup/queue internals, `api_gateway.py` auth/token validation, `rollback.py`, existing `_deps.py` singletons

### Critical Pitfalls

The research surfaces 15 documented pitfalls across all phases. The top 7 that can silently break functionality or cause security issues:

1. **litellm budget/rate-limit fallback is silently broken** — `BudgetExceededError` and `RateLimitError` do not trigger the Router's fallback list (GitHub issue #10052, unresolved in OSS version). Must add explicit try/except in `SynapseLLMRouter._do_call()` to manually chain the next fallback. Address in Phase 1 before users depend on multi-provider failover.

2. **TTS and image gen must be BackgroundTasks, never inline awaits** — TTS synthesis takes 500ms-3s; image gen 10-30s. If awaited inline inside `persona_chat()`, the MessageWorker serializes around them and queues back up. The existing auto-continue BackgroundTask pattern is the correct model. Never deviate from it.

3. **WhatsApp voice notes require OGG+Opus, not MP3** — ElevenLabs and edge-tts both output MP3 by default. Sending MP3 via Baileys results in a downloadable file attachment (not an inline voice note with earphone icon). Request `opus_48000_32` from ElevenLabs directly, or convert with `ffmpeg`. Set `ptt: true` and `mimetype: "audio/ogg; codecs=opus"` on the Baileys call.

4. **Vault hemisphere isolation must be enforced at every cloud-API dispatch point** — Image generation and any skill calling external cloud APIs must check `hemisphere_tag == "spicy"` and return a soft decline. Add `cloud_safe: false` metadata to `SKILL.md` for all cloud-calling skills. Failure leaks private user content to OpenAI/ElevenLabs moderation pipelines and exposes NSFW content policy violations.

5. **Cron agents must not run on the main event loop or share global singletons** — A cron job on the uvicorn event loop blocks the entire chat pipeline (asyncio cooperative scheduling). Using global `MemoryEngine`/`SBS` singletons from cron corrupts live session state. Use `ProcessPoolExecutor` for CPU-heavy cron work; pass fresh isolated instances, never the global singleton. `asyncio.wait_for` on `ThreadPoolExecutor` work creates zombie threads (CPython issue #41699) — use `ProcessPoolExecutor` instead.

6. **`synapse_config.py` must remain import-free of Synapse internals** — Imported by 50+ modules. Any `from workspace.module import X` inside it creates a circular import that crashes startup. Add new config as plain dataclass fields with `None` defaults; use `TYPE_CHECKING` guards for type hints only. Run `pycycle --here` in CI after every change.

7. **Bundled skills must use `synapse.` namespace prefix** — User-installed skill named `weather` silently conflicts with bundled `weather`. The v2.0 skill router has no conflict detection. Add `namespace` field to `SKILL.md`; user skills always win; log a warning when a bundled skill is shadowed.

---

## Implications for Roadmap

All research converges on the same 6-phase order. This ordering is dependency-driven.

### Phase 1: LLM Provider Expansion
**Rationale:** Zero infrastructure risk — litellm already supports all target providers via configuration. Proves the routing layer before building anything on top of it. The budget-fallback bug must be patched here before users rely on multi-provider failover.
**Delivers:** OpenAI native, Anthropic, DeepSeek, Mistral, Together.ai entries in `synapse.json.example`; per-role fallback chains documented; `BudgetExceededError` explicit catch in `_do_call`; Copilot shim regression test; `deepseek` entry in `_KEY_MAP`; `croniter` and `sse-starlette` added to requirements.txt.
**Features addressed:** Multi-provider routing with failover (table stakes)
**Pitfalls to avoid:** Silent budget fallback failure (#1), model alias collision (#2), Copilot shim regression (#3), `synapse_config.py` circular import (#13 — establish pattern from day one)
**Research flag:** Standard patterns — skip research-phase

### Phase 2: Bundled Skills Library
**Rationale:** Highest user-visible value at lowest technical risk. The entire skill loading infrastructure is complete. Work is content (SKILL.md files), not infrastructure. No new dependencies. Ships substantial user value immediately.
**Delivers:** 10 bundled SKILL.md skills with `synapse.` namespace prefix; first-boot copy to `~/.synapse/skills/`; lazy import enforcement; `namespace` field in SKILL.md schema; startup time benchmark gate (< 5s).
**Features addressed:** 10+ bundled skills (table stakes)
**Pitfalls to avoid:** Skill namespace collision (#14), heavy dependency startup bloat (#15)
**Research flag:** Standard patterns — skip research-phase

### Phase 3: TTS Voice Output
**Rationale:** Depends only on existing channel adapters and new pip installs. Independent of image gen and voice streaming. Establishes the BackgroundTask media delivery pattern that Phase 4 reuses exactly. OGG+Opus conversion requires `ffmpeg` — document system dependency clearly.
**Delivers:** `tts/` module (TTSProvider ABC, EdgeTTSProvider, ElevenLabsProvider, TTSRouter); `send_audio()` method on WA/Telegram/Discord channel adapters; OGG+Opus conversion via pydub+ffmpeg; `tts` section in `SynapseConfig`; per-sender opt-in flag; sentence-chunking for latency reduction.
**Stack used:** `edge-tts>=7.2.8`, `elevenlabs>=2.42.0`, `pydub>=0.25.1`
**Features addressed:** TTS voice replies on WhatsApp (table stakes)
**Pitfalls to avoid:** TTS blocking pipeline (#5), audio format mismatch (#4)
**Research flag:** Standard patterns — skip research-phase

### Phase 4: Image Generation
**Rationale:** Builds directly on the BackgroundTask delivery pattern proven in Phase 3. Requires Phase 1 (provider routing) for fal.ai key injection. Time-sensitive: DALL-E 3 deprecates May 12, 2026; must target `gpt-image-1`.
**Delivers:** `image_gen/` module (ImageProvider ABC, DALLEProvider using `gpt-image-1`, optional FalProvider); image intent detection in `persona_chat()`; `send_image()` on channel adapters; `cloud_safe: false` hemisphere check for Vault sessions; image cache with TTL cleanup via GentleWorkerLoop.
**Stack used:** `openai` SDK (already transitive dep via litellm), `fal-client>=0.13.2`
**Features addressed:** Image generation ("draw me X") (table stakes)
**Pitfalls to avoid:** Image gen blocking MessageWorker (#6), Vault hemisphere leak (#7)
**Research flag:** Needs research-phase — Vault hemisphere enforcement contract design; `gpt-image-1` API parameters vs litellm `image_generation()` interface; fal.ai model ID pinning strategy

### Phase 5: Cron Wiring + Web Control Panel
**Rationale:** Dashboard panels are most valuable when TTS and image gen events are already being emitted (Phases 3+4 complete). CronService wiring and dashboard cron panel are tightly coupled — the panel is the primary control surface for cron jobs.
**Delivers:** `CronService.execute_fn` wired to `persona_chat()`; `IsolatedContextBuilder` for memory snapshot injection; ProcessPoolExecutor isolation for cron; expanded dashboard panels (cron editor, channel health, model routing log, skill manager) via vanilla JS panel modules; new SSE event types; `/tts/voices` and `/image-gen/history` API endpoints.
**Stack used:** `sse-starlette>=2.0.0`; vanilla JS ES modules (no bundler)
**Features addressed:** Cron context injection (differentiator), real-time dashboard panels (differentiator)
**Pitfalls to avoid:** Cron shared event loop / state corruption (#8), zombie thread accumulation (#9), dashboard WebSocket backpressure (#10), dashboard token leak (#11)
**Research flag:** Needs research-phase — ProcessPoolExecutor cron isolation with isolated MemoryEngine copies; dashboard session token auth design (httpOnly cookie vs loopback-only binding)

### Phase 6: Realtime Voice Streaming
**Rationale:** Highest complexity feature; depends on TTS (Phase 3) for the audio response path. Requires browser-side AudioWorklet code, VAD integration, streaming STT, and streaming TTS back to client. Build last — most likely to surface edge cases, most likely to require iteration on VAD calibration.
**Delivers:** `voice/` module (VoiceSessionManager, Transcriber reusing existing Groq Whisper path, VAD using Silero); WebSocket `/voice/stream` endpoint; VoiceChannel registered in `channel_setup.py`; browser voice recorder UI panel; barge-in cancel (new speech within 2s cancels current TTS playback); conservative VAD (mode 1 + 700ms silence threshold).
**Stack used:** `faster-whisper>=1.2.1`, `sounddevice>=0.5.5`
**Features addressed:** Realtime voice streaming (differentiator)
**Pitfalls to avoid:** VAD double response / false positive (#12)
**Research flag:** Needs research-phase — VAD aggressiveness calibration methodology; AudioWorklet PCM format requirements (16kHz mono 16-bit PCM for webrtcvad); latency budget from mic capture to LLM response to TTS audio delivery

### Phase Ordering Rationale

- Phase 1 before everything: the litellm router budget-fallback fix is a correctness dependency for all LLM-reliant features. Discovering and fixing routing bugs in a config-only phase is far safer than discovering them mid-media-feature build.
- Phase 2 before media: the 10 bundled skills require no new infrastructure — SkillLoader handles them already. Delivering substantial user-visible value (10 skills) immediately after provider routing maximizes early momentum.
- Phase 3 before Phase 4: the BackgroundTask media delivery pattern is established in TTS (simpler) and then reused identically in image gen (higher risk). Learning the pattern in the simpler case first is the correct order.
- Phase 5 after Phases 3+4: dashboard panels have meaningful content only when TTS and image gen are already emitting SSE events. A dashboard panel for features that don't exist yet delivers zero value.
- Phase 6 last: realtime voice is the only feature with browser-side code, VAD tuning requirements, streaming buffer edge cases, and a full dependency on the TTS chain. It is the highest risk and deserves a clean context after all other features are stable.

### Research Flags

**Needs research-phase before planning:**
- **Phase 4 (Image Generation):** Vault hemisphere enforcement design needs an explicit contract; `gpt-image-1` API parameters (format, quality, size options) need verification against litellm `image_generation()` interface; fal.ai model ID stability needs a pinning strategy before implementation
- **Phase 5 (Cron + Dashboard):** ProcessPoolExecutor isolation pattern for cron agents (passing isolated MemoryEngine copies to subprocess); dashboard session token auth design (httpOnly cookie vs loopback-only binding — security vs simplicity tradeoff)
- **Phase 6 (Voice Streaming):** VAD calibration methodology for home/office environments; AudioWorklet PCM streaming format requirements (16kHz mono 16-bit PCM); latency budget from mic capture through LLM to TTS playback; barge-in cancel implementation pattern

**Standard patterns — skip research-phase:**
- **Phase 1 (Provider Expansion):** litellm provider docs are comprehensive; all prefixes and env vars are verified at HIGH confidence; budget-fallback fix is a known 5-line patch
- **Phase 2 (Skills Library):** SkillLoader pattern is already in production; SKILL.md format is defined; 10 target skills are LOW-to-MEDIUM complexity with no new infrastructure
- **Phase 3 (TTS):** edge-tts and ElevenLabs SDK patterns are well-documented; BackgroundTask pattern is already in codebase; audio format requirements (OGG+Opus) are fully specified

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All core packages verified against PyPI and official docs as of April 2026; version numbers confirmed; DALL-E deprecation date confirmed |
| Features | HIGH | Cross-referenced against live codebase inspection, OpenClaw docs, litellm docs, and competitor feature analysis |
| Architecture | HIGH | Based on direct codebase inspection of `_deps.py`, `api_gateway.py`, `chat_pipeline.py`, `llm_router.py`, `cron/service.py`; all integration points explicitly mapped with line-count estimates |
| Pitfalls | HIGH | Multiple verified sources per pitfall; litellm GitHub issues cited; WhatsApp audio format requirements independently confirmed via Baileys issues and Vonage API docs |

**Overall confidence:** HIGH

### Gaps to Address

- **fal.ai model ID stability:** Model strings like `fal-ai/flux/schnell` change with provider updates. Pin a specific version during Phase 4 planning and document a quarterly review cadence. Verify litellm's fal.ai model string format against current fal.ai API at planning time.
- **edge-tts endpoint reliability:** Wraps an undocumented Microsoft Edge service; can be rate-limited silently. The fallback chain (edge-tts → ElevenLabs) must be explicit in TTSRouter. Validate the fallback behavior during Phase 3 implementation.
- **`aiohttp` as edge-tts transitive dependency:** Stack research flags that edge-tts requires `aiohttp`. Verify whether it is already in the project's transitive dependencies before adding to `requirements-optional.txt` to avoid silent version conflicts.
- **React vs HTMX disagreement between research files:** STACK.md recommends React+Vite; ARCHITECTURE.md and FEATURES.md explicitly recommend against it (zero build toolchain constraint for self-hosted deployment). ARCHITECTURE.md wins — vanilla JS + HTMX + SSE is confirmed. This is resolved; no ambiguity during planning.
- **faster-whisper asyncio streaming integration:** The local transcription path (Phase 6) requires careful non-blocking asyncio integration. This is the only Phase 6 component with MEDIUM stack confidence that involves new async coordination. Budget extra time and prototype early.

---

## Sources

### Primary (HIGH confidence)
- litellm providers docs — confirmed prefixes for OpenAI, Anthropic, DeepSeek, Mistral, Together AI
- litellm routing + fallback docs — `allowed_fails`, `cooldown_time`, Router strategies
- litellm `image_generation()` + fal.ai integration — API confirmed
- litellm GitHub issue #10052 — budget fallback silent failure, confirmed unresolved in OSS
- elevenlabs PyPI v2.42.0 (April 7, 2026) — SDK v2, `eleven_flash_v2_5` model confirmed
- edge-tts PyPI v7.2.8 (March 22, 2026) — async-native, no API key
- fal-client PyPI v0.13.2 (March 24, 2026) — `subscribe_async()` confirmed
- openai PyPI v2.30.0 (March 25, 2026) — `gpt-image-1`, DALL-E 3 deprecation May 2026 confirmed
- faster-whisper GitHub v1.2.1 — CPU INT8 path confirmed
- sounddevice PyPI v0.5.5
- sse-starlette GitHub (March 2026) — Python >=3.10, FastAPI-native
- croniter PyPI v6.2.2 (March 15, 2026) — already imported in `cron/schedule.py`
- Direct codebase inspection: `_deps.py`, `api_gateway.py`, `chat_pipeline.py`, `llm_router.py`, `cron/service.py`, `skills/schema.py`, `pipeline_emitter.py`, `static/dashboard/index.html`
- WhatsApp PTT OGG+Opus format requirement — Vonage API docs + Baileys issue #1828
- CPython issue #41699, #85865 — zombie threads from `wait_for` + `run_in_executor` documented limitation

### Secondary (MEDIUM confidence)
- ElevenLabs TTS latency benchmarks — `eleven_flash_v2_5` ~300ms per chunk measured
- FastRTC library (2025) — WebRTC+WebSocket voice with FastAPI `.mount(app)`; limited production history
- WhisperLiveKit PyPI — simultaneous STT streaming, 2025
- Silero VAD vs webrtcvad accuracy comparison — Silero recommended for home/office environments
- FastAPI SSE dashboard patterns — verified against existing codebase SSE structure
- DALL-E timeout patterns — 10-30s spikes documented in OpenAI community

### Tertiary (LOW confidence)
- fal.ai model IDs (`fal-ai/flux/schnell`, `fal-ai/flux-pro/v1.1-ultra`) — subject to change; must pin during Phase 4 planning
- OpenAI Realtime API (`gpt-4o-transcribe` via WebSocket) — confirmed as alternative to local faster-whisper but not the primary recommendation

---

*Research completed: 2026-04-08*
*Ready for roadmap: yes*
