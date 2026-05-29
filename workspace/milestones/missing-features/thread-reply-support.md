# Thread and Reply-To Support: Missing Features in Synapse-OSS

## Overview

openclaw has first-class thread support across all channels — session-scoped thread bindings,
automatic subagent spawning in Discord/Matrix threads, Slack thread context resolution, Telegram
forum topic routing, and thread ID propagation through the full session key and outbound adapter
pipeline. Synapse-OSS has partial thread awareness in context fields but no routing, binding, or
lifecycle management for threads.

---

## 1. Thread Binding Manager (Telegram)

### What openclaw has

`extensions/telegram/src/thread-bindings.ts` implements a full per-account, file-persisted
binding store:

```typescript
// Key types
type TelegramThreadBindingRecord = {
  accountId: string;
  conversationId: string;       // Telegram thread/topic ID
  targetKind: "subagent"|"acp";
  targetSessionKey: string;
  idleTimeoutMs?: number;       // default: 24 hours
  maxAgeMs?: number;            // 0 = unlimited
  boundAt: number;
  lastActivityAt: number;
  label?: string;
  metadata?: Record<string, unknown>;
};
```

Operations: `getByConversationId()`, `listBySessionKey()`, `touchConversation()`,
`unbindConversation()`, `unbindBySessionKey()`.

A sweep interval (`THREAD_BINDINGS_SWEEP_INTERVAL_MS = 60_000`) periodically expires bindings
past their `idleTimeoutMs` or `maxAgeMs`. Mutations are written to disk atomically via
`writeJsonFileAtomically()`. State is shared across bundled module chunks via a global
`Symbol.for("openclaw.telegramThreadBindings")` store.

### What Synapse-OSS has (or lacks)

`MsgContext` has `message_thread_id: str = ""` and `thread_label: str = ""` as context fields
but there is no binding manager, no persistence, no lifecycle policy (idle timeout / max age),
and no dispatch to sub-sessions. Thread IDs are captured but ignored after normalization.

### Gap summary

| Capability | openclaw | Synapse-OSS |
|---|---|---|
| Thread-to-session binding store | Yes (file-persisted) | No |
| Idle timeout expiry | Yes | No |
| Max age expiry | Yes | No |
| Touch on activity | Yes | No |
| Atomic persist | Yes | No |
| Global state sharing across chunks | Yes | No |

### Implementation notes for porting

1. Create `channels/thread_bindings.py` with `ThreadBindingStore` (in-memory with optional file
   persistence).
2. Add `bind_thread(conversation_id, session_key, idle_timeout_s, max_age_s)` and
   `get_binding(conversation_id)`.
3. Run a sweep coroutine with `asyncio.create_task(sweep_loop())`.

---

## 2. Thread Binding Policy — Automatic Subagent Spawn in Discord/Matrix

### What openclaw has

`src/channels/thread-bindings-policy.ts` defines which channels support automatic subagent
spawn from thread bindings:

```typescript
// src/channels/thread-bindings-policy.ts
export function supportsAutomaticThreadBindingSpawn(channel: string): boolean {
  return channel === "discord" || channel === "matrix";
}

export function requiresNativeThreadContextForThreadHere(channel: string): boolean {
  return channel !== "telegram" && channel !== "feishu" && channel !== "line";
}

export type ThreadBindingSpawnPolicy = {
  channel: string; accountId: string;
  enabled: boolean; spawnEnabled: boolean;
};
```

For Discord and Matrix, when a message arrives in a thread with no existing binding, the policy
creates a new subagent session scoped to that thread. This is how openclaw can run concurrent
agent conversations in separate Discord threads.

### What Synapse-OSS has (or lacks)

There is no concept of thread-scoped sessions and no auto-spawn capability. All messages in
any thread go to the global message worker.

### Implementation notes for porting

1. Add `supports_thread_spawn: bool = False` class attribute to channel adapters.
2. Set to `True` for Discord and Matrix.
3. In `enqueue_fn`, check `msg.message_thread_id` — if non-empty and no binding exists, create
   a new session scoped to that thread ID.

---

## 3. Slack Thread Context and Auto-Participation

### What openclaw has

`extensions/slack/src/threading.ts` — `resolveSlackThreadContext()` disambiguates:

```typescript
// Distinguishes genuine thread replies from bot-generated thread_ts (e.g. typing)
export function resolveSlackThreadContext(params: {
  message: SlackMessageEvent|SlackAppMentionEvent;
  replyToMode: ReplyToMode;
}): SlackThreadContext {
  const isThreadReply = hasThreadTs && (incomingThreadTs !== messageTs || ...);
  const messageThreadId = isThreadReply
    ? incomingThreadTs
    : (replyToMode === "all" ? messageTs : undefined);
  return { incomingThreadTs, messageTs, isThreadReply, replyToId, messageThreadId };
}
```

