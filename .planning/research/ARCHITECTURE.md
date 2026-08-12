# Architecture Research

**Domain:** Self-hosted personal AI middleware — v3.0 OpenClaw Feature Harvest
**Researched:** 2026-04-08
**Confidence:** HIGH (based on direct codebase inspection + verified external sources)

---

## Standard Architecture

### System Overview — Existing v2.0 Baseline

```
+----------------------------------------------------------------------+
|                        Channel Layer                                  |
|  WhatsApp  |  Telegram  |  Discord  |  Slack  |  WebSocket  |  HTTP  |
+----------------------------------------------------------------------+
|                        Gateway Layer                                  |
|     FloodGate (3s batch) -> Dedup (5-min TTL) -> TaskQueue (100)      |
|                           MessageWorker x2                            |
+----------------------------------------------------------------------+
|                        Chat Pipeline                                  |
|   persona_chat()                                                      |
|     SBS.get_prompt() -> MemoryEngine.query() -> DualCognition.think() |
|     -> route_traffic_cop() -> SynapseLLMRouter.call()                 |
+----------------------------------------------------------------------+
|                        Singleton Registry (_deps.py)                  |
|  brain  gate  memory_engine  dual_cognition  sbs_registry             |
|  skill_registry  skill_router  agent_registry  synapse_llm_router     |
+----------------------------------------------------------------------+
|                        Persistence Layer                              |
|  SQLite+sqlite-vec  |  LanceDB  |  SQLiteGraph  |  ~/.synapse/        |
+----------------------------------------------------------------------+
```

### v3.0 Target Architecture — New Components in Context

```
+----------------------------------------------------------------------+
|                        Channel Layer (unchanged)                      |
|  WhatsApp  Telegram  Discord  Slack  WebSocket  HTTP                  |
|                 + Voice channel (new: WebRTC/STT input)               |
+----------------------------------------------------------------------+
|                        Gateway Layer (unchanged)                      |
|     FloodGate -> Dedup -> TaskQueue -> MessageWorker                  |
|            + MediaRouter (new: routes audio/image payloads)           |
+----------------------------------------------------------------------+
|                        Chat Pipeline (modified)                       |
|   persona_chat()                                                      |
|     SBS -> Memory -> DualCognition -> TrafficCop -> LLMRouter         |
|          + SkillRunner.run(manifest) [expand bundled skills]          |
|          + TTSRouter.synthesize(text) [new: voice output gate]        |
|          + ImageRouter.generate(prompt) [new: image gen gate]         |
+----------------------------------------------------------------------+
|                        Provider Layer (modified)                      |
|  SynapseLLMRouter (synapse.json model_mappings, already extensible)  |
|    + TTSProvider (new: ElevenLabs | edge-tts selector)                |
|    + ImageProvider (new: DALL-E 3 | fal.ai/Flux selector)             |
+----------------------------------------------------------------------+
|                        Singleton Registry (_deps.py, modified)        |
|  [existing singletons unchanged]                                      |
|    + tts_router: TTSRouter | None                                     |
|    + image_router: ImageRouter | None                                 |
|    + cron_service: CronService (v2, already exists, needs wiring)     |
+----------------------------------------------------------------------+
|                        Web Control Panel (new)                        |
|  dashboard/ (Vanilla JS + SSE, existing skeleton)                     |
|    Expand: skill mgmt, cron editor, provider config, voice monitor    |
+----------------------------------------------------------------------+
|                        Persistence Layer (unchanged)                  |
|  SQLite  |  LanceDB  |  SQLiteGraph  |  ~/.synapse/                   |
|    + ~/.synapse/tts_cache/ (new: audio file store)                    |
|    + ~/.synapse/image_cache/ (new: generated image store)             |
+----------------------------------------------------------------------+
```

---

## Component Responsibilities — What's New vs Modified vs Unchanged

### New Components (build from scratch)

