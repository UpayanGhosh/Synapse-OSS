# Polling Resilience and Session Persistence: Missing Features in Synapse-OSS

## Overview

openclaw's Telegram extension has a production-grade polling stack: persisted update offsets,
stall-watchdog timers, recoverable-vs-pre-connect error classification, grpc-style polling
restart with backoff, graceful stop races, and per-account network proxy support. Synapse-OSS
uses python-telegram-bot's built-in long-polling with no offset persistence, no stall detection,
and no classified network error handling.

---

## 1. Persisted Telegram Update Offset Store

### What openclaw has

`extensions/telegram/src/update-offset-store.ts` persists the last processed Telegram
`update_id` to disk per account:

- File path: `<stateDir>/telegram/update-offset-<accountId>.json`
- Format version `STORE_VERSION = 2` with forward/backward migration guard.
- Validates `lastUpdateId` is a safe integer `>= 0`; rejects corrupt values.
- Extracts `botId` from the token prefix (digit sequence before `:`) to detect token rotation.
- On bot-ID mismatch (token was rotated), the store is reset to prevent replaying old updates
  from the previous bot.
- `writeJsonFileAtomically()` prevents partial writes.

### What Synapse-OSS has (or lacks)

`TelegramChannel.start()` calls `start_polling(drop_pending_updates=True)`. There is no
persistent offset store. On restart, all updates from the polling gap are dropped (not replayed)
or Telegram's `drop_pending_updates=True` wipes them. If the bot crashes mid-conversation, the
recovery message from the user may be lost.

### Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| Persistent offset file | Yes (per account) | No |
| Bot-ID rotation detection | Yes | No |
| Atomic file writes | Yes | No |
| Schema version guard | Yes | No |

### Implementation notes for porting

1. Create `channels/telegram_offset_store.py` with `load_offset(account_id)` /
   `save_offset(account_id, update_id, bot_id)`.
2. On startup, load last offset and pass to PTB's `Updater` as initial offset.
3. Reset store if `bot_id` extracted from token differs from stored `bot_id`.

---

## 2. Polling Session with Stall Watchdog

### What openclaw has

`extensions/telegram/src/polling-session.ts` wraps `@grammyjs/runner`'s polling loop with:

- `POLL_STALL_THRESHOLD_MS = 90_000` — if no update is processed for 90 s, the session is
  considered stalled.
- `POLL_WATCHDOG_INTERVAL_MS = 30_000` — checked every 30 s.
- `POLL_STOP_GRACE_MS = 15_000` — `waitForGracefulStop()` races a 15 s timeout against the
  graceful stop coroutine to prevent indefinite hangs.
- Restart policy:
  ```typescript
  const TELEGRAM_POLL_RESTART_POLICY = {
    initialMs: 2000, maxMs: 30_000, factor: 1.8, jitter: 0.25,
  };
  ```
  On stall or recoverable error, the bot is restarted with exponential backoff.
- `AbortSignal` propagation for clean cancellation.

### What Synapse-OSS has (or lacks)

PTB's `start_polling()` runs the internal updater loop with no stall detection. There is no
watchdog — a stalled connection will wait indefinitely. There is no restart policy on stall;
only on crash (the outer `while attempts < self.MAX_RESTARTS` in `WhatsAppChannel` pattern,
but nothing like that for Telegram).

### Implementation notes for porting

1. Wrap PTB's `run_polling()` coroutine in a watchdog task that checks
   `time.monotonic() - last_update_at > STALL_THRESHOLD_S`.
2. On stall, cancel the polling task and restart with backoff.
3. Add `max_restart_attempts` and a circuit breaker for persistent failures.

---

## 3. Network Error Classification (Recoverable vs. Pre-Connect)

### What openclaw has

`extensions/telegram/src/network-errors.ts` classifies errors into two important sets:

**`RECOVERABLE_ERROR_CODES`** — errors that may fire AFTER Telegram received the request:
`ECONNRESET`, `ETIMEDOUT`, `ESOCKETTIMEDOUT`, `UND_ERR_CONNECT_TIMEOUT`, etc.
These are safe to retry for POLLING (can re-fetch same updates) but NOT for SEND (may duplicate).

**`PRE_CONNECT_ERROR_CODES`** — errors that fire BEFORE the request reaches Telegram:
`ECONNREFUSED`, `ENOTFOUND`, `EAI_AGAIN`, `ENETUNREACH`, `EHOSTUNREACH`.
These are safe to retry for BOTH polling and send operations.

```typescript
// network-errors.ts
const PRE_CONNECT_ERROR_CODES = new Set([
  "ECONNREFUSED", "ENOTFOUND", "EAI_AGAIN", "ENETUNREACH", "EHOSTUNREACH",
]);

export function isSafeToRetrySendError(err: unknown): boolean {
  // Only pre-connect errors — never post-connect which may have duplicated
}
export function isRecoverableTelegramNetworkError(err: unknown): boolean {
  // Broader set including post-connect for polling restart only
}
```

