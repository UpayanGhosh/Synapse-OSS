# Phase 8: TTS Voice Output - Research

**Researched:** 2026-04-09
**Domain:** Text-to-speech synthesis, audio format conversion, WhatsApp PTT delivery
**Confidence:** HIGH

## Summary

Phase 8 introduces TTS voice output delivered as WhatsApp voice notes (PTT). The architecture requires three discrete concerns: (1) synthesizing audio bytes from text, (2) converting from MP3 to OGG Opus (WhatsApp's required format), and (3) delivering the audio to WhatsApp through the Baileys bridge with the correct PTT parameters. All three must happen in a BackgroundTask so the text reply is never blocked.

The default provider is `edge-tts` (v7.2.8, released March 2026) — a Python library that reverse-engineers Microsoft Edge's TTS service, requires zero credentials, and provides 400+ neural voices. ElevenLabs is the premium opt-in, using the official `elevenlabs` Python SDK. Both providers generate MP3 by default; the output must be transcoded to OGG Opus before Baileys sends it.

A critical integration gap exists in the Baileys bridge: the current `/send` endpoint passes `{ [mediaTypeKey]: buffer }` to `sock.sendMessage()` but does NOT include `ptt: true` or `mimetype: "audio/ogg; codecs=opus"`. Without these two parameters, WhatsApp renders the message as a regular audio file attachment rather than an inline playable voice note. The bridge needs a new `/send-voice` endpoint (or `/send` must accept optional `ptt` and `mimetype` fields) to support PTT delivery.

**Primary recommendation:** Add a `/send-voice` endpoint to the Baileys bridge that accepts `{ jid, audioUrl }` and calls `sock.sendMessage(jid, { audio: buffer, ptt: true, mimetype: "audio/ogg; codecs=opus" })`. On the Python side: synthesize → convert → serve the OGG file via a short-TTL local HTTP endpoint → call `/send-voice` from a `BackgroundTask`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TTS-01 | User receives voice replies as playable WhatsApp voice notes (OGG Opus) | Baileys bridge requires `/send-voice` with `ptt: true` + `mimetype: "audio/ogg; codecs=opus"`; OGG file served from FastAPI static mount or media store |
| TTS-02 | edge-tts is the default TTS provider (zero API key, 400+ voices) | edge-tts v7.2.8 confirmed; `Communicate(text, voice).save(path)` async API; outputs MP3, requires ffmpeg transcode to OGG Opus |
| TTS-03 | ElevenLabs is available as premium opt-in TTS provider | `elevenlabs` Python SDK; `AsyncElevenLabs.text_to_speech.convert(text, voice_id)` returns audio bytes iterator; ELEVENLABS_API_KEY injected from providers config |
| TTS-04 | TTS runs as BackgroundTask — never blocks the chat pipeline | `asyncio.create_task()` pattern (same as auto-continue in chat_pipeline.py) with `background_tasks.add_task()` when BackgroundTasks object is available |
| TTS-05 | User can configure preferred voice in synapse.json | `tts.voice` key in synapse.json; `SynapseConfig` needs `tts: dict` field; default `"en-US-AriaNeural"` for edge-tts |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| edge-tts | 7.2.8 | Default TTS synthesis (MP3 output) | Zero credentials, 400+ Microsoft neural voices, pure Python async, active maintenance |
| elevenlabs | latest (official SDK) | Premium TTS synthesis | Official ElevenLabs SDK, `AsyncElevenLabs` for non-blocking calls |
| asyncio subprocess / `asyncio.to_thread` | stdlib | ffmpeg transcoding MP3 → OGG Opus | No blocking the event loop during CPU/IO-bound transcode |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| ffmpeg (system binary) | any modern | Transcode MP3 → OGG Opus 48kHz | Required for both edge-tts and ElevenLabs (both output MP3); must be in PATH |
| pydub | latest | Alternative transcode path | Use only if ffmpeg subprocess proves unreliable; pydub still requires ffmpeg underneath — no benefit |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| edge-tts | pyttsx3 | pyttsx3 is offline but voice quality is poor and Windows-only; edge-tts neural voices are vastly better |
| edge-tts | OpenAI TTS | OpenAI TTS requires API key, costs money — violates zero-cost default requirement |
| asyncio subprocess for ffmpeg | pydub | pydub wraps ffmpeg but adds dependency weight with no async benefit; direct subprocess is simpler |
| New `/send-voice` bridge endpoint | Reuse `/send` with extra params | `/send` currently ignores extra fields silently; safer to add a dedicated endpoint with clear contract |

**Installation:**
```bash
pip install edge-tts elevenlabs
# ffmpeg must be installed separately (apt install ffmpeg / brew install ffmpeg / winget install ffmpeg)
```

## Architecture Patterns

### Recommended Project Structure
```
workspace/sci_fi_dashboard/
├── tts/
│   ├── __init__.py
│   ├── engine.py          # TTSEngine: synthesize() → bytes (MP3), provider dispatch
│   ├── convert.py         # ogg_from_mp3_bytes(): MP3 bytes → OGG Opus bytes via ffmpeg
│   └── providers/
│       ├── edge.py        # EdgeTTSProvider: uses edge_tts.Communicate
│       └── elevenlabs.py  # ElevenLabsProvider: uses AsyncElevenLabs
baileys-bridge/
└── index.js               # NEW: POST /send-voice endpoint
```

### Pattern 1: BackgroundTask TTS Dispatch
**What:** After `persona_chat()` returns the text reply, schedule TTS as a fire-and-forget background task — same pattern as `auto_continue` in `chat_pipeline.py`.
**When to use:** Always — TTS must never block the message worker.
**Example:**
```python
# In pipeline_helpers.process_message_pipeline(), after reply is sent:
async def _send_voice_note(reply: str, chat_id: str, channel_id: str = "whatsapp"):
    from sci_fi_dashboard.tts.engine import TTSEngine
    engine = TTSEngine()
    ogg_bytes = await engine.synthesize(reply)     # MP3 → OGG pipeline
    if ogg_bytes:
        # Save to media store, get local serve URL
        # POST to Baileys /send-voice
        await _deliver_voice_note(chat_id, ogg_bytes)

# Source: BackgroundTask pattern from chat_pipeline.py lines 1028-1040
task = asyncio.create_task(_send_voice_note(reply, chat_id))
_background_tasks.add(task)
task.add_done_callback(_background_tasks.discard)
```

### Pattern 2: edge-tts Synthesis
**What:** Use `Communicate(text, voice)` async API to save MP3 bytes.
**When to use:** `tts.provider` is `"edge-tts"` (default) or not configured.
**Example:**
```python
# Source: https://github.com/rany2/edge-tts + PyPI page
import edge_tts
import tempfile
from pathlib import Path

async def synthesize_edge(text: str, voice: str = "en-US-AriaNeural") -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name
    try:
        await communicate.save(tmp_path)
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)
```

### Pattern 3: ElevenLabs Synthesis
**What:** Use `AsyncElevenLabs.text_to_speech.convert()` to get audio bytes.
**When to use:** `tts.provider` is `"elevenlabs"` and `ELEVENLABS_API_KEY` is set.
**Example:**
```python
# Source: https://github.com/elevenlabs/elevenlabs-python README
from elevenlabs.client import AsyncElevenLabs

async def synthesize_elevenlabs(text: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM") -> bytes:
    # ELEVENLABS_API_KEY already in os.environ via _inject_provider_keys()
    import os
    client = AsyncElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY", ""))
    audio_gen = await client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        output_format="mp3_44100_128",
    )
    chunks = []
    async for chunk in audio_gen:
        if isinstance(chunk, bytes):
            chunks.append(chunk)
    return b"".join(chunks)
```

### Pattern 4: MP3 → OGG Opus Conversion
**What:** Transcode MP3 bytes to OGG Opus using ffmpeg via asyncio subprocess.
**When to use:** Before every Baileys PTT delivery — WhatsApp only renders earphone-icon playable voice notes for OGG Opus with `ptt: true`.
**Example:**
```python
# Source: ffmpeg docs + WhatsApp PTT format requirements
import asyncio
import tempfile
from pathlib import Path

async def mp3_to_ogg_opus(mp3_bytes: bytes) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fin:
        fin.write(mp3_bytes)
        in_path = fin.name
    out_path = in_path.replace(".mp3", ".ogg")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", in_path,
            "-c:a", "libopus", "-b:a", "48k", "-ar", "48000",
            "-f", "ogg", out_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg conversion failed")
        return Path(out_path).read_bytes()
    finally:
        Path(in_path).unlink(missing_ok=True)
        Path(out_path).unlink(missing_ok=True)
```

### Pattern 5: Baileys `/send-voice` Endpoint (Node.js bridge change)
**What:** New endpoint in `baileys-bridge/index.js` that sends audio as PTT voice note.
**When to use:** Any time Python delivers an OGG Opus audio file as a voice note.
**Example:**
```javascript
// Source: Baileys docs / WhiskeySockets/Baileys issues #1745, #1828
app.post('/send-voice', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid, audioUrl } = req.body;
  if (!jid || !audioUrl) {
    return res.status(400).json({ error: 'jid and audioUrl are required' });
  }
  try {
    await new Promise((r) => setTimeout(r, 1000 + Math.random() * 2000)); // anti-spam jitter
    const response = await fetch(audioUrl, { signal: AbortSignal.timeout(30000) });
    if (!response.ok) {
      return res.status(400).json({ error: `Failed to fetch audio: ${response.status}` });
    }
    const buffer = Buffer.from(await response.arrayBuffer());
    const sentMsg = await sock.sendMessage(jid, {
      audio: buffer,
      ptt: true,
      mimetype: 'audio/ogg; codecs=opus',
    });
    res.json({ ok: true, messageId: sentMsg?.key?.id || null });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});
```

### Pattern 6: TTS Config in synapse.json
**What:** `tts` top-level key in synapse.json controls provider and voice selection.
**When to use:** Default config ships with edge-tts; user overrides to ElevenLabs.
```json
{
  "tts": {
    "enabled": true,
    "provider": "edge-tts",
    "voice": "en-US-AriaNeural"
  }
}
```
For ElevenLabs:
```json
{
  "providers": {
    "elevenlabs": {"api_key": "YOUR_ELEVENLABS_KEY"}
  },
  "tts": {
    "provider": "elevenlabs",
    "voice": "Rachel"
  }
}
```

### Pattern 7: Voice Name Resolution (ElevenLabs)
**What:** ElevenLabs uses `voice_id` (UUID-like string), not human names, in API calls. The config accepts human names like `"Rachel"` but the engine must resolve them to IDs.
**Resolution approach:** Maintain a hardcoded dict of common premade voice name → voice_id. Rachel = `21m00Tcm4TlvDq8ikWAM`, Josh = `TxGEqnHWrfWFTfGW9XjX`. Fallback: if the configured voice value looks like a UUID/ID (no spaces, 20+ chars), use it directly. Do NOT hit the voices API on every TTS call — too slow.

### Pattern 8: Media Serve-and-Forget
**What:** Save OGG bytes to the existing `media/store.py` (subdir `"tts_outbound"`) to get a local file path, then serve it at `http://127.0.0.1:8000/media/tts_outbound/{file}` via FastAPI static mount. The Baileys bridge fetches it from that URL. After delivery, clean up the file.
**Why:** The bridge already uses URL-based media fetching (`fetch(mediaUrl)`). Reusing the existing media store and FastAPI static mount avoids introducing new serving infrastructure.

### Anti-Patterns to Avoid
- **Awaiting TTS inside `persona_chat()`:** The TTS pipeline (synthesis + transcode) takes 2–10 seconds. Never await it inline — the message worker would block.
- **Using `ptt: false` or omitting `ptt`:** WhatsApp renders audio without `ptt: true` as a document attachment, not a voice note. The earphone icon will NOT appear.
- **Using `mimetype: "audio/ogg"` without codec qualifier:** WhatsApp requires `"audio/ogg; codecs=opus"` — the short form fails recognition as a voice note.
- **Calling ElevenLabs voices API on every synthesis:** Too slow and burns API rate limit. Use the hardcoded name → ID map.
- **Generating voice notes for very long messages:** Long TTS synthesis (>500 chars) may timeout or produce audio too long for comfortable listening. Consider a character limit (e.g., 300 chars) above which TTS is skipped.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MP3 → OGG Opus transcode | Custom audio codec implementation | `ffmpeg` subprocess with `libopus` | ffmpeg handles all sample rate/bitrate/channel concerns correctly; custom codec is a multi-week project |
| TTS synthesis | Custom SSML-to-speech pipeline | `edge-tts` library | edge-tts reverse-engineers Microsoft's production TTS WebSocket — this is non-trivial to implement |
| ElevenLabs API client | Custom HTTP client with auth headers | Official `elevenlabs` Python SDK | SDK handles auth, retries, streaming, and model updates |
| Voice name → ID resolution | Hitting `/voices` endpoint on every call | Hardcoded premade voice dict + direct ID pass-through | The voices endpoint adds 200ms+ latency per TTS call |

**Key insight:** Audio format conversion is deceptively complex (sample rate, channel count, bitrate, container vs codec). Always delegate to ffmpeg.

## Common Pitfalls

### Pitfall 1: Missing `ptt: true` in Baileys send call
**What goes wrong:** Audio is delivered as a regular audio file attachment, not a playable voice note. The earphone icon does not appear. User must tap "download" instead of seeing inline playback.
**Why it happens:** The current Baileys bridge `/send` endpoint constructs `{ [mediaTypeKey]: buffer }` which does not include PTT parameters. Passing `mediaType: "audio"` is not enough.
**How to avoid:** Add a `/send-voice` endpoint that hardcodes `ptt: true` and `mimetype: "audio/ogg; codecs=opus"`. Never reuse the generic `/send` endpoint for voice notes.
**Warning signs:** Voice message shows as attachment icon (paper clip) in WhatsApp instead of earphone icon with waveform.

### Pitfall 2: Sending MP3 directly (skipping OGG Opus conversion)
**What goes wrong:** WhatsApp will not recognize the audio as a voice note even with `ptt: true`. It may show as an unplayable or corrupted message on some clients.
**Why it happens:** WhatsApp PTT messages expect OGG container with Opus codec. MP3 is in a different container format entirely.
**How to avoid:** Always run mp3_to_ogg_opus() before calling the bridge. Verify the file format: `file output.ogg` should say "Ogg data, Opus audio".
**Warning signs:** Voice note plays on desktop but not mobile, or shows error on send.

### Pitfall 3: Blocking the event loop during ffmpeg transcode
**What goes wrong:** The asyncio event loop blocks for 1–3 seconds during subprocess execution if using `subprocess.run()` (synchronous). All other messages queue behind it.
**Why it happens:** ffmpeg transcode is CPU/IO-bound. Synchronous subprocess blocks the event loop.
**How to avoid:** Always use `asyncio.create_subprocess_exec()`, not `subprocess.run()`. The entire TTS pipeline runs inside `asyncio.create_task()` anyway — ensure no synchronous blocking calls inside the task.
**Warning signs:** Other messages take 2–3s longer to process when voice note is being synthesized.

### Pitfall 4: TTS synthesis for messages that are too long
**What goes wrong:** Synthesizing a 500-word message produces a 3–4 minute audio file. This is not a good voice note UX, and ElevenLabs charges per character.
**Why it happens:** No length guard on input text before synthesis.
**How to avoid:** In `TTSEngine.synthesize()`, truncate or skip TTS if `len(text) > MAX_TTS_CHARS` (recommend 400 chars). Return `None` if skipped — the caller should gracefully handle `None` (just no voice note, text already sent).
**Warning signs:** Very long replies producing multi-minute audio.

### Pitfall 5: ElevenLabs API key not in os.environ when TTS is called
**What goes wrong:** `AsyncElevenLabs(api_key="")` silently creates a client that fails on first API call with an auth error.
**Why it happens:** `_inject_provider_keys()` runs at `SynapseLLMRouter` init time, not at TTS engine init time. TTS module initializes separately.
**How to avoid:** `TTSEngine` must call `SynapseConfig.load()` and read `providers.elevenlabs.api_key` directly, then pass it to `AsyncElevenLabs(api_key=...)`. Do NOT rely on `os.environ` being pre-populated from llm_router init.
**Warning signs:** `AuthenticationError` or `401` from ElevenLabs on first voice note.

### Pitfall 6: ffmpeg not installed on fresh OSS installs
**What goes wrong:** `asyncio.create_subprocess_exec("ffmpeg", ...)` raises `FileNotFoundError`. TTS silently fails and the user never gets a voice note.
**Why it happens:** ffmpeg is a system binary, not a Python package. It is not in `requirements.txt`.
**How to avoid:** (1) Catch `FileNotFoundError` and log a clear message: `"ffmpeg not found — voice notes disabled. Install ffmpeg to enable TTS."` (2) Add ffmpeg to the preflight check in `pipeline_helpers.py:validate_env()`. (3) Document the ffmpeg requirement in HOW_TO_RUN.md.
**Warning signs:** No voice notes are delivered, no error surfaced to user.

### Pitfall 7: OGG file served by FastAPI before ffmpeg writes it (race)
**What goes wrong:** The Baileys bridge calls the OGG file URL before ffmpeg has finished writing it, getting a partial or empty file.
**Why it happens:** `asyncio.create_subprocess_exec` + `await proc.wait()` is correct — but only if `await` is respected throughout. If the TTS task is structured wrong and `proc.wait()` is not awaited, the file is served half-written.
**How to avoid:** Ensure the transcode step uses `await proc.wait()` before reading bytes. Write to a temp file first, then atomic-rename to the final path before serving.

### Pitfall 8: Voice note delivery triggers auto-continue loop
**What goes wrong:** If the voice note reply text ends without terminal punctuation (same condition that triggers auto-continue), two things run in parallel: auto-continue generates a continuation, and TTS synthesizes the original reply. The user receives a voice note AND a follow-up text continuation.
**Why it happens:** Both BackgroundTasks fire on the same reply text.
**How to avoid:** In `process_message_pipeline`, only trigger TTS if the reply is reasonably complete (ends with terminal punctuation) OR accept the dual-delivery as acceptable behavior. Document this interaction explicitly.

## Code Examples

Verified patterns from official sources:

### edge-tts: Synthesize to MP3 bytes
```python
# Source: https://pypi.org/project/edge-tts/ + https://github.com/rany2/edge-tts
import asyncio
import edge_tts
import tempfile
from pathlib import Path

async def edge_tts_to_mp3_bytes(text: str, voice: str = "en-US-AriaNeural") -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name
    try:
        await communicate.save(tmp_path)
        return Path(tmp_path).read_bytes()
    finally:
        Path(tmp_path).unlink(missing_ok=True)
```

### ElevenLabs: Async synthesis to MP3 bytes
```python
# Source: https://github.com/elevenlabs/elevenlabs-python README
from elevenlabs.client import AsyncElevenLabs

async def elevenlabs_to_mp3_bytes(
    text: str,
    voice_id: str,
    api_key: str,
) -> bytes:
    client = AsyncElevenLabs(api_key=api_key)
    audio_gen = await client.text_to_speech.convert(
        voice_id=voice_id,
        text=text,
        output_format="mp3_44100_128",
    )
    chunks = [chunk async for chunk in audio_gen if isinstance(chunk, bytes)]
    return b"".join(chunks)
```

### ffmpeg: Async MP3 → OGG Opus transcode
```python
# Source: ffmpeg documentation + WhatsApp PTT format requirements
import asyncio
import tempfile
from pathlib import Path

async def mp3_to_ogg_opus(mp3_bytes: bytes) -> bytes:
    """Transcode MP3 → OGG+Opus for WhatsApp PTT delivery."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fin:
        fin.write(mp3_bytes)
        in_path = fin.name
    out_path = in_path.replace(".mp3", ".ogg")
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", in_path,
            "-c:a", "libopus", "-b:a", "48k", "-ar", "48000",
            "-ac", "1",          # mono — reduces file size
            "-f", "ogg", out_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg exited {proc.returncode}")
        return Path(out_path).read_bytes()
    finally:
        for p in (in_path, out_path):
            Path(p).unlink(missing_ok=True)
```

### Baileys `/send-voice` endpoint (Node.js)
```javascript
// Source: WhiskeySockets/Baileys issues #1745, #1828; PTT format requirements
app.post('/send-voice', async (req, res) => {
  if (!sock || connectionState !== 'connected') {
    return res.status(503).json({ error: 'Bridge not connected', connectionState });
  }
  const { jid, audioUrl } = req.body;
  if (!jid || !audioUrl) {
    return res.status(400).json({ error: 'jid and audioUrl are required' });
  }
  try {
    await new Promise((r) => setTimeout(r, 1000 + Math.random() * 2000));
    const response = await fetch(audioUrl, { signal: AbortSignal.timeout(30000) });
    if (!response.ok) {
      return res.status(400).json({ error: `Audio fetch failed: ${response.status}` });
    }
    const buffer = Buffer.from(await response.arrayBuffer());
    const sentMsg = await sock.sendMessage(jid, {
      audio: buffer,
      ptt: true,
      mimetype: 'audio/ogg; codecs=opus',
    });
    res.json({ ok: true, messageId: sentMsg?.key?.id || null });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});
```

### synapse.json: TTS configuration schema
```json
{
  "tts": {
    "enabled": true,
    "provider": "edge-tts",
    "voice": "en-US-AriaNeural",
    "max_chars": 400
  }
}
```

### SynapseConfig: Add tts field
```python
# In synapse_config.py — add to SynapseConfig dataclass
tts: dict = field(default_factory=dict)
# And in load():
tts = raw.get("tts", {})
# Then pass tts=tts to cls(...)
```

### WhatsApp channel: send_voice_note helper
```python
# In channels/whatsapp.py — new method
async def send_voice_note(self, chat_id: str, audio_url: str) -> bool:
    """Send OGG Opus audio as a WhatsApp PTT voice note."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"http://127.0.0.1:{self._port}/send-voice",
                json={"jid": chat_id, "audioUrl": audio_url},
            )
            return r.status_code == 200
    except httpx.RequestError as exc:
        logger.error("[WA] send_voice_note() failed: %s", exc)
        return False
```

### ElevenLabs premade voice name → ID lookup
```python
# Hardcoded premade voices — avoid per-call API lookups
# Source: https://elevenlabs-sdk.mintlify.app/voices/premade-voices
_ELEVENLABS_PREMADE_VOICES: dict[str, str] = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Josh": "TxGEqnHWrfWFTfGW9XjX",
    "Sam": "yoZ06aMxZJJ28mfd3POQ",
    "Bella": "EXAVITQu4vr4xnSDxMaL",
    "Adam": "pNInz6obpgDQGcFmaJgB",
    "Elli": "MF3mGyEYCl7XYWbV9V6O",
    "Arnold": "VR6AewLTigWG4xSOukaG",
    "Domi": "AZnzlk1XvdvUeBnXmlld",
    "Antoni": "ErXwobaYiN019PkySvjV",
}

def resolve_elevenlabs_voice_id(name_or_id: str) -> str:
    """Return voice_id for a given name or pass through if already an ID."""
    return _ELEVENLABS_PREMADE_VOICES.get(name_or_id, name_or_id)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| espeak / Festival TTS | edge-tts (Microsoft neural) | 2020+ | Dramatically better voice quality; neural voices vs robot voices |
| DALL-E 3 | gpt-image-1 (tracked in Phase 9) | May 2026 | Relevant for Phase 9, not 8 |
| WhiskeySockets/Baileys waveform PTT | Waveform support broken in v6.7.9+ | 2025 | Skip waveform parameter; PTT still works without it; flat line display is acceptable |

**Deprecated/outdated:**
- `pydub` for OGG conversion: Still works but wraps ffmpeg anyway; direct subprocess is preferred.
- ElevenLabs v1 SDK (`generate()` function): Replaced by `client.text_to_speech.convert()` in the v2+ SDK.

## Open Questions

1. **TTS for non-WhatsApp channels (Telegram, Discord, Slack)**
   - What we know: The phase scope is WhatsApp voice notes only.
   - What's unclear: Should TTS be channel-aware? Telegram also supports voice notes via OGG Opus; Discord has different audio requirements.
   - Recommendation: Gate TTS delivery to WhatsApp channel only in this phase. Channel-abstracted TTS delivery is a v3.1+ concern.

2. **TTS toggle per-user vs global**
   - What we know: The `tts.enabled` config is global.
   - What's unclear: Users may want to opt out of voice notes (prefer text only).
   - Recommendation: Implement as global toggle in this phase. Per-user preference can be a follow-on.

3. **ffmpeg availability on Windows for OSS users**
   - What we know: The project runs on Windows (confirmed by env: win32).
   - What's unclear: Windows users may not have ffmpeg in PATH by default. `winget install Gyan.FFmpeg` works but is not automatic.
   - Recommendation: Add a preflight check for ffmpeg in `validate_env()`. Gracefully disable TTS (not crash) if absent. Document `winget install Gyan.FFmpeg` in HOW_TO_RUN.md.

4. **Auto-continue + TTS interaction**
   - What we know: Both auto-continue and TTS fire as BackgroundTasks on the same reply.
   - What's unclear: Whether delivering a voice note AND a follow-up text continuation is acceptable UX.
   - Recommendation: Only trigger TTS if auto-continue is NOT triggered (i.e., reply ends with terminal punctuation). Mutually exclusive BackgroundTask dispatch.

## Sources

### Primary (HIGH confidence)
- [PyPI: edge-tts 7.2.8](https://pypi.org/project/edge-tts/) — current version, CLI examples
- [GitHub: rany2/edge-tts](https://github.com/rany2/edge-tts) — Communicate class API, stream() method, voice format
- [GitHub: elevenlabs/elevenlabs-python](https://github.com/elevenlabs/elevenlabs-python) — AsyncElevenLabs pattern, audio generation
- [ElevenLabs Docs: TTS Convert API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert) — output formats (27 formats), voice_id param, output_format encoding scheme
- Codebase: `baileys-bridge/index.js` lines 390-425 — current `/send` endpoint without PTT support
- Codebase: `channels/whatsapp.py` lines 396-418 — `send_media()` pattern used for reference
- Codebase: `chat_pipeline.py` lines 1028-1040 — existing BackgroundTask pattern for auto-continue
- Codebase: `llm_router.py` lines 228-244 — `_inject_provider_keys()` pattern

### Secondary (MEDIUM confidence)
- [WhiskeySockets/Baileys Issue #1828](https://github.com/WhiskeySockets/Baileys/issues/1828) — PTT audio bug, `ptt: true` + `mimetype` requirement confirmed
- [WhiskeySockets/Baileys Issue #1745](https://github.com/WhiskeySockets/Baileys/issues/1745) — Waveform broken in v6.7.9; PTT itself unaffected
- [ElevenLabs premade voices](https://elevenlabs-sdk.mintlify.app/voices/premade-voices) — Rachel, Josh, Adam voice IDs
- WebSearch: ffmpeg command `ffmpeg -c:a libopus -b:a 48k -ar 48000 -f ogg` for WhatsApp PTT

### Tertiary (LOW confidence)
- VideoSDK edge-tts guide — voice list examples; specific voice catalog may drift

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — edge-tts PyPI page confirms v7.2.8 (March 2026); ElevenLabs SDK verified via official GitHub
- Architecture: HIGH — Baileys bridge code read directly; PTT requirement confirmed from Baileys issue tracker
- Pitfalls: HIGH — Most pitfalls derived from direct codebase analysis (bridge missing ptt:true, no ffmpeg in requirements)

**Research date:** 2026-04-09
**Valid until:** 2026-05-09 (stable libraries; Baileys PTT behavior unlikely to change)
