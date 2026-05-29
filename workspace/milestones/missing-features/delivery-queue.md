# Delivery Queue and Retry Infrastructure: Missing Features in Synapse-OSS

## Overview

openclaw has sophisticated per-channel delivery pipelines with rate-limit-aware retry runners,
exponential backoff for auth failures, draft-streaming with preview lanes, inbound debouncing,
and per-account typed backoff policies. Synapse-OSS has basic `try/except` error handling on
outbound `send()` calls with no retry, no backoff, and no delivery state tracking.

---

## 1. Rate-Limit-Aware Retry Runner (Discord)

### What openclaw has

`extensions/discord/src/retry.ts` implements a `RetryRunner` backed by the plugin SDK:

```typescript
// extensions/discord/src/retry.ts
export const DISCORD_RETRY_DEFAULTS = {
  attempts: 3,
  minDelayMs: 500,
  maxDelayMs: 30_000,
  jitter: 0.1,
} satisfies RetryConfig;

export function createDiscordRetryRunner(params: {
  retry?: RetryConfig;
  configRetry?: RetryConfig;
  verbose?: boolean;
}): RetryRunner {
  return createRateLimitRetryRunner({
    ...params,
    defaults: DISCORD_RETRY_DEFAULTS,
    logLabel: "discord",
    shouldRetry: (err) => err instanceof RateLimitError,
    retryAfterMs: (err) => err instanceof RateLimitError ? err.retryAfter * 1000 : undefined,
  });
}
```

The `createRateLimitRetryRunner` primitive (from `openclaw/plugin-sdk/retry-runtime`) wraps any
async operation, inspects `retry-after` headers on rate-limit errors, applies jittered backoff,
and retries up to the configured attempt count.

### What Synapse-OSS has (or lacks)

`DiscordChannel.send()` wraps `channel.send(text)` in a `try/except discord.HTTPException` that
logs and returns `False`. There is no retry, no `retry_after` header inspection, and no backoff.
A rate-limited Discord send silently drops the message.

### Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| Configurable attempt count | Yes | No |
| `Retry-After` header respect | Yes (from `RateLimitError`) | No |
| Jittered backoff | Yes | No |
| Per-account retry override | Yes | No |

### Implementation notes for porting

1. Create `channels/retry.py` with a `RetryConfig` dataclass and `retry_with_backoff()` async helper.
2. Inspect `discord.HTTPException.status == 429` and parse `Retry-After` from `response.headers`.
3. Apply per-account retry config from `channels.discord.accounts.<id>.retry`.

---

## 2. Telegram 401-Backoff and Circuit Breaker for Typing Indicators

### What openclaw has

`extensions/telegram/src/sendchataction-401-backoff.ts` implements a per-account global handler
for `sendChatAction` that tracks 401 errors across all message contexts. On each 401:

- Increments a consecutive failure counter.
- Computes exponential backoff (`initialMs: 1000, maxMs: 300_000, factor: 2, jitter: 0.1`).
- After `maxConsecutive401` (default 10) failures, sets `suspended = true`, drops all subsequent
  calls, and logs a `CRITICAL` warning that Telegram may delete the bot.

The policy resolves via `createTelegramSendChatActionHandler({ sendChatActionFn, logger })`.

### What Synapse-OSS has (or lacks)

`TelegramChannel.send_typing()` calls `send_chat_action(...)` inside `contextlib.suppress(TelegramError)`. All errors are silently swallowed with no backoff and no circuit-breaker. Repeated 401 errors on typing will fire indefinitely.

### Implementation notes for porting

1. Add `_consecutive_typing_401: int = 0` and `_typing_suspended: bool = False` to
   `TelegramChannel`.
2. In `send_typing()`, apply exponential backoff on 401 and trip the circuit after N failures.
3. Reset on any successful `sendChatAction` call.

---

## 3. Draft-Streaming Reply Preview (Telegram)

### What openclaw has

`extensions/telegram/src/draft-stream.ts` implements live streaming previews using Telegram's
`sendMessageDraft` Bot API extension. As the agent generates tokens:

- A draft message is created in the chat with an incrementing draft ID.
- The draft is updated (edited) as tokens arrive, at configurable min/max character chunk sizes
  (`resolveTelegramDraftStreamingChunking()` in `draft-chunking.ts`).
- On completion, the draft is finalized to a normal message.
- Falls back gracefully to standard send if `sendMessageDraft` is unavailable.

The `TELEGRAM_DRAFT_ID_MAX = 2_147_483_647` guard ensures IDs never overflow. Draft state is
tracked in a global store keyed by `Symbol.for("openclaw.telegramDraftStreamState")` to survive
module code-splitting.

### What Synapse-OSS has (or lacks)

