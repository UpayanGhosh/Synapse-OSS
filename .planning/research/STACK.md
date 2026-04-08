# Stack Research

**Domain:** AI personal assistant — v3.0 new capability additions
**Researched:** 2026-04-08
**Confidence:** HIGH (provider configs verified via litellm docs + PyPI), MEDIUM (voice streaming patterns), LOW (React frontend specifics — project has not started that yet)

---

> **Scope:** v3.0 OpenClaw Feature Harvest ONLY. Validated v2.0 stack (FastAPI, litellm, SQLite, LanceDB, FastEmbed, FlashRank, asyncio) is NOT re-researched here. Only net-new libraries and integration points are documented.

---

## Recommended Stack

### 1. Expanded LLM Providers (zero new libraries)

**Finding:** No new pip packages needed. litellm already covers all five target providers via provider-prefixed model strings. The work is configuration, not code.

| Provider | litellm Prefix | Key Env Var | Example Model String | Notes |
|----------|---------------|-------------|---------------------|-------|
| OpenAI | `openai/` | `OPENAI_API_KEY` | `openai/gpt-4o` | Already works; `openai/gpt-4o-mini` for casual role |
| Anthropic | `anthropic/` | `ANTHROPIC_API_KEY` | `anthropic/claude-3-5-sonnet-20241022` | Already works via `litellm.drop_params=True` shim |
| DeepSeek | `deepseek/` | `DEEPSEEK_API_KEY` | `deepseek/deepseek-chat`, `deepseek/deepseek-reasoner` | Reasoner: pass `thinking={"type":"enabled"}` — litellm handles it |
| Mistral | `mistral/` | `MISTRAL_API_KEY` | `mistral/mistral-large-latest`, `mistral/mistral-small-latest` | Direct Mistral API (not Vertex) |
| Together AI | `together_ai/` | `TOGETHERAI_API_KEY` | `together_ai/meta-llama/Llama-3-70b-chat-hf` | Open-source model hosting |

**Integration point:** `synapse.json → providers` section. Add provider block with `api_key` (referenced via `_inject_provider_keys()` in `synapse_config.py`). Add new role entries to `model_mappings`. No changes to `llm_router.py` or `api_gateway.py`.

**What NOT to do:** Do not add provider-specific SDKs (anthropic, openai, together) as direct dependencies — litellm is the abstraction layer and adding raw SDKs creates duplicate auth paths.

**Confidence:** HIGH — verified against litellm docs (providers page, DeepSeek page, Together AI page).

---

### 2. Bundled Skills Library (no new framework libraries)

**Finding:** The skills framework (v2.0) is complete: `skills/loader.py`, `skills/registry.py`, `skills/router.py`, `skills/runner.py`, `skills/schema.py`, `skills/watcher.py`. Bundled skills live in `skills/bundled/`. New skills are SKILL.md directories — no Python plugin system changes needed.

**Per-skill external dependencies** (added to `requirements-optional.txt` gated by `# optional: skill-X`):

| Skill | New Dependency | Version | Why | Install Gate |
|-------|---------------|---------|-----|-------------|
| Weather | `httpx` | already present | OpenWeatherMap / wttr.in REST calls | none (already in core) |
| Reminders / Notes | none | — | Writes to SQLite via existing `db.py` | none |
| Web Scrape | `trafilatura` | >=2.0.0 | Already in `requirements-optional.txt` | none (already optional) |
| Translate | `httpx` | already present | LibreTranslate self-hosted or DeepL API | none |
| Summarize | none | — | LLM call via existing `SynapseLLMRouter` | none |
| Image Describe | none | — | Pass image URL to multimodal model role | none |

**Key insight:** All 10 planned bundled skills can be implemented using only libraries already in requirements. The skill framework's LLM-call path (`runner.py` → `SynapseLLMRouter`) handles model dispatch. No new framework code is needed.

---

### 3. TTS / Voice Output

**Decision: Dual-mode — `edge-tts` as default (zero API cost), `elevenlabs` as premium opt-in.**

