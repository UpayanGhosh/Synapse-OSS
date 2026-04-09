# Phase 9: Image Generation - Research

**Researched:** 2026-04-09
**Domain:** OpenAI gpt-image-1 API, fal.ai FLUX, Traffic Cop extension, BackgroundTask media delivery
**Confidence:** HIGH

## Summary

Phase 9 adds image generation to the Synapse chat pipeline. The user says "draw me X" and receives an immediate text acknowledgment followed by a generated image delivered via WhatsApp's media send pathway. The architecture reuses two patterns from prior phases: the BackgroundTask fire-and-forget dispatch from Phase 8 TTS, and the `send_media(mediaType="image")` method already present in `channels/whatsapp.py` which calls the Baileys bridge `/send` endpoint.

The primary provider is OpenAI's `gpt-image-1` (DALL-E 3 is deprecated May 12, 2026 — time-sensitive). `gpt-image-1` always returns `b64_json` (not a URL) — the Python code must decode base64, save to the media store, and serve it locally before calling the Baileys bridge. The secondary provider is fal.ai's FLUX model via the `fal-client` Python package, which returns an image URL directly — simpler download path. The Vault hemisphere block and Traffic Cop IMAGE classification are the two new behaviors that must be wired into `chat_pipeline.py` and `llm_wrappers.py`.

A critical discovery: the `send_media()` method in `channels/whatsapp.py` (lines 396–418) already passes `mediaType="image"` and `mediaUrl` to the Baileys bridge `/send` endpoint, which constructs `{ image: buffer }` for Baileys. This means **no Baileys bridge changes are needed for image delivery** — unlike Phase 8 TTS which required a new `/send-voice` endpoint with `ptt: true`. The image path is already fully wired in the bridge.

**Primary recommendation:** Add `image_gen/` module under `sci_fi_dashboard/`, extend `route_traffic_cop()` to return `IMAGE` classification, add IMAGE role handling to the `chat_pipeline.py` routing block, and dispatch image generation as a `BackgroundTask` after sending the acknowledgment text.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| IMG-01 | User can request image generation ("draw me X") and receive it in chat | Traffic cop classifies IMAGE → pipeline sends ack text → BackgroundTask generates + delivers image via `send_media(mediaType="image")`. Baileys bridge `/send` already handles `mediaType: "image"` without changes. |
| IMG-02 | Traffic Cop classifies image requests as IMAGE role | `route_traffic_cop()` in `llm_wrappers.py` must add `IMAGE` to its classification set. The system prompt needs one additional bullet: `- IMAGE: Draw, generate, create an image, picture, photo, art.` The chat_pipeline routing block needs `elif "IMAGE" in classification: role = "image_gen"` + early-exit to BackgroundTask dispatch. |
| IMG-03 | gpt-image-1 (OpenAI) is default; Flux (fal.ai) is configurable alternative | `openai` Python package for gpt-image-1 (uses `client.images.generate(model="gpt-image-1", ...)`). `fal-client` for FLUX (`fal_client.run_async("fal-ai/flux/dev", arguments={"prompt": ...})`). Provider selection via `image_gen.provider` in synapse.json. |
| IMG-04 | Image gen respects Vault hemisphere — blocked in spicy mode | Same check as skills/tools: `if session_mode == "spicy": return ack_text + decline_note; return`. Decline message sent immediately. No OpenAI/fal API call made. Confirmed by the existing pattern at chat_pipeline.py:622–628. |
| IMG-05 | Generation runs as BackgroundTask with immediate text acknowledgment | Pattern mirrors auto-continue from chat_pipeline.py:1030–1040. Text reply ("generating your image...") is sent first via the normal pipeline return. BackgroundTask fires `_generate_and_send_image(prompt, chat_id)` after. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| openai | >=1.0.0 (latest) | gpt-image-1 image generation via `client.images.generate()` | Official OpenAI Python SDK; gpt-image-1 requires this SDK (not litellm images API). `OPENAI_API_KEY` already injected by Phase 6 `_inject_provider_keys()`. |
| fal-client | 0.13.2 (March 2026) | FLUX image generation via `fal_client.run_async()` | Official fal.ai Python client; async-native; returns image URL directly; zero transcode needed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | >=0.25.0 (already in requirements.txt) | Download fal image URL → bytes for media store | Use when `image_gen.provider = "fal"` to download the returned URL |
| base64 | stdlib | Decode gpt-image-1 `b64_json` response | Always needed for OpenAI provider path |
| `media/store.py` | codebase | Save image bytes → `image_gen_outbound` subdir | Reuse existing `save_media_buffer()` with `subdir="image_gen_outbound"`; handles atomic write + TTL cleanup |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| openai SDK | litellm image generation | litellm does support image generation but its OpenAI image path is less tested; the official SDK is simpler and the key is already injected |
| fal-client FLUX | Replicate API | Replicate requires a separate API key and has slower cold-start; fal FLUX is faster and the ecosystem recommendation for FLUX |
| gpt-image-1 | DALL-E 3 | DALL-E 3 is deprecated May 12, 2026 — cannot use |

