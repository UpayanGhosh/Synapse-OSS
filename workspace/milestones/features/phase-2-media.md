# Phase 2: Media & Document Sharing on Chat Channels

## Overview

OpenClaw supports end-to-end media and document sharing across all major chat channels
(Telegram, Discord, Slack, Signal, iMessage, WhatsApp). Media flows inbound from
channel CDNs through the gateway into the agent pipeline, and outbound from tool
results through a delivery queue back to the originating channel. The system handles
images, audio, video, and documents with transcoding, transcription, MIME sniffing,
size limits, and SSRF-protected downloads.

---

## Key Files

| File | Role |
|------|------|
| `src/gateway/chat-attachments.ts` | Inbound attachment parsing, offloading to disk |
| `src/media/store.ts` | Persistent media storage with UUID-based naming |
| `src/media/mime.ts` | Magic-number MIME detection + extension mapping |
| `src/media/outbound-attachment.ts` | Outbound attachment resolution (URL/path) |
| `src/media/fetch.ts` | SSRF-safe HTTP media download |
| `src/media/constants.ts` | Global size constants (5MB max, 2MB offload threshold) |
| `src/media-understanding/types.ts` | `MediaAttachment`, `MediaUnderstandingProvider` |
| `src/media-understanding/attachments.normalize.ts` | `normalizeAttachments()`, kind classification |
| `src/media-understanding/runner.ts` | Media processing orchestration |
| `src/auto-reply/types.ts` | `ReplyPayload` — outbound media delivery contract |
| `src/infra/outbound/delivery-queue-storage.ts` | Persistent retry queue for channel delivery |
| `src/channels/plugins/media-limits.ts` | Per-channel/per-account size limits |
| `extensions/discord/src/monitor/message-utils.ts` | Discord CDN download |
| `extensions/telegram/src/bot/delivery.replies.ts` | Telegram media send logic |
| `extensions/slack/src/monitor/media.ts` | Slack media download (auth-aware) |
| `extensions/signal/src/outbound-adapter.ts` | Signal media outbound |
| `src/agents/subagent-attachments.ts` | Subagent inline attachment materialization |

---

## Core Types

### MediaAttachment (`src/media-understanding/types.ts`)

```typescript
type MediaAttachment = {
  path?: string
  url?: string
  mime?: string
  index: number
  alreadyTranscribed?: boolean
}
```

### ReplyPayload (`src/auto-reply/types.ts`)

```typescript
type ReplyPayload = {
  text?: string
  mediaUrl?: string          // single media item
  mediaUrls?: string[]       // multiple media items
  interactive?: InteractiveReply
  channelData?: Record<string, unknown>
  replyToId?: string
  audioAsVoice?: boolean     // send audio as voice note
  isError?: boolean
  isReasoning?: boolean
}
```

### QueuedDeliveryPayload (`src/infra/outbound/delivery-queue-storage.ts`)

```typescript
type QueuedDeliveryPayload = {
  channel: OutboundChannel
  to: string
  accountId?: string
  payloads: ReplyPayload[]
  threadId?: string | number | null
  replyToId?: string | null
  bestEffort?: boolean
  gifPlayback?: boolean
  forceDocument?: boolean
  silent?: boolean
}
```

---

## Phase A: Inbound — Channel → Gateway

### 1. Channel-Level Download

Each channel adapter downloads media from its CDN before sending to the gateway.

**Discord** (`extensions/discord/src/monitor/message-utils.ts`):

```typescript
resolveMediaList(message, maxBytes, fetchImpl?, ssrfPolicy?)
// → fetchRemoteMedia(url) → saveMediaBuffer() → DiscordMediaInfo[]
```

CDN allowlist: `cdn.discordapp.com`, `media.discordapp.net`. Stickers (PNG, GIF,
Lottie, APNG) handled separately.

**Slack** (`extensions/slack/src/monitor/media.ts`):

```typescript
fetchWithSlackAuth(url, token)
// Authorization header stripped on cross-origin redirects (Slack uses pre-signed URLs)
// Max 3 concurrent downloads, max 8 files per message
// audio/* override: slack_audio subtype with video/* MIME → rewritten to audio/*
```

**Telegram, Signal, iMessage**: Use channel-specific download functions with
`createScopedChannelMediaMaxBytesResolver()` for per-account size limits.

### 2. Gateway Attachment Parsing (`src/gateway/chat-attachments.ts`)

