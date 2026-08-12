# Pitfalls Research: Synapse-OSS v3.0 Feature Additions

**Domain:** Adding LLM providers, skills library, TTS, image generation, cron agents, web dashboard, and streaming voice to an existing Python asyncio AI system.
**Researched:** 2026-04-08
**Confidence:** HIGH (multiple verified sources per finding; litellm and asyncio claims cross-checked against official docs and GitHub issues)

---

## Critical Pitfalls

### Pitfall 1: litellm Budget/Rate-Limit Exceptions Do Not Trigger Fallbacks

**What goes wrong:**
When a key-level limit (TPM, RPM, or monthly budget) is hit on the primary model, the router raises `BudgetExceededError` or `RateLimitError`. The fallback list is configured, but the fallback is silently skipped and the exception propagates to the caller as a hard 429. The user sees a failure, not a seamless provider switch.

**Why it happens:**
litellm Router's fallback logic was designed around model-level errors, not key-level limit exceptions. The internal check uses a different exception classification path for budget exhaustion. This is a documented open bug (GitHub issue #10052) and is not fixed in the standard OSS version — only in the Enterprise proxy.

**How to avoid:**
Wrap `SynapseLLMRouter._do_call()` in a try/except that explicitly catches `BudgetExceededError` and `litellm.RateLimitError`, then manually triggers the next model in the fallback list. Do not rely on the Router's automatic fallback for budget exhaustion.

```python
# In llm_router.py: manual fallback on budget/rate errors
except (litellm.BudgetExceededError, litellm.RateLimitError):
    if fallback_models:
        return await self._do_call(fallback_models[0], messages, fallback_models[1:])
    raise
```

**Warning signs:**
- Users complain "no response" at the same time every month (budget resets)
- Logs show `BudgetExceededError` without any subsequent "fallback to X" log line
- `litellm.Router` cooldown state does NOT activate for budget errors (only rate-limit 429s from the provider activate cooldown)

**Phase to address:** LLM Provider Expansion (Phase 1 of v3.0 roadmap)

---

### Pitfall 2: litellm Model Name Conflicts Across Providers

**What goes wrong:**
Adding providers like Together AI or Mistral introduces model aliases that collide. Example: `mistral/mistral-large-latest` and Together's own hosted `mistral-large` resolve to the same model name internally. When `model_mappings` in `synapse.json` has `"analysis": "mistral/mistral-large-latest"` and also a Together entry for the same model, the Router picks an unexpected deployment, silently bypassing auth keys.

**Why it happens:**
litellm uses a provider-prefixed model string (`provider/model-name`). When two entries share the same resolved canonical name, the Router's routing decision is non-deterministic if both have equal weight. Unlike named deployments in a proxy config, in-code Router configs rely entirely on the prefix for disambiguation.

**How to avoid:**
- Every `model_list` entry in the Router must have a unique `model_name` field (the internal alias).
- Never use the raw `provider/model` string as both the alias and the model in different entries.
- Document the canonical alias map in `synapse.json` comments: `"analysis_mistral_together": "together_ai/mistral-7b-instruct"`.

**Warning signs:**
- Auth errors on a provider you didn't intend to call
- LLM responses appearing in unexpected quality tier (cheap model being used for analysis role)
- `litellm.Router` logs show `picked deployment: X` but you expected Y

**Phase to address:** LLM Provider Expansion (Phase 1 of v3.0 roadmap)

---

### Pitfall 3: GitHub Copilot Shim Breaks With New Provider Entries

**What goes wrong:**
`llm_router.py` has a shim that rewrites `github_copilot/` prefixes to `openai/` and injects `api_base` + `extra_headers`. When new provider entries are added to the Router's `model_list`, a bug in the rewrite condition can cause legitimate `openai/` entries to also get the Copilot `api_base` injected, routing them to GitHub Copilot's endpoint instead of the real OpenAI API.

**Why it happens:**
The shim checks `if "github_copilot" in model_string` but when adding `openai/gpt-4o` it doesn't match. However, if the condition is accidentally broadened (e.g., checking for `openai/` prefix to set base URL), all OpenAI calls are poisoned.

**How to avoid:**
Keep the shim condition exact: `if model_string.startswith("github_copilot/")`. Add a unit test that passes an `openai/gpt-4o` call and asserts the endpoint is `api.openai.com`, not the Copilot endpoint.

