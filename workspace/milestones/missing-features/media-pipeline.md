# Media Pipeline — Gaps in Synapse-OSS

## Overview

openclaw has a production-grade media pipeline with atomic disk storage, full-spectrum MIME detection via magic-bytes sniffing, context-aware attachment routing, a multi-provider media-understanding layer (audio transcription + image/video description), and per-channel size/concurrency enforcement. Synapse-OSS has a partial media store (ported from openclaw patterns) and a single-backend Groq audio transcription script. Several subsystems present in openclaw are either absent or significantly less capable in Synapse-OSS.

---

## What openclaw Has

### 1. Media Store (`src/media/store.ts`)

- `saveMediaBuffer(buffer, contentType?, subdir?, maxBytes?, originalFilename?)` — UUID-keyed atomic write with `{original}---{uuid}.{ext}` filename embedding.
- `saveMediaSource(source, headers?, subdir?)` — unified URL-or-path entry point; streams URLs to disk with SSRF-pinned DNS, captures first 16 KB for MIME sniffing mid-stream.
- `resolveMediaBufferPath(id, subdir)` — safe read-back: rejects path separators, `..`, null bytes, symlinks.
- `deleteMediaBuffer(id, subdir)` — safe unlink with the same traversal guards.
- `cleanOldMedia(ttlMs, {recursive, pruneEmptyDirs})` — TTL sweep that also prunes empty subdirectories; called inline on every write, not on a background timer.
- `extractOriginalFilename(filePath)` — recovers the original name from the `{name}---{uuid}` pattern.
- Directory mode `0o700`, file mode `0o644` (Docker sandbox access without root).
- Retry-after-mkdir: handles race between mkdir and file write in concurrent access.

**File:** `src/media/store.ts`

### 2. MIME Detection (`src/media/mime.ts`)

