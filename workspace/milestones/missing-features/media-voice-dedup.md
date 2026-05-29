# Media Handling, Voice Messages, and Deduplication: Missing Features in Synapse-OSS

## Overview

openclaw has dedicated voice message pipelines for Telegram and Discord (OGG/Opus transcoding,
waveform generation, ffprobe/ffmpeg integration), a sticker vision pipeline, PluralKit proxy
deduplication for Discord, mention-gating with bypass logic, and ack-reaction scope policies.
Synapse-OSS has basic media URL pass-through on `MsgContext` but no voice transcoding, no sticker
handling, no deduplication, and no mention-gating with bypass.

---

## 1. Discord Voice Message Sending (OGG/Opus + Waveform)

### What openclaw has

`extensions/discord/src/voice-message.ts` implements the full Discord voice message protocol:

- **Format conversion**: Uses `ffmpeg` to transcode any audio to OGG/Opus at 48 kHz
  (`DISCORD_OPUS_SAMPLE_RATE_HZ = 48_000`).
- **Waveform generation**: Samples the audio into 256 amplitude values (`WAVEFORM_SAMPLES = 256`),
  base64-encodes the `Uint8Array`, and attaches it as the `waveform` field.
- **Duration extraction**: Uses `ffprobe` via `parseFfprobeCodecAndSampleRate()` to get exact
  duration in seconds.
- **Message flag**: Sets `DISCORD_VOICE_MESSAGE_FLAG = 1 << 13` (IS_VOICE_MESSAGE) so Discord
  renders the native voice player UI.
- **Constraint**: Voice messages cannot contain text, embeds, or other content.

```typescript
// From voice-message.ts
const DISCORD_VOICE_MESSAGE_FLAG = 1 << 13;
const WAVEFORM_SAMPLES = 256;
const DISCORD_OPUS_SAMPLE_RATE_HZ = 48_000;

export type VoiceMessageMetadata = {
  durationSecs: number;
  waveform: string; // base64 encoded
};
```

### What Synapse-OSS has (or lacks)

`DiscordChannel.send()` only sends text. There is no `send_voice_message()`, no ffmpeg
transcoding, no waveform generation, and no voice flag support. Audio would have to be sent as
a plain file attachment, losing the native voice player UI.

### Gap summary

| Capability | openclaw | Synapse-OSS |
|---|---|---|
| OGG/Opus transcoding via ffmpeg | Yes | No |
| Waveform generation (256 samples) | Yes | No |
| `IS_VOICE_MESSAGE` flag (1<<13) | Yes | No |
| Duration extraction via ffprobe | Yes | No |
| Rate-limit retry on voice send | Yes | No |

### Implementation notes for porting

1. Add `async def send_voice_message(self, chat_id, audio_path)` to `DiscordChannel`.
2. Transcode to OGG/Opus with `asyncio.create_subprocess_exec("ffmpeg", ...)`.
3. Sample waveform: read PCM frames, downsample to 256 points, normalize to `[0, 255]`,
   base64-encode.
4. POST to `POST /channels/{id}/messages` with `flags=8192`, `attachments`, `waveform`,
   `duration_secs`.

---

## 2. Telegram Voice Message Decision Logic

### What openclaw has

`extensions/telegram/src/voice.ts` implements a routing decision before sending audio:

```typescript
export function resolveTelegramVoiceDecision(opts: {
  wantsVoice: boolean;
  contentType?: string | null;
  fileName?: string | null;
}): { useVoice: boolean; reason?: string }
```

`isTelegramVoiceCompatibleAudio()` (from `openclaw/plugin-sdk/media-runtime`) checks whether
the audio is in a Telegram-compatible voice format (OGG/Opus). If not, the bot falls back to
sending as a regular audio file with a log message. This prevents silent failures when the agent
produces non-voice-compatible audio.

### What Synapse-OSS has (or lacks)

`TelegramChannel` has no audio-sending capability beyond `send()` (text only). There is no voice
decision, no format check, and no fallback path.

### Implementation notes for porting

1. Add `async def send_audio(self, chat_id, file_path, use_voice=False)` to `TelegramChannel`.
2. Check MIME type / extension: only use `send_voice()` for OGG/Opus files.
3. Fall back to `send_audio()` for non-Opus formats with a log warning.

---

## 3. Telegram Sticker Vision Pipeline

### What openclaw has

`extensions/telegram/src/sticker-cache.ts` provides a file-persisted sticker cache:

```typescript
export interface CachedSticker {
  fileId: string;
  fileUniqueId: string;
  emoji?: string;
  setName?: string;
  description: string;     // AI-generated visual description
  cachedAt: string;
  receivedFrom?: string;
}
```

When a sticker is received, `sticker-vision.runtime.ts` sends it through the media understanding
pipeline (vision model) to generate a text description. The description is cached by
`fileUniqueId` to avoid re-describing the same sticker. The description is included in the
agent's context as if the sticker were a text message.

### What Synapse-OSS has (or lacks)