```typescript
parseMessageWithAttachments(message, attachments, opts?)
→ ParsedMessageWithImages {
    message:       string             // with media:// markers for offloaded files
    images:        ChatImageContent[] // inline base64 blocks (≤ 2MB)
    offloadedRefs: OffloadedRef[]    // disk-saved refs (> 2MB)
    imageOrder:    "inline" | "offloaded"
  }
```

**Processing rules:**

| Condition | Action |
|-----------|--------|
| File ≤ 2MB | Passed inline as `ChatImageContent[]` to model |
| File > 2MB | Saved to disk via `saveMediaBuffer()` with `media://inbound/<id>` URI |
| MIME sniffing fails | Error: 4xx |
| Disk write fails | `MediaOffloadError` (5xx) |

Best-effort cleanup: if a later attachment fails, already-saved files are deleted.

**Size constants** (`src/media/constants.ts`):

```typescript
DEFAULT_MAX_BYTES = 5_000_000      // 5MB hard limit
OFFLOAD_THRESHOLD_BYTES = 2_000_000 // 2MB offload threshold
```

---

## Phase B: Media Storage (`src/media/store.ts`)

```typescript
saveMediaBuffer(
  buffer: Buffer,
  contentType?: string,
  subdir = "inbound",
  maxBytes?: number,
  originalFilename?: string
): Promise<SavedMedia>
```

Files stored at: `{configDir}/media/{subdir}/{sanitized}---{uuid}.{ext}`

- File mode: `0o644` (readable by Docker sandbox containers)
- Directory mode: `0o700`
- TTL cleanup: 2-minute default sweep

```typescript
resolveMediaBufferPath(id, subdir = "inbound"): string
// Security: rejects path separators, "..", null bytes
// Rejects symlinks and directories
```

### MIME Detection (`src/media/mime.ts`)

```typescript
detectMime({ buffer, headerMime, filePath }): string
// Magic number sniffing (first 16KB)
// Falls back to headerMime, then filePath extension
```

---

## Phase C: Media Understanding Pipeline (`src/media-understanding/`)

### Kind Classification (`attachments.normalize.ts`)

```typescript
resolveAttachmentKind(attachment): "image" | "audio" | "video" | "document"
```

| Kind | Triggers |
|------|---------|
| `image` | `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.bmp`, `.tiff` + `image/*` MIME |
| `audio` | `.mp3`, `.wav`, `.m4a`, `.aac` + `audio/*` MIME |
| `video` | `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`, `.m4v` + `video/*` MIME |
| `document` | Everything else (PDFs, Word, text, etc.) |

### MediaUnderstandingProvider Capabilities

```typescript
interface MediaUnderstandingProvider {
  transcribeAudio(req: AudioTranscriptionRequest): Promise<string>  // Deepgram, OpenAI
  describeImage(req: ImageDescriptionRequest): Promise<string>      // Claude, GPT-4V
  describeVideo(req: VideoDescriptionRequest): Promise<string>
  describeImages(req: ImagesDescriptionRequest): Promise<string[]>  // batch
}
```

Concurrency is managed via `src/media-understanding/concurrency.ts` to avoid
resource exhaustion on parallel media messages.

---

## Phase D: Outbound — Agent → Channel

### Tool Result Media Extraction

When tools return media (images, generated files), `extractMedia()` in the agent
pipeline separates media from the tool result:

```typescript
const { sanitized, media } = extractMedia(result)
// sanitized → injected into model message history (placeholder text)
// media → queued for async delivery to the originating channel
```

### ReplyPayload Construction

The agent assembles `ReplyPayload` objects containing `mediaUrl` or `mediaUrls`.
These flow through the delivery handler:

```typescript
createBlockReplyDeliveryHandler({
  onBlockReply: async (payload: ReplyPayload) => { /* send immediately */ },
  normalizeMediaPaths: async (payload) => { /* resolve media:// URIs */ }
})
```

### Delivery Queue (`src/infra/outbound/delivery-queue-storage.ts`)

```typescript
enqueueDelivery(params: QueuedDeliveryPayload, stateDir?): Promise<string>
```

- Persisted to `{stateDir}/delivery-queue/{id}.json`
- Retry with exponential backoff on failure
- `lastError` field updated on each failure
- On max retries exceeded: moved to `failed/` directory

---

## Phase E: Channel Outbound Adapters

All adapters implement `ChannelOutboundAdapter`:

```typescript
interface ChannelOutboundAdapter {
  deliveryMode: "direct" | "queued"
  textChunkLimit: number
  sendText(to, text, opts?): Promise<void>
  sendMedia(to, text, mediaUrl, opts?): Promise<void>
  sendPayload(to, payload, opts?): Promise<void>
}
```

