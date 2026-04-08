# Feature Research: Synapse-OSS v3.0 — OpenClaw Feature Harvest

**Domain:** Personal AI assistant — expanded LLM routing, skills, TTS, image gen, cron isolation, dashboard, realtime voice
**Researched:** 2026-04-08
**Confidence:** HIGH (multi-source; WebSearch verified against official docs and live codebase inspection)

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist in a production-grade personal AI. Missing these = product feels incomplete or unpolished.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| OpenAI, Anthropic, DeepSeek provider support | Users switching from ChatGPT/Claude expect native integration | LOW | litellm already covers these; `synapse.json` `model_mappings` is the only config surface. No code changes to gateway. |
| Mistral and Together.ai routing | Popular open-weight hosting; users want cost flexibility | LOW | litellm native providers. Add entries in `model_mappings` + document required API keys. |
| Provider failover (automatic) | If one provider is down, AI should still respond | MEDIUM | litellm Router supports `allowed_fails` + `cooldown_time`. Existing `InferenceLoop` retry covers most cases; add per-role fallback keys in `synapse.json`. |
| TTS voice replies on WhatsApp | Users already send voice notes; expecting voice back feels natural | HIGH | OGG Opus format required for WhatsApp PTT. edge-tts (free, no key) generates MP3; FFmpeg conversion needed. ElevenLabs generates OGG directly (paid). Baileys bridge must accept outbound binary audio. |
| "Draw me X" image generation in chat | Image gen is now a core expectation for frontier AI companions | MEDIUM | litellm `image_generation()` unified call covers DALL-E (openai/dall-e-3), Flux (fal_ai/...), Stability SD3.5. Route via Traffic Cop or keyword detect. Return URL or base64; Baileys can send image from URL. |
| 10+ bundled skills out of the box | OpenClaw ships 53 skills; users comparing expect useful defaults | MEDIUM | Skills as SKILL.md dirs already designed. Needs 10 skill implementations: weather, notes, reminders, web search, translate, summarize, calculator, news, unit convert, timer. |
| Cron job memory isolation | Background tasks contaminating chat history is a bug, not a feature | LOW | Already partially built: `isolated_agent.py` uses a fresh `session_key`. Gap: no per-job memory scope or context file injection. |
| Real-time dashboard (not just static HTML) | Users expect live system status, active jobs, channel health | MEDIUM | Existing `/dashboard` is static HTML + SSE `/pipeline/events`. Needs interactive controls: enable/disable jobs, view cron run log, channel toggle, model override UI. |

### Differentiators (Competitive Advantage)