There is no sticker handling. Telegram sticker messages would be received as `Update` objects
but the current handler only processes `msg.text`, so stickers are silently dropped.

### Implementation notes for porting

1. Add a `MessageHandler(filters.Sticker.ALL, self._on_sticker)` PTB handler.
2. Download sticker file via `bot.get_file(sticker.file_id)`.
3. Call vision model to describe; cache by `file_unique_id`.
4. Inject description as `[sticker: <description>]` into `MsgContext.body`.

---

## 4. PluralKit Proxy Deduplication (Discord)

### What openclaw has

`extensions/discord/src/pluralkit.ts` integrates with the PluralKit API to handle proxied
Discord messages:

```typescript
export async function fetchPluralKitMessageInfo(params: {
  messageId: string;
  config?: DiscordPluralKitConfig;
  fetcher?: typeof fetch;
}): Promise<PluralKitMessageInfo | null>
```

When PluralKit is enabled, the monitor fetches metadata for each incoming message from
`https://api.pluralkit.me/v2/messages/{id}`. If the message is a PluralKit proxy (sent by a
system member), the `original` message ID is retrieved and the webhook author is replaced with
the actual system member's identity. This prevents the bot from double-responding when PluralKit
proxies a message.

### What Synapse-OSS has (or lacks)

No PluralKit handling. Discord servers using PluralKit will trigger double-responses: once for
the original message (before PluralKit deletes it) and possibly again for the proxied message.

### Implementation notes for porting

1. Add `pluralkit_enabled: bool = False` and `pluralkit_token: str = ""` to Discord channel config.
2. In `on_message`, if PluralKit is enabled, fetch PK API and skip if `original` is set.
3. Replace `author_id` / `author_name` with PK member info.

---

## 5. Mention Gating with Command-Bypass Logic

### What openclaw has

`src/channels/mention-gating.ts` implements a two-phase mention gate:

```typescript
// Phase 1: basic mention check
export function resolveMentionGating(params: MentionGateParams): MentionGateResult
// { effectiveWasMentioned, shouldSkip }

// Phase 2: command-bypass check
export function resolveMentionGatingWithBypass(params: MentionGateWithBypassParams):
  MentionGateWithBypassResult
```

`resolveMentionGatingWithBypass` grants a bypass when ALL of these are true:
- The message is in a group
- `requireMention = true` (bot does not respond without mention)
- The user was NOT mentioned
- No `@` mentions in the message
- `allowTextCommands = true`
- The command is authorized (`commandAuthorized = true`)
- The message IS a control command (`hasControlCommand = true`)

This allows authorized users to issue control commands in groups without `@mentioning` the bot,
while still blocking unsolicited responses.

`src/channels/ack-reactions.ts` adds a second policy layer — `shouldAckReaction()` with scopes:
`"all" | "direct" | "group-all" | "group-mentions" | "off"` — controlling whether to react with
an emoji to acknowledge inbound messages (separate from sending a text reply).

### What Synapse-OSS has (or lacks)

Telegram's `_on_group_message` checks `bot_username.lower() in text.lower()`. Discord checks
`self._client.user in message.mentions`. There is no bypass logic for control commands, no
`requireMention` flag, no `implicitMention` path, and no ack-reaction scoping.

### Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| `requireMention` toggle | Yes | Hard-coded check |
| Command bypass for mention gate | Yes | No |
| Implicit mention detection | Yes | No |
| Ack-reaction scope policy | Yes | No |

### Implementation notes for porting

1. Add `require_mention: bool = True` to channel config.
2. Implement `should_dispatch(msg, require_mention, was_mentioned, has_command)` helper.
3. Add bypass: if `require_mention and not was_mentioned and has_command and authorized` → allow.
4. Add `ack_reaction_scope: str = "group-mentions"` config with `send_reaction()` call on accept.

---

## 6. Message Deduplication Cache

### What openclaw has

Several channels use in-memory deduplication caches backed by the plugin SDK's
`resolveGlobalDedupeCache()`:

- Slack (`sent-thread-cache.ts`): `Symbol.for("openclaw.slackThreadParticipation")` —
  deduplicates thread participation events.
- Telegram (`sent-message-cache.ts`): tracks sent message IDs to prevent double-delivery.
- Discord monitor: tracks received message IDs within a TTL window.

The `resolveGlobalDedupeCache(key, { ttlMs, maxSize })` primitive is shared across module
code-splitting boundaries via the `Symbol.for(...)` key, ensuring only one cache instance
exists per process regardless of how many times the module is imported.

### What Synapse-OSS has (or lacks)

There is no deduplication layer. If the same message is delivered twice (e.g. due to a webhook
retry or a race in the polling loop), the agent will process it twice.

### Implementation notes for porting

1. Create `channels/dedup_cache.py` with a `DedupeCache(ttl_s, max_size)` class using an
   `OrderedDict` with timestamp entries.
2. Add `_seen_message_ids: DedupeCache` to each channel adapter.
3. In the dispatch path, check `self._seen_message_ids.check(message_id)` before enqueuing.
