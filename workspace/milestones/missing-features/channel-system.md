# Channel System: Missing Features in Synapse-OSS

## Overview

openclaw has a mature, typed channel abstraction backed by a plugin registry and a strict contract
surface. Synapse-OSS has a working but far simpler channel system — single-file adapters with a
thin `BaseChannel` ABC and no concept of plugin-level contract isolation, account multiplexing,
or channel metadata catalogues.

---

## 1. Channel ID Catalogue and Ordering

### What openclaw has

`src/channels/ids.ts` exports a stable ordered tuple of all built-in channel IDs and a
discriminated union type:

```typescript
export const CHAT_CHANNEL_ORDER = [
  "telegram", "whatsapp", "discord", "irc", "googlechat",
  "slack", "signal", "imessage", "line",
] as const;
export type ChatChannelId = (typeof CHAT_CHANNEL_ORDER)[number];
export const CHANNEL_IDS = [...CHAT_CHANNEL_ORDER] as const;
```

`src/channels/chat-meta.ts` provides `getChatChannelMeta()`, `listChatChannels()`,
`listChatChannelAliases()`, and `normalizeChatChannelId()` — all of which are safe to call in
shared/sandbox code without importing any channel runtime.

### What Synapse-OSS has (or lacks)

Synapse-OSS has no central channel catalogue. The `ChannelRegistry` only knows about channels
after `register()` is called at startup. There is no typed union, no ordering guarantee, no alias
resolution, and no metadata per channel type. `registry.list_ids()` returns whatever was
registered in whatever order.

### Gap summary

| Capability | openclaw | Synapse-OSS |
|---|---|---|
| Typed channel ID union | `ChatChannelId` in `ids.ts` | No |
| Canonical ordering | `CHAT_CHANNEL_ORDER` | No |
| Alias resolution | `normalizeChatChannelId()` | No |
| Markdown-capable flag per channel | `ChannelMeta.markdownCapable` | No |

### Implementation notes for porting

1. Create `channels/ids.py` with a `CHANNEL_ORDER` tuple and `ChannelId = Literal[...]` type.
2. Extend `BaseChannel` with a `markdown_capable: bool = False` class attribute.
3. Move alias resolution into `ChannelRegistry.normalize_channel_id(raw)`.

---

## 2. Plugin-Driven Channel Registry with Alias and Metadata Lookup

### What openclaw has

`src/channels/registry.ts` wraps the live plugin registry and provides
`normalizeAnyChannelId(raw)` — which resolves both built-in IDs and registered plugin IDs
(including their aliases) without eagerly loading channel implementations. This is a deliberate
lazy-loading boundary:

```typescript
// src/channels/registry.ts
export function normalizeAnyChannelId(raw?: string | null): ChannelId | null { ... }
```

Channel plugins declare `meta.aliases` and `meta.markdownCapable` in their manifest; the registry
exposes them via `listChatChannels()` / `getChatChannelMeta()` without importing channel runtime
code.

### What Synapse-OSS has (or lacks)

`ChannelRegistry` (`sci_fi_dashboard/channels/registry.py`) supports only registration,
`get(id)`, `list_ids()`, `start_all()`, and `stop_all()`. There is no alias lookup, no per-channel
metadata, and no lazy-load boundary — importing a channel file immediately runs its top-level code
(e.g. the Windows ProactorEventLoop policy set at module import in `whatsapp.py`).

### Implementation notes for porting

1. Add `aliases: list[str] = []` and `markdown_capable: bool = False` to `BaseChannel`.
2. Extend `ChannelRegistry.get()` to try aliases in addition to `channel_id`.
3. Add `ChannelRegistry.list_meta()` returning lightweight dicts without importing adapters.

---

## 3. Multi-Account Channel Support

### What openclaw has

Every channel extension supports multiple accounts, each with its own bot token, config, and
session namespace. Resolution is done through helpers like:

- `extensions/telegram/src/accounts.ts` — `resolveTelegramAccount({ cfg, accountId })`
- `extensions/discord/src/accounts.ts` — `resolveDiscordAccount({ cfg, accountId })`
- `extensions/slack/src/accounts.ts` — `resolveDefaultSlackAccountId(cfg)`