| Component | File Location | Responsibility |
|-----------|--------------|----------------|
| `TTSRouter` | `sci_fi_dashboard/tts/router.py` | Provider selector (ElevenLabs vs edge-tts), rate-limit guard, audio file write |
| `TTSProvider` ABC | `sci_fi_dashboard/tts/base.py` | Interface: `synthesize(text, voice_id) -> Path` |
| `ElevenLabsProvider` | `sci_fi_dashboard/tts/elevenlabs.py` | ElevenLabs async SDK, streaming audio |
| `EdgeTTSProvider` | `sci_fi_dashboard/tts/edgetts.py` | edge-tts offline fallback |
| `ImageRouter` | `sci_fi_dashboard/image_gen/router.py` | DALL-E 3 / Flux API dispatch, prompt detection |
| `ImageProvider` ABC | `sci_fi_dashboard/image_gen/base.py` | Interface: `generate(prompt) -> Path` |
| `VoiceChannel` | `channels/voice.py` | WebRTC/WebSocket inbound STT, maps to ChannelMessage |
| `VoiceSessionManager` | `sci_fi_dashboard/voice/session.py` | Lifecycle of real-time voice sessions |
| `SkillBundle` (10 skills) | `sci_fi_dashboard/skills/bundled/` | weather, reminders, notes, translate, summarize, web-scrape, image-describe, calculator, timer, currency-convert |
| Dashboard v2 | `static/dashboard/` | Expanded interactive panels (cron editor, skill manager, provider config, voice monitor) |

### Modified Components (extend, not rewrite)

| Component | Change Needed | Risk |
|-----------|--------------|------|
| `_deps.py` | Add `tts_router`, `image_router` singletons — new fields only | LOW |
| `api_gateway.py` lifespan | Init `TTSRouter`, `ImageRouter` — same pattern as SkillSystem init | LOW |
| `chat_pipeline.py` `persona_chat()` | Post-LLM hooks: TTS gate check, image intent check, BackgroundTask dispatch | MEDIUM — stays after LLM call, before send |
| `llm_router.py` `_KEY_MAP` | Already has mistral, togetherai, cohere, xai — add `deepseek`, `fal_ai`, `elevenlabs` entries | LOW |
| `synapse_config.py` | Add `tts`, `image_gen` config sections to SynapseConfig dataclass | MEDIUM — 50+ importers, add-only changes |
| `CronService` | Already built and started in lifespan — wire `execute_fn` to `persona_chat()` | LOW |
| `routes/` | Add `tts.py`, `image_gen.py`, `voice.py` route modules | LOW |
| `PipelineEventEmitter` | Add new event types: `tts.synthesizing`, `image_gen.generating`, `voice.transcribing` | LOW |

### Zone 1 (Immutable — Do Not Touch)

Per PROJECT.md non-negotiable constraints:
- `api_gateway.py` core auth and gateway token validation
- `rollback.py` and snapshot/consent flow
- `gateway/` flood, dedup, queue internals
- `_deps.py` existing singletons (only additive changes allowed)

---

## Recommended Project Structure — v3.0 Additions Only

```
workspace/sci_fi_dashboard/
+-- tts/
|   +-- __init__.py
|   +-- base.py              # TTSProvider ABC: synthesize(text) -> Path
|   +-- router.py            # TTSRouter: selects provider, caches output
|   +-- elevenlabs.py        # ElevenLabsProvider (requires ELEVENLABS_API_KEY)
|   +-- edgetts.py           # EdgeTTSProvider (zero-dependency offline fallback)
+-- image_gen/
|   +-- __init__.py
|   +-- base.py              # ImageProvider ABC: generate(prompt) -> Path
|   +-- router.py            # ImageRouter: intent detection, provider dispatch
|   +-- dalle.py             # DALL-E 3 via litellm image generation endpoint
|   +-- fal.py               # fal.ai/Flux (optional, lower cost)
+-- voice/
|   +-- __init__.py
|   +-- session.py           # VoiceSessionManager: track active WebRTC sessions
|   +-- transcriber.py       # Whisper/Groq STT wrapper (reuse existing audio path)
|   +-- vad.py               # Voice Activity Detection (simple energy or webrtcvad)
+-- skills/
|   +-- bundled/             # 10 bundled skills -- SKILL.md directories only
|       +-- weather/
|       +-- reminders/
|       +-- notes/
|       +-- translate/
|       +-- summarize/
|       +-- web-scrape/
|       +-- image-describe/
|       +-- calculator/
|       +-- timer/
|       +-- currency-convert/
+-- routes/
|   +-- tts.py               # GET /tts/voices, POST /tts/preview
|   +-- image_gen.py         # POST /image-gen/generate, GET /image-gen/history
|   +-- voice.py             # WebSocket /voice/stream (WebRTC signaling + STT)
+-- static/dashboard/
    +-- index.html           # Extend: add skill mgmt, cron editor, provider config
    +-- synapse.js           # Extend: TTS player, image preview, voice recorder UI
    +-- panels/
    |   +-- skills.js        # Skill manager panel
    |   +-- cron.js          # Cron job editor panel
    |   +-- providers.js     # Provider config + test panel
    |   +-- voice.js         # Voice session monitor
    +-- skill-creator/       # Already exists
```