**Installation:**
```bash
pip install openai fal-client
```

## Architecture Patterns

### Recommended Project Structure
```
workspace/sci_fi_dashboard/
├── image_gen/
│   ├── __init__.py
│   ├── engine.py          # ImageGenEngine: generate() → bytes, provider dispatch
│   └── providers/
│       ├── openai_img.py  # OpenAIImageProvider: uses openai.AsyncOpenAI.images.generate()
│       └── fal_img.py     # FalImageProvider: uses fal_client.run_async()
```

### Pattern 1: Traffic Cop IMAGE Classification
**What:** Add `IMAGE` as a fifth classification label to `route_traffic_cop()`. When classified, the pipeline skips the normal LLM call and dispatches to BackgroundTask image generation instead.
**When to use:** Always — image requests must never go through the chat LLM.
**Example:**
```python
# In llm_wrappers.py route_traffic_cop():
system = (
    "Classify this message. Reply with EXACTLY ONE WORD: "
    "CASUAL, CODING, ANALYSIS, REVIEW, or IMAGE.\n\n"
    "- IMAGE: Draw, generate, create an image, picture, photo, illustration, art.\n"
    "- CODING: Write code, debug, script, API, python.\n"
    "- ANALYSIS (Synthesis/Data): Summarize logs, explain history, "
    "deep dive, data aggregation.\n"
    "- REVIEW (Critique/Judgment): Grade this, find flaws, audit, critique.\n"
    "- CASUAL: Chat, greetings, daily life, simple questions."
)
```

### Pattern 2: IMAGE Routing in chat_pipeline.py
**What:** After traffic cop returns `IMAGE`, the pipeline sends an immediate acknowledgment text and schedules the actual generation as a BackgroundTask. The normal MoA LLM call is bypassed entirely.
**When to use:** When `classification == "IMAGE"`.
**Example:**
```python
# In persona_chat() safe-hemisphere block, after classification:
if "IMAGE" in classification:
    # Vault block
    if session_mode == "spicy":
        return {
            "reply": "Image generation isn't available in private mode.",
            "role": "image_blocked",
            ...
        }
    ack_text = "Got it — generating your image now..."
    # Send ack immediately by returning it, then fire BackgroundTask
    from sci_fi_dashboard.image_gen.engine import ImageGenEngine

    async def _generate_and_send(prompt: str, chat_id: str):
        engine = ImageGenEngine()
        img_bytes = await engine.generate(prompt)
        if img_bytes:
            saved = save_media_buffer(img_bytes, "image/png", subdir="image_gen_outbound")
            img_url = f"http://127.0.0.1:8000/media/image_gen_outbound/{saved.path.name}"
            channel = deps.channel_registry.get(channel_id)
            if hasattr(channel, "send_media"):
                await channel.send_media(chat_id, img_url, media_type="image", caption=prompt[:50])

    if background_tasks:
        background_tasks.add_task(_generate_and_send, user_msg, request.user_id)
    else:
        asyncio.create_task(_generate_and_send(user_msg, request.user_id))

    return {"reply": ack_text, "role": "image_gen", ...}
```