### What Synapse-OSS has (or lacks)

`TelegramChannel.send()` wraps `send_message()` in `except TelegramError`. All errors are
treated the same (log + return False). There is no distinction between errors safe to retry
(pre-connect) and errors that would cause duplicate messages (post-connect).

### Implementation notes for porting

1. Create `channels/network_errors.py` with `PRE_CONNECT_ERRNO` and `RECOVERABLE_ERRNO` sets.
2. Implement `is_safe_to_retry_send(exc)` checking `exc.errno` / `exc.__class__.__name__`.
3. In `send()`, only retry on `is_safe_to_retry_send()` errors.

---

## 4. Per-Account Network Proxy Configuration

### What openclaw has

`extensions/telegram/src/network-config.ts` and `proxy.ts` support per-account proxy
configuration for the Telegram bot API HTTP client. The proxy fetch transport is injected into
the grammy bot via `proxyFetch` parameter in `createTelegramBot()`:

```typescript
// polling-session.ts
type TelegramPollingSessionOpts = {
  proxyFetch: Parameters<typeof createTelegramBot>[0]["proxyFetch"];
  // ...
};
```

`extensions/telegram/src/fetch.ts` defines `TelegramTransport` — a typed HTTP transport
wrapper that can be rebuilt after stall/network recovery when marked dirty via
`createTelegramTransport?: () => TelegramTransport`.

### What Synapse-OSS has (or lacks)

`TelegramChannel` uses `ApplicationBuilder().token(self._token).build()` with no proxy support.
All HTTP traffic goes direct. Organizations behind corporate proxies cannot use the Telegram
channel.

### Implementation notes for porting

1. Add `proxy_url: str | None = None` to Telegram channel config.
2. Pass `proxy_url` to PTB's `ApplicationBuilder().proxy_url(...)` (PTB v20+).
3. Add `BOT_API_SERVER_BASE_URL` support for self-hosted Bot API servers.

---

## 5. WhatsApp Baileys-Bridge Retry Queue Integration

### What openclaw has

`extensions/whatsapp/src/reconnect.ts` exports `DEFAULT_RECONNECT_POLICY`:
```typescript
export const DEFAULT_RECONNECT_POLICY: ReconnectPolicy = {
  initialMs: 2_000, maxMs: 30_000, factor: 1.8, jitter: 0.25, maxAttempts: 12,
};
```

`WhatsAppChannel.update_connection_state()` in `whatsapp.py` (Synapse-OSS's copy) references
`self._retry_queue.flush()` when the connection recovers, but the openclaw version tracks this
through a proper `RetryQueue` object:

- Failed sends during disconnection are enqueued.
- On connection recovery (`connectionState == "connected"`), `retry_queue.flush()` drains the
  queue and retries each failed send.
- The retry queue reference is injected by `api_gateway` after channel construction.

### What Synapse-OSS has (or lacks)

`WhatsAppChannel` in Synapse-OSS has `self._retry_queue = None` as a placeholder, and
`update_connection_state()` calls `asyncio.create_task(self._retry_queue.flush())` — but
`_retry_queue` is never assigned. This is a dead code path; failed sends during WhatsApp
disconnection are permanently lost.

### Implementation notes for porting

1. Implement `RetryQueue` in `channels/retry_queue.py` with `enqueue(coro)` and
   `flush()` (drains and retries all enqueued coroutines).
2. In `api_gateway.py`, inject a `RetryQueue` into `WhatsAppChannel` after construction.
3. In `WhatsAppChannel.send()`, on `httpx.RequestError`, enqueue the send for retry rather
   than returning `False`.
4. Wire `update_connection_state()` to call `await self._retry_queue.flush()` on reconnect.

---

## 6. WhatsApp Session QR Login and Link Management

### What openclaw has

`extensions/whatsapp/src/login.ts` implements a full QR-pairing lifecycle:

- Creates a Baileys socket with `createWaSocket(showQr=True)`.
- Waits for connection via `waitForWaConnection()`.
- Handles PTB code 515 (restart-after-pairing): closes the socket, waits for credential
  flush, reopens, and verifies the session is live.
- Handles status code 401 (logged out): clears the auth cache and prompts re-login.
- Exposes `logoutWeb()` for explicit session revocation.
- Exposes `loginWeb()` as a CLI-callable async function.

The Synapse-OSS `WhatsAppChannel` manages the bridge subprocess but the QR pairing flow is
delegated to the bridge. There is no Python-side QR login CLI, no code-515 handling, and no
auth-cache clearing on 401.

### Implementation notes for porting

This is tightly coupled to the Baileys bridge architecture and is lower priority than other
items. The bridge's HTTP `/qr` and `/logout` endpoints partially cover this. The main gap is
the CLI `openclaw channels login whatsapp` command equivalent.

1. Add a `synapse_cli.py` subcommand `channels login whatsapp` that POSTs `/relink` and polls
   `/qr` displaying the QR code in the terminal.
2. Handle code-515 by waiting for creds flush before re-checking health.