---

## Architectural Patterns

### Pattern 1: Provider ABC with Lifespan-Gated Init

**What:** Each new capability (TTS, image gen) uses an ABC with multiple backend implementations. The router is initialized in the lifespan block, same pattern as `SkillSystem` init in `api_gateway.py`.

**When to use:** Any feature where the backend is swappable (ElevenLabs vs edge-tts, DALL-E vs Flux).

**Trade-offs:** Adds one indirection layer but means zero changes to `chat_pipeline.py` when swapping backends. Consistent with existing skill and embedding provider patterns already in the codebase.

```python
# tts/base.py
class TTSProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, voice_id: str | None = None) -> Path: ...

# tts/router.py
class TTSRouter:
    def __init__(self, provider: TTSProvider, cache_dir: Path):
        self._provider = provider
        self._cache_dir = cache_dir

    async def synthesize(self, text: str) -> Path | None:
        # Returns path to .ogg file, or None if TTS is disabled
        ...
```

### Pattern 2: Post-Pipeline Hook in persona_chat()

**What:** After the LLM returns text, run lightweight classifiers that decide whether to also produce audio or an image. These are additive post-processing hooks, not replacements to the core flow.

**When to use:** TTS (triggers on every reply if TTS enabled), image gen (only when `image_intent` detected).

**Trade-offs:** Adds latency risk to reply path. Mitigate by: TTS runs as a `BackgroundTask` for async delivery, image gen sends a second message. Never block the text reply.

```python
# chat_pipeline.py — after LLM call, before return
if deps.tts_router and config.tts_enabled:
    background_tasks.add_task(
        _send_tts_reply, reply_text, channel_id, chat_id
    )

if deps.image_router and _looks_like_image_request(user_message):
    background_tasks.add_task(
        _send_image_reply, user_message, channel_id, chat_id
    )
```

### Pattern 3: Bundled Skills as SKILL.md Directories

**What:** The 10 bundled skills ship as directories under `skills/bundled/`. The SkillLoader already handles directory-based skill loading. Bundled skills are copied to `~/.synapse/skills/` on first boot if not present.

**When to use:** Every bundled skill. No Python plugin required — skills are `SKILL.md` + optional `scripts/` entry point.

**Trade-offs:** User-editable skills can diverge from the shipped version (intended behavior per "skills as AI-writable" design decision). Risk: updates to bundled skills do not auto-apply if user has modified them. Accept this trade-off consciously.

### Pattern 4: CronService Already Built — Wire, Not Rebuild

**What:** `cron/` module (`CronService`, `isolated_agent.py`, types, store) is fully implemented in v2.0. The `api_gateway.py` lifespan already starts it. The missing piece is passing a real `execute_fn` that routes through `persona_chat()`.

**When to use:** Cron v2 feature work. The only work needed is ensuring `execute_fn` is wired to the actual chat pipeline, not a stub, and that isolated agents receive a memory snapshot, not the live `MemoryEngine`.

```python
# api_gateway.py lifespan — replace stub execute_fn with a real one
async def _cron_execute(message: str, session_key: str, **kwargs) -> str:
    from sci_fi_dashboard.chat_pipeline import persona_chat
    req = ChatRequest(message=message, session_key=session_key, **kwargs)
    result = await persona_chat(req, background_tasks=BackgroundTasks(), ...)
    return result.get("reply", "")

app.state.cron_service = CronService(
    agent_id="system",
    data_root=str(deps._synapse_cfg.data_root),
    execute_fn=_cron_execute,
    channel_registry=deps.channel_registry,
)
```

