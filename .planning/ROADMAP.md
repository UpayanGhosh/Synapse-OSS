# Roadmap: Synapse-OSS

## Milestones

- ✅ **v1.0 OSS Independence** - Phases 0-9 (shipped 2026-03-03)
- ✅ **v2.0 The Adaptive Core** - Phases 0-5 (shipped 2026-04-08)
- 🚧 **v3.0 OpenClaw Feature Harvest** - Phases 6-11 (in progress)

---

<details>
<summary>✅ v1.0 OSS Independence (Phases 0-9) — SHIPPED 2026-03-03</summary>

All channels live, hybrid RAG memory, SBS 8-layer profiling, Dual Cognition Engine, proactive outreach.
38 plans, 10 phases, 100% complete. See `.planning/phases/` for archive.

</details>

<details>
<summary>✅ v2.0 The Adaptive Core (Phases 0-5) — SHIPPED 2026-04-08</summary>

Skills-as-directories, safe self-modification + rollback, subagent system, onboarding wizard v2, browser tool, embedding refactor (Qdrant → LanceDB), Ollama made optional, Docker removed.

### Phase 0: Session & Context Persistence
**Goal**: Every WhatsApp conversation maintains history across messages.
**Plans**: 5/5

Plans:
- [x] 00-01-PLAN.md — ConversationCache singleton in _deps.py + _LLMClientAdapter class
- [x] 00-02-PLAN.md — Wire session key + history load/save + compaction into process_message_pipeline
- [x] 00-03-PLAN.md — Rewrite routes/sessions.py: GET /sessions from SessionStore + POST reset
- [x] 00-04-PLAN.md — Tests: session key, history load/save, isolation, compaction, sessions API
- [x] 00-05-PLAN.md — /new command: archive transcript + rotate session ID + confirm reset

### Phase 1: Skill Architecture
**Goal**: Any capability lives in a skill directory, not the core codebase.
**Plans**: 5/5

Plans:
- [x] 01-01-PLAN.md — Define SKILL.md schema + create SkillLoader class with validation
- [x] 01-02-PLAN.md — Implement SkillRegistry: startup scan, hot-reload watcher, GET /skills endpoint
- [x] 01-03-PLAN.md — Implement description-based SkillRouter: embed descriptions at load, cosine-match
- [x] 01-04-PLAN.md — Wire SkillRegistry + SkillRouter into api_gateway.py pipeline
- [x] 01-05-PLAN.md — Create skill-creator skill: SKILL.md template + scripts/create_skill.py

### Phase 2: Safe Self-Modification + Rollback
**Goal**: Synapse can modify its own Zone 2 architecture — every change is consented, snapshotted, reversible.
**Plans**: 5/6 (02-06 integration tests pending)

Plans:
- [x] 02-01-PLAN.md — SnapshotEngine: write/list/restore lifecycle + test_snapshot_engine.py
- [x] 02-02-PLAN.md — Zone 1/Zone 2 registry in Sentinel: IMMUTABLE_PATHS + WRITABLE_ZONES constants
- [x] 02-03-PLAN.md — ConsentProtocol: explain → confirm → execute → snapshot orchestration
- [x] 02-04-PLAN.md — Wire ConsentProtocol into api_gateway.py
- [x] 02-05-PLAN.md — Rollback: by snapshot ID, by date string, by natural language description
- [ ] 02-06-PLAN.md — Integration tests: full consent → execute → snapshot → rollback cycle

### Phase 3: Subagent System
**Goal**: Main conversation can delegate to isolated async sub-agents without blocking the parent.
**Plans**: 4/4

Plans:
- [x] 03-01-PLAN.md — SubAgent dataclass + AgentRegistry CRUD lifecycle + GET /agents endpoint
- [x] 03-02-PLAN.md — SubAgentRunner: isolated asyncio execution, scoped memory snapshots, ProgressReporter
- [x] 03-03-PLAN.md — Spawn intent gate + pipeline wiring + result delivery via channel.send()
- [x] 03-04-PLAN.md — Unit + integration tests

### Phase 4: Onboarding Wizard v2
**Goal**: Fresh install reaches personalized baseline in under 5 minutes.
**Plans**: 4/4

Plans:
- [x] 04-01-PLAN.md — Setup entrypoint + SBS profile init + persona questions
- [x] 04-02-PLAN.md — Verify subcommand: parallel provider + channel validation
- [x] 04-03-PLAN.md — Non-interactive SBS env var support + input validation
- [x] 04-04-PLAN.md — Test coverage for all v2 wizard features

### Phase 5: Browser Tool
**Goal**: Synapse can access live web content, summarize it, and inject it into context as a skill.
**Plans**: 4/4