Both are pure Python async, produce MP3/OGG, and integrate cleanly into the existing `AudioProcessor` + Baileys bridge pipeline.

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `edge-tts` | 7.2.8 | Zero-cost TTS via Microsoft Edge neural voices | No API key, fully async (`Communicate.save()` is a coroutine), 400+ voices across 40+ languages, outputs MP3 directly. Works offline once warmed. |
| `elevenlabs` | 2.42.0 | Premium high-quality TTS | ElevenLabs SDK v2, `text_to_speech.convert()` returns bytes or streaming generator. Use `eleven_flash_v2_5` for low-latency at 50% cost. Requires `ELEVENLABS_API_KEY`. |

**Audio format for WhatsApp:** Baileys accepts OGG Opus for voice messages. edge-tts outputs MP3; elevenlabs can output MP3 or OGG. Conversion is needed.

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `pydub` | >=0.25.1 | MP3 → OGG/Opus conversion | Required for WhatsApp voice messages. Needs `ffmpeg` system binary. Accept ffmpeg as a system dependency (already needed for some optional features). |

**Alternative to pydub (if ffmpeg is unacceptable):** `PyOgg` + `opuslib` for pure Opus encoding — but this adds C library system dependencies (libopus, libvorbis) which are harder to manage on Windows than ffmpeg. Stick with pydub + ffmpeg.

**Integration point:** New `tts/` module under `sci_fi_dashboard/`. Called from `channels/whatsapp_bridge.py` send path when `reply_format = "voice"`. TTS provider configured via `synapse.json → tts.provider` (`"edge-tts"` default, `"elevenlabs"` opt-in).

```bash
# requirements-optional.txt additions
edge-tts>=7.2.8
elevenlabs>=2.42.0    # optional: elevenlabs TTS
pydub>=0.25.1         # optional: audio format conversion (requires system ffmpeg)
```

**Confidence:** HIGH for edge-tts (async-native, no-cost, confirmed v7.2.8). HIGH for elevenlabs SDK (confirmed v2.42.0, April 2026). MEDIUM for pydub (ffmpeg system dependency is a runtime concern on fresh installs).

---

### 4. Image Generation

**Decision: `openai` SDK for gpt-image-1 (DALL-E successor), `fal-client` for Flux.**

DALL-E 2 and DALL-E 3 are deprecated as of May 12, 2026. The replacement is `gpt-image-1` via the `openai.images.generate()` endpoint — accessed through the existing `openai` SDK that litellm already pulls as a transitive dependency.

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `openai` | >=2.30.0 | `gpt-image-1` generation | Already a transitive dep via litellm. `AsyncOpenAI().images.generate()` returns base64 PNG. Use model `"gpt-image-1"`. |
| `fal-client` | 0.13.2 | Flux image generation | `fal_client.subscribe_async("fal-ai/flux/schnell", ...)` for fast local-style images. Every method has `_async` suffix for asyncio. Requires `FAL_KEY` env var. |

**Integration point:** New `image_gen/` module. Skill `draw` detects generation requests via traffic cop → skill router. Result is a PNG bytes blob → saved to `media/` temp dir → sent via channel `send_image()` method.

**Provider selection:** Configured via `synapse.json → image_gen.provider` (`"openai"` default, `"fal"` alt). Falls back gracefully if provider key absent.

```bash
# requirements-optional.txt additions
fal-client>=0.13.2    # optional: Flux image generation
# openai is already a transitive dependency of litellm — no explicit add needed
```

**Confidence:** HIGH for openai SDK path (confirmed transitive dep, gpt-image-1 is current model). MEDIUM for fal-client (confirmed v0.13.2, March 2026, but Flux model IDs change frequently — pin to `fal-ai/flux/schnell` for speed or `fal-ai/flux-pro/v1.1` for quality).

---

### 5. Cron with Isolated Agent Contexts

**Finding: Cron infrastructure is already complete. Missing dependency is `croniter`.**

The `cron/` module is fully implemented: `CronService`, `CronStore`, `CronSchedule` (AT/EVERY/CRON kinds), `run_isolated_agent()`, `RunLog`, stagger support. The CRON schedule kind uses `croniter` for expression parsing, but `croniter` is not in any requirements file.

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `croniter` | 6.2.2 | Cron expression parsing in `cron/schedule.py` | Already imported in `schedule.py` — just missing from requirements. Maintained by pallets-eco, Python >=3.9, stable API. |

**What NOT to add:** APScheduler, Celery, or any external job queue. The existing `CronService` async timer loop owns job firing — it's cleaner, asyncio-native, and has zero external process dependencies. APScheduler would be a step backward.