### Pattern 5: Voice Channel as a Standard BaseChannel

**What:** WebRTC/voice input is treated as another channel adapter — it produces `ChannelMessage` objects and pushes them into the existing `TaskQueue`. Voice transcription (Whisper via Groq — already used for WhatsApp OGG audio) runs in the channel adapter, not in the pipeline.

**When to use:** Real-time voice streaming. Keeps the pipeline agnostic to input modality.

**Trade-offs:** STT latency (200-500ms) is absorbed by the channel layer before the message enters the pipeline. Acceptable for conversational voice, not for sub-100ms interactive use.

### Pattern 6: Web Control Panel — Expand Existing, No Framework Swap

**What:** The existing `static/dashboard/index.html` + `synapse.js` uses vanilla JS + Tailwind CDN + SSE. Extend this — add panel modules as separate `.js` files, keep the SSE connection from `pipeline_emitter.py`.

**Why not React/Vue:** Self-hosted tool, zero build step required. Adding a JS framework means adding npm, a bundler, and a build step that breaks the simple "drop files in static/" model. The existing dashboard already renders well.

**Trade-offs:** Vanilla JS is more verbose for complex UIs, but the complexity here is panels, not full SPAs. ES modules work natively in modern browsers without a bundler.

---

## Data Flow

### TTS Voice Reply Flow

```
persona_chat() returns text reply
    |
    +-> text reply sent immediately via channel_registry.send(text)
    |
    +-> BackgroundTask: TTSRouter.synthesize(reply_text)
            |
            +-> TTSProvider.synthesize() -> .ogg at ~/.synapse/tts_cache/
            |
            +-> channel_registry.send(audio_path, chat_id)
                via WhatsAppChannel.send_audio() [new method]
```

### Image Generation Flow

```
User: "draw me a sunset over Tokyo"
    |
    +-> FloodGate -> Dedup -> TaskQueue -> MessageWorker -> persona_chat()
    |
    +-> text reply: "Sure, generating that for you..."  [sent immediately]
    |
    +-> BackgroundTask: ImageRouter.generate(user_message)
            |
            +-> ImageProvider.generate(prompt) -> .png at ~/.synapse/image_cache/
            |
            +-> channel_registry.send(image_path, chat_id)
```

### Cron Isolated Agent Flow

```
CronService._timer_loop() fires
    |
    +-> _execute_job(job) -> _run_payload(job)
            |
            +-- ISOLATED session: run_isolated_agent(payload, session_key, execute_fn)
            |       +-> execute_fn(message, session_key) -> persona_chat()
            |               +-> memory snapshot (NOT live MemoryEngine)
            |               +-> SubAgentRunner isolation pattern
            |
            +-> deliver_output(output, job.delivery, channel_registry)
                    +-> channel_registry.send(output, to=job.delivery.to)
```

### Voice Streaming Flow

```
Browser/Client opens WebSocket to /voice/stream
    |
    +-> VoiceChannel.start() listens for audio chunks
            |
            +-> Transcriber.transcribe(audio_chunk) -> partial text (Groq Whisper)
                    |
                    +-> On sentence boundary: build ChannelMessage
                            |
                            +-> TaskQueue.put(ChannelMessage)
                                    +-> MessageWorker -> persona_chat()
                                            +-> TTSRouter.synthesize(reply)
                                                    +-> stream audio back to client
```

### Expanded Provider Selection Flow

```
synapse.json model_mappings:
  casual:   "deepseek/deepseek-chat"
  code:     "anthropic/claude-3-5-sonnet-20241022"
  analysis: "together_ai/meta-llama/Llama-3-70b-chat-hf"
    |
    +-> SynapseLLMRouter._do_call(model=...) -- NO change needed
            litellm handles deepseek/, together_ai/, anthropic/ natively
            _KEY_MAP already has mistral, togetherai -- add deepseek entry only
```

---

## Integration Points — Explicit Mapping

### New vs Existing Boundaries