- Uses [`file-type`](https://github.com/sindresorhus/file-type) npm package for magic-byte sniffing (supports 270+ formats).
- Priority: sniffed > extension-mapped > header-supplied, with special logic to prevent generic container types (ZIP) from overriding a specific extension mapping (XLSX).
- `normalizeMimeType`, `kindFromMime`, `isAudioFileName`, `imageMimeFromFormat`, `isGifMedia`.
- Full coverage: HEIC/HEIF, Opus, FLAC, M4A, MOV, 7z, RAR, CSV, Markdown, etc.

**File:** `src/media/mime.ts`

### 3. Gateway Attachment Offload (`src/gateway/chat-attachments.ts`)

- Inline threshold: **2 MB** (`OFFLOAD_THRESHOLD_BYTES = 2_000_000`).
- Attachments above threshold → saved to disk via `saveMediaBuffer("inbound")` → opaque `media://inbound/<id>` URI injected into the message.
- Attachments below threshold → passed inline as `{type:"image", data, mimeType}` blocks.
- MIME double-check: sniffs base64 payload before trusting caller-supplied MIME; drops non-image attachments.
- `verifyDecodedSize` guards against silent base64 corruption (Node's `Buffer.from` silently strips bad chars).
- `MediaOffloadError` (5xx) vs `Error` (4xx) distinction so the gateway can respond correctly.
- `OffloadedRef` metadata returned separately for transcript persistence.
- Best-effort cleanup on parse failure via `Promise.allSettled`.
- `supportsImages: false` path drops all attachments cleanly for text-only models.

**File:** `src/gateway/chat-attachments.ts`

### 4. Media Understanding — Runner (`src/media-understanding/runner.ts`)

Multi-backend resolution chain for `audio`, `image`, and `video` capabilities:

1. Active model entry (explicit override from config/session).
2. Local binary probing: `sherpa-onnx-offline`, `whisper-cli`, `whisper` (priority order).
3. `gemini` CLI probe (invoked with `--output-format json`, cached).
4. Provider key lookup: `AUTO_AUDIO_KEY_PROVIDERS`, `AUTO_IMAGE_KEY_PROVIDERS`, `AUTO_VIDEO_KEY_PROVIDERS` constants.
5. Per-attachment decision tracking with `MediaUnderstandingDecision` struct.
6. Vision-native skip: if the active model supports vision (`modelSupportsVision`), image understanding is bypassed (model receives the image directly).
7. Scope deny policy per message context.

**File:** `src/media-understanding/runner.ts`

### 5. Media Understanding — Image (`src/media-understanding/image.ts`)

- `describeImageWithModel` / `describeImagesWithModel` — dispatches to any Pi-model registry provider.
- Minimax VLM special path with `data:` URL encoding and per-image prompting in multi-image batches.
- Timeout with `AbortController`.
- Resolves provider base URL from config for custom endpoints.

**File:** `src/media-understanding/image.ts`

### 6. Audio Transcription (`src/media-understanding/runner.ts`, `audio-transcription-runner.ts`)

- Deepgram provider integration.
- OpenAI-compatible audio endpoint (`openai-compatible-audio.ts`).
- Claude vision-based audio description fallback.
- `audio-preflight.ts`: checks file size and duration before sending to API.
- `runner.skip-tiny-audio.test.ts`: tiny audio files are skipped.
- `concurrency.ts`: per-provider concurrent download caps.

**Files:** `src/media-understanding/audio-transcription-runner.ts`, `audio-preflight.ts`, `concurrency.ts`

### 7. Video Understanding (`src/media-understanding/video.ts`)

- `describeVideo` provider interface.
- Gemini CLI video path using `--include-directories {{MediaDir}}`.
- Auto-resolution via `AUTO_VIDEO_KEY_PROVIDERS`.

**File:** `src/media-understanding/video.ts`

### 8. FFmpeg Integration (`src/media/ffmpeg-exec.ts`, `ffmpeg-limits.ts`)

- `runFfmpeg(args, opts)` — runs ffmpeg with timeout, size caps, and stderr capture.
- `ffmpeg-limits.ts`: per-operation limits (max output bytes, max duration).
- Used by audio preprocessing and image ops.

**Files:** `src/media/ffmpeg-exec.ts`, `src/media/ffmpeg-limits.ts`

### 9. Image Operations (`src/media/image-ops.ts`)

- Resize, strip metadata, convert format (HEIC→JPEG, etc.) via sharp.
- Input guard: rejects SVG and other non-raster formats.
- Temp-dir isolation: operations run in a temp directory, output copied back atomically.

**File:** `src/media/image-ops.ts`

### 10. Per-Channel Media Adapters

- Each channel (Telegram, Discord, Slack, WhatsApp, iMessage) has a media size limit enforced before download.
- `src/media-understanding/attachments.ts`: `normalizeAttachments`, `selectAttachments`, `MediaAttachmentCache` — attachment selection by policy with per-session caching to avoid re-downloading.
- `src/media/read-response-with-limit.ts`: streaming read with byte cap.

---

## What Synapse-OSS Has (or Lacks)

Synapse-OSS has a **partial port** of openclaw's media store, implemented in Python:

| Feature | Synapse-OSS (`sci_fi_dashboard/media/`) | openclaw |
|---|---|---|
| `save_media_buffer` | Yes — partial (12-char hex ID, not full UUID, no `originalFilename`) | Full (36-char UUID, original filename embedded) |
| `detect_mime` | Yes — python-magic + extension fallback | Full (file-type magic bytes, 270+ formats) |
| `clean_old_media` (TTL) | Yes — basic mtime sweep, per-subdir throttle 60 s | Full (recursive, prunes empty dirs, 2 min TTL) |
| SSRF guard | Yes — `is_ssrf_blocked` + `download_to_file` | Full (pinned DNS, two-phase, redirect header stripping) |
| Gateway offload (2 MB threshold) | **Missing** — no claim-check / `media://` URI pattern | Full |
| Image understanding | **Missing** | Full (multi-provider, Minimax VLM, Gemini CLI) |
| Video understanding | **Missing** | Full |
| Audio transcription pipeline | Minimal — single Groq/Whisper script (`do_transcribe.py`) | Full (Deepgram, OpenAI-compatible, local whisper-cli, sherpa-onnx) |
| FFmpeg integration | **Missing** | Full |
| Image ops (resize, convert) | **Missing** | Full (sharp-based) |
| Per-channel size limits | **Missing** | Full |
| Attachment concurrency caps | **Missing** | Full |
| Multi-attachment cache | **Missing** | Full |
| Audio preflight (size/duration) | **Missing** | Full |
| Vision-native skip logic | **Missing** | Full |

---

## Gap Summary

The core gaps are:

1. **No gateway claim-check offload** — large attachments are never saved to disk and injected as `media://` URIs; they either OOM the process or are dropped silently.
2. **No multi-provider media understanding** — no image or video description capability; audio transcription is a standalone CLI script not integrated into the message pipeline.
3. **No FFmpeg or image ops layer** — no format conversion or resize before sending to providers.
4. **No per-channel media enforcement** — size limits and concurrent download caps are absent.
5. **MIME detection coverage gap** — Synapse-OSS covers ~12 types; openclaw covers 270+ via the `file-type` magic-bytes library.

---

## Implementation Notes for Porting

1. **Claim-check offload** — Port `parseMessageWithAttachments` from `src/gateway/chat-attachments.ts`. Key invariants: (a) `OFFLOAD_THRESHOLD_BYTES = 2_000_000`; (b) decode+validate base64 before the storage try/catch to keep error classification correct; (c) cleanup on parse failure via `asyncio.gather(*cleanups, return_exceptions=True)`.

2. **Media understanding** — Create a `MediaUnderstandingPipeline` class mirroring `runner.ts`. Resolution order: active model → local binary → API key. For audio: Groq and Deepgram providers already exist in `sci_fi_dashboard`. For image: add an OpenAI/Anthropic provider.

3. **MIME detection** — Replace `python-magic` with `python-magic` + `filetype` package for broader coverage, or add a priority chain similar to `detectMimeImpl`.

4. **FFmpeg** — Add a `ffmpeg_exec.py` async wrapper with timeout and byte-cap enforcement. Reuse `asyncio.create_subprocess_exec`.

5. **Filename schema** — Change `save_media_buffer` to use `uuid.uuid4().hex` (32 chars) and support the `{original}---{uuid}.{ext}` pattern for `originalFilename`.