```bash
# requirements.txt addition (NOT optional — cron is a core feature)
croniter>=6.2.2
```

**Confidence:** HIGH — `croniter` is already imported in the codebase, just undeclared.

---

### 6. Interactive Web Dashboard with Real-Time SSE

**Finding: SSE infrastructure already exists via `pipeline_emitter.py`. Missing pieces are a proper SSE endpoint library and a React frontend build.**

**Backend (Python):**

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `sse-starlette` | >=2.0.0 (March 2026) | W3C-compliant SSE endpoint for FastAPI | The existing `PipelineEventEmitter` produces raw SSE strings. `sse-starlette`'s `EventSourceResponse` wraps async generators cleanly. Handles client disconnect, graceful shutdown. FastAPI-native. Python >=3.10. |

`sse-starlette` adds a clean `EventSourceResponse` wrapper around the existing `asyncio.Queue`-based emitter. The integration is: `async def sse_stream(): while True: yield await q.get()` wrapped in `EventSourceResponse`.

**Frontend (React + Vite):**

The existing dashboard is `static/dashboard/index.html` + `synapse.js` — static files served by FastAPI's `StaticFiles`. For v3.0 interactive dashboard, upgrade to a proper React/Vite SPA still served from the same FastAPI mount point.

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| React | 18.x | UI framework | Industry standard, excellent async/SSE patterns with `useEffect` + `EventSource`. |
| Vite | 5.x | Frontend build tool | Near-instant HMR, ESM-first, minimal config. Outputs to `static/dashboard/` for FastAPI serving. |
| Tailwind CSS | 3.x | Styling | Zero-runtime utility CSS, works well with Vite, no design system coupling. |

**Integration:** Vite builds to `workspace/sci_fi_dashboard/static/dashboard/dist/`. FastAPI serves via `app.mount("/dashboard", StaticFiles(directory="static/dashboard/dist", html=True))`. No separate Node.js process in production. SSE consumed via browser `EventSource` API at `/api/pipeline/stream`.

**No WebSocket upgrade needed.** The existing `/ws` WebSocket handles control-plane commands. SSE handles one-directional pipeline events to dashboard — correct tool for the job.

```bash
# requirements.txt additions (Python side)
sse-starlette>=2.0.0

# Frontend: managed via package.json in workspace/sci_fi_dashboard/static/dashboard/
# npm install react react-dom @vitejs/plugin-react vite tailwindcss
```

**Confidence:** HIGH for sse-starlette (confirmed active, Python >=3.10, FastAPI-native). MEDIUM for React/Vite choice (standard pattern, but frontend framework is not verified via codebase — project may already have a preference).

---

### 7. Realtime Voice Streaming / Transcription

**Decision: Two-tier approach — Groq Whisper API for WhatsApp voice notes (already works), faster-whisper local for realtime desktop streaming.**

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `faster-whisper` | 1.2.1 | Local realtime transcription (large-v3 or distil-large-v3) | CTranslate2-backed, 4x faster than openai-whisper, INT8 on CPU for 8GB RAM hosts, no cloud dependency for sensitive conversations. Used by `faster-whisper-live` for asyncio streaming. |
| `sounddevice` | 0.5.5 | Cross-platform mic capture (Windows/Mac/Linux) | PortAudio bindings with numpy arrays, callback-based capture feeds asyncio queues, cleaner API than PyAudio on Windows. |

**OpenAI Realtime API alternative:** `openai>=2.30.0` (already in transitive deps) supports `gpt-4o-transcribe` via WebSocket for streaming transcription. Use this when the user has `OPENAI_API_KEY` and prefers cloud quality over local privacy. Route via `synapse.json → voice.transcription_provider` (`"faster-whisper"` default, `"openai-realtime"` opt-in).

**Streaming pattern:** `sounddevice.InputStream(callback=...)` → 20ms PCM chunks → `asyncio.Queue` → `faster_whisper.WhisperModel.transcribe()` with streaming output → partial transcripts emitted via SSE to dashboard and/or forwarded to chat pipeline.