| Boundary | Communication | Integration Work |
|----------|--------------|-----------------|
| `chat_pipeline.py` <-> `TTSRouter` | Direct call via BackgroundTask | ~10 lines post-LLM in `persona_chat()` |
| `chat_pipeline.py` <-> `ImageRouter` | Direct call via BackgroundTask | Image intent check + BackgroundTask |
| `WhatsAppChannel` <-> `TTSRouter` | `send_audio(path, chat_id)` on channel | Add `send_audio()` to WA/Telegram/Discord adapters |
| `api_gateway.py` <-> `TTSRouter` | Lifespan init (same as SkillSystem pattern) | ~20-line block in lifespan |
| `CronService` <-> `persona_chat()` | `execute_fn` callback | Wire real `execute_fn`; currently initialized with None |
| `_deps.py` <-> `TTSRouter`/`ImageRouter` | Module-level `None` singletons | 2 new lines — same pattern as `skill_registry` |
| `synapse_config.py` <-> TTS/Image config | New optional config sections | Add-only fields on `SynapseConfig` (LOW blast radius) |
| `PipelineEventEmitter` <-> Dashboard | New event type strings | Add event constants, emit from TTS/image routers |
| `VoiceChannel` <-> `ChannelRegistry` | `channel_registry.register(VoiceChannel(...))` | Standard channel registration in `channel_setup.py` |
| `SynapseLLMRouter._KEY_MAP` <-> new providers | Dict entry addition | 2-3 new lines in `_KEY_MAP` in `llm_router.py` |
| `static/dashboard/` <-> new panels | New `.js` panel files | No FastAPI changes required — static files only |

### External Services

| Service | Integration Pattern | Config | Confidence |
|---------|---------------------|--------|------------|
| ElevenLabs | `pip install elevenlabs`, `AsyncElevenLabs` client | `ELEVENLABS_API_KEY` in `synapse.json -> providers` | MEDIUM — SDK well-documented, streaming latency varies |
| edge-tts | `pip install edge-tts`, `communicate()` coroutine | No key needed | HIGH — offline fallback, zero external dependency |
| DALL-E 3 | `litellm.aimage_generation()` — already in litellm | `OPENAI_API_KEY` (already in `_KEY_MAP`) | HIGH — litellm docs confirmed |
| fal.ai / Flux | `pip install fal-client`, REST API | `FAL_KEY` | LOW — less tested path, optional secondary |
| DeepSeek | litellm `deepseek/` prefix | `DEEPSEEK_API_KEY` -> add to `_KEY_MAP` | HIGH — litellm docs confirmed |
| Together AI | litellm `together_ai/` prefix | `TOGETHERAI_API_KEY` -> already in `_KEY_MAP` | HIGH — confirmed |
| Mistral native | litellm `mistral/` prefix | `MISTRAL_API_KEY` -> already in `_KEY_MAP` | HIGH — confirmed |
| FastRTC | `pip install fastrtc`, `.mount(app)` on FastAPI | No external key | MEDIUM — released 2025, limited production history |
| Groq Whisper | Already in codebase via `AudioProcessor` | `GROQ_API_KEY` (already exists) | HIGH — reuse existing path |

---

## Scaling Considerations

Synapse is a single-user self-hosted system. Scaling concerns are about resource contention, not user count.

| Resource | Current State | v3.0 Risk | Mitigation |
|----------|---------------|-----------|------------|
| CPU | asyncio single-threaded, non-blocking | TTS synthesis blocks if sync call used | Use `asyncio.to_thread()` for edge-tts; ElevenLabs SDK is already async |
| Memory | SQLite WAL + LanceDB in-process | Image and audio caches grow unbounded | TTL-based cleanup in `GentleWorkerLoop` (same pattern as `media/` 120s TTL) |
| Disk | `~/.synapse/` | TTS cache accumulates .ogg files over time | Prune cache files older than 7 days in `GentleWorkerLoop` |
| Network | litellm Router handles backoff | Image gen adds large response payloads | Resize and compress images before channel send |
| uvicorn event loop | `asyncio.create_task()` for all workers | Voice WebRTC adds a persistent connection per session | One task per voice session; add configurable max concurrent sessions |

---

## Anti-Patterns

### Anti-Pattern 1: Calling asyncio.run() Inside the Lifespan