Synapse-OSS has no streaming reply support. `TelegramChannel.send()` fires a single
`bot.send_message()` only after the agent response is complete. Users see no progress
indication during long agent runs.

### Gap summary

This is a large missing capability. Synapse-OSS offers no analog to:
- `draft-stream.ts` — live draft management
- `draft-chunking.ts` — chunk size/break-preference resolution
- `lane-delivery-text-deliverer.ts` — multi-lane (answer + reasoning) delivery state machine
- `lane-delivery-state.ts` — delivery snapshot tracking

### Implementation notes for porting

1. Expose an `on_partial_reply(chat_id, text, draft_id)` callback in `enqueue_fn` contract.
2. Use `python-telegram-bot`'s `bot.edit_message_text()` to update a previously sent placeholder.
3. Implement chunk size and break-preference policy matching openclaw's configurable approach.

---

## 4. Per-Channel Text Chunk Limits

### What openclaw has

`extensions/telegram/src/outbound-adapter.ts` exports:
```typescript
export const TELEGRAM_TEXT_CHUNK_LIMIT = 4000;
```

`extensions/slack/src/limits.ts` defines Slack's message body limits.
`extensions/discord/src/chunk.ts` defines Discord's 2000-char limit.

The plugin SDK exposes `resolveTextChunkLimit(cfg, channel, accountId, { fallbackLimit })` so
each channel extension enforces the correct maximum, splitting long agent replies into multiple
messages with proper boundaries (paragraph → newline → sentence preference).

### What Synapse-OSS has (or lacks)

`MsgContext.max_chars = 4000` is the only limit, hard-coded on the context dataclass. There is
no per-channel enforcement in the send path, no automatic splitting of long messages, and no
configurable break preference. Long Discord messages (>2000 chars) will produce an API error.

### Gap summary

| Channel | openclaw limit | Synapse-OSS |
|---|---|---|
| Telegram | `TELEGRAM_TEXT_CHUNK_LIMIT = 4000` (configurable) | 4000 on context only |
| Discord | 2000 chars, `chunk.ts` | No limit enforced |
| Slack | section text max 3000, `limits.ts` | No limit enforced |

### Implementation notes for porting

1. Add `MAX_CHARS: int` class attribute to each channel adapter.
2. Implement `split_for_channel(text, max_chars, break_preference)` in `channels/utils.py`.
3. Call the splitter in `send()` before dispatching to the API.

---

## 5. Inbound Message Debouncing

### What openclaw has

`src/channels/inbound-debounce-policy.ts` wraps `createChannelInboundDebouncer()` which
combines:

- `shouldDebounceTextInbound()` — skips debounce for media messages and control commands.
- `resolveInboundDebounceMs()` — reads per-channel debounce window from config
  (`cfg.channels.<channel>.inboundDebounceMs`).
- `createInboundDebouncer<T>()` — collects rapid-fire messages within the window and delivers
  only the last one (or accumulated batch).

This prevents the agent from triggering on every keystroke when a user sends several short
messages in quick succession.

### What Synapse-OSS has (or lacks)

All channels enqueue messages immediately on receipt with no debounce. Rapid-fire messages
produce rapid-fire agent invocations.

### Implementation notes for porting

1. Add `inbound_debounce_ms: int = 0` to channel config.
2. Implement a `debounce_inbound(chat_id, msg, window_ms)` async wrapper around `enqueue_fn`.
3. Skip debounce for media payloads and command-prefixed messages.

---

## 6. Typing Indicator Keepalive Loop with TTL Safety

### What openclaw has

`src/channels/typing.ts` — `createTypingCallbacks()` provides:

- A `TypingStartGuard` that tracks consecutive start failures and trips a circuit breaker after
  `maxConsecutiveFailures` (default 2).
- A `keepaliveLoop` that re-fires `sendChatAction("typing")` every `keepaliveIntervalMs` (default
  3000 ms) while the agent is running.
- A TTL safety timer (`maxDurationMs`, default 60 s) that auto-stops the typing indicator if the
  agent stalls without calling `stop`.

### What Synapse-OSS has (or lacks)

- Telegram: `send_typing()` fires once per message. No keepalive. For agent runs > 5 seconds the
  typing indicator disappears.
- Discord: `send_typing()` is a no-op. Discord typing is managed inline via
  `async with message.channel.typing()` which auto-stops when the context exits.
- Slack: `send_typing()` is a no-op.

No channel has a circuit breaker for typing failures.

### Implementation notes for porting

1. Add `async def start_typing_keepalive(self, chat_id: str, interval_s: float = 3.0)`.
2. Run as `asyncio.create_task()`, cancelling on reply completion.
3. Add `_typing_failures: int = 0` and trip the breaker after N consecutive failures.