### Pattern 3: OpenAI gpt-image-1 Provider
**What:** Use `AsyncOpenAI.images.generate()` to generate an image. Always returns `b64_json`. Decode to bytes.
**When to use:** `image_gen.provider` is `"openai"` (default).
**Example:**
```python
# Source: OpenAI Cookbook https://cookbook.openai.com/examples/generate_images_with_gpt_image
import base64
from openai import AsyncOpenAI

async def generate_openai(prompt: str, api_key: str, size: str = "1024x1024") -> bytes:
    client = AsyncOpenAI(api_key=api_key)
    result = await client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=size,          # "1024x1024" | "1536x1024" | "1024x1536"
        quality="medium",   # "low" | "medium" | "high" | "auto"
        n=1,
    )
    # gpt-image-1 always returns b64_json — never a URL
    b64_data = result.data[0].b64_json
    return base64.b64decode(b64_data)
```

### Pattern 4: fal.ai FLUX Provider
**What:** Use `fal_client.run_async()` to call fal-ai/flux/dev. Returns an image URL — download it to bytes.
**When to use:** `image_gen.provider` is `"fal"`.
**Example:**
```python
# Source: PyPI fal-client 0.13.2 + fal.ai FLUX dev API page
import fal_client
import httpx

async def generate_fal(prompt: str, api_key: str) -> bytes:
    import os
    os.environ["FAL_KEY"] = api_key  # fal-client reads from env
    response = await fal_client.run_async(
        "fal-ai/flux/dev",
        arguments={
            "prompt": prompt,
            "image_size": "square_hd",  # or "landscape_4_3", "landscape_16_9"
            "num_images": 1,
        },
    )
    image_url = response["images"][0]["url"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(image_url)
        r.raise_for_status()
        return r.content
```

### Pattern 5: Image Config in synapse.json
**What:** `image_gen` top-level key controls provider, model, and size.
**When to use:** Default ships with OpenAI; user can switch to fal.
```json
{
  "image_gen": {
    "enabled": true,
    "provider": "openai",
    "size": "1024x1024",
    "quality": "medium"
  }
}
```
For fal.ai:
```json
{
  "providers": {
    "fal": {"api_key": "YOUR_FAL_KEY"}
  },
  "image_gen": {
    "provider": "fal",
    "image_size": "square_hd"
  }
}
```

### Pattern 6: SynapseConfig Extension
**What:** Add `image_gen: dict` field to `SynapseConfig` and parse it from `synapse.json`.
**When to use:** All image gen config access goes through `SynapseConfig.image_gen`.
```python
# In synapse_config.py — SynapseConfig dataclass
image_gen: dict = field(default_factory=dict)
# In load():
image_gen = raw.get("image_gen", {})
# Pass to cls(image_gen=image_gen, ...)
```