Features that set Synapse apart from ChatGPT wrappers and basic self-hosted alternatives.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Realtime voice streaming (STT) | Full duplex voice chat; no push-to-talk friction | HIGH | WhisperLiveKit (WhisperLiveKit PyPI) or Groq streaming endpoint. FastAPI WebSocket endpoint receives raw audio chunks, streams VAD-gated transcription, feeds normal pipeline. Requires: silero-VAD or webrtcvad for turn detection. |
| Cron context files (Honcho-style) | Isolated cron agents get awareness of recent events without polluting main session | MEDIUM | Cron service generates a "context file" at job start summarizing last N messages + recent decisions. Agent reads it, discards it. Honcho Memory pattern from OpenClaw ecosystem. |
| Persona-aware TTS voice selection | TTS voice adapts to relationship role (partner vs creator) | MEDIUM | edge-tts voices are free and role-selectable. Store voice ID per SBS persona in `synapse.json`. No additional cost vs. flat ElevenLabs pricing. |
| Provider cost tracking per role | Users understand where their AI money goes | LOW | litellm Router logs `usage` per call; aggregate in SQLite by role+provider. Expose on dashboard. |
| Skill routing via semantic classifier | Skills triggered by meaning not keyword matching | MEDIUM | Already designed in v2.0 skill architecture. Needs the 10 bundled skill SKILL.md files for router to have meaningful choices. |
| Image generation + immediate context | Generated image URL stored in memory so AI can reference it later | MEDIUM | After `image_generation()` call, ingest the prompt + URL into MemoryEngine. Enables "make it darker" follow-ups. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that look good in a GitHub readme but create real operational pain.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| WebRTC for voice chat UI | "Real-time" sounds better | WebRTC requires STUN/TURN servers, signaling server, browser-side JS media capture, NAT traversal — enormous scope for a self-hosted personal tool. Also incompatible with WhatsApp/Telegram voice path. | WebSocket streaming for the web dashboard voice input; WhatsApp voice note OGG pipeline for mobile. Two targeted solutions vs. one heavyweight generic one. |
| Always-on local Whisper for streaming | Low latency without Groq API costs | faster-whisper large-v3 requires 3-4 GB VRAM or is 10-15x real-time on CPU — unusable on 8 GB RAM dev machines under load | Groq Whisper streaming endpoint (free tier, 7200 audio seconds/day). Fall back to local only if user explicitly opts in with hardware check. |
| ElevenLabs as the only TTS option | High voice quality | ElevenLabs charges per character; voice messages are long-form. At $0.30/1k chars, a 200-char reply costs $0.06 — multiplied by 50 msgs/day = $3/day. | edge-tts as default (free, Microsoft neural voices, 300+ voices). ElevenLabs as opt-in premium override in `synapse.json`. |
| Midjourney integration for image gen | Best artistic quality | Midjourney has no public API — requires Discord bot workarounds that violate ToS and break unpredictably. | DALL-E 3 (or GPT Image 1.5) via litellm for reliable API. Flux via fal.ai for quality/cost balance. |
| Hosting a Stability AI local model | On-device, no API cost | SD3.5 requires 6-10 GB VRAM. Unusable on CPU. Crashes 8 GB shared-RAM systems. | API-based only (fal.ai/Stability API). Document hardware requirements clearly if user wants local. |
| Real-time collaborative sessions | "Share your AI" request | Architecture is per-user by design — Zone 1 data (personal memory, SBS profile) must never be mixed. Multi-user requires full auth rethink. | Explicitly out of scope. Document why in README. |
| Full React SPA dashboard rewrite | Modern UI feel | React build pipeline, node_modules, hot reload adds dev complexity with zero functional benefit for a personal single-user tool. | Enhance existing static HTML + HTMX for interactive controls. Add SSE for live updates. Ship in <2 days vs. weeks. |

---

## Feature Breakdown by Question Area

### (1) Multi-Provider LLM Routing with Failover

**Status:** 80% already built. Existing `SynapseLLMRouter` + litellm Router handles this.

**What's missing:**
- Provider entries for OpenAI (non-Copilot), Anthropic (native, not Max), DeepSeek, Mistral, Together.ai in docs and `synapse.json` template.
- `allowed_fails` + `cooldown_time` config exposed in `synapse.json` (currently hardcoded defaults).
- Per-role fallback chain documented: e.g., `code → claude-3.7 → gpt-4o → deepseek-coder`.

**Key production pattern:** litellm Router `simple-shuffle` strategy distributes load across same-model deployments. Cooldown mechanism marks failed deployments unhealthy for configurable seconds (default 1s). Circuit breaker at the gateway layer is overkill for single-user personal use.

**Complexity:** LOW — config additions, not code changes.

### (2) Bundled Skills Library

**What OpenClaw ships as bundled:** web research, file ops, shell execution, browser automation. The "53 skills" are community-built registry skills, not bundled.

**What a personal AI needs as table stakes (mapped to Synapse skill SKILL.md format):**