**CUDA note:** faster-whisper 1.2.1 requires CUDA 12 + cuDNN 9 for GPU. CPU INT8 is the safe default for v3.0 (Synapse targets 8GB RAM hosts with no guaranteed GPU). Set `device="cpu"`, `compute_type="int8"`.

```bash
# requirements-optional.txt additions (voice streaming is opt-in)
faster-whisper>=1.2.1    # optional: local realtime transcription
sounddevice>=0.5.5       # optional: microphone capture (requires portaudio system lib)
```

**What NOT to use:** `openai-whisper` (original) — 2-4x slower, no streaming, larger VRAM. `whisper-live` — adds WebSocket server overhead, unnecessary for single-user embedded use case.

**Confidence:** MEDIUM for faster-whisper (confirmed v1.2.1, CPU path is well-documented, but streaming asyncio integration needs careful implementation). MEDIUM for sounddevice (confirmed v0.5.5, PortAudio system dep on Linux/Mac but included in Windows wheels).

---

## Complete Install Summary

```bash
# requirements.txt (core — add now)
croniter>=6.2.2
sse-starlette>=2.0.0

# requirements-optional.txt (feature-gated)
edge-tts>=7.2.8                    # TTS: free Microsoft voices
elevenlabs>=2.42.0                 # TTS: premium (requires ELEVENLABS_API_KEY)
pydub>=0.25.1                      # TTS: audio format conversion (requires system ffmpeg)
fal-client>=0.13.2                 # Image gen: Flux (requires FAL_KEY)
faster-whisper>=1.2.1              # Voice: local transcription (CPU INT8)
sounddevice>=0.5.5                 # Voice: mic capture (requires system portaudio)

# openai SDK: already a transitive dependency of litellm — no explicit add needed
# React/Vite frontend: managed via package.json (not pip)
```

---

## Alternatives Considered

| Feature | Recommended | Alternative | Why Not |
|---------|-------------|-------------|---------|
| TTS free tier | `edge-tts` | `pyttsx3` | pyttsx3 uses OS TTS (SAPI on Windows) — low quality, no control over voice style |
| TTS premium | `elevenlabs` | `openai/tts-1` | Both valid; ElevenLabs has more voice variety and better streaming; openai TTS simpler if OPENAI_API_KEY already set (acceptable fallback) |
| Image gen | `openai` gpt-image-1 | `replicate` | Replicate adds another API dependency; gpt-image-1 uses existing openai key; Flux via fal is already the open-source alternative |
| Cron scheduler | croniter + existing CronService | APScheduler | CronService is already implemented and asyncio-native; APScheduler adds 3rd-party scheduler with its own lifecycle that fights uvicorn's event loop |
| SSE | `sse-starlette` | raw StreamingResponse | `sse-starlette` handles reconnect, ping, client disconnect out-of-box; raw `StreamingResponse` requires manual keepalive logic |
| Voice streaming | `faster-whisper` local | `groq` Whisper API | Groq already handles WhatsApp OGG files (batch). Realtime streaming needs <100ms latency — Groq API round-trip adds network overhead; local faster-whisper wins for desktop use |
| Frontend | React + Vite | HTMX + Alpine.js | HTMX works for simpler dashboards but SSE + real-time chart updates + WebSocket control channel is complex without a real component model |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `anthropic` SDK directly | litellm already wraps Anthropic; adding the raw SDK creates two auth paths and import conflicts | `litellm` with `anthropic/` prefix |
| `openai` SDK directly for LLM calls | Same — litellm is the abstraction. Direct openai calls bypass traffic cop, fallback routing, and inference loop | `litellm` with `openai/` prefix |
| `celery` or `redis` for cron | Zero-Docker constraint; CronService is already async-native and sufficient for single-user jobs | Existing `CronService` + `croniter` |
| `pyaudio` | Has build failures on some Windows configurations (needs C compiler); `sounddevice` is cleaner | `sounddevice` |
| `openai-whisper` (original) | No streaming, 2-4x slower, larger RAM/VRAM footprint | `faster-whisper` |
| DALL-E 2 / DALL-E 3 | OpenAI deprecating both on May 12, 2026 | `gpt-image-1` via openai SDK |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `sse-starlette>=2.0.0` | `fastapi>=0.104.0`, Python >=3.10 | Requires Python 3.10+; project is on 3.11 — fine |
| `faster-whisper>=1.2.1` | `ctranslate2>=4.4.0` (auto-installed); CUDA 12 + cuDNN 9 for GPU | CPU INT8 path has no CUDA requirement |
| `sounddevice>=0.5.5` | System PortAudio (Windows wheels bundle it; Linux: `apt install portaudio19-dev`) | Windows is primary dev — bundled. Linux users need apt/brew |
| `pydub>=0.25.1` | System `ffmpeg` binary | Not pip-installable; document in INSTALL.md |
| `croniter>=6.2.2` | Python >=3.9 | No conflicts with current stack |
| `fal-client>=0.13.2` | Python >=3.8, `httpx` (already in core deps) | Async via `subscribe_async()` — no extra async deps |
| `elevenlabs>=2.42.0` | Python >=3.8, `httpx` (already in core deps) | SDK v2 (breaking change from v1); install fresh |
| `edge-tts>=7.2.8` | Python >=3.8, `aiohttp` (new dep — check if already present) | Verify `aiohttp` not already in requirements before adding |