Plans:
- [x] 05-01-PLAN.md — Browser skill directory: SKILL.md + fetch_and_summarize.py + SSRF guard
- [x] 05-02-PLAN.md — Web search via DuckDuckGo (DDGS): rate limiting, result ranking, source URLs
- [x] 05-03-PLAN.md — Browser skill orchestrator: hemisphere guard + search→fetch→summarize chain
- [x] 05-04-PLAN.md — Integration tests: SSRF rejection, HTML-free prompts, hemisphere guard, source URLs

</details>

---

## 🚧 v3.0 OpenClaw Feature Harvest (In Progress)

**Milestone Goal:** Port high-value design patterns from the OpenClaw TypeScript codebase into Synapse-OSS Python — concepts not code, depth not breadth. Deliver 10+ bundled skills, expanded provider routing, TTS voice output, image generation, cron with isolated agents, a real-time web control panel, and realtime voice streaming.

## Phases

- [x] **Phase 6: LLM Provider Expansion** - Expose all major providers via config; patch silent litellm budget fallback bug; update onboarding wizard (completed 2026-04-09)
- [ ] **Phase 7: Bundled Skills Library** - Ship 10 production-ready skills out of the box with namespace isolation and first-boot installation
- [ ] **Phase 8: TTS Voice Output** - Voice replies as WhatsApp voice notes (OGG Opus) via edge-tts default + ElevenLabs opt-in
- [ ] **Phase 9: Image Generation** - "Draw me X" delivers an image in chat via gpt-image-1; runs as BackgroundTask; Vault-safe
- [ ] **Phase 10: Cron Wiring + Web Control Panel** - Wire CronService to persona_chat() with isolated agents; real-time SSE dashboard
- [ ] **Phase 11: Realtime Voice Streaming** - Full-duplex voice chat from dashboard: VAD + Groq STT + streaming TTS + barge-in cancel

## Phase Details

### Phase 6: LLM Provider Expansion
**Goal**: Users can route to any of 10+ LLM providers by editing synapse.json — no code changes. The litellm budget-fallback bug is patched so failover chains actually work.
**Depends on**: Nothing (first v3.0 phase; all work is config + 1 bug patch in llm_router.py)
**Requirements**: PROV-01, PROV-02, PROV-03, PROV-04
**Success Criteria** (what must be TRUE):
  1. User adds `deepseek/deepseek-chat` as a provider in synapse.json and the next chat message routes through it — confirmed by litellm debug log showing the provider prefix
  2. User sets a budget cap for OpenAI in synapse.json; after exceeding it, the next message falls back to the configured fallback provider instead of returning a 500 error
  3. Running `python -m synapse setup` shows all 10+ providers (OpenAI, Anthropic, DeepSeek, Mistral, Together, Gemini, Groq, Cohere, Ollama, GitHub Copilot) in the provider selection menu
  4. `croniter` and `sse-starlette` appear in `pip list` on a clean install (declared in requirements.txt)
**Plans**: 3 plans in 2 waves

Plans:
- [ ] 06-01-PLAN.md — DeepSeek provider maps + requirements.txt deps + synapse.json.example (Wave 1)
- [ ] 06-02-PLAN.md — BudgetExceededError fallback fix + per-provider budget caps + DeepSeek _KEY_MAP (Wave 1)
- [ ] 06-03-PLAN.md — Unit tests for provider expansion and budget fallback (Wave 2)

---

### Phase 7: Bundled Skills Library
**Goal**: A fresh Synapse install ships with 10 useful skills ready to invoke. Skills use the `synapse.` namespace prefix to avoid conflicts with user-installed skills. No new infrastructure — uses the existing SkillLoader.
**Depends on**: Phase 6 (some skills call cloud APIs; provider routing must be stable)
**Requirements**: SKILL-01, SKILL-02, SKILL-03, SKILL-04
**Success Criteria** (what must be TRUE):
  1. On first boot, `~/.synapse/skills/` contains all 10 bundled skill directories (weather, reminders, notes, translate, summarize, web-scrape, news, image-describe, timer, dictionary) — confirmed by `ls ~/.synapse/skills/`
  2. Saying "what's the weather in Tokyo?" routes to the `synapse.weather` skill without any user configuration beyond a weather API key
  3. A user-installed skill named `weather` shadows the bundled `synapse.weather` and Synapse logs a warning at startup — the user's version wins
  4. Disabling `synapse.reminders` by setting `enabled: false` in its SKILL.md means reminder requests return a graceful "I can't set reminders right now" — not a routing error
  5. All cloud-calling bundled skills declare `cloud_safe: false` in their SKILL.md — confirmed by grepping the bundled skill directories
**Plans**: 3 plans