`resolveSlackThreadTargets()` returns `replyThreadTs` and `statusThreadTs` separately —
status (typing) indicators always go to the same thread as the reply, even when `replyToMode`
is `"all"`.

`extensions/slack/src/sent-thread-cache.ts` records threads the bot has participated in
(TTL 24 h, max 5000 entries) so the bot auto-responds in threads without requiring `@mention`
on follow-up messages.

### What Synapse-OSS has (or lacks)

`SlackChannel._dispatch()` passes the raw `event` dict. There is no thread context resolution,
no `replyToMode` support, and no thread participation cache. The bot must be `@mentioned` every
time in every message.

### Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| Thread vs. new message disambiguation | Yes | No |
| `replyToMode` (thread/all/direct) | Yes | No |
| Thread participation cache | Yes (24 h TTL) | No |
| Status indicator thread routing | Yes | No |

### Implementation notes for porting

1. Add `reply_to_mode: Literal["thread","all","direct"] = "thread"` to Slack config.
2. Implement `resolve_slack_thread_context(event, reply_to_mode)` returning
   `(reply_thread_ts, is_thread_reply)`.
3. Add `SlackThreadCache` (dict with TTL) tracking `(account_id, channel_id, thread_ts)`.

---

## 4. Telegram Forum Topic Routing

### What openclaw has

`extensions/telegram/src/forum-service-message.ts` handles Telegram forum channel service
messages that carry topic-creation events. The session key resolution for Telegram includes a
`messageThreadId` dimension for forum topics:

```typescript
// extensions/telegram/src/bot-message-context.ts (referenced)
// extensions/telegram/src/bot-message-context.dm-topic-threadid.test.ts
```

`extensions/telegram/src/create-telegram-bot.channel-post-media.test.ts` covers media
handling in forum topics.

The thread ID is normalized, validated, and used to route forum topic messages to separate
sessions, allowing different agents to handle different forum topics.

### What Synapse-OSS has (or lacks)

`TelegramChannel._dispatch()` does not extract `message_thread_id` from PTB `Update` objects.
Forum topic messages are routed identically to regular group messages — to the single global
session.

### Implementation notes for porting

1. Extract `msg.message_thread_id` in `_dispatch()` and populate `MsgContext.message_thread_id`.
2. Include `message_thread_id` in session key construction when non-empty.
3. Handle `forum_topic_created` service messages and create initial binding.

---

## 5. Discord Thread Creation and Sent-Message Cache

### What openclaw has

`extensions/discord/src/send.ts` exports `createThreadDiscord()` and `listThreadsDiscord()`.
`extensions/discord/src/send.creates-thread.test.ts` covers rate-limit retry during thread
creation.

The Discord `monitor.ts` uses `outbound-session-route.ts` to determine whether the reply should
go to:
- The originating channel (direct reply mode)
- An existing thread (thread participation mode)
- A newly created thread (auto-spawn mode for new conversations)

`extensions/discord/src/sent-thread-cache.ts` (similar to Slack) tracks threads the bot has
created or replied in, with TTL-based expiry.

### What Synapse-OSS has (or lacks)

`DiscordChannel.send()` sends to the literal `chat_id` string. There is no thread creation,
no thread routing logic, and no participation cache. The `reply_callable` stored in `raw` from
`on_message` is never used.

### Implementation notes for porting

1. Expose `create_thread(channel_id, name)` on `DiscordChannel` using `discord.py`'s
   `TextChannel.create_thread()`.
2. Track thread participation in `DiscordThreadCache` (TTL 24 h).
3. In `send()`, route to thread if `chat_id` is a thread ID (determined by channel type).

---

## 6. Thread Session Key Resolution (Core)

### What openclaw has

`src/routing/session-key.ts` — `resolveThreadSessionKeys()`:

```typescript
export function resolveThreadSessionKeys(params: {
  baseSessionKey: string;
  threadId?: string | null;
  parentSessionKey?: string;
  useSuffix?: boolean;
  normalizeThreadId?: (id: string) => string;
}): { sessionKey: string; parentSessionKey?: string } {
  // Returns e.g. "agent:main:discord:group:123:thread:456"
}
```

Thread session keys include a `:thread:<id>` suffix (when `useSuffix = true`) so thread
conversations are persisted and routed independently of their parent channel session.
`parentSessionKey` enables binding inheritance: a thread can inherit the agent binding of its
parent group/channel.

### What Synapse-OSS has (or lacks)

`MsgContext.session_key()` produces `<channel>:<chat_type>:<target_id>`. There is no
`:thread:` suffix and no parent session key concept. All messages in a channel (including
thread replies) share the same session.

### Implementation notes for porting

1. Extend `MsgContext.session_key_str` to append `":thread:<message_thread_id>"` when
   `message_thread_id` is non-empty.
2. Add `parent_session_key: str = ""` to `MsgContext` for binding inheritance.
3. Update routing to try parent session key binding before falling back to channel default.