**What people do:** When adding new async services (TTS router startup, voice session manager), call `asyncio.run()` to initialize them.

**Why it's wrong:** uvicorn owns the event loop. Nested `asyncio.run()` raises `RuntimeError: This event loop is already running`. Every service init since v1.0 uses `asyncio.create_task()` or direct `await` inside the lifespan body.

**Do this instead:** `await tts_router.start()` inside the lifespan `async with` block, same as all existing service inits.

### Anti-Pattern 2: Modifying synapse_config.py Non-Additively

**What people do:** Change existing field names or restructure `SynapseConfig` to accommodate new features.

**Why it's wrong:** `synapse_config.py` is imported by 50+ files. Renaming or removing any field causes `AttributeError` across the codebase without a systematic grep and fix pass.

**Do this instead:** Add new optional config sections as separate dataclass fields with `None` defaults. Never rename or remove existing fields. Use `Optional[TTSConfig] = None` pattern.

### Anti-Pattern 3: Blocking the Chat Pipeline for TTS or Image Gen

**What people do:** Await TTS synthesis or image generation inside `persona_chat()` before returning the text reply.

**Why it's wrong:** TTS synthesis takes 500ms-3s; image generation 5-30s. The user sees no reply until synthesis completes, and the pipeline queue backs up.

**Do this instead:** Return the text reply immediately, use `BackgroundTasks` to run TTS/image generation and deliver the result as a second message. This is identical to the existing `auto-continue` BackgroundTask pattern already in `chat_pipeline.py`.

### Anti-Pattern 4: Hardcoding Provider Credentials in New Files

**What people do:** Put `ELEVENLABS_API_KEY = "sk_..."` directly in new provider files, or embed API base URLs in Python code.

**Why it's wrong:** The OSS pre-push checklist explicitly prohibits tokens in committed files. Also bypasses the `_inject_provider_keys()` pattern that centralizes credential injection.

**Do this instead:** Add entries to `_KEY_MAP` in `llm_router.py` (or a parallel `_TTS_KEY_MAP` in `tts/router.py`). Read from `synapse.json -> providers -> elevenlabs -> api_key`. Inject via the same env-var pattern.

### Anti-Pattern 5: Rewriting CronService v2

**What people do:** Seeing both `cron_service.py` (old simple file) and `cron/service.py` (new v2 module), treat the v2 as incomplete and rewrite from scratch.

**Why it's wrong:** `cron/service.py` (`CronService`) is fully implemented with isolated agent support, delivery modes, failure alerting, and missed-job catch-up. The only gap is the `execute_fn` wiring.

**Do this instead:** Wire `execute_fn` to `persona_chat()` in the lifespan block. The infrastructure is complete and tested.

### Anti-Pattern 6: Adding a JS Framework to the Dashboard

**What people do:** Reach for React or Vue when dashboard panels get complex.

**Why it's wrong:** Self-hosted deployment model — zero build toolchain is a hard constraint. The existing dashboard loads as static files from `StaticFiles("/static")`. A JS framework build requires npm + vite + build pipeline + compiled artifacts, breaking zero-dependency server startup.

**Do this instead:** Vanilla JS module pattern — split functionality into panel `.js` files, import as ES modules. Use the existing Tailwind CDN + SSE infrastructure. No bundler needed.

---

## Suggested Build Order — Dependency-Driven

The order below is based on: (a) what each feature depends on, (b) complexity/risk, (c) user-visible value delivered early.

### Phase 1: Expanded Provider Routing (2 days)

**Dependencies:** Nothing new. litellm already supports all target providers.

**Work:** Add `deepseek` to `_KEY_MAP` in `llm_router.py`. Update `synapse.json.example` with example `model_mappings` for all 10+ providers. Add provider config documentation.

**Why first:** Zero risk — the router is already litellm-backed. Proves the litellm prefix pattern for the 10+ provider requirement without any infrastructure work.

### Phase 2: Bundled Skills Library (5 days)

**Dependencies:** SkillSystem (already in `_deps.py` and lifespan). No new infrastructure needed.

**Work:** Create 10 skill directories under `skills/bundled/`. Each is a `SKILL.md` file + optional `scripts/skill.py`. Add first-boot copy logic to lifespan: if `~/.synapse/skills/weather/` does not exist, copy from bundled.