Plans:
- [ ] 07-01-PLAN.md — Schema + Loader + Registry infrastructure (cloud_safe, enabled fields, shadow warning, seed_bundled_skills)
- [ ] 07-02-PLAN.md — Author 10 bundled SKILL.md directories with entry_point scripts
- [ ] 07-03-PLAN.md — SkillRunner cloud_safe enforcement + comprehensive tests for SKILL-01 through SKILL-04

---

### Phase 8: TTS Voice Output
**Goal**: Users receive voice replies as playable WhatsApp voice notes. edge-tts is the zero-cost default (400+ voices, no API key). ElevenLabs is available for premium opt-in. TTS never blocks the chat pipeline.
**Depends on**: Phase 6 (ElevenLabs uses the provider key injection pattern from PROV work)
**Requirements**: TTS-01, TTS-02, TTS-03, TTS-04, TTS-05
**Success Criteria** (what must be TRUE):
  1. User receives a reply as a WhatsApp voice note (earphone icon visible, inline playable) — the file format is OGG+Opus, not MP3, confirmed by inspecting the Baileys send call parameters (`ptt: true`, `mimetype: audio/ogg; codecs=opus`)
  2. TTS works out of the box on a fresh install with no API keys configured — edge-tts generates audio using a Microsoft Edge neural voice with zero credentials
  3. User sets `tts.provider: elevenlabs` and `tts.voice: "Rachel"` in synapse.json — the next voice reply uses ElevenLabs Rachel voice, confirmed by ElevenLabs API call log
  4. A chat message followed immediately by another chat message does not queue behind TTS synthesis — the text reply arrives first, the voice note arrives seconds later as a separate message (BackgroundTask pattern verified by timing)
  5. User sets `tts.voice: "en-US-AriaNeural"` in synapse.json — all subsequent voice replies use the configured voice name
**Plans**: 3 plans in 2 waves

Plans:
- [ ] 08-01-PLAN.md — TTS engine core: edge-tts + ElevenLabs providers, MP3-to-OGG converter, SynapseConfig tts field (Wave 1)
- [ ] 08-02-PLAN.md — Baileys bridge /send-voice endpoint + WhatsAppChannel.send_voice_note() (Wave 1)
- [ ] 08-03-PLAN.md — Pipeline wiring: BackgroundTask TTS dispatch, media serving, tests (Wave 2)

---

### Phase 9: Image Generation
**Goal**: Users can request image generation in natural language and receive the image in chat. gpt-image-1 is the default (DALL-E 3 is deprecated May 2026). Runs as BackgroundTask with immediate text acknowledgment. Blocked in Vault hemisphere.
**Depends on**: Phase 6 (OpenAI API key injection), Phase 8 (reuses BackgroundTask media delivery pattern)
**Requirements**: IMG-01, IMG-02, IMG-03, IMG-04, IMG-05
**Success Criteria** (what must be TRUE):
  1. Saying "draw me a sunset over a cyberpunk city" delivers an image in WhatsApp — the text reply arrives first ("generating..."), the image arrives as a follow-up within 30 seconds
  2. Traffic Cop classifies the image request as IMAGE role — confirmed by the routing log in `GET /sessions` or gateway debug output showing `role=IMAGE` before the BackgroundTask dispatch
  3. In a spicy-hemisphere session, saying "draw me X" returns a soft decline ("image generation isn't available in private mode") instead of making an OpenAI API call — confirmed by asserting no outbound HTTP to `api.openai.com/v1/images`
  4. Setting `image_gen.provider: fal` in synapse.json routes image requests to fal.ai instead of OpenAI — confirmed by fal-client API call appearing in logs
  5. The immediate text acknowledgment ("working on it...") arrives before image generation completes — confirmed by message timestamp ordering
**Plans**: 3 plans in 2 waves

Plans:
- [ ] 09-01-PLAN.md — ImageGenEngine + OpenAI/fal providers + SynapseConfig image_gen field + requirements.txt (Wave 1)
- [ ] 09-02-PLAN.md — Traffic Cop IMAGE classification + IMAGE routing branch in chat_pipeline (Wave 1)
- [ ] 09-03-PLAN.md — Pipeline wiring: BackgroundTask dispatch, Vault block, media serving, tests (Wave 2)

---