**Warning signs:**
- `401 Unauthorized` from OpenAI when Copilot token is expired
- Response headers show `x-ms-` Azure headers on a call intended for native OpenAI
- Cost tracking shows GitHub Copilot usage for non-Copilot model calls

**Phase to address:** LLM Provider Expansion (Phase 1 of v3.0 roadmap)

---

### Pitfall 4: TTS Audio Format Mismatch Crashes WhatsApp Voice Delivery

**What goes wrong:**
ElevenLabs returns `mp3_44100_128` by default. WhatsApp via Baileys requires OGG Opus (`audio/ogg; codecs=opus`) with `ptt: true` for the message to render as a voice note (earphone icon). Sending raw MP3 through Baileys results in the audio appearing as a downloadable file attachment, not a playable voice message.

**Why it happens:**
WhatsApp enforces OGG+Opus as the only codec that renders natively inline. ElevenLabs and edge-tts both produce formats that require conversion. Developers assume "audio file" = "voice message" — it does not.

**How to avoid:**
- Request `output_format="opus_48000_32"` from ElevenLabs (produces native Opus in a container) OR
- Convert with `ffmpeg` via `subprocess`: `ffmpeg -i input.mp3 -c:a libopus -b:a 32k output.ogg`
- Pass to Baileys with `{ audio: fs.readFileSync(path), mimetype: "audio/ogg; codecs=opus", ptt: true }`
- On Windows, ship ffmpeg binary or use `pydub` with ffmpeg backend

**Warning signs:**
- User receives a document/attachment icon in WhatsApp instead of the voice note play button
- Baileys `sendMessage` succeeds (200 OK) but audio is not playable inline
- iOS WhatsApp plays the audio; Android shows download button (codec mismatch)

**Phase to address:** TTS / Voice Output (Phase 3 of v3.0 roadmap)

---

### Pitfall 5: TTS Latency Kills Perceived Responsiveness

**What goes wrong:**
TTS generation is added as a synchronous step after the LLM response is ready: `llm_response → tts_generate(full_text) → send_audio`. For long responses (200+ words), ElevenLabs synthesis adds 2–8 seconds before the user hears anything. The user thinks Synapse is slow or broken.

**Why it happens:**
Developers treat TTS as a post-processing step applied to the complete text. In a chat pipeline where the LLM already streams tokens, waiting for the full response to arrive before synthesizing defeats the benefit.

**How to avoid:**
- Sentence-chunk the LLM output: synthesize and send each sentence as a separate audio message as it arrives
- Use `eleven_flash_v2_5` model (lowest latency, ~300ms per chunk) not `eleven_multilingual_v2`
- edge-tts is free and offline-adjacent with 200–400ms latency — use it as a fallback when ElevenLabs quota is exhausted
- Gate TTS behind a per-sender preference flag; do not make it the default for all messages

**Warning signs:**
- Gateway logs show `tts_generate` taking > 3s consistently
- Users asking "are you there?" after sending a voice-reply-eligible message
- WhatsApp "typing" indicator visible for unusually long time before audio arrives

**Phase to address:** TTS / Voice Output (Phase 3 of v3.0 roadmap)

---

### Pitfall 6: Image Generation Timeouts Block the Chat Pipeline

**What goes wrong:**
`asyncio.create_task(generate_image(...))` is awaited inline in `persona_chat()`. DALL-E 3 can take 10–30 seconds during peak hours (documented 504 Gateway Timeout spikes between 15:00–17:00 UTC). When the await blocks for 30 seconds, the FloodGate batch window fills, the TaskQueue backs up, and other users' messages queue behind the image generation.

**Why it happens:**
Image generation is I/O-bound but has 10–100x the latency of a normal LLM call. Treating it as a regular pipeline step rather than a detached background operation serializes the entire chat pipeline around it.

**How to avoid:**
- Detach image generation as a `BackgroundTask` (same pattern as Auto-Continue):
  ```python
  background_tasks.add_task(generate_and_send_image, prompt, channel_id, peer_id)
  return text_ack_response  # "Generating, give me a moment..."
  ```
- Set `asyncio.wait_for` timeout at 45 seconds with a user-facing fallback message
- Use Flux via a fast inference API (Replicate, Together) as a backup to DALL-E when timeouts occur

**Warning signs:**
- `MessageWorker` queue depth climbing during image generation requests
- `FloodGate` batch completion times spiking above 30s
- Cascade: WhatsApp users getting "message not delivered" because the connection times out before the image is ready