### Per-Channel Limits

| Channel | Text Limit | Delivery Mode |
|---------|-----------|---------------|
| Discord | 2000 chars | direct |
| Telegram | 4000 chars | direct |
| Signal | 4000 chars | direct |
| Slack | 50 blocks | direct |
| iMessage | varies | direct |
| WhatsApp | varies | direct |

### Channel-Specific Media Handling

**Discord**: Media via `sendPayloadMediaSequenceOrFallback()`. Supports embeds,
components, and webhook-based thread identity. Sticker media handled separately.

**Telegram**: `sendPayloadMediaSequenceOrFallback()` routes by MIME type:
`sendPhoto`, `sendVideo`, `sendDocument`, `sendVoice`. HTML text mode with
markdown-to-Telegram conversion. Inline buttons attached to first media item only.

**Slack**: Block-Kit based (text, buttons, image blocks). Media via
`sendPayloadMediaSequenceAndFinalize()`. Thread replies with optional pinning.

**Signal**: Direct media via `sendFormattedMedia()`. Per-account media byte limits.

**iMessage / WhatsApp**: Use generic `createDirectTextMediaOutbound()` factory.

### Delivery Sequence Pattern

```typescript
sendPayloadMediaSequenceOrFallback({
  text,
  mediaUrls,
  fallbackResult,
  sendNoMedia: async () => { /* text only */ },
  send: async ({ text, mediaUrl, isFirst }) => { /* text + media */ }
})
```

First item receives text + buttons. Remaining items sent as separate messages.

---

## Per-Channel Size Limits (`src/channels/plugins/media-limits.ts`)

```typescript
resolveChannelMediaMaxBytes({
  resolveChannelLimitMb: (params) => number | undefined,
  accountId?: string
}): number | undefined
```

Resolution order (highest priority first):

```
1. Per-account limit:  cfg.channels[channel].accounts[accountId].mediaMaxMb
2. Channel default:    cfg.channels[channel].mediaMaxMb
3. Global default:     cfg.agents.defaults.mediaMaxMb
```

---

## Subagent Attachments (`src/agents/subagent-attachments.ts`)

Subagents can receive inline attachments from their parent:

```typescript
type SubagentInlineAttachment = {
  name: string
  content: string
  encoding?: "utf8" | "base64"
  mimeType?: string
}
```

`materializeSubagentAttachments()`:
1. Creates isolated attachment directory per session
2. Validates file count, total bytes, individual file size
3. Stores manifest as `.manifest.json`
4. Returns receipt with SHA256 hashes for integrity

---

## Security

| Concern | Mitigation |
|---------|-----------|
| Base64 corruption | Size estimate vs decoded length check |
| Path traversal | Reject `/`, `\`, `..`, null bytes in media IDs |
| Symlinks | `resolveMediaBufferPath` rejects symlinks |
| MIME spoofing | Magic number sniffing overrides declared Content-Type |
| SSRF on downloads | Hostname pinning, protocol restriction, `loadWebMedia()` policy |
| Cross-origin redirects | Slack auth headers stripped on redirect |
| Disk exhaustion | TTL-based cleanup, per-account size limits |
| Concurrent overload | Max concurrent download caps per channel (e.g., Slack: 3) |

---

## End-to-End Flow

```
USER SENDS MEDIA
        │
[CHANNEL ADAPTER]
        ├─ Download from CDN (auth-aware, SSRF-checked)
        ├─ Save to media store via saveMediaBuffer()
        └─ Forward to gateway

[GATEWAY]
        ├─ parseMessageWithAttachments()
        ├─ ≤ 2MB → inline ChatImageContent[] to model
        ├─ > 2MB → disk offload → media://inbound/<id>
        └─ Pass ParsedMessageWithImages to agent

[AGENT]
        ├─ normalizeAttachments() → MediaAttachment[]
        ├─ MediaUnderstandingProvider.transcribeAudio() / describeImage()
        ├─ Tools generate media → extractMedia(result)
        └─ Build ReplyPayload { mediaUrl, mediaUrls }

[DELIVERY QUEUE]
        ├─ enqueueDelivery(payload)
        ├─ Persist to disk for retry-on-failure
        └─ Send to channel adapter

[CHANNEL OUTBOUND ADAPTER]
        ├─ Load media bytes via outbound access
        ├─ Text chunking + formatting
        ├─ sendPayloadMediaSequenceOrFallback()
        └─ Deliver to user
```