| Skill | Why Essential | Dependency | Complexity |
|-------|--------------|------------|------------|
| `weather` | Daily utility, top user request | wttr.in free API or openweathermap | LOW |
| `notes` | Create/read/search personal notes in `~/.synapse/notes/` | None | LOW |
| `reminders` | One-shot timed reminders via CronService | CronService (already built) | LOW |
| `web-search` | Current information lookups | Brave Search API / DuckDuckGo scrape | MEDIUM |
| `translate` | Multilingual users (Banglish already handled in pipeline) | litellm call or Google Translate free | LOW |
| `summarize` | Long document or URL summarization | Browser tool (already built in v2.0) | LOW |
| `calculator` | Precise arithmetic without LLM hallucination | Python `eval` with safety sandbox | LOW |
| `news` | Headlines on demand | RSS + browser tool | MEDIUM |
| `unit-convert` | Practical utility | Pure Python, no API | LOW |
| `timer` | "Remind me in 10 minutes" | CronService (already built) | LOW |

**10 skills total. 7 are LOW complexity. None require new infrastructure.**

### (3) TTS Voice Output

**Architecture decision: two-tier**

| Tier | Provider | Latency | Cost | Format | When |
|------|----------|---------|------|--------|------|
| Default | edge-tts (Microsoft Edge neural voices) | 400-800ms total (network + gen) | Free (wraps Edge service) | MP3 → convert to OGG Opus via FFmpeg | Always |
| Premium | ElevenLabs Flash v2.5 | ~350ms measured (75ms claimed) | $0.30/1k chars | OGG direct | Opt-in via `synapse.json tts.provider: "elevenlabs"` |

**Critical path for WhatsApp voice notes:**
```
TTS text → edge-tts MP3 → FFmpeg → OGG Opus → Baileys bridge send_voice(ptt=true)
```
FFmpeg is already used in the audio pipeline (AudioProcessor). Adding OGG output is a one-flag change.

**Streaming TTS vs batch:** Streaming (chunk-by-chunk) is only needed for realtime voice conversation (question 7). For WhatsApp voice replies, batch is correct — send one complete voice note.

**Complexity:** MEDIUM — edge-tts install, FFmpeg flag, Baileys outbound voice path.

### (4) Image Generation Integration

**Recommendation: DALL-E 3 via litellm as default + Flux Schnell via fal.ai as fast/cheap option**

| Model | API | Cost/image | Quality | Speed | litellm call |
|-------|-----|------------|---------|-------|--------------|
| DALL-E 3 (gpt-image-1 mini) | OpenAI | $0.04-0.005 | High, instruction-following | 5-15s | `litellm.image_generation(model="dall-e-3", ...)` |
| Flux.1 Schnell | fal.ai | $0.015 | Good, fast | 4-5s | `litellm.image_generation(model="fal_ai/fal-ai/flux/schnell", ...)` |
| Flux 2 Pro | fal.ai | $0.055 | Highest | 4-5s | `litellm.image_generation(model="fal_ai/fal-ai/flux-pro/v1.1-ultra", ...)` |