---

## synapse.json Config Schema Additions

New top-level sections to add to `synapse.json` (all optional, fall back gracefully if absent):

```json
{
  "providers": {
    "openai":       { "api_key": "sk-..." },
    "anthropic":    { "api_key": "sk-ant-..." },
    "deepseek":     { "api_key": "sk-..." },
    "mistral":      { "api_key": "..." },
    "together":     { "api_key": "..." },
    "elevenlabs":   { "api_key": "..." },
    "fal":          { "api_key": "..." }
  },
  "tts": {
    "provider": "edge-tts",
    "voice": "en-US-AriaNeural",
    "elevenlabs_voice_id": "21m00Tcm4TlvDq8ikWAM"
  },
  "image_gen": {
    "provider": "openai",
    "model": "gpt-image-1",
    "size": "1024x1024"
  },
  "voice": {
    "transcription_provider": "faster-whisper",
    "model": "distil-large-v3",
    "device": "cpu",
    "compute_type": "int8"
  }
}
```

---

## Sources

- [litellm Providers page](https://docs.litellm.ai/docs/providers) — confirmed prefixes for all 5 providers (HIGH confidence)
- [litellm DeepSeek page](https://docs.litellm.ai/docs/providers/deepseek) — `deepseek/` prefix, thinking mode (HIGH)
- [litellm Together AI page](https://docs.litellm.ai/docs/providers/togetherai) — `together_ai/` prefix, `TOGETHERAI_API_KEY` (HIGH)
- [litellm Mistral page](https://docs.litellm.ai/docs/providers/mistral) — `mistral/` prefix, `MISTRAL_API_KEY` (HIGH)
- [elevenlabs PyPI](https://pypi.org/project/elevenlabs/) — v2.42.0 confirmed April 7, 2026 (HIGH)
- [edge-tts PyPI](https://pypi.org/project/edge-tts/) — v7.2.8 confirmed March 22, 2026 (HIGH)
- [fal-client PyPI / socket.dev](https://socket.dev/pypi/package/fal-client) — v0.13.2, March 24, 2026, async `subscribe_async` confirmed (HIGH)
- [fal.ai Python docs](https://docs.fal.ai/clients/python/) — async suffix pattern confirmed (HIGH)
- [openai PyPI](https://pypi.org/project/openai/) — v2.30.0, March 25, 2026 (HIGH); DALL-E 3 deprecation May 2026 confirmed (HIGH)
- [faster-whisper GitHub releases](https://github.com/SYSTRAN/faster-whisper/releases) — v1.2.1 confirmed (HIGH)
- [sounddevice PyPI](https://pypi.org/project/sounddevice/) — v0.5.5 (HIGH)
- [sse-starlette GitHub](https://github.com/sysid/sse-starlette) — Python >=3.10, March 2026 release, FastAPI-native (HIGH)
- [croniter PyPI](https://pypi.org/project/croniter/) — v6.2.2, March 15, 2026 (HIGH); already imported in `cron/schedule.py`
- [OpenAI Realtime API docs](https://developers.openai.com/api/docs/guides/realtime) — gpt-4o-transcribe WebSocket streaming confirmed (MEDIUM)

---

*Stack research for: Synapse-OSS v3.0 — OpenClaw Feature Harvest*
*Researched: 2026-04-08*