### Pattern 7: Media Store + Local Serve for Bridge Delivery
**What:** Save generated image bytes to `save_media_buffer(bytes, "image/png", subdir="image_gen_outbound")`. The FastAPI static mount at `/media` (via Baileys bridge's existing media serve) OR a FastAPI `StaticFiles` mount must serve it so the bridge can fetch from `http://127.0.0.1:8000/media/image_gen_outbound/{filename}`.
**Critical:** FastAPI must have a `StaticFiles` mount for the media store root. Check whether this exists. The TTS phase (Phase 8) needs this same pattern — if Phase 8 is implemented first, the mount is already present.

### Anti-Patterns to Avoid
- **Awaiting image generation inline in `persona_chat()`:** Generation takes 10–30 seconds. Never await it in the chat path — the message worker blocks for 30s.
- **Returning an image URL from gpt-image-1 (not b64_json):** gpt-image-1 does NOT support `response_format="url"`. It always returns `b64_json`. Don't try to pass a URL to the Baileys bridge directly from OpenAI.
- **Using DALL-E 3 (`dall-e-3`):** Deprecated May 12, 2026. Any model string `dall-e-3` will fail after that date.
- **Putting image detection in keyword regex instead of traffic cop:** Keyword matching ("draw", "generate", "create") produces false positives (e.g., "create a plan"). The traffic cop LLM call is the correct classifier — add IMAGE to its prompt.
- **Making the Vault block an afterthought:** The Vault check MUST happen before any API call is dispatched. The BackgroundTask must not be spawned if `session_mode == "spicy"`. The ack-text path and the decline-text path are mutually exclusive.
- **Not guarding against missing OPENAI_API_KEY:** If the key is not configured, `AsyncOpenAI` will raise `AuthenticationError` inside the BackgroundTask with no user-visible error. Validate key presence before spawning the task.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Image generation | Custom HTTP calls to OpenAI images endpoint | `openai` Python SDK `AsyncOpenAI.images.generate()` | SDK handles auth headers, response parsing, retries, and the b64_json decoding contract |
| FLUX API client | Custom HTTP calls to fal.ai REST API | `fal-client` (fal_client.run_async) | fal-client handles auth (FAL_KEY env), queue management, and response format |
| Image classification in user message | Keyword regex (`re.search(r"draw|generate|create image", msg)`) | Traffic cop LLM classification returning `IMAGE` | Regex has high false-positive rate; traffic cop already handles ambiguity with context |
| Image file serving | New HTTP server for generated images | FastAPI `StaticFiles` mount (already needed for TTS Phase 8) | StaticFiles mount on the media store path serves all generated media; single infrastructure point |
| Image byte storage | Raw `open()` write | `save_media_buffer(bytes, subdir="image_gen_outbound")` | Atomic write, TTL cleanup, MIME detection — all free from the existing media store |

**Key insight:** The Baileys bridge `/send` endpoint already handles `mediaType: "image"` — this is the one place where image delivery is simpler than TTS (which needed a new `/send-voice` endpoint).

## Common Pitfalls

### Pitfall 1: gpt-image-1 returns only b64_json, never URL
**What goes wrong:** Code calls `result.data[0].url` — gets `None` or `AttributeError`. Image is never delivered.
**Why it happens:** Unlike DALL-E 2/3 which offered `response_format="url"`, gpt-image-1 always returns `b64_json`. The `url` field on the response object is empty.
**How to avoid:** Always use `result.data[0].b64_json` for gpt-image-1. Decode with `base64.b64decode(b64_data)`. Never pass OpenAI's response URL to the bridge.
**Warning signs:** `NoneType` error when accessing `.url`, or bridge gets `None` as `mediaUrl`.

### Pitfall 2: Image BackgroundTask spawns in spicy session (Vault violation)
**What goes wrong:** User in a spicy session says "draw me X". BackgroundTask spawns, calls `api.openai.com` — Vault air-gap violated. Sensitive session context has been confirmed to a cloud API.
**Why it happens:** The Vault check is in the synchronous pipeline path but the BackgroundTask is spawned before the check.
**How to avoid:** The Vault check (`if session_mode == "spicy": return decline`) MUST happen BEFORE `background_tasks.add_task(...)`. The pattern is: check → if allowed, spawn task; if not, return decline text.
**Warning signs:** Outbound HTTPS to `api.openai.com` in the gateway log during a spicy session.

### Pitfall 3: OPENAI_API_KEY not available when BackgroundTask runs
**What goes wrong:** `_inject_provider_keys()` in `SynapseLLMRouter` runs at startup and injects keys into `os.environ`. But if the BackgroundTask creates a new `AsyncOpenAI()` client at task-time and the key hasn't been injected yet (rare timing window), auth fails.
**Why it happens:** `_inject_provider_keys()` is triggered by `SynapseLLMRouter.__init__`, which runs during `lifespan()`. If the task fires before lifespan completes (unlikely but possible), the key may not be in `os.environ`.
**How to avoid:** `ImageGenEngine` should read the API key directly from `SynapseConfig.load().providers.get("openai", {}).get("api_key")` and pass it explicitly to `AsyncOpenAI(api_key=...)`. Do NOT rely solely on the env var.
**Warning signs:** `AuthenticationError: No API key provided` in BackgroundTask logs.

### Pitfall 4: Generated image file not served before bridge fetches it (race)
**What goes wrong:** BackgroundTask generates image, calls `save_media_buffer()`, then immediately calls `send_media(img_url)`. The Baileys bridge tries to `fetch(img_url)` but FastAPI hasn't served the file yet (file write/mount timing).
**Why it happens:** `save_media_buffer()` uses `os.replace()` (atomic), so the file IS written before the URL is passed — this is not a real race if the code is structured correctly. But if the `StaticFiles` mount has a path mismatch with the media store path, the file exists on disk but isn't served at the URL.
**How to avoid:** Verify that the FastAPI `StaticFiles` mount path matches `~/.synapse/state/media/`. Add a smoke test that writes a file and fetches its URL from 127.0.0.1:8000 before confirming the path is correct.
**Warning signs:** Bridge returns 404 when fetching the image URL; file exists on disk.

### Pitfall 5: Traffic cop returning `IMAGE` breaks existing role-mapping code
**What goes wrong:** `chat_pipeline.py` routing block uses `elif "CODING" in classification`. If IMAGE is added but the routing block doesn't have a case for it, it falls through to `role = "casual"` and tries to call the LLM for a normal chat reply — generating a text response to an image request instead of ack + image.
**Why it happens:** The routing block is a linear if/elif/else chain. New classifications must be explicitly handled.
**How to avoid:** Add `elif "IMAGE" in classification:` before the `else: role = "casual"` branch, with a full early-return that sends ack + fires BackgroundTask.
**Warning signs:** Image requests receive a text reply about the image rather than an image; `role=casual` appears in routing logs for image requests.

### Pitfall 6: fal-client FAL_KEY must be set before first call
**What goes wrong:** `fal_client.run_async(...)` raises `AuthenticationError` or `ValueError` if `FAL_KEY` is not in `os.environ` at call time.
**Why it happens:** fal-client reads `FAL_KEY` from `os.environ` at call time (not at import time). If the BackgroundTask runs before `_inject_provider_keys()` has set the env var, or if the user hasn't configured a `fal` provider key, it fails silently in the background.
**How to avoid:** `FalImageProvider` should set `os.environ["FAL_KEY"] = api_key` explicitly before calling `fal_client.run_async()`. Read `api_key` from `SynapseConfig.load().providers.get("fal", {}).get("api_key")`. If blank, log an error and return `None` (no image delivered, but no crash).
**Warning signs:** BackgroundTask logs `KeyError: FAL_KEY` or auth error; no image delivered.

### Pitfall 7: Image prompt is extracted incorrectly (full message vs. stripped)
**What goes wrong:** User says "draw me a sunset over a cyberpunk city". The full message including "draw me" prefix is passed to the image API. This is fine for gpt-image-1 (good at intent extraction) but may waste tokens. More critically: if the traffic cop fires on a message like "can you draw me a plan?" — it should classify ANALYSIS not IMAGE.
**Why it happens:** Keyword overlap between image requests ("draw", "create") and other intents ("create a plan", "draw up a spec").
**How to avoid:** (1) Trust the traffic cop LLM classification — it handles context. Don't add keyword pre-filter. (2) Pass the full user message as the image prompt — gpt-image-1 is good at understanding intent from natural language. (3) Add "draw up a plan" and "create a document" as negative examples in the traffic cop IMAGE bullet if false positives are observed.
**Warning signs:** Non-image requests classified as IMAGE; planning/document requests trigger image generation.

### Pitfall 8: image_gen disabled check
**What goes wrong:** `image_gen.enabled` is `false` in synapse.json (or not set) but image requests still generate images.
**Why it happens:** No check for `image_gen.enabled` before dispatching.
**How to avoid:** Check `deps._synapse_cfg.image_gen.get("enabled", True)` before spawning the BackgroundTask. If disabled, return a soft decline text instead.

## Code Examples

Verified patterns from official sources:

### OpenAI gpt-image-1: Async image generation to bytes
```python
# Source: OpenAI Cookbook https://cookbook.openai.com/examples/generate_images_with_gpt_image
import base64
from openai import AsyncOpenAI

async def generate_openai_image(
    prompt: str,
    api_key: str,
    size: str = "1024x1024",
    quality: str = "medium",
) -> bytes:
    """Generate image with gpt-image-1, return PNG bytes."""
    client = AsyncOpenAI(api_key=api_key)
    result = await client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=size,    # "1024x1024" | "1536x1024" | "1024x1536"
        quality=quality,  # "low" | "medium" | "high" | "auto"
        n=1,
        # No response_format parameter — gpt-image-1 always returns b64_json
    )
    b64_data = result.data[0].b64_json
    return base64.b64decode(b64_data)
```

### fal.ai FLUX: Async image generation to bytes
```python
# Source: PyPI fal-client 0.13.2 (March 2026)
import os
import fal_client
import httpx

async def generate_fal_image(prompt: str, api_key: str) -> bytes:
    """Generate image with FLUX via fal.ai, return image bytes."""
    os.environ["FAL_KEY"] = api_key  # fal-client reads from env
    response = await fal_client.run_async(
        "fal-ai/flux/dev",
        arguments={
            "prompt": prompt,
            "image_size": "square_hd",  # 1024x1024 equivalent
            "num_images": 1,
        },
    )
    image_url = response["images"][0]["url"]
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(image_url)
        r.raise_for_status()
        return r.content
```

### ImageGenEngine: Provider dispatch
```python
# workspace/sci_fi_dashboard/image_gen/engine.py
import logging
from synapse_config import SynapseConfig

logger = logging.getLogger(__name__)
MAX_PROMPT_CHARS = 4000  # gpt-image-1 supports up to 32,000 tokens in prompt


class ImageGenEngine:
    def __init__(self):
        self._cfg = SynapseConfig.load()
        self._img_cfg = self._cfg.image_gen

    async def generate(self, prompt: str) -> bytes | None:
        """Generate image bytes from prompt. Returns None on error."""
        if len(prompt) > MAX_PROMPT_CHARS:
            prompt = prompt[:MAX_PROMPT_CHARS]
        provider = self._img_cfg.get("provider", "openai")
        try:
            if provider == "fal":
                from sci_fi_dashboard.image_gen.providers.fal_img import generate_fal_image
                api_key = self._cfg.providers.get("fal", {}).get("api_key", "")
                if not api_key:
                    logger.error("[IMG] fal api_key not configured")
                    return None
                return await generate_fal_image(prompt, api_key)
            else:  # default: openai
                from sci_fi_dashboard.image_gen.providers.openai_img import generate_openai_image
                api_key = self._cfg.providers.get("openai", {}).get("api_key", "")
                if not api_key:
                    logger.error("[IMG] openai api_key not configured")
                    return None
                size = self._img_cfg.get("size", "1024x1024")
                quality = self._img_cfg.get("quality", "medium")
                return await generate_openai_image(prompt, api_key, size=size, quality=quality)
        except Exception as exc:
            logger.error("[IMG] Generation failed: %s", exc)
            return None
```

### BackgroundTask: Generate + deliver image
```python
# In persona_chat() — the IMAGE branch (after traffic cop returns "IMAGE")
from sci_fi_dashboard.image_gen.engine import ImageGenEngine
from sci_fi_dashboard.media.store import save_media_buffer

async def _generate_and_send_image(prompt: str, chat_id: str, channel_id: str = "whatsapp"):
    engine = ImageGenEngine()
    img_bytes = await engine.generate(prompt)
    if img_bytes is None:
        logger.warning("[IMG] Generation returned None for prompt: %s", prompt[:80])
        return
    saved = save_media_buffer(img_bytes, content_type="image/png", subdir="image_gen_outbound")
    img_url = f"http://127.0.0.1:8000/media/image_gen_outbound/{saved.path.name}"
    channel = deps.channel_registry.get(channel_id)
    if channel and hasattr(channel, "send_media"):
        await channel.send_media(chat_id, img_url, media_type="image", caption="")
    else:
        logger.warning("[IMG] Cannot deliver — channel '%s' has no send_media()", channel_id)

# In pipeline:
if "IMAGE" in classification:
    if session_mode == "spicy":
        return {"reply": "Image generation isn't available in private mode.", "role": "image_blocked"}
    if background_tasks:
        background_tasks.add_task(_generate_and_send_image, user_msg, request.user_id, channel_id)
    else:
        asyncio.create_task(_generate_and_send_image(user_msg, request.user_id, channel_id))
    return {"reply": "Generating your image — it'll be with you in a moment!", "role": "image_gen"}
```

### Traffic Cop: Add IMAGE classification
```python
# In llm_wrappers.py route_traffic_cop() — updated system prompt
system = (
    "Classify this message. Reply with EXACTLY ONE WORD: "
    "CASUAL, CODING, ANALYSIS, REVIEW, or IMAGE.\n\n"
    "- IMAGE: Draw, generate, create an image, picture, photo, illustration, or artwork.\n"
    "- CODING: Write code, debug, script, API, python.\n"
    "- ANALYSIS (Synthesis/Data): Summarize logs, explain history, "
    "deep dive, data aggregation. (Use Gemini Pro Context).\n"
    "- REVIEW (Critique/Judgment): Grade this, find flaws, audit, "
    "critique logic, opinion. (Use Claude Opus nuance).\n"
    "- CASUAL: Chat, greetings, daily life, simple questions."
)
```

### synapse.json: image_gen configuration schema
```json
{
  "image_gen": {
    "enabled": true,
    "provider": "openai",
    "size": "1024x1024",
    "quality": "medium"
  }
}
```

### SynapseConfig: Add image_gen field
```python
# In synapse_config.py — add to SynapseConfig dataclass and load():
image_gen: dict = field(default_factory=dict)
# In load():
image_gen = raw.get("image_gen", {})
# Add to cls(...) call:
# image_gen=image_gen,
```

### FastAPI: StaticFiles mount for generated media
```python
# In api_gateway.py lifespan or app startup — if not already present from Phase 8:
from fastapi.staticfiles import StaticFiles
from synapse_config import SynapseConfig

_cfg = SynapseConfig.load()
_media_root = _cfg.data_root / "state" / "media"
_media_root.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_media_root)), name="media")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| DALL-E 3 (`dall-e-3`) | gpt-image-1 | May 2026 (DALL-E 3 deprecated May 12, 2026) | gpt-image-1 is the only supported OpenAI image model going forward |
| DALL-E URL response | gpt-image-1 b64_json always | With gpt-image-1 launch | Must decode base64, cannot use URL from OpenAI response directly |
| Stable Diffusion via Replicate | FLUX via fal.ai | 2024-2025 | FLUX.1 dev/schnell/pro is the community standard for open-weight image gen; fal.ai is the fastest FLUX serving platform |

**Deprecated/outdated:**
- `dall-e-3`: Deprecated May 12, 2026 — do not use.
- `dall-e-2`: Also deprecated May 12, 2026 — do not use.
- OpenAI `response_format="url"` for gpt-image-1: Not supported — always returns b64_json only.

## Open Questions

1. **FastAPI StaticFiles mount — does it exist yet?**
   - What we know: The Baileys bridge serves its own `/media` endpoint for inbound media (at port 5010). The FastAPI gateway (port 8000) currently does NOT appear to have a `/media` StaticFiles mount for outbound generated media.
   - What's unclear: Phase 8 TTS also needs this mount. If Phase 8 is implemented before Phase 9, the mount may already exist. If Phase 9 is planned independently, it must create the mount.
   - Recommendation: Phase 9 plan should include creating the FastAPI `/media` mount with path `~/.synapse/state/media/` as Wave 0. If Phase 8 already created it, this step is a no-op.

2. **`channel_id` availability in BackgroundTask context**
   - What we know: `continue_conversation()` takes `channel_id` as a parameter. The BackgroundTask for image gen needs the same to call `channel_registry.get(channel_id).send_media(...)`.
   - What's unclear: How `channel_id` flows into `persona_chat()`. It comes from `request.channel_id` or is defaulted to `"whatsapp"`.
   - Recommendation: Add `channel_id: str` parameter to `_generate_and_send_image()`, passed from `request.channel_id` at dispatch time.

3. **Image delivery to non-WhatsApp channels**
   - What we know: Telegram, Discord, Slack channels each have their own `send_media()` or equivalent. The phase scope is WhatsApp-first.
   - What's unclear: Whether non-WhatsApp channels already support `send_media(media_type="image")`.
   - Recommendation: Gate image delivery to channels with `hasattr(channel, "send_media")`. This ensures a no-op on channels that don't support it. Channel-universal image delivery can be a follow-on.

4. **STRATEGY_TO_ROLE — should IMAGE be added?**
   - What we know: `STRATEGY_TO_ROLE` maps cognitive strategies to classifications, skipping the traffic cop call. Image generation is unlikely to map to a cognitive strategy.
   - What's unclear: Whether any DualCognition `response_strategy` values could map to IMAGE.
   - Recommendation: Do NOT add IMAGE to STRATEGY_TO_ROLE. The traffic cop must always classify image requests explicitly — never infer from cognitive strategy.

## Validation Architecture

> nyquist_validation not found in config.json — treating as false (skip).

## Sources

### Primary (HIGH confidence)
- OpenAI Cookbook [Generate images with GPT Image](https://cookbook.openai.com/examples/generate_images_with_gpt_image) — `images.generate()` API, b64_json return format, parameter list
- [PyPI: fal-client 0.13.2](https://pypi.org/project/fal-client/) — `run_async()` API, FAL_KEY env var, response structure
- Codebase: `workspace/sci_fi_dashboard/channels/whatsapp.py` lines 396–418 — `send_media()` with `mediaType="image"` already fully wired
- Codebase: `baileys-bridge/index.js` lines 391–425 — `/send` endpoint handles `mediaType: "image"` via `{ image: buffer }` — no bridge changes needed
- Codebase: `workspace/sci_fi_dashboard/llm_wrappers.py` lines 90–115 — `route_traffic_cop()` — four-label prompt, clean extension point for IMAGE
- Codebase: `workspace/sci_fi_dashboard/chat_pipeline.py` lines 622–628 — Vault/spicy hemisphere block pattern
- Codebase: `workspace/sci_fi_dashboard/chat_pipeline.py` lines 1028–1040 — BackgroundTask pattern (auto-continue)
- Codebase: `workspace/sci_fi_dashboard/media/store.py` — `save_media_buffer()` API — reuse with `subdir="image_gen_outbound"`
- Codebase: `workspace/synapse_config.py` lines 79–189 — `SynapseConfig` dataclass — `image_gen: dict` field follows same pattern as `tts: dict` (Phase 8)

### Secondary (MEDIUM confidence)
- [fal.ai FLUX.1 dev API page](https://fal.ai/models/fal-ai/flux/dev/api) — FLUX model ID, `arguments.prompt`, `arguments.image_size`, response `images[0].url`
- [OpenAI image generation guide](https://platform.openai.com/docs/guides/image-generation) — gpt-image-1 parameter list, deprecation notice for DALL-E 3 May 2026
- WebSearch confirmation: gpt-image-1 always returns b64_json, never URL — `result.data[0].url` is null/None

### Tertiary (LOW confidence)
- [glmimages fal.ai guide 2026](https://www.glmimages.com/blog/fal-ai-api-guide-2026) — corroborates fal-client 0.13.2 version, async API

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — openai SDK confirmed from official cookbook; fal-client version confirmed from PyPI (March 2026)
- Architecture: HIGH — codebase read directly; `send_media()`, Baileys `/send`, BackgroundTask, and media store all confirmed
- Pitfalls: HIGH — Most pitfalls derived from direct codebase analysis and confirmed API behavior (b64_json only for gpt-image-1, Vault pattern from existing code)

**Research date:** 2026-04-09
**Valid until:** 2026-05-09 (openai SDK stable; gpt-image-1 is the current default. Verify DALL-E 3 deprecation date hasn't moved.)