Account IDs flow through session keys, allowlists, outbound adapters, approval configs, and
thread-binding stores. The routing layer (`src/routing/session-key.ts`) includes account ID as a
dimension in the session key:

```typescript
// e.g. agent:main:telegram:default:group:123456
buildAgentPeerSessionKey({ agentId, channel, accountId, peerKind, peerId })
```

### What Synapse-OSS has (or lacks)

Each channel adapter is a single-account singleton. `TelegramChannel(token=..., enqueue_fn=...)`,
`DiscordChannel(token=...)`, and `SlackChannel(bot_token=..., app_token=...)` each hold exactly
one set of credentials. Running two Telegram bots requires two separate process instances.

### Gap summary

| Capability | openclaw | Synapse-OSS |
|---|---|---|
| Per-channel multi-account config | Yes (all channels) | No |
| Account-scoped session keys | Yes | No |
| Account-scoped allowlists | Yes | No |
| Account-scoped thread bindings | Yes (Telegram) | No |

### Implementation notes for porting

1. Change `__init__` signatures to accept `account_id: str = "default"`.
2. Move token resolution to `config.py` pattern `channels.<provider>.accounts.<id>.token`.
3. Include `account_id` as a dimension in `MsgContext.session_key_str`.

---

## 4. Channel-to-Agent Binding Resolution (Routing Layer)

### What openclaw has

`src/routing/resolve-route.ts` implements a multi-tier, priority-ordered binding evaluation
engine. When a message arrives on channel X from peer Y, the routing layer resolves the correct
agent through a waterfall:

1. `binding.peer` — direct peer ID match
2. `binding.peer.parent` — parent peer (thread parent inheritance)
3. `binding.peer.wildcard` — wildcard-kind match
4. `binding.guild+roles` — Discord guild + role-based routing
5. `binding.guild` — Discord guild match
6. `binding.team` — Slack team match
7. `binding.account` — account-scoped fallback
8. `binding.channel` — channel-level wildcard
9. `default` — global default agent

All tiers are indexed at config-load time into `EvaluatedBindingsIndex` maps for O(1) lookup.
The resolved route includes `sessionKey`, `mainSessionKey`, `matchedBy`, and `lastRoutePolicy`.

### What Synapse-OSS has (or lacks)

`MsgContext.session_key(channel, chat_type, target_id)` builds a deterministic key string but
there is no binding layer. All messages go to one implicit "agent" (the `MessageWorker`). There
is no concept of routing different peers or guilds to different agent instances.

### Gap summary

Synapse-OSS has no equivalent to the 8-tier binding resolver, no multi-agent routing, no
guild/role-based dispatch, and no session key derived from agent identity.

### Implementation notes for porting

1. Create `routing/bindings.py` with a `Binding` dataclass `(match, agent_id)`.
2. Implement a `resolve_agent_route(channel, account_id, peer_kind, peer_id, ...)` function
   returning `ResolvedRoute(agent_id, session_key)`.
3. Bind the registry to a configurable binding list (JSON/YAML).

---

## 5. Identity Links and DM Scope Collapsing

### What openclaw has

`src/routing/session-key.ts` — `buildAgentPeerSessionKey()` supports a `dmScope` parameter:

- `"main"` — all DMs collapse to one session key regardless of sender
- `"per-peer"` — separate session per peer ID
- `"per-channel-peer"` — separate session per channel + peer ID
- `"per-account-channel-peer"` — separate session per account + channel + peer ID

It also supports `identityLinks: Record<string, string[]>` which maps canonical peer names to
sets of alternate IDs (e.g. linking a Telegram ID to a Discord ID). When building a session key,
the identity-link table is consulted to normalize the peer ID to its canonical form, producing a
shared session across channels.

### What Synapse-OSS has (or lacks)

`MsgContext.session_key()` is a static method that always produces `<channel>:<chat_type>:<id>`.
There is no DM scope concept and no identity linking.

### Implementation notes for porting

1. Add `dm_scope: Literal["main", "per-peer", "per-channel-peer"] = "main"` to `MsgContext`.
2. Add `identity_links: dict[str, list[str]] = {}` to config.
3. Resolve canonical peer ID before constructing session key.