**litellm support:** HIGH confidence. `litellm.image_generation()` is a documented, shipped API. fal.ai + DALL-E both verified in litellm docs. Azure Flux also supported (PR #13592 merged).

**Integration point in Synapse:** Traffic Cop classifies message → new `IMAGE` role → routes to `_handle_image_request()` in api_gateway.py → `litellm.image_generation()` → return URL → Baileys sends as image attachment.

**Complexity:** MEDIUM — new Traffic Cop classification, `image_generation()` wrapper, outbound media path.

### (5) Cron with Isolated Agents

**Current state:** `isolated_agent.py` creates a fresh `session_key` (no conversation history). `CronService` fully implemented with CRUD, timer loop, catch-up. **Already covers most of this requirement.**

**Gap vs. OpenClaw pattern:**
- Isolated sessions currently have zero context awareness (they don't know what happened recently).
- OpenClaw's recommended pattern: generate a "context summary file" at job start with the last N memory items + recent decisions, inject as system context. Session is still ephemeral — no history pollution.
- No per-job memory scope (jobs share the same LanceDB memory as the main session).

**What to build:**
1. `IsolatedContextBuilder` — queries MemoryEngine for top-k recent items → renders a 500-token context string → passed as `system_prefix` to `execute_fn`.
2. Per-job `tools_allow` list already supported in `CronPayload` — leverage to restrict tool access.
3. Job timeout enforcement: `asyncio.wait_for(timeout=payload.timeout_seconds)` — already in `CronPayload.timeout_seconds` field, just needs wiring in `run_isolated_agent()`.

**Complexity:** LOW to MEDIUM — existing infrastructure is solid. Context builder is new but small.

### (6) Real-Time Web Dashboard

**What production AI assistant dashboards show (based on research):**

| Panel | Content | Update mechanism |
|-------|---------|-----------------|
| System health | CPU, RAM, process uptime, Ollama status | SSE poll every 5s |
| Channel status | WhatsApp QR/connected, Telegram, Discord, Slack — last message timestamp | SSE event on channel state change |
| Active pipeline | Current message in flight, model used, latency | SSE event from gateway worker |
| Cron job manager | List all jobs, last run status, next run time, enable/disable toggle | REST API (already `/cron` endpoints) + SSE for run events |
| Memory stats | Total memories, last ingested, hemisphere split (safe/spicy count) | REST API |
| Model routing log | Last 20 LLM calls with provider, model, tokens, latency | SSE stream from llm_router |
| TTS/image queue | Pending voice/image generation requests | SSE |

**Transport recommendation: SSE for broadcast + REST for actions**
- `/pipeline/events` SSE endpoint already exists — extend event types.
- Interactive controls (enable job, change model) go through REST endpoints already in api_gateway.
- No need for full WebSocket bidirectional stream for dashboard. SSE + REST is simpler, works through proxies, reconnects automatically.
- HTMX or vanilla JS fetch + SSE listener is sufficient — no React needed.

**Complexity:** MEDIUM — extend SSE event system, add cron panel, channel health panel. No infrastructure change.

### (7) Realtime Voice Streaming

**Architecture choice: WebSocket streaming (NOT WebRTC)**

WebRTC adds: STUN/TURN infrastructure, ICE negotiation, signaling server, browser getUserMedia permissions management, NAT traversal. For a single-user personal tool where the client is either the web dashboard (same LAN) or a phone channel (WhatsApp/Telegram — pre-existing voice message path), this is architectural overkill.

**Recommended stack:**
```
Browser mic → AudioWorklet (16kHz PCM chunks) → WebSocket /voice/stream
  → FastAPI WS endpoint
  → silero-VAD (lightweight, CPU-friendly, 1MB) or webrtcvad (Google, py-webrtcvad)
  → VAD gates → accumulate speech segment
  → Groq Whisper streaming (2488ms response time measured) or WhisperLiveKit
  → transcribed text → normal persona_chat() pipeline
  → LLM response text → TTS → audio WebSocket back to browser
```

**VAD comparison for this use case:**

| VAD | Size | CPU | Accuracy | Python | Verdict |
|-----|------|-----|----------|--------|---------|
| webrtcvad (Google) | 50KB | Very low | Basic energy-based | `py-webrtcvad` | Good enough, simple |
| Silero VAD | 1MB | Low | Deep learning, much better | `silero-vad` package | Recommended for accuracy |
| Cobra (Picovoice) | Tiny | Lowest | Deep learning | SDK required | Overkill, license cost |

**Turn detection:** Silero VAD + end-of-utterance heuristic (500ms silence after speech detected = turn complete). Do NOT use OpenAI Realtime API — vendor lock-in, cloud dependency, requires OpenAI account, expensive ($0.06/min input audio).

**Complexity:** HIGH — new WebSocket endpoint, AudioWorklet browser code, VAD integration, streaming TTS back. Most complex feature in v3.0. Build last.

---

## Feature Dependencies

```
(1) Multi-provider routing
    └──enhances──> (2) Skills library [skills can call specific providers per task]
    └──required by──> (4) Image generation [needs fal.ai / openai provider configured]

(2) Skills library
    └──requires──> CronService [reminders, timer skills use it]
    └──requires──> Browser tool [summarize, news, web-search skills use it]
    └──requires──> MemoryEngine [notes skill reads/writes memory]

(3) TTS voice output
    └──requires──> FFmpeg [already used in AudioProcessor]
    └──required by──> (7) Realtime voice [TTS is the voice output half of voice streaming]
    └──enhances──> Baileys bridge [outbound voice note path]

(4) Image generation
    └──requires──> (1) Provider routing [fal_ai provider key in synapse.json]
    └──requires──> outbound media path [Baileys image attachment]
    └──enhances──> MemoryEngine [image prompts stored for follow-up context]

(5) Cron isolated agents
    └──requires──> CronService [already built, needs context builder addition]
    └──uses──> MemoryEngine [context builder queries recent memories]

(6) Web dashboard
    └──requires──> SSE /pipeline/events [already exists, needs extension]
    └──requires──> CronService REST API [already exists]
    └──enhances──> (5) Cron jobs [dashboard is primary control surface for cron]

(7) Realtime voice streaming
    └──requires──> (3) TTS [TTS output for voice responses]
    └──requires──> FastAPI WebSocket [already in ws_server.py pattern]
    └──requires──> silero-VAD or webrtcvad [new dependency]
    └──conflicts──> Always-on local Whisper [RAM constraint]
```

### Dependency Notes

- **(4) image generation requires (1) provider routing:** fal.ai needs `FAL_AI_API_KEY` in providers, routed through litellm `image_generation()`. Can't work without provider config.
- **(7) realtime voice requires (3) TTS:** Voice streaming is STT → LLM → TTS. TTS must be built first as the output path.
- **(2) skills library enhances (1) routing:** Once skills are registered, semantic router can pick provider based on skill requirements (e.g., skills needing vision use gpt-4o, skills needing speed use flash).
- **(6) dashboard conflicts with Full React rewrite:** HTMX + SSE is the deliberate choice. Full SPA rewrite deferred — it conflicts with "ship fast" constraint of a milestone harvest.

---

## MVP Definition

### Launch With (v3.0 Phase 1 — Provider + Skills)

Minimum to unlock the headline capability and unblock users who are waiting.

- [ ] OpenAI, Anthropic native, DeepSeek, Mistral, Together.ai documented in `synapse.json` template — config only, validates the routing layer works for 10+ providers
- [ ] 10 bundled skills (weather, notes, reminders, web-search, translate, summarize, calculator, news, unit-convert, timer) — fills the skills library gap

### Add After Validation (v3.0 Phase 2 — Media Output)

After routing is proven stable.

- [ ] TTS voice replies (edge-tts default, ElevenLabs opt-in) — voice output is table stakes differentiator
- [ ] Image generation (DALL-E 3 + Flux via litellm) — "draw me X" is frequently requested

### Add Next (v3.0 Phase 3 — Cron + Dashboard)

Operational visibility and cron improvement.

- [ ] Cron context file injection (IsolatedContextBuilder) — makes cron agents actually useful for proactive tasks
- [ ] Real-time dashboard panels (cron manager, channel health, model routing log) — makes the system observable

### Future Consideration (v3.0 Phase 4 — Voice Streaming)

Deferred due to HIGH complexity and hardware constraints.

- [ ] Realtime voice streaming (WebSocket + VAD + streaming STT + streaming TTS) — build last, highest risk

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| 10+ provider routing (config) | HIGH | LOW | P1 |
| 10 bundled skills | HIGH | MEDIUM | P1 |
| TTS voice replies (WhatsApp) | HIGH | MEDIUM | P1 |
| Image generation ("draw me X") | HIGH | MEDIUM | P1 |
| Cron context injection | MEDIUM | LOW | P2 |
| Real-time dashboard panels | MEDIUM | MEDIUM | P2 |
| Realtime voice streaming | HIGH | HIGH | P3 |

**Priority key:**
- P1: Ship in v3.0 core phases
- P2: Ship in v3.0 operational phases
- P3: Ship in v3.0 final phase — needs dedicated phase

---

## Competitor Feature Analysis

| Feature | OpenClaw (TypeScript) | ChatGPT (cloud) | Synapse v3.0 approach |
|---------|----------------------|-----------------|----------------------|
| Provider routing | 47 providers, config-driven | OpenAI only | litellm covers 100+ — expose 10 key ones in docs |
| Skills / plugins | 53 bundled + 13K community | Plugins (deprecated) / GPTs | 10 bundled SKILL.md format; community-extensible |
| TTS voice output | ElevenLabs skill | Voice mode (GPT-4o Realtime) | edge-tts default (free) + ElevenLabs opt-in |
| Image generation | DALL-E / Flux via skill | DALL-E 3 built-in | litellm `image_generation()` — provider-agnostic |
| Cron / scheduling | Isolated per-agent cron jobs | No scheduling | CronService (built) + context builder (new) |
| Dashboard | OpenClaw.app GUI | Web interface | FastAPI + HTMX + SSE — functional not beautiful |
| Realtime voice | WebRTC in app | GPT-4o Realtime | WebSocket + Silero VAD + Groq Whisper |

---

## Sources

- litellm Router docs (routing strategies, fallback, cooldown): [https://docs.litellm.ai/docs/routing](https://docs.litellm.ai/docs/routing)
- litellm image_generation() + fal.ai: [https://docs.litellm.ai/docs/image_generation](https://docs.litellm.ai/docs/image_generation), [https://docs.litellm.ai/docs/providers/fal_ai](https://docs.litellm.ai/docs/providers/fal_ai)
- ElevenLabs TTS latency and streaming: [https://elevenlabs.io/blog/enhancing-conversational-ai-latency-with-efficient-tts-pipelines](https://elevenlabs.io/blog/enhancing-conversational-ai-latency-with-efficient-tts-pipelines)
- edge-tts Python library: [https://github.com/rany2/edge-tts](https://github.com/rany2/edge-tts)
- TTS latency benchmark 2025: [https://picovoice.ai/blog/text-to-speech-latency/](https://picovoice.ai/blog/text-to-speech-latency/)
- Image gen API comparison 2026: [https://blog.laozhang.ai/en/posts/ai-image-generation-api-comparison-2026](https://blog.laozhang.ai/en/posts/ai-image-generation-api-comparison-2026)
- OpenClaw cron isolation pattern: [https://dev.to/hex_agent/openclaw-cron-jobs-automate-your-ai-agents-daily-tasks-4dpi](https://dev.to/hex_agent/openclaw-cron-jobs-automate-your-ai-agents-daily-tasks-4dpi)
- Honcho Memory isolated context pattern: [https://termo.ai/skills/honcho-memory](https://termo.ai/skills/honcho-memory)
- VAD comparison 2025: [https://picovoice.ai/blog/best-voice-activity-detection-vad-2025/](https://picovoice.ai/blog/best-voice-activity-detection-vad-2025/)
- WhisperLiveKit streaming STT: [https://pypi.org/project/whisperlivekit/](https://pypi.org/project/whisperlivekit/)
- Realtime STT/TTS architecture comparison: [https://softcery.com/lab/ai-voice-agents-real-time-vs-turn-based-tts-stt-architecture](https://softcery.com/lab/ai-voice-agents-real-time-vs-turn-based-tts-stt-architecture)
- OpenClaw bundled skills list: [https://docs.openclaw.ai/tools/skills](https://docs.openclaw.ai/tools/skills)
- FastAPI SSE real-time dashboard: [https://blog.greeden.me/en/2025/10/28/weaponizing-real-time-websocket-sse-notifications-with-fastapi-connection-management-rooms-reconnection-scale-out-and-observability/](https://blog.greeden.me/en/2025/10/28/weaponizing-real-time-websocket-sse-notifications-with-fastapi-connection-management-rooms-reconnection-scale-out-and-observability/)
- WhatsApp PTT OGG Opus format: [https://www.wappbiz.com/blogs/voice-messages-using-whatsapp-api/](https://www.wappbiz.com/blogs/voice-messages-using-whatsapp-api/)

---

*Feature research for: Synapse-OSS v3.0 OpenClaw Feature Harvest*
*Researched: 2026-04-08*