**Phase to address:** Image Generation (Phase 4 of v3.0 roadmap)

---

### Pitfall 7: NSFW Filter False Positives Break Vault Hemisphere Isolation

**What goes wrong:**
The Vault (spicy) hemisphere handles private/sensitive content deliberately routed away from cloud models. If image generation is wired into the normal chat pipeline without hemisphere-awareness, a "draw me something romantic" request in a Vault session gets routed to DALL-E (a cloud API), leaking user context to OpenAI's moderation pipeline. Conversely, DALL-E's content filter may reject the request entirely, surfacing an error to the user.

**Why it happens:**
Image generation APIs are external cloud calls by definition. Developers add image generation as a skill and forget that skills can fire in Vault context.

**How to avoid:**
- Skills that call external cloud APIs must check `hemisphere_tag == "spicy"` at the top of their dispatch logic and return a soft decline message if so
- Add a skill metadata field: `cloud_safe: false` — the skill router must refuse to dispatch cloud-API skills in Vault context
- For Vault sessions, offer local Stable Diffusion via Ollama or ComfyUI only

**Warning signs:**
- Image generation errors appearing in conversation logs that should be private
- OpenAI moderation rejection (`400 content_policy_violation`) appearing in spicy session logs
- Any `requests` or `httpx` outbound call from within a Vault-session code path

**Phase to address:** Image Generation (Phase 4 of v3.0 roadmap); also touches Skills Architecture

---

### Pitfall 8: Cron Agents Share the Main Event Loop and Leak State

**What goes wrong:**
Cron jobs are implemented as `asyncio.create_task()` calls on the main uvicorn event loop. The job function imports `MemoryEngine`, `DualCognitionEngine`, and `PersonaManager` from the global singletons in `api_gateway.py`. Two things break: (1) a long-running cron job can starve the chat pipeline of event loop time, and (2) a cron job that writes to memory or modifies SBS state can corrupt the live session state if it runs concurrently with a message handler.

**Why it happens:**
Python asyncio is cooperative: all coroutines share one thread. A cron job that does heavy CPU work (embedding, reranking) or holds locks for extended periods blocks all other coroutines. Additionally, singletons are not designed for concurrent write access from multiple "users" (the chat pipeline and the cron agent).

**How to avoid:**
- Run cron agents in a `ProcessPoolExecutor` or a dedicated thread pool, NOT on the main event loop
- Each cron agent must get a fresh, isolated copy of `MemoryEngine` and `DualCognitionEngine` — never pass the global singleton
- Use `asyncio.run_coroutine_threadsafe()` only to communicate results back; never write to shared state directly
- Use `APScheduler` with `AsyncIOScheduler` for scheduling, but dispatch heavy work to executor

**Warning signs:**
- Chat response times spiking at predictable intervals (cron firing time)
- `asyncio` slow-coroutine warnings in logs (tasks taking > 100ms without yielding)
- SBS profile updates appearing at unexpected times unrelated to chat activity

**Phase to address:** Cron with Isolated Agents (Phase 5 of v3.0 roadmap)

---

### Pitfall 9: Zombie Cron Tasks on Timeout — asyncio.wait_for Thread Leak

**What goes wrong:**
If a cron agent job uses `asyncio.wait_for(job(), timeout=300)` and the job is running CPU-heavy work in a `run_in_executor` thread, timing out the `wait_for` cancels the `Future` but does NOT stop the underlying thread. The thread continues running, accumulating as a zombie in the shared `ThreadPoolExecutor`. Over days of operation, zombie threads exhaust the executor pool, causing new cron jobs to silently queue forever.