### Phase 10: Cron Wiring + Web Control Panel
**Goal**: CronService is wired to `persona_chat()` so scheduled jobs actually run with isolated agent contexts. The dashboard becomes a real-time interactive control panel — sessions, cron jobs, model routing decisions, memory stats — observable and controllable from a browser.
**Depends on**: Phase 8 + Phase 9 (dashboard panels have meaningful content only after TTS and image gen are emitting SSE events), Phase 6 (provider routing log panel)
**Requirements**: CRON-01, CRON-02, CRON-03, CRON-04, DASH-01, DASH-02, DASH-03, DASH-04, DASH-05
**Success Criteria** (what must be TRUE):
  1. A cron job defined in synapse.json fires at its scheduled time and the user receives a proactive message — the job ran through `persona_chat()` confirmed by the conversation log showing a cron-originated entry
  2. Two cron jobs firing simultaneously do not corrupt each other's memory context — each job receives its own isolated memory snapshot, confirmed by log entries showing distinct session keys per job
  3. Opening `http://127.0.0.1:8000/dashboard` in a browser shows live pipeline events updating in real time via SSE (no page refresh required) — TTS synthesis events, image gen completions, and cron job fires are all visible
  4. User sends a test message from the dashboard text box and receives a reply in the dashboard — the message flows through the normal `persona_chat()` pipeline
  5. Navigating to the dashboard from outside `127.0.0.1` (e.g., another machine on the LAN) returns 403 — loopback-only enforcement confirmed
  6. Dashboard is built with vanilla JS + Tailwind — no npm, no node_modules, no build step required to serve it
**Plans**: 4 plans in 3 waves

Plans:
- [ ] 10-01-PLAN.md — Cron wiring: ChatRequest session_key + execute_fn adapter + SSE emission (Wave 1)
- [ ] 10-02-PLAN.md — Dashboard infra: LoopbackOnlyMiddleware + cron API routes (Wave 1)
- [ ] 10-03-PLAN.md — Dashboard UI: 4 new panels (sessions, cron, memory, routing) + JS fetch/SSE (Wave 2)
- [ ] 10-04-PLAN.md — Tests: cron wiring, loopback middleware, cron routes, DASH-05 compliance (Wave 3)

---

### Phase 11: Realtime Voice Streaming
**Goal**: Users can have a full-duplex voice conversation from the dashboard. Silero VAD detects speech boundaries, Groq Whisper transcribes in real time, the LLM response is TTS-streamed back as audio, and barge-in cancels the current TTS playback. Highest complexity — built last.
**Depends on**: Phase 8 (TTS audio delivery chain is a hard dependency), Phase 10 (dashboard WebSocket infrastructure and VoiceChannel registration)
**Requirements**: VOICE-01, VOICE-02, VOICE-03, VOICE-04, VOICE-05
**Success Criteria** (what must be TRUE):
  1. User clicks "Start Voice" in the dashboard, speaks a sentence, and receives a spoken reply within 3 seconds — full round-trip from mic capture to TTS playback confirmed in a live demo
  2. Silero VAD correctly ends speech capture after 700ms of silence — confirmed by logging VAD boundary events and asserting no premature cutoffs mid-sentence in a 10-utterance test
  3. Groq Whisper transcription of a clear English sentence achieves word-error-rate under 10% — confirmed by comparing transcribed text to the known test utterance
  4. While the AI is speaking a long response, saying a new sentence cancels the current TTS playback and begins processing the new input — barge-in latency under 500ms from speech onset to playback stop
  5. Closing the voice session tab cleanly terminates the WebSocket, stops mic capture, and releases the audio device — confirmed by asserting no dangling sounddevice streams after tab close
**Plans**: 3 plans in 2 waves

Plans:
- [ ] 11-01-PLAN.md — Server-side voice infrastructure: VoiceSession, VoiceChannel, WS binary frames, voice.* protocol, transcribe_bytes (Wave 1)
- [ ] 11-02-PLAN.md — Browser-side voice module: VAD init, Float32-to-WAV encoder, AudioContext playback queue, barge-in handler (Wave 1)
- [ ] 11-03-PLAN.md — Pipeline wiring: VoiceChannel registration, dashboard voice UI, comprehensive tests (Wave 2)

---

## Progress

**Execution Order:**
Phases execute in dependency order: 6 → 7 → 8 → 9 → 10 → 11

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 0. Session & Context Persistence | v2.0 | 5/5 | Complete | 2026-04-07 |
| 1. Skill Architecture | v2.0 | 5/5 | Complete | 2026-04-07 |
| 2. Safe Self-Modification + Rollback | v2.0 | 5/6 | In Progress | — |
| 3. Subagent System | v2.0 | 4/4 | Complete | 2026-04-07 |
| 4. Onboarding Wizard v2 | v2.0 | 4/4 | Complete | 2026-04-07 |
| 5. Browser Tool | v2.0 | 4/4 | Complete | 2026-04-07 |
| 6. LLM Provider Expansion | 3/3 | Complete   | 2026-04-09 | — |
| 7. Bundled Skills Library | 1/3 | In Progress|  | — |
| 8. TTS Voice Output | 1/3 | In Progress|  | — |
| 9. Image Generation | v3.0 | 0/TBD | Not started | — |
| 10. Cron Wiring + Web Control Panel | v3.0 | 0/TBD | Not started | — |
| 11. Realtime Voice Streaming | v3.0 | 0/3 | Planned | — |