**Why second:** Highest user value, lowest technical risk. The entire skill loading infrastructure already exists. Work is content (the SKILL.md files), not infrastructure.

### Phase 3: TTS Voice Output (5 days)

**Dependencies:** Working channel `send()` (exists). ElevenLabs and edge-tts pip packages.

**Work:** New `tts/` module (TTSProvider ABC, ElevenLabsProvider, EdgeTTSProvider, TTSRouter). Add `send_audio()` to WhatsApp/Telegram/Discord channel adapters. Wire into `persona_chat()` as BackgroundTask. Add `tts` config section to `SynapseConfig`. Add `/tts/` route module.

**Why third:** Depends only on stable channel adapters and pip dependencies. Independent of image gen and voice streaming.

### Phase 4: Image Generation (4 days)

**Dependencies:** litellm `aimage_generation()` (exists). TTS phase complete for consistent multimodal delivery pattern.

**Work:** New `image_gen/` module (ImageProvider ABC, DALLEProvider, optional FalProvider, ImageRouter). Image intent detection in `persona_chat()`. Channel adapter `send_image()` methods. Image cache with TTL cleanup.

**Why fourth:** Lower risk than voice streaming. Builds on the async BackgroundTask delivery pattern proven in Phase 3.

### Phase 5: Web Control Panel Expansion (6 days)

**Dependencies:** New event types emitted by TTS and image gen. CronService `execute_fn` wiring.

**Work:** Expand `static/dashboard/index.html`. Add panel JS files: `skills.js`, `cron.js`, `providers.js`, `voice.js`. Add `/tts/voices` and `/image-gen/history` API endpoints. Wire CronService `execute_fn` to `persona_chat()` (covered here as it feeds the cron panel).

**Why fifth:** Depends on previous features emitting events worth displaying. A panel showing no data is low value until the underlying features work.

### Phase 6: Realtime Voice Streaming (8 days)

**Dependencies:** TTS (Phase 3 complete), existing Groq Whisper audio path, channel infrastructure.

**Work:** New `voice/` module (VoiceSessionManager, Transcriber, VAD). WebSocket `/voice/stream` endpoint. VoiceChannel adapter registered in `channel_setup.py`. Browser-side voice recorder UI in dashboard. Integration with TTS for streaming audio response back to client.

**Why last:** Highest complexity, depends on TTS working end-to-end, requires browser WebRTC/WebSocket support in the dashboard UI, and most likely to surface edge cases around session lifecycle, partial transcription buffering, and concurrent connections.

---

## Sources

- Direct codebase inspection: `_deps.py`, `api_gateway.py`, `chat_pipeline.py`, `llm_router.py`, `cron/service.py`, `skills/schema.py`, `skills/router.py`, `pipeline_emitter.py`, `channels/base.py`, `static/dashboard/index.html` (HIGH confidence — current code)
- litellm provider docs: [docs.litellm.ai/docs/providers](https://docs.litellm.ai/docs/providers) — DeepSeek, Mistral, Together AI confirmed supported natively (HIGH confidence)
- ElevenLabs Python SDK: [elevenlabs.io/docs/api-reference/how-to-use-tts-with-streaming](https://elevenlabs.io/docs/api-reference/how-to-use-tts-with-streaming) — async client, streaming audio (MEDIUM confidence)
- FastRTC, Hugging Face 2025: [fastrtc.org](https://fastrtc.org) — WebRTC + WebSocket voice with FastAPI `.mount(app)` (MEDIUM confidence — new library)
- WhisperLiveKit: [github.com/QuentinFuxa/WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) — simultaneous STT, 2025 (MEDIUM confidence)
- FastAPI SSE dashboard patterns: [testdriven.io/blog/fastapi-svelte](https://testdriven.io/blog/fastapi-svelte) (MEDIUM confidence — pattern verified against existing codebase structure)
- DALL-E via litellm: [docs.litellm.ai](https://docs.litellm.ai) — `litellm.image_generation()` confirmed (HIGH confidence)

---

*Architecture research for: Synapse-OSS v3.0 — OpenClaw Feature Harvest*
*Researched: 2026-04-08*