**Why it happens:**
Python cannot kill threads. `asyncio.wait_for` cancels the coroutine wrapper but the C-extension or blocking I/O inside the thread continues. This is a documented CPython limitation (Python tracker issue #41699, #85865).

**How to avoid:**
- Use a `ProcessPoolExecutor` instead of `ThreadPoolExecutor` for cron agents — processes can be killed
- Implement cooperative cancellation: check a `threading.Event` inside the job thread periodically
- Log thread pool size on each cron fire; alert if it grows beyond `max_workers`

```python
executor = ProcessPoolExecutor(max_workers=2)
loop = asyncio.get_event_loop()
try:
    await asyncio.wait_for(
        loop.run_in_executor(executor, blocking_job, args),
        timeout=300
    )
except asyncio.TimeoutError:
    executor.shutdown(wait=False, cancel_futures=True)  # Python 3.9+
```

**Warning signs:**
- `concurrent.futures.thread._worker` count in `threading.enumerate()` growing over time
- Cron job scheduled to run at interval but execution actually delayed by minutes
- Memory growth correlated with cron fire frequency rather than message volume

**Phase to address:** Cron with Isolated Agents (Phase 5 of v3.0 roadmap)

---

### Pitfall 10: Web Dashboard WebSocket Backpressure Crashes Slow Clients

**What goes wrong:**
The dashboard subscribes to real-time events (message logs, memory stats, SBS profile updates). A fast-typing user generates bursts of events. If the dashboard WebSocket consumer (browser) is rendering a complex chart and falls behind, the server-side asyncio `send()` buffer grows without bound. Eventually the Python process memory bloats, or the WebSocket write raises `ConnectionResetError` mid-burst, taking the entire gateway down.

**Why it happens:**
`websocket.send_json()` in FastAPI/Starlette buffers outgoing data in the websocket write buffer. There is no built-in backpressure — if the client is slow, the buffer grows. In an `asyncio` single-process server, a buffer overflow on one WebSocket connection can affect all connections.

**How to avoid:**
- Use a per-client `asyncio.Queue(maxsize=50)` as a buffer; drop or summarize stale messages when the queue is full
- Distinguish event classes: real-time chat events (never drop) vs. stats/telemetry (drop freely if queue full)
- Add a heartbeat coroutine that monitors queue depth and disconnects clients whose queue has been at maxsize for > 10s

```python
async def broadcast_to_client(client_queue: asyncio.Queue, event: dict):
    try:
        client_queue.put_nowait(event)
    except asyncio.QueueFull:
        # Drop telemetry; log the drop
        pass
```

**Warning signs:**
- Server memory growing proportional to number of connected dashboard tabs
- Dashboard showing events lagged 30–60 seconds behind real activity
- `ConnectionResetError` in FastAPI logs coinciding with high-traffic periods

**Phase to address:** Web Control Panel (Phase 6 of v3.0 roadmap)

---

### Pitfall 11: Dashboard Auth Leaks Gateway Token Into Browser

**What goes wrong:**
The existing WebSocket gateway authenticates with `SYNAPSE_GATEWAY_TOKEN`. When adding the web dashboard, the token is embedded in the HTML source of the dashboard page (e.g., as a JavaScript constant set by the Jinja template) so the browser WebSocket can authenticate. Any person who opens the browser dev tools sees the full token.

**Why it happens:**
The fastest way to auth a browser WebSocket is to pass the token in the URL or embed it in the page. Developers copy the existing API auth pattern without considering that browsers are not trusted environments.

**How to avoid:**
- Implement short-lived session tokens: user logs into the dashboard with a separate password, server issues a `dashboard_session_token` with a 24h TTL stored in an httpOnly cookie
- The `SYNAPSE_GATEWAY_TOKEN` never leaves the server — only the dashboard session token is sent to the browser
- For a local-only dashboard (127.0.0.1), a simpler approach is IP-binding: refuse connections not from loopback, document that the dashboard must not be exposed publicly

**Warning signs:**
- `SYNAPSE_GATEWAY_TOKEN` visible in browser source code or JavaScript variables
- Dashboard reachable from non-localhost IP (Synapse is designed for local-only use)
- Token visible in WebSocket URL in browser network tab (`ws://host/ws?token=ghu_...`)

**Phase to address:** Web Control Panel (Phase 6 of v3.0 roadmap)

---

### Pitfall 12: VAD False Positives Cause Double Responses in Streaming Voice

**What goes wrong:**
Voice Activity Detection (VAD) is tuned too aggressively. A pause in speech (thinking, breathing, background noise) triggers end-of-utterance, Whisper transcribes the partial speech, the LLM generates a response, and TTS starts playing. The user then continues their sentence, triggering a second response to the incomplete utterance. The user hears two responses to one question.

**Why it happens:**
Default WebRTC VAD aggressiveness modes 0–3 are calibrated for phone noise conditions, not home/office environments with background noise. Mode 3 (most aggressive) cuts utterances at < 300ms of silence, which is shorter than a normal thinking pause. Developers test with clean microphone input in a quiet room; production has background noise, fan hum, and music.

**How to avoid:**
- Start at VAD aggressiveness mode 1 (less aggressive), expose it as a user-configurable setting
- Add a minimum silence duration of 700–1000ms before declaring end-of-utterance (well beyond the 300ms default)
- Implement a barge-in cancel: if new speech starts within 2s of the previous response beginning, cancel the current TTS playback and restart STT

**Warning signs:**
- Test transcripts show sentences split into two separate entries
- LLM is generating responses to single words or partial phrases ("uh", "so")
- Users reporting "it answers before I finish talking"

**Phase to address:** Realtime Voice Streaming (Phase 7 of v3.0 roadmap)

---

### Pitfall 13: synapse_config.py Modification Triggers Circular Import Cascade

**What goes wrong:**
`synapse_config.py` is imported by 50+ modules. Adding new v3.0 configuration keys (e.g., `tts_provider`, `image_gen_provider`, `cron_jobs`) to `synapse_config.py` triggers a reimport chain on startup. If any new v3.0 module also imports `synapse_config.py` and `synapse_config.py` imports that new module for type hints or validation, Python raises `ImportError: cannot import name X` (circular import).

**Why it happens:**
High-fanout configuration modules are a circular import magnet. Adding a line like `from workspace.sci_fi_dashboard.tts_engine import TTSEngine` to `synapse_config.py` for type validation creates a cycle because `tts_engine.py` itself imports `synapse_config`.

**How to avoid:**
- `synapse_config.py` must import nothing from the Synapse codebase — only Python stdlib and third-party libraries
- New v3.0 config sections must be added as plain `dict` or `dataclass` fields, never typed to internal classes
- Use `TYPE_CHECKING` guards for any internal type hints: `if TYPE_CHECKING: from .tts_engine import TTSEngine`
- Run `pycycle --here` in CI after any change to `synapse_config.py` to detect new cycles before merge

**Warning signs:**
- `ImportError` on startup after adding a new module that imports `synapse_config`
- Test suite passing locally but failing on fresh virtualenv (import order differs)
- `python -c "import workspace.synapse_config"` hanging or raising circular import error

**Phase to address:** All v3.0 phases (every phase that adds config keys); enforce from Phase 1

---

### Pitfall 14: Skills Library Skill Name Collision Causes Silent Routing Failure

**What goes wrong:**
A new bundled skill `weather` is added to the skills library. An existing user already has a custom skill named `weather` in their `~/.synapse/skills/` directory. The skill router discovers both and uses whichever was loaded last (discovery order is filesystem-dependent). The user's custom weather skill is silently shadowed, or vice versa.

**Why it happens:**
Skill discovery iterates directories and registers by `skill_name` from `SKILL.md`. If the name field is not guaranteed unique per installation, collisions are silent. There is no conflict detection in the existing v2.0 skill architecture.

**How to avoid:**
- Bundled skills use a reserved namespace prefix: `synapse.weather`, `synapse.translate`, etc.
- User skills use unprefixed names; bundled skills are never loaded if a user skill with the same base name exists (user wins, always)
- On startup, log a warning if a bundled skill name is shadowed by a user skill
- `SKILL.md` must include a `namespace` field: `built-in` or `user`

**Warning signs:**
- Skill routing behavior changes after updating Synapse (new bundled skill added that shadows user skill)
- Two `SKILL.md` files with identical `name:` field in different directories, no error raised
- Feature requests from users saying "my weather skill stopped working after update"

**Phase to address:** Skills Library (Phase 2 of v3.0 roadmap)

---

### Pitfall 15: Skills with Heavy Dependencies Slow Down Startup for All Users

**What goes wrong:**
A bundled skill for image description requires `Pillow`, `transformers`, and a 200MB CLIP model. These are imported at startup when the skill is discovered, even if the user never uses image description. Startup time grows from 3s to 30s. On 8GB machines with Ollama already loaded, the model download triggers OOM.

**Why it happens:**
The existing v2.0 skill architecture uses eager loading: on startup, all skill modules are imported to build the routing table. Heavy-dependency skills poison the startup path for all users.

**How to avoid:**
- Skills must declare dependencies in `SKILL.md` as `requires: [pillow, transformers]`, NOT import them at module load time
- Use lazy import inside the skill's `execute()` function: `import Pillow` inside the function body, not at module top
- Skills with model downloads must declare `model_size_mb: 200` in `SKILL.md`; onboarding wizard asks before downloading
- The skill router's discovery phase must import only the `SKILL.md` manifest, never the Python module

**Warning signs:**
- Startup time increases linearly with number of bundled skills
- `ImportError` for optional skill dependencies breaks ALL skills (due to eager import chain)
- Memory usage at idle grows with each new bundled skill added

**Phase to address:** Skills Library (Phase 2 of v3.0 roadmap)

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Inline TTS after LLM response (blocking) | Simple implementation | 2–8s latency per voice reply; pipeline serialization | Never in production |
| Global singleton singletons for cron agents | No refactoring needed | State corruption with concurrent chat + cron | Never |
| Embedding `SYNAPSE_GATEWAY_TOKEN` in dashboard HTML | Fastest auth implementation | Token exposure in browser dev tools | Never |
| Eager skill module import at startup | Simple routing table build | Startup time grows O(skills); OOM risk | Never for skills with heavy deps |
| Triggering image generation inline in chat handler | Simple code flow | Blocks entire MessageWorker for 10–30s | Never; always background |
| edge-tts as primary TTS (not ElevenLabs) | Zero API key needed | Undocumented endpoint, can be rate-limited by Microsoft silently | Acceptable as fallback |
| `asyncio.wait_for` on ThreadPoolExecutor work | Simple timeout pattern | Zombie threads accumulate | Never for long-running jobs; use ProcessPoolExecutor |
| Single `synapse_config.py` for all new v3.0 config | No new files needed | Circular import risk grows with each addition | Acceptable if no internal type imports |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| ElevenLabs | Pass full LLM response as single TTS request | Sentence-chunk; stream synthesis in parallel with LLM output |
| ElevenLabs | Ignore `output_format` parameter | Request `opus_48000_32` directly; skip ffmpeg conversion |
| Baileys audio send | Send MP3 file | Convert to OGG+Opus; set `ptt: true` and `mimetype: "audio/ogg; codecs=opus"` |
| DALL-E / Flux | Await image generation in chat handler | Background task with ack message; 45s timeout |
| DALL-E | Not checking `hemisphere_tag` before API call | Skill dispatch layer must block cloud calls in Vault context |
| litellm new providers | Add provider entry, assume fallback works for budget errors | Add explicit try/except for `BudgetExceededError` in `_do_call` |
| litellm Together/Mistral | Use same model alias for two providers | Unique `model_name` per Router entry; never duplicate aliases |
| APScheduler + asyncio | Use `BlockingScheduler` in asyncio app | Use `AsyncIOScheduler` only; dispatch CPU work to executor |
| WebRTC VAD | Use default aggressiveness (3) | Start at mode 1; add 700ms silence buffer before end-of-utterance |
| FastAPI WebSocket | Broadcast to all clients from one coroutine | Per-client `asyncio.Queue` with bounded maxsize |
| Web dashboard | Serve `SYNAPSE_GATEWAY_TOKEN` to browser | Issue short-lived dashboard session token; bind to loopback only |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Synchronous TTS in chat path | Response latency 5–10s for voice replies | Background task + sentence chunking | Immediately at any usage |
| Blocking image gen in MessageWorker | Worker queue depth climbs; other users queued | Background task; worker never awaits image | First concurrent image request |
| Cron agent on main event loop | Chat latency spikes at cron intervals | ProcessPoolExecutor for CPU-heavy cron work | When cron job > 100ms |
| Zombie threads from wait_for + run_in_executor | Thread count grows; jobs silently queue | ProcessPoolExecutor; cooperative cancellation check | After ~100 timeout events |
| WebSocket broadcast loop blocking | All WebSocket sends serialized; one slow client affects all | Per-client queue; non-blocking put_nowait | First slow browser client |
| Eager skill imports at startup | Startup time 30s+; OOM risk | Lazy imports inside execute(); SKILL.md manifest-only discovery | At ~5 heavy-dependency skills |
| LanceDB index rebuild during cron | Memory spike during index rebuild overlaps with chat | Rebuild in Gentle Worker Loop (CPU < 20%) | Simultaneous cron + high traffic |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Cloud API call from within Vault session | Private/spicy content leaks to API provider | Skill dispatch checks `hemisphere_tag`; `cloud_safe: false` metadata blocks cloud skills in spicy context |
| Dashboard serving `SYNAPSE_GATEWAY_TOKEN` to browser | Token usable by any script in browser context; exposure in DevTools | httpOnly cookie for dashboard auth; loopback-only binding |
| Image generation prompt logged verbatim in safe context | User's private image request visible in safe-mode logs | Log prompts only in hemisphere-appropriate log channel; spicy prompts to separate log file |
| Bundled skill imports at module load running network requests | External service called at startup regardless of user preference | All network calls must be inside `execute()`; never in module scope or `__init__` |
| ffmpeg binary path from user-controlled config | Path traversal / command injection via crafted config value | Validate ffmpeg path against allowlist; use `shlex.quote`; prefer `subprocess` list form |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No acknowledgment before image generation starts | User resends the request thinking it failed | Send text ack immediately: "Generating, one moment..." before background task starts |
| Voice reply for every message including one-word answers | Constant audio notifications; annoying for short confirmations | Gate TTS on response length > 50 chars AND user opt-in preference |
| VAD cutting mid-sentence | User must repeat half their sentence; frustrating voice UX | Conservative VAD mode + 700ms silence threshold |
| Dashboard showing all-time logs on load | Page freezes loading 50k log entries | Paginate; show last 100 events with "load more" |
| Cron agent output appearing in chat without context | User confused by unsolicited messages | Cron output must include a preamble: "Good morning — here is your daily summary:" |
| Image sent without caption | User doesn't know what the image is (no ALT in WhatsApp) | Always send a text caption with the image describing what was generated |

---

## "Looks Done But Isn't" Checklist

- [ ] **TTS integration:** Often missing OGG+Opus conversion — verify WhatsApp voice note renders with earphone icon, not attachment icon
- [ ] **TTS integration:** Often missing per-sender opt-in flag — verify TTS can be disabled per-user without code change
- [ ] **Image generation:** Often missing hemisphere check — verify a request from a Vault session does NOT call DALL-E
- [ ] **Image generation:** Often missing background task detachment — verify MessageWorker processes other messages during image generation
- [ ] **Provider expansion:** Often missing explicit budget exception catch — verify a budget-exhausted provider falls back to next provider
- [ ] **Provider expansion:** Often missing Copilot shim regression test — verify OpenAI native calls don't route to Copilot endpoint
- [ ] **Skills library:** Often missing namespace prefix for bundled skills — verify user skill named `weather` is not shadowed by bundled `weather`
- [ ] **Skills library:** Often missing lazy import gate — verify `import synapse` with all skills registered takes < 5s on clean virtualenv
- [ ] **Cron agents:** Often missing executor isolation — verify cron job memory is not readable from chat pipeline session
- [ ] **Cron agents:** Often missing zombie thread detection — verify thread count is stable after 10 timed-out cron executions
- [ ] **Web dashboard:** Often missing token isolation — verify browser DevTools cannot reveal `SYNAPSE_GATEWAY_TOKEN`
- [ ] **Web dashboard:** Often missing backpressure on per-client queue — verify slow browser tab does not cause memory growth on server
- [ ] **Streaming voice:** Often missing barge-in cancel — verify new utterance within 2s of TTS playback start cancels the current playback
- [ ] **synapse_config.py changes:** Often missing circular import check — verify `python -c "import workspace.synapse_config"` succeeds after every new config key added

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Budget fallback silent failure | LOW | Add explicit `BudgetExceededError` catch in `_do_call`; deploy; no data migration needed |
| Model alias collision | LOW | Rename conflicting entry in `synapse.json`; restart gateway |
| Copilot shim regression | LOW | Revert shim condition to `startswith("github_copilot/")`; add regression test |
| TTS format mismatch | LOW | Add ffmpeg conversion step; no message history affected |
| TTS blocking pipeline | MEDIUM | Refactor to background task; requires changing `persona_chat()` return path |
| Image gen blocking MessageWorker | MEDIUM | Refactor to background task; existing queued messages may timeout during deploy |
| NSFW filter breaking Vault isolation | HIGH | Add `cloud_safe` metadata to all skills; audit all skills for external API calls; re-test hemisphere isolation |
| Zombie thread accumulation | MEDIUM | Switch `ThreadPoolExecutor` → `ProcessPoolExecutor` for cron; rolling restart clears existing zombies |
| Dashboard token leak | HIGH | Rotate `SYNAPSE_GATEWAY_TOKEN`; implement session token auth; consider forcing re-auth for all existing dashboard sessions |
| Circular import from synapse_config.py change | MEDIUM | Remove internal type import; use `TYPE_CHECKING` guard; restart required |
| Skill namespace collision post-update | LOW | Rename bundled skill with `synapse.` prefix; issue migration note in changelog |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Budget fallback silent failure | Phase 1: LLM Provider Expansion | Unit test: mock `BudgetExceededError` on provider A; assert response comes from provider B |
| Model name alias collision | Phase 1: LLM Provider Expansion | Integration test: two providers for same model; assert router picks correct one |
| Copilot shim regression | Phase 1: LLM Provider Expansion | Unit test: `openai/gpt-4o` call does not get Copilot `api_base` |
| Skill name collision / shadowing | Phase 2: Skills Library | Test: install bundled `weather` skill; add user `weather` skill; assert user skill wins |
| Heavy skill dependencies slow startup | Phase 2: Skills Library | Benchmark: `time python -c "import workspace.synapse_config"` must be < 5s with all bundled skills |
| TTS audio format mismatch | Phase 3: TTS / Voice Output | End-to-end test: synthesize text; send via Baileys; verify WhatsApp renders voice note icon |
| TTS blocking pipeline | Phase 3: TTS / Voice Output | Load test: send voice-reply request + 5 normal messages concurrently; assert normal messages complete in < 2s |
| Image generation blocking MessageWorker | Phase 4: Image Generation | Load test: concurrent image + chat request; chat response arrives before image |
| NSFW / Vault hemisphere leak | Phase 4: Image Generation | Security test: send image request in Vault session; assert no outbound HTTP to DALL-E / Flux |
| Cron agent shared event loop / state | Phase 5: Cron Agents | Stress test: run cron job with 5s CPU spin; measure chat response time during run |
| Zombie threads from cron timeout | Phase 5: Cron Agents | Test: timeout 20 cron jobs; assert `threading.enumerate()` count does not grow |
| Dashboard WebSocket backpressure | Phase 6: Web Control Panel | Load test: flood dashboard with 1000 events/s; assert process memory stays flat |
| Dashboard token leak | Phase 6: Web Control Panel | Security test: fetch dashboard HTML; assert `SYNAPSE_GATEWAY_TOKEN` string not present in response |
| VAD double response / false positive | Phase 7: Voice Streaming | User test: 500ms thinking pause in speech; assert single response generated |
| synapse_config circular import | All phases | CI gate: `pycycle --here` passes after every PR that touches `synapse_config.py` |

---

## Sources

- litellm fallback silent failure on budget errors: https://github.com/BerriAI/litellm/issues/10052
- litellm Router routing docs: https://docs.litellm.ai/docs/routing
- litellm reliability / fallbacks: https://docs.litellm.ai/docs/completion/reliable_completions
- ElevenLabs TTS latency pipeline: https://elevenlabs.io/blog/enhancing-conversational-ai-latency-with-efficient-tts-pipelines
- ElevenLabs models (flash_v2_5 for low latency): https://elevenlabs.io/docs/overview/models
- edge-tts Python async latency (200–400ms): https://github.com/rany2/edge-tts
- WhatsApp audio format requirements (OGG+Opus for PTT): https://api.support.vonage.com/hc/en-us/articles/10900821425308-What-file-types-and-sizes-are-supported-on-WhatsApp
- Baileys voice message OGG/Opus issue: https://github.com/WhiskeySockets/Baileys/issues/1828
- DALL-E timeout patterns: https://community.openai.com/t/400-badrequesterror-when-calling-images-generate-with-dall-e-3/1289697
- asyncio zombie threads from wait_for + run_in_executor: https://bugs.python.org/issue41699 and https://github.com/python/cpython/issues/85865
- asyncio task cleanup / uvicorn lifespan: https://superfastpython.com/asyncio-server-background-task/
- FastAPI WebSocket backpressure: https://hexshift.medium.com/managing-websocket-backpressure-in-fastapi-applications-893c049017d4
- Python circular imports in large codebases: https://dev.to/vivekjami/circular-imports-in-python-the-architecture-killer-that-breaks-production-539j
- WebRTC VAD false positives in production: https://dev.to/callstacktech/implementing-vad-and-turn-taking-for-natural-voice-ai-flow-my-experience-1bdf
- py-webrtcvad frame requirements (16-bit mono PCM, 8/16/32/48 kHz): https://github.com/wiseman/py-webrtcvad
- VAD network jitter: https://www.videosdk.live/developer-hub/webrtc/webrtc-voice-activity-detection
- Python module naming conflicts: https://arxiv.org/html/2401.02090v1
- APScheduler asyncio scheduler: https://apscheduler.readthedocs.io/en/3.x/userguide.html

---
*Pitfalls research for: Synapse-OSS v3.0 feature additions to existing Python asyncio AI system*
*Researched: 2026-04-08*
