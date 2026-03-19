# MULTIUSER_MEMORY_BLUEPRINT.md

> **Purpose**: AI-actionable reverse-engineering document covering OpenClaw's multi-user session
> isolation, three-layer memory architecture, compaction pipeline, and per-agent personality system.
> Every claim is verified against actual source code with exact file paths and line numbers.

---

## Table of Contents

- [Section 0: Architecture Overview](#section-0-architecture-overview)
- [Section 1: Session Key Generation & Identity Routing](#section-1-session-key-generation--identity-routing)
- [Section 2: Session Lifecycle & Flat Session Store](#section-2-session-lifecycle--flat-session-store)
- [Section 3: Three-Layer Memory Architecture](#section-3-three-layer-memory-architecture)
- [Section 4: Compaction & Memory Flush Pipeline](#section-4-compaction--memory-flush-pipeline)
- [Section 5: Personality & System Prompt Assembly](#section-5-personality--system-prompt-assembly)
- [Section 6: Multi-Agent Routing & Subagent Lifecycle](#section-6-multi-agent-routing--subagent-lifecycle)
- [Section 7: Context Window, Security & Configuration Reference](#section-7-context-window-security--configuration-reference)
- [Section 8: Build-It-Yourself — Multi-User Memory System](#section-8-build-it-yourself--multi-user-memory-system)

---

## Section 0: Architecture Overview

### The "One Agent Brain, Many Conversation Threads" Model

OpenClaw runs a **single shared agent process** that simultaneously handles conversations from many
users across many channels. There is no per-user process fork. Isolation is achieved entirely through
**session keys** — every inbound message is assigned a deterministic string key before any processing
starts. The key determines which JSONL transcript file to read/write, which context window to load,
and which compaction budget to respect.

```
WhatsApp user A  ──┐
WhatsApp user B  ──┤                          ┌─────────────────────────────────────┐
Telegram user C  ──┤                          │         Gateway WebSocket           │
Slack #channel   ──┤──► Channel adapters ──►  │  ws://127.0.0.1:18789              │
Discord guild    ──┤                          └──────────────┬──────────────────────┘
Cron triggers    ──┘                                         │
                                                             ▼
                                              ┌──────────────────────────────────────┐
                                              │        Session Key Router             │
                                              │                                       │
                                              │  buildAgentPeerSessionKey()           │
                                              │  resolveLinkedPeerId()                │
                                              │  resolveThreadSessionKeys()           │
                                              └──────────────┬───────────────────────┘
                                                             │  session key string
                                                             ▼
                                              ┌──────────────────────────────────────┐
                                              │       Per-Session FIFO Queue          │
                                              │  SessionActorQueue (KeyedAsyncQueue)  │
                                              │  Key = ACP session handle key         │
                                              └──────────────┬───────────────────────┘
                                                             │
                                         ┌───────────────────┼───────────────────────┐
                                         ▼                   ▼                       ▼
                            ┌────────────────┐   ┌─────────────────┐   ┌───────────────────┐
                            │  Session A      │   │  Session B       │   │  Session C         │
                            │  JSONL file     │   │  JSONL file      │   │  JSONL file        │
                            │  agent:main:... │   │  agent:main:...  │   │  agent:cron:...    │
                            └────────┬───────┘   └────────┬────────┘   └─────────┬──────────┘
                                     │                     │                       │
                                     └──────────┬──────────┘                       │
                                                ▼                                   ▼
                                  ┌─────────────────────────┐       ┌──────────────────────────┐
                                  │  Shared Agent Process    │       │  Shared Agent Process     │
                                  │  (pi-embedded-runner)    │       │  (pi-embedded-runner)     │
                                  └─────────────┬───────────┘       └──────────────┬────────────┘
                                                │                                   │
                                                ▼                                   ▼
                                  ┌─────────────────────────┐       ┌──────────────────────────┐
                                  │  Three-Layer Memory      │       │  Three-Layer Memory       │
                                  │  Layer 1: Workspace .md  │       │  (same workspace dir)     │
                                  │  Layer 2: SQLite vector  │       │                           │
                                  │  Layer 3: JSONL index    │       │                           │
                                  └─────────────────────────┘       └──────────────────────────┘
                                                │
                                                ▼
                                  ┌─────────────────────────┐
                                  │  LLM Provider            │
                                  │  (Anthropic / Gemini /   │
                                  │   Ollama / OpenRouter)   │
                                  └─────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|---|---|
| File-based memory (Markdown + JSONL) | No external database dependency; content readable/editable by humans and tools; portable across machines |
| Flat `sessions.json` store | Single JSON file per agent is trivially atomic via temp-rename; simpler than a database for a personal assistant workload |
| Markdown as persistence format for personality | `SOUL.md`, `USER.md`, `MEMORY.md` etc. are editable without code. Agent reads them as bootstrap context on every run. |
| Session isolation vs shared memory | Each session key maps to an isolated JSONL transcript (private) but all sessions share the same workspace markdown files and SQLite vector store (shared long-term memory) |
| No per-user process | One Node.js process handles all sessions; FIFO `SessionActorQueue` prevents concurrent writes to the same session key |

---

## Section 1: Session Key Generation & Identity Routing

**Primary source**: `src/routing/session-key.ts`
**Secondary source**: `src/sessions/session-key-utils.ts`

### 1.1 Conceptual Model

Every message entering OpenClaw is reduced to a normalized, colon-delimited string called a
**session key** before any processing occurs. The session key determines:

1. Which JSONL transcript file to load (conversation history)
2. Which entry in `sessions.json` to read/update
3. Which compaction budget and context window to apply
4. Which agent (via `agent:<agentId>` prefix) should handle the request

### 1.2 `buildAgentMainSessionKey` — Default Key

**Location**: `src/routing/session-key.ts:118-125`

```typescript
function buildAgentMainSessionKey(params: {
  agentId: string;
  mainKey?: string | undefined;
}): string
// Returns: "agent:<agentId>:<mainKey>"
// mainKey defaults to "main" (DEFAULT_MAIN_KEY)
// Example: "agent:main:main"
```

Used when `dmScope === "main"` (default) — ALL direct messages share one session regardless of
who sent them.

### 1.3 `buildAgentPeerSessionKey` — The Central Key Builder

**Location**: `src/routing/session-key.ts:127-174`

```typescript
function buildAgentPeerSessionKey(params: {
  agentId: string;
  mainKey?: string | undefined;
  channel: string;
  accountId?: string | null;
  peerKind?: ChatType | null;    // defaults to "direct"
  peerId?: string | null;
  identityLinks?: Record<string, string[]>;
  dmScope?: "main" | "per-peer" | "per-channel-peer" | "per-account-channel-peer";
}): string
```

**Logic flow**:

1. If `peerKind !== "direct"` (groups/channels): always produces `agent:<agentId>:<channel>:<peerKind>:<peerId>`.
2. If `peerKind === "direct"` (DMs): the `dmScope` parameter selects one of four key shapes.

#### The Four `dmScope` Variants

| `dmScope` | Key Template | Example (WhatsApp) | Notes |
|---|---|---|---|
| `"main"` *(default)* | `agent:<agentId>:<mainKey>` | `agent:main:main` | All DMs share one session; `identityLinks` ignored |
| `"per-peer"` | `agent:<agentId>:direct:<peerId>` | `agent:main:direct:919876543210` | One session per phone number across all channels |
| `"per-channel-peer"` | `agent:<agentId>:<channel>:direct:<peerId>` | `agent:main:whatsapp:direct:919876543210` | One session per channel+user |
| `"per-account-channel-peer"` | `agent:<agentId>:<channel>:<accountId>:direct:<peerId>` | `agent:main:whatsapp:default:direct:919876543210` | Most isolated; separate session per bot account |

**Concrete examples across channels**:

| Scenario | Session Key |
|---|---|
| WhatsApp DM from +91-98765-43210, `dmScope=per-channel-peer` | `agent:main:whatsapp:direct:919876543210` |
| Telegram user 123456789 in group, `dmScope=per-channel-peer` | `agent:main:telegram:group:987654321` |
| Telegram user in topic thread 42 | `agent:main:telegram:group:987654321:thread:42` |
| Slack user U01ABCDEF in thread `1620000000.000100` | `agent:main:slack:direct:u01abcdef:thread:1620000000.000100` |
| Discord guild 888 channel 999 | `agent:main:discord:channel:999` |
| Subagent spawned from main | `agent:main:subagent:<runId>` |
| Cron job named "daily" | `agent:main:cron:daily:session:<id>` |

**Note**: `peerId` is always lowercased. `channel` is always lowercased and trimmed. Absent values
fall back to `"unknown"`.

### 1.4 `resolveLinkedPeerId` — Identity Merging

**Location**: `src/routing/session-key.ts:176-220`

This function merges cross-channel identities so a single user known by different IDs on different
platforms maps to the same session key.

**Algorithm (step by step)**:

1. If `identityLinks` is absent or empty, return `null` immediately (no substitution).
2. If `dmScope === "main"`, `resolveLinkedPeerId` is never called (optimization at call site, line 143).
3. Build a candidate `Set<string>` containing:
   - The raw `peerId` (lowercased), e.g. `"919876543210"`
   - A channel-scoped candidate `"<channel>:<peerId>"`, e.g. `"whatsapp:919876543210"`
4. Iterate `Object.entries(identityLinks)`. `identityLinks` shape:
   ```json
   {
     "alice": ["919876543210", "telegram:123456789"],
     "bob":   ["slack:U01ABCDEF"]
   }
   ```
5. For each `[canonical, ids]` pair, normalize each `id` in `ids` to lowercase.
6. If any normalized `id` is in the candidate set, return `canonical` (e.g. `"alice"`).
7. If no match found, return `null` and the original `peerId` is used unchanged.

**Effect**: When matched, `peerId` in the session key is replaced by the canonical name.
Example: WhatsApp `919876543210` and Telegram `123456789` both produce `agent:main:whatsapp:direct:alice`
and `agent:main:telegram:direct:alice` respectively (with `per-channel-peer` scope).

**Gotcha**: `identityLinks` only has effect when `dmScope !== "main"`. With the default `main`
scope, all DMs already share one session regardless of who sent them — identity links would be
meaningless.

### 1.5 `resolveThreadSessionKeys` — Thread Suffix Logic

**Location**: `src/routing/session-key.ts:234-253`

```typescript
function resolveThreadSessionKeys(params: {
  baseSessionKey: string;
  threadId?: string | null;
  parentSessionKey?: string;
  useSuffix?: boolean;                            // default: true
  normalizeThreadId?: (threadId: string) => string; // default: toLowerCase
}): { sessionKey: string; parentSessionKey?: string }
```

**Logic**:
- If `threadId` is empty/absent: returns `baseSessionKey` unchanged, `parentSessionKey` undefined.
- If `threadId` is present and `useSuffix === true` (default): appends `:thread:<normalizedThreadId>` to `baseSessionKey`.
- `normalizeThreadId` defaults to `toLowerCase`. Telegram passes a custom normalizer for numeric topic IDs.

**Examples**:
- Telegram topic 42 on group 987654321: `agent:main:telegram:group:987654321:thread:42`
- Slack thread `1620000000.000100`: `agent:main:slack:channel:C01ABCDEF:thread:1620000000.000100`

**Reverse (parent lookup)**: `resolveThreadParentSessionKey()` in `src/sessions/session-key-utils.ts:112-132`
finds the last occurrence of `:thread:` or `:topic:` and strips everything from that index onward.

### 1.6 Group Session Keys

**Location**: `src/routing/session-key.ts:171-173` (inside `buildAgentPeerSessionKey`)

When `peerKind` is `"group"` or `"channel"`, the key is always:
```
agent:<agentId>:<channel>:<peerKind>:<peerId>
```

Examples:
- WhatsApp group `120363000000000@g.us` → `agent:main:whatsapp:group:120363000000000-g-us` (sanitized)
- Telegram channel → `agent:main:telegram:channel:<channelId>`
- Discord text channel → `agent:main:discord:channel:<channelId>`

`buildGroupHistoryKey()` (`src/routing/session-key.ts:222-232`) produces a separate key used for
group history tracking (not session isolation): `<channel>:<accountId>:<peerKind>:<peerId>`.

### 1.7 `getSubagentDepth` — Nesting Detection

**Location**: `src/sessions/session-key-utils.ts:89-95`

```typescript
function getSubagentDepth(sessionKey: string | undefined | null): number {
  // Counts occurrences of ":subagent:" in the lowercase key
  return raw.split(":subagent:").length - 1;
}
```

Examples:
- `"agent:main:main"` → depth `0` (no subagents)
- `"agent:main:subagent:abc123"` → depth `1`
- `"agent:main:subagent:abc123:subagent:def456"` → depth `2`

Used to prevent runaway subagent spawning.

### 1.8 `parseAgentSessionKey` — Parsing a Key

**Location**: `src/sessions/session-key-utils.ts:12-32`

```typescript
function parseAgentSessionKey(
  sessionKey: string | undefined | null,
): ParsedAgentSessionKey | null

type ParsedAgentSessionKey = {
  agentId: string;  // e.g. "main"
  rest: string;     // everything after "agent:<agentId>:"
}
```

**Algorithm**:
1. Trim and lowercase the raw input.
2. Split by `":"`, filter empty parts.
3. Require at least 3 parts; first part must be `"agent"`.
4. `agentId` = `parts[1]`, `rest` = `parts.slice(2).join(":")`.
5. Returns `null` if any validation fails.

Example: `parseAgentSessionKey("agent:main:whatsapp:direct:919876543210")`
→ `{ agentId: "main", rest: "whatsapp:direct:919876543210" }`

### 1.9 Key Type Predicates

| Function | Location | Pattern matched |
|---|---|---|
| `isSubagentSessionKey()` | `session-key-utils.ts:77-87` | `rest` starts with `"subagent:"` |
| `isCronSessionKey()` | `session-key-utils.ts:69-75` | `rest` starts with `"cron:"` |
| `isCronRunSessionKey()` | `session-key-utils.ts:61-67` | `rest` matches `/^cron:[^:]+:run:[^:]+$/` |
| `isAcpSessionKey()` | `session-key-utils.ts:97-108` | `rest` starts with `"acp:"` |

### 1.10 Agent ID Normalization

**Location**: `src/routing/session-key.ts:89-107`

```typescript
function normalizeAgentId(value: string | undefined | null): string
// Rules:
// 1. Trim, lowercase
// 2. If matches /^[a-z0-9][a-z0-9_-]{0,63}$/i → return as-is (lowercased)
// 3. Otherwise: collapse invalid chars to "-", strip leading/trailing dashes, slice to 64 chars
// 4. Empty result falls back to DEFAULT_AGENT_ID = "main"
```

`DEFAULT_AGENT_ID = "main"` (line 19).
`DEFAULT_ACCOUNT_ID = "default"` (`src/routing/account-id.ts:3`).
Account IDs use the same canonicalization logic with an LRU cache of 512 entries.

### 1.11 JSONL Transcript Line Schema

Each line in a `<sessionId>.jsonl` transcript is an `AgentMessage` from `@mariozechner/pi-agent-core`.
The set of roles used in practice:

| `role` | When written | Key fields |
|---|---|---|
| `"user"` | On inbound user message | `content: string \| ContentBlock[]`, `timestamp: number` |
| `"assistant"` | On LLM response | `content: string \| ContentBlock[]`, `timestamp: number` |
| `"toolUse"` / `"toolCall"` | When agent invokes a tool | `id: string`, `name: string`, `input: object` |
| `"toolResult"` | Tool execution result returned to LLM | `toolUseId: string`, `content: string \| ContentBlock[]` |
| `"system"` | Session header written at creation | `content: string` (session ID, cwd, model) |

The JSONL file is **append-only during a run**. Compaction rewrites the file from a designated
`firstKeptEntryId` forward, prepending a synthetic summary message.

---

## Section 2: Session Lifecycle & Flat Session Store

**Primary sources**:
- `src/config/sessions/store.ts`
- `src/config/sessions/types.ts`
- `src/config/sessions/paths.ts`
- `src/config/sessions/store-maintenance.ts`

### 2.1 Directory Layout

```
~/.openclaw/
├── workspace/                           ← DEFAULT workspace (OPENCLAW_PROFILE=default or unset)
│   ├── SOUL.md
│   ├── AGENTS.md
│   ├── USER.md
│   ├── IDENTITY.md
│   ├── TOOLS.md
│   ├── HEARTBEAT.md
│   ├── BOOTSTRAP.md
│   ├── MEMORY.md  (or memory.md)
│   └── memory/
│       └── 2025-03-19.md               ← Written by memory flush turns
│
├── workspace-myprofile/                 ← Alt workspace when OPENCLAW_PROFILE=myprofile
│
└── state/                               ← State dir — NOT affected by OPENCLAW_PROFILE
    ├── memory/
    │   ├── main.sqlite                  ← Layer 2 vector store for agent "main"
    │   └── coding.sqlite                ← Layer 2 vector store for agent "coding"
    └── agents/
        ├── main/
        │   └── sessions/
        │       ├── sessions.json                    ← Flat session store (all sessions)
        │       ├── <sessionId>.jsonl                ← Regular transcript
        │       ├── <sessionId>-topic-<topicId>.jsonl ← Telegram topic variant
        │       └── <sessionId>.jsonl.deleted.1710000000000 ← Archived/pruned transcript
        └── coding/
            └── sessions/
                └── sessions.json
```

**Critical caveat — `OPENCLAW_PROFILE`**: Setting `OPENCLAW_PROFILE=myprofile` changes the workspace
dir to `~/.openclaw/workspace-myprofile` but the state dir (`~/.openclaw/state/`) is **never
affected**. This means two profiles sharing the same agent ID (`main`) will collide on the same
`sessions.json` and the same SQLite vector store. If per-profile isolation of sessions and memory is
needed, a separate agent ID must be configured via `agents.list[]`.
(`src/agents/workspace.ts:17-22`, `src/config/paths.ts`)

### 2.2 The `SessionEntry` Type

**Location**: `src/config/sessions/types.ts:68-174`

`sessions.json` is a `Record<string, SessionEntry>` keyed by normalized (lowercase) session key.

**Complete field list**:

```typescript
type SessionEntry = {
  // Core identity
  sessionId: string;                    // UUID — stable JSONL filename stem
  updatedAt: number;                    // epoch ms, updated on every write

  // File reference
  sessionFile?: string;                 // relative path to JSONL transcript
  spawnedBy?: string;                   // parent session key (for subagent scoping)
  spawnedWorkspaceDir?: string;         // workspace dir inherited from spawner

  // Fork / subagent state
  forkedFromParent?: boolean;           // true after thread session forked parent transcript
  spawnDepth?: number;                  // 0=main, 1=sub-agent, 2=sub-sub-agent
  subagentRole?: "orchestrator" | "leaf";
  subagentControlScope?: "children" | "none";

  // Run state
  systemSent?: boolean;                 // session header written to JSONL
  abortedLastRun?: boolean;
  abortCutoffMessageSid?: string;       // stop boundary after /stop command
  abortCutoffTimestamp?: number;

  // Session type metadata
  chatType?: SessionChatType;           // "direct" | "group" | "channel" | ...
  label?: string;
  displayName?: string;
  channel?: string;
  groupId?: string;
  subject?: string;
  groupChannel?: string;
  space?: string;
  origin?: SessionOrigin;               // { label, provider, surface, chatType, from, to, accountId, threadId }
  deliveryContext?: DeliveryContext;    // normalized send-back routing info
  lastChannel?: SessionChannelId;
  lastTo?: string;
  lastAccountId?: string;
  lastThreadId?: string | number;

  // Runtime model overrides (per-session)
  thinkingLevel?: string;
  fastMode?: boolean;
  verboseLevel?: string;
  reasoningLevel?: string;
  elevatedLevel?: string;
  ttsAuto?: TtsAutoMode;
  execHost?: string;
  execSecurity?: string;
  execAsk?: string;
  execNode?: string;
  responseUsage?: "on" | "off" | "tokens" | "full";
  providerOverride?: string;
  modelOverride?: string;
  authProfileOverride?: string;
  authProfileOverrideSource?: "auto" | "user";
  authProfileOverrideCompactionCount?: number;

  // Group activation
  groupActivation?: "mention" | "always";
  groupActivationNeedsSystemIntro?: boolean;
  sendPolicy?: "allow" | "deny";

  // Queue tuning
  queueMode?: "steer" | "followup" | "collect" | "steer-backlog" | "steer+backlog" | "queue" | "interrupt";
  queueDebounceMs?: number;
  queueCap?: number;
  queueDrop?: "old" | "new" | "summarize";

  // Token accounting (updated after each run)
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
  totalTokensFresh?: boolean;           // false = stale/unknown for display
  cacheRead?: number;
  cacheWrite?: number;
  modelProvider?: string;
  model?: string;
  fallbackNoticeSelectedModel?: string;
  fallbackNoticeActiveModel?: string;
  fallbackNoticeReason?: string;
  contextTokens?: number;

  // Compaction tracking
  compactionCount?: number;             // incremented after each successful compaction
  memoryFlushAt?: number;               // epoch ms of last memory flush turn
  memoryFlushCompactionCount?: number;  // compactionCount when flush last ran (dedup guard)

  // CLI integration
  cliSessionIds?: Record<string, string>;
  claudeCliSessionId?: string;

  // Heartbeat
  lastHeartbeatText?: string;
  lastHeartbeatSentAt?: number;

  // Snapshot and diagnostics
  skillsSnapshot?: SessionSkillSnapshot;
  systemPromptReport?: SessionSystemPromptReport;

  // ACP (Agent Control Protocol) metadata
  acp?: SessionAcpMeta;
};
```

### 2.3 `SessionAcpMeta` State Machine

**Location**: `src/config/sessions/types.ts:38-49`

```typescript
type SessionAcpMeta = {
  backend: string;             // ACP backend identifier
  agent: string;               // agent name in the ACP backend
  runtimeSessionName: string;  // ACP session handle name
  identity?: SessionAcpIdentity;
  mode: "persistent" | "oneshot";
  runtimeOptions?: AcpSessionRuntimeOptions;
  cwd?: string;
  state: "idle" | "running" | "error";  // ← state machine
  lastActivityAt: number;
  lastError?: string;
};

type SessionAcpIdentity = {
  state: "pending" | "resolved";
  acpxRecordId?: string;
  acpxSessionId?: string;
  agentSessionId?: string;
  source: "ensure" | "status" | "event";
  lastUpdatedAt: number;
};
```

**State transitions**:
```
idle ──► running  (when ACP turn starts)
running ──► idle  (turn completes successfully)
running ──► error (turn throws; lastError recorded)
error ──► running (next turn starts; error cleared)
```

**ACP metadata preservation**: `collectAcpMetadataSnapshot()` snapshots `entry.acp` before any
store mutator runs. After the mutator, `preserveExistingAcpMetadata()` re-injects the snapshot if
the caller didn't carry `acp` forward. Session keys in `allowDropAcpMetaSessionKeys` bypass this
safety net. (`src/config/sessions/store.ts:585-603`)

### 2.4 Atomic Write Sequence

**Location**: `src/config/sessions/store.ts:585-603` (`updateSessionStore`)

The canonical write pattern:

```
1. Acquire per-storePath FIFO queue slot (LOCK_QUEUES map)
2. Acquire file-based write lock on <storePath>.lock
   - Timeout: 10 seconds default
   - Stale lock detection: 30 seconds (lock file with dead PID removed)
3. loadSessionStore(storePath, { skipCache: true })
   - Re-reads from disk, bypasses object cache
   - On Windows: up to 3 retries with 50ms Atomics.wait() between attempts
     (handles 0-byte file during concurrent temp-rename write)
4. collectAcpMetadataSnapshot(store)
5. Run caller-supplied mutator(store)
6. preserveExistingAcpMetadata({ previousAcpByKey, nextStore, ... })
7. writeTextAtomic(storePath, JSON.stringify(store, null, 2))
   - Writes to a temp file in the same directory
   - Renames temp file over storePath (atomic on POSIX; best-effort on Windows)
   - File mode: 0o600
   - Windows: up to 5 rename retry attempts with 50ms backoff
8. Update object cache (writeSessionStoreCache)
9. Release file lock
10. Release FIFO queue slot
```

**Why re-read inside the lock**: Multiple processes (gateway + CLI) can update `sessions.json`
concurrently. The `skipCache: true` ensures the writer sees the most recent on-disk state before
merging its patch. The in-memory TTL cache is only used for read-only callers.

### 2.5 TTL Cache

**Location**: `src/config/sessions/store.ts:52` (`DEFAULT_SESSION_STORE_TTL_MS = 45_000`)

- Cache key: `{ storePath, mtimeMs, sizeBytes }` (stale if `mtime` or `size` changed)
- TTL: 45 seconds default, overridden by `OPENCLAW_SESSION_CACHE_TTL_MS` env var
- Cache is in-process memory only (not shared across processes)
- Disabled entirely if TTL ≤ 0
- Write path always uses `skipCache: true` and then updates the cache post-write

### 2.6 `mergeSessionEntry` Semantics

**Location**: `src/config/sessions/types.ts:277-281` (`mergeSessionEntry`)
**Full implementation**: `src/config/sessions/types.ts:253-275` (`mergeSessionEntryWithPolicy`)

```typescript
function mergeSessionEntry(
  existing: SessionEntry | undefined,
  patch: Partial<SessionEntry>,
): SessionEntry
```

**Merge strategy**:
1. If `existing` is undefined: create new entry from `patch` (assigns a random UUID `sessionId`).
2. If `existing` exists: **shallow spread** — `{ ...existing, ...patch }`. All fields in `patch` overwrite `existing`. No deep merge.
3. `sessionId`: `patch.sessionId ?? existing.sessionId ?? crypto.randomUUID()`
4. `updatedAt`: `Math.max(existing.updatedAt ?? 0, patch.updatedAt ?? 0, Date.now())`
5. **Runtime model guard**: If `patch` contains `model` but not `modelProvider`, and the model
   changed, `modelProvider` is deleted from the merged result to prevent stale provider carry-over.
6. `normalizeSessionRuntimeModelFields()` is applied to trim whitespace from `model`/`modelProvider`.

Two additional variants:
- `mergeSessionEntryWithPolicy(existing, patch, { policy: "preserve-activity" })`: uses `existing.updatedAt` instead of `Date.now()` — used when a background writer should not bump the activity timestamp.
- `mergeSessionEntryPreserveActivity(existing, patch)`: convenience wrapper for the above.

### 2.7 Legacy Key Migration

**Location**: `src/config/sessions/store.ts:115-154` (`resolveSessionStoreEntry`)

When looking up a session key:
1. Normalize the input key to lowercase.
2. Look for exact match in store.
3. Fall back: scan all keys case-insensitively. If multiple matches exist, pick the one with the
   highest `updatedAt`.
4. The non-normalized keys are returned as `legacyKeys` and are deleted + replaced with the
   normalized key on the next write.

### 2.8 Maintenance & Pruning

**Location**: `src/config/sessions/store-maintenance.ts:12-16`

| Parameter | Default | Config key |
|---|---|---|
| Prune stale entries older than | 30 days | `sessions.maintenance.pruneAfter` (duration string, e.g. `"30d"`) |
| Max entries cap | 500 | `sessions.maintenance.maxEntries` |
| Rotate `sessions.json` when larger than | 10 MB (10,485,760 bytes) | `sessions.maintenance.rotateBytes` |
| Default maintenance mode | `"warn"` | `sessions.maintenance.mode` |
| Disk budget high-water ratio | `0.8` | Derived from `maxDiskBytes`; high-water threshold = `floor(maxDiskBytes × 0.8)`. Override via `sessions.maintenance.highWaterBytes`. |

**Mode semantics**:
- `"warn"` (default): logs warnings when thresholds are exceeded; **never mutates** the store.
- `"enforce"`: applies all of: prune stale → cap entry count → archive removed transcripts →
  purge old archives → rotate JSON file → enforce disk budget.

**Transcript archiving**: When a session is pruned or reset, its JSONL transcript is **not deleted**
immediately. It is renamed with a suffix: `<sessionId>.jsonl.deleted.<timestamp>` or
`<sessionId>.jsonl.reset.<timestamp>`. Archives are purged by a separate disk budget sweep.

### 2.9 Transcript Filename Rules

**Location**: `src/config/sessions/paths.ts:60` (`SAFE_SESSION_ID_RE`)

```typescript
const SAFE_SESSION_ID_RE = /^[a-z0-9][a-z0-9._-]{0,127}$/i;
```

- Regular transcript: `<sessionId>.jsonl`
- Telegram topic variant: `<sessionId>-topic-<topicId>.jsonl`
  (where `topicId` is URL-encoded for string IDs, or plain decimal for numeric IDs)
- Archived transcript: `<sessionId>.jsonl.deleted.<timestamp>` or `<sessionId>.jsonl.reset.<timestamp>`

`sessionId` must match `SAFE_SESSION_ID_RE`. `validateSessionId()` throws on violation.

---

## Section 3: Three-Layer Memory Architecture

**Primary sources**:
- `src/agents/memory-search.ts` (layer configuration)
- `src/agents/workspace.ts` (layer 1 file loading)
- `extensions/memory-core/index.ts` (runtime tools: `createMemorySearchTool`, `createMemoryGetTool`)

**Design note**: The three-layer architecture is not named anywhere in the source code. This document
names it to make the structure explicit for implementors.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         Three-Layer Memory                                    │
├──────────────────────────────────────────────────────────────────────────────┤
│  Layer 1: Workspace Markdown Files  (static bootstrap context)                │
│                                                                               │
│  Loaded once per run at session start. Read by the agent as part of the      │
│  system prompt. Human-editable. No search; full-content injection.            │
│                                                                               │
│  ~/.openclaw/workspace/SOUL.md       (personality)                           │
│  ~/.openclaw/workspace/AGENTS.md     (other agent references)                │
│  ~/.openclaw/workspace/USER.md       (user profile known to agent)           │
│  ~/.openclaw/workspace/IDENTITY.md   (agent identity override)               │
│  ~/.openclaw/workspace/TOOLS.md      (tool hints/restrictions)               │
│  ~/.openclaw/workspace/HEARTBEAT.md  (periodic ping instructions)            │
│  ~/.openclaw/workspace/BOOTSTRAP.md  (extra boot instructions)               │
│  ~/.openclaw/workspace/MEMORY.md     (long-term notes, prefer memory/*.md)   │
├──────────────────────────────────────────────────────────────────────────────┤
│  Layer 2: SQLite Vector Store  (semantic search)                              │
│                                                                               │
│  Per-agent SQLite DB at ~/.openclaw/state/memory/<agentId>.sqlite            │
│  Hybrid BM25 + vector search. Documents chunked from workspace files and     │
│  memory/*.md files written by memory flush turns.                             │
│  Searched dynamically via memory_search tool or on every turn if enabled.    │
├──────────────────────────────────────────────────────────────────────────────┤
│  Layer 3: JSONL Session Transcript Index  (session memory, experimental)     │
│                                                                               │
│  Indexes JSONL session transcripts into the SQLite DB.                       │
│  Disabled by default (requires experimental.sessionMemory=true +             │
│  sources: ["memory","sessions"] in config).                                  │
│  Synced on session start, on search, and via file-watcher (debounced).       │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Layer 1: Workspace Markdown Bootstrap Files

**Location**: `src/agents/workspace.ts:487-547` (`loadWorkspaceBootstrapFiles`)

#### File Constants

**Location**: `src/agents/workspace.ts:25-33`

```typescript
export const DEFAULT_AGENTS_FILENAME    = "AGENTS.md";
export const DEFAULT_SOUL_FILENAME      = "SOUL.md";
export const DEFAULT_TOOLS_FILENAME     = "TOOLS.md";
export const DEFAULT_IDENTITY_FILENAME  = "IDENTITY.md";
export const DEFAULT_USER_FILENAME      = "USER.md";
export const DEFAULT_HEARTBEAT_FILENAME = "HEARTBEAT.md";
export const DEFAULT_BOOTSTRAP_FILENAME = "BOOTSTRAP.md";
export const DEFAULT_MEMORY_FILENAME    = "MEMORY.md";
export const DEFAULT_MEMORY_ALT_FILENAME = "memory.md";  // fallback
```

#### Load Order

Files are loaded in this exact order (lines 493-522):

1. `AGENTS.md`
2. `SOUL.md`
3. `TOOLS.md`
4. `IDENTITY.md`
5. `USER.md`
6. `HEARTBEAT.md`
7. `BOOTSTRAP.md`
8. `MEMORY.md` (falls back to `memory.md` if absent)

#### Constraints

- **Max file size**: 2 MB per file (`MAX_WORKSPACE_BOOTSTRAP_FILE_BYTES = 2 * 1024 * 1024`, line 40).
  Truncation is tracked in `SessionSystemPromptReport.bootstrapTruncation`.
- **Path safety**: Files are read via `openBoundaryFile()` which enforces path containment within
  the workspace directory (prevents path traversal).
- **Inode cache**: Files are cached by `"<canonicalPath>|<dev>:<ino>:<size>:<mtimeMs>"` identity
  (`workspaceFileIdentity()`, line 52). Stale cache entries are evicted when `mtime` or `size`
  changes.

#### MEMORY.md Deduplication Gotcha

On case-insensitive filesystems (macOS default, Docker volume mounts), both `MEMORY.md` and `memory.md`
may pass `fs.access()` but `realpath` does not normalize case through certain mount layers, causing
double injection. The code avoids `realpath` dedup: it simply tries `MEMORY.md` first, then `memory.md`,
and uses the first one found. Do **not** add realpath-based dedup — it is unreliable here.
(`src/agents/workspace.ts:470-484`)

#### Subagent / Cron Filter

**Location**: `src/agents/workspace.ts:549-565` (`filterBootstrapFilesForSession`)

When the session key is a subagent key (`rest` starts with `"subagent:"`) or a cron key (`rest`
starts with `"cron:"`), only files in `MINIMAL_BOOTSTRAP_ALLOWLIST` are included:

```typescript
const MINIMAL_BOOTSTRAP_ALLOWLIST = new Set([
  "AGENTS.md",
  "TOOLS.md",
  "SOUL.md",
  "IDENTITY.md",
  "USER.md",
  // HEARTBEAT.md, BOOTSTRAP.md, MEMORY.md are excluded
]);
```

This is an important token budget optimization — subagents don't need heartbeat instructions,
bootstrap procedures, or the full memory file.

### 3.2 `ResolvedMemorySearchConfig` — Full Type Table

**Location**: `src/agents/memory-search.ts:15-89` (type definition), `:91-112` (constants)

This is the fully resolved config produced by `resolveMemorySearchConfig()`. Every field, its
TypeScript type, and its default value:

| Field | Type | Default | Notes |
|---|---|---|---|
| `enabled` | `boolean` | `true` | Master switch for Layer 2 |
| `sources` | `Array<"memory" \| "sessions">` | `["memory"]` | `"sessions"` requires `experimental.sessionMemory=true` |
| `extraPaths` | `string[]` | `[]` | Additional file paths to index beyond workspace |
| `multimodal` | `MemoryMultimodalSettings` | (disabled) | Image embedding support |
| `provider` | `"openai" \| "local" \| "gemini" \| "voyage" \| "mistral" \| "ollama" \| "auto"` | `"auto"` | Embedding provider |
| `remote.baseUrl` | `string \| undefined` | `undefined` | Custom embedding endpoint |
| `remote.apiKey` | `SecretInput \| undefined` | `undefined` | API key for remote provider |
| `remote.headers` | `Record<string, string> \| undefined` | `undefined` | Extra HTTP headers |
| `remote.batch.enabled` | `boolean` | `false` | Enable batched embedding requests |
| `remote.batch.wait` | `boolean` | `true` | Wait for batch completion |
| `remote.batch.concurrency` | `number` | `2` | Max concurrent batch requests |
| `remote.batch.pollIntervalMs` | `number` | `2000` | Batch polling interval |
| `remote.batch.timeoutMinutes` | `number` | `60` | Batch overall timeout |
| `experimental.sessionMemory` | `boolean` | `false` | Enable Layer 3 (JSONL indexing) |
| `fallback` | `"openai" \| "gemini" \| "local" \| "voyage" \| "mistral" \| "ollama" \| "none"` | `"none"` | Fallback provider if primary fails |
| `model` | `string` | Provider-specific (see below) | Embedding model ID |
| `outputDimensionality` | `number \| undefined` | `undefined` | Override embedding dimensions |
| `local.modelPath` | `string \| undefined` | `undefined` | Path to local embedding model |
| `local.modelCacheDir` | `string \| undefined` | `undefined` | Cache dir for local models |
| `store.driver` | `"sqlite"` | `"sqlite"` | Storage backend (only SQLite supported) |
| `store.path` | `string` | `~/.openclaw/state/memory/<agentId>.sqlite` | Vector DB file path |
| `store.vector.enabled` | `boolean` | `true` | Enable vector extension |
| `store.vector.extensionPath` | `string \| undefined` | `undefined` | Path to sqlite-vec extension |
| `chunking.tokens` | `number` | `400` | Chunk size in tokens |
| `chunking.overlap` | `number` | `80` | Overlap between chunks in tokens |
| `sync.onSessionStart` | `boolean` | `true` | Sync workspace files when session starts |
| `sync.onSearch` | `boolean` | `true` | Sync before each memory search |
| `sync.watch` | `boolean` | `true` | Watch workspace dir for file changes |
| `sync.watchDebounceMs` | `number` | `1500` | Watch debounce delay |
| `sync.intervalMinutes` | `number` | `0` | Periodic sync interval (0=disabled) |
| `sync.sessions.deltaBytes` | `number` | `100000` | Min bytes changed to trigger session sync |
| `sync.sessions.deltaMessages` | `number` | `50` | Min messages added to trigger session sync |
| `sync.sessions.postCompactionForce` | `boolean` | (from config) | Force sync after compaction |
| `query.maxResults` | `number` | `6` | Max search results returned |
| `query.minScore` | `number` | `0.35` | Minimum similarity score threshold |
| `query.hybrid.enabled` | `boolean` | `true` | Enable hybrid BM25+vector search |
| `query.hybrid.vectorWeight` | `number` | `0.7` | Vector score weight |
| `query.hybrid.textWeight` | `number` | `0.3` | BM25 text score weight |
| `query.hybrid.candidateMultiplier` | `number` | `4` | Fetch `maxResults * 4` candidates before re-ranking |
| `query.hybrid.mmr.enabled` | `boolean` | `false` | Maximal Marginal Relevance re-ranking |
| `query.hybrid.mmr.lambda` | `number` | `0.7` | MMR diversity/relevance tradeoff |
| `query.hybrid.temporalDecay.enabled` | `boolean` | `false` | Time-based score decay |
| `query.hybrid.temporalDecay.halfLifeDays` | `number` | `30` | Half-life for temporal decay |
| `cache.enabled` | `boolean` | `true` | In-process query result cache |
| `cache.maxEntries` | `number \| undefined` | `undefined` | Max cache entries (unlimited if unset) |

**Weight normalization**: `vectorWeight + textWeight` must sum to 1.0. The resolver does not
auto-normalize — set both values intentionally. If `hybrid.enabled=false`, only vector search runs.

### 3.3 Layer 2: SQLite Vector Store

**Store path**: `~/.openclaw/state/memory/<agentId>.sqlite`
Supports `{agentId}` token substitution in `store.path` config string.

**Search pipeline** (when `hybrid.enabled=true`):

```
Query string
    │
    ├─► BM25 full-text search ──────────────────────────────────┐
    │                                                            │
    └─► Embed query ──► ANN vector search ─────────────────────┤
                                                                ▼
                                          Fetch (maxResults * candidateMultiplier) candidates
                                                 = maxResults * 4 = 24 by default
                                                                ▼
                                          Combine scores: 0.7 * vectorScore + 0.3 * bm25Score
                                                                ▼
                                          Filter: score >= minScore (0.35)
                                                                ▼
                                          Optional MMR re-ranking (default: off)
                                                                ▼
                                          Return top maxResults (6) chunks
```

**Chunking**: Documents are split into chunks of `tokens=400` with `overlap=80` tokens before
indexing. Each chunk is embedded separately.

**Embedding provider auto-resolution** (`provider: "auto"`): Tries providers in order:
1. `local` (bundled local model)
2. `openai` (requires `OPENAI_API_KEY`)
3. `gemini` (requires `GEMINI_API_KEY`)
4. `voyage` (requires `VOYAGE_API_KEY`)
5. `mistral` (requires `MISTRAL_API_KEY`)

Default models per provider (`src/agents/memory-search.ts:91-95`):
- `openai`: `text-embedding-3-small`
- `gemini`: `gemini-embedding-001`
- `voyage`: `voyage-4-large`
- `mistral`: `mistral-embed`
- `ollama`: `nomic-embed-text`

### 3.4 Layer 3: Session Transcript Index (Experimental)

**Activation**: Must explicitly set `experimental.sessionMemory: true` **and** add `"sessions"` to
`sources` array in config. Both conditions are required — setting `sessionMemory=true` alone is not
sufficient (`src/agents/memory-search.ts:114-131`, `normalizeSources()`).

**Sync triggers**:
- `onSessionStart=true`: Sync before first run of a session
- `onSearch=true`: Sync before each `memory_search` tool call
- `watch=true`: File watcher on workspace dir, debounced 1500ms
- `postCompactionForce=true`: Force sync after compaction completes

**Delta thresholds** (prevent excessive re-indexing):
- `sync.sessions.deltaBytes=100000`: Only re-index a session if it has grown by ≥100 KB since last sync
- `sync.sessions.deltaMessages=50`: Only re-index a session if ≥50 new messages were added

**Gotcha**: Session memory search is off by default. An agent with no explicit memory config will
never index JSONL transcripts. This must be an explicit opt-in for operators who want semantic
search over conversation history.

---

## Section 4: Compaction & Memory Flush Pipeline

**Primary sources**:
- `src/agents/compaction.ts` (core algorithms)
- `src/agents/pi-embedded-runner/compact.ts` (runner integration)
- `src/agents/pi-embedded-runner/compaction-safety-timeout.ts`
- `src/auto-reply/reply/memory-flush.ts` (flush settings)

### 4.1 Constants

**Location**: Lines 12–16 (`src/agents/compaction.ts:12-16`) contain the first four exported/private constants; `SUMMARIZATION_OVERHEAD_TOKENS` is defined separately at line 133.

```typescript
// compaction.ts:12-16
export const BASE_CHUNK_RATIO = 0.4;         // baseline chunk size as fraction of context window
export const MIN_CHUNK_RATIO = 0.15;         // minimum allowed chunk ratio (prevents tiny chunks)
export const SAFETY_MARGIN = 1.2;            // 20% buffer for token estimation inaccuracy
//  (chars/4 heuristic misses multi-byte chars, special tokens, code tokens)
const DEFAULT_SUMMARY_FALLBACK = "No prior history.";  // fallback text when no summary exists (unexported)
const DEFAULT_PARTS = 2;                     // default number of chunks in summarizeInStages

// compaction.ts:133
export const SUMMARIZATION_OVERHEAD_TOKENS = 4096;  // tokens reserved for prompt + reasoning
```

**Safety timeout**: `EMBEDDED_COMPACTION_TIMEOUT_MS = 900_000` (15 minutes)
(`src/agents/pi-embedded-runner/compaction-safety-timeout.ts:4`)

Overridable via `agents.defaults.compaction.timeoutSeconds` in config.

### 4.2 Trigger Conditions

**Overflow trigger**: The agent's pi-embedded runner detects that the current context is
approaching the context window limit. The formula involves three config values:
- `contextWindow`: model's reported context window
- `reserveTokensFloor`: minimum tokens reserved for the response (from `DEFAULT_PI_COMPACTION_RESERVE_TOKENS_FLOOR`)
- `softThresholdTokens` (default 4000, from `DEFAULT_MEMORY_FLUSH_SOFT_TOKENS`): pre-compaction flush trigger zone

When `usedTokens > contextWindow - reserveTokensFloor - softThresholdTokens`, a memory flush turn
fires first (if enabled). Then, when context is actually full, compaction is triggered.

**Manual trigger**: User runs `/compact` command. Sets `trigger="manual"` in `CompactEmbeddedPiSessionParams`.

### 4.3 Lane Queuing

Compaction uses two levels of queuing to prevent concurrent operations on the same session or
globally:

1. **Session lane** (`resolveSessionLane(sessionKey)`): Ensures no two compactions for the same
   session key run concurrently.
2. **Global lane** (`resolveGlobalLane()`): Single global slot for all compactions system-wide
   (prevents simultaneous compactions from exhausting API rate limits).

Both are coordinated via `enqueueCommandInLane()` (`src/process/command-queue.ts`).

`compactEmbeddedPiSessionDirect()` is the **core** function (no lane queuing). Call it when already
inside a session/global lane to avoid deadlocks. The wrapper `compactEmbeddedPiSession()` handles
lane acquisition.

### 4.4 `summarizeInStages` Algorithm

**Location**: `src/agents/compaction.ts:333-396`

```
Input: messages[], model, apiKey, signal, reserveTokens, maxChunkTokens, contextWindow, parts=2

1. If messages is empty → return previousSummary ?? "No prior history."

2. Compute minMessagesForSplit = max(2, params.minMessagesForSplit ?? 4)
   Normalize parts = min(max(1, floor(parts)), max(1, messageCount))

3. If parts <= 1 OR messageCount < minMessagesForSplit OR totalTokens <= maxChunkTokens:
   → Delegate to summarizeWithFallback() (single-chunk path)

4. Split messages into N chunks by token share:
   splitMessagesByTokenShare(messages, parts)
   - Accumulates token counts per message
   - Cuts a new chunk when currentTokens + nextMessageTokens > totalTokens/N
   - Result: N roughly equal-size arrays

5. For each chunk:
   summary[i] = await summarizeWithFallback({ messages: chunk[i] })
   (no previousSummary passed between chunks — each chunk summarized independently)

6. If only 1 split was produced → return single summary

7. Merge partial summaries:
   - Create "messages" array: [{ role: "user", content: summary[0] }, { role: "user", content: summary[1] }, ...]
   - Use MERGE_SUMMARIES_INSTRUCTIONS as custom instructions (see below)
   - Call summarizeWithFallback() on these meta-messages

MERGE_SUMMARIES_INSTRUCTIONS preserves:
  - Active tasks and their status (in-progress, blocked, pending)
  - Batch operation progress (e.g., "5/17 items completed")
  - Last user request and what was being done about it
  - Decisions and rationale
  - TODOs, open questions, constraints
  - Commitments and follow-ups promised
  Prioritizes: recent context over older history
```

**`summarizeWithFallback`**: Calls `summarizeChunks` first. If that fails, retries with only
non-oversized messages (messages where tokens < 50% of contextWindow), noting omissions. Final
fallback: returns a plain string describing count and oversized message count.

**`summarizeChunks`**: Calls `generateSummary()` from `@mariozechner/pi-coding-agent` on each chunk
sequentially (passing previous chunk's summary as `previousSummary`). Each call retried up to 3
times with exponential backoff (500ms–5000ms, 20% jitter, aborts on `AbortError`).

**Security**: `stripToolResultDetails()` is called on all messages before any `generateSummary()`
call. See Section 4.7 for rationale.

### 4.5 `pruneHistoryForContextShare` — Drop-Oldest-Chunk Loop

**Location**: `src/agents/compaction.ts:398-460`

Called when sharing context between sessions (e.g., spawning a subagent with parent history).
Trims history to fit within a budget without triggering a full compaction/summarization LLM call.

```
Input:
  messages[]       — current session history
  maxContextTokens — context window size
  maxHistoryShare  — fraction of window allowed for history (default: 0.5 = 50%)
  parts            — chunk split count (default: 2)

Formula:
  budgetTokens = floor(maxContextTokens * maxHistoryShare)
  e.g., 200,000 * 0.5 = 100,000 tokens

Loop while estimateMessagesTokens(kept) > budgetTokens:
  1. splitMessagesByTokenShare(kept, parts) → chunks
  2. If chunks.length <= 1: cannot split further, break
  3. Drop chunks[0] (oldest chunk)
  4. flatRest = chunks.slice(1).flat()
  5. repairReport = repairToolUseResultPairing(flatRest)
     - Drops orphaned tool_results (whose tool_use was in the dropped chunk)
     - Returns { messages, droppedOrphanCount }
  6. kept = repairReport.messages
  7. Accumulate: droppedChunks++, droppedMessages += dropped.length + orphanedCount

Returns:
  { messages, droppedMessagesList, droppedChunks, droppedMessages, droppedTokens, keptTokens, budgetTokens }
```

### 4.6 `repairToolUseResultPairing` — Why and When

**Location**: `src/agents/session-transcript-repair.ts:342`

**Problem**: Anthropic's API (and Claude Code Assist) reject transcripts where `tool_result` messages
appear without their matching `tool_use` in the immediately preceding assistant turn. When the oldest
chunk is dropped from history, `tool_use` blocks in the dropped messages leave **orphaned**
`tool_result` blocks in the remaining messages.

**What it does**:
1. Scans through messages to build a map of `toolUseId → toolUse block`.
2. For each `tool_result`, checks if its `toolUseId` has a corresponding `tool_use` block.
3. Drops orphaned `tool_result` blocks (no matching `tool_use`).
4. Moves displaced `tool_result` blocks to immediately follow their matching `tool_use` assistant turn.
5. Inserts synthetic error `tool_result` blocks for unmatched `tool_use` blocks.
6. Returns `{ messages, added, droppedDuplicateCount, droppedOrphanCount }`.

**Called**: In `pruneHistoryForContextShare` after every chunk drop, and in `limitHistoryTurns`
after DM history capping.

### 4.7 `stripToolResultDetails` — Security Rationale

**Location**: `src/agents/session-transcript-repair.ts:198`

```typescript
export function stripToolResultDetails(messages: AgentMessage[]): AgentMessage[]
```

Tool results may contain **untrusted, verbose payloads** from external tools (file contents, API
responses, bash output). These payloads must never be fed directly into a compaction LLM call
because:

1. They can contain injection attacks designed to manipulate the summary.
2. They inflate token counts unpredictably.
3. They may contain sensitive data (tokens, passwords, PII) that should not be re-sent to an LLM.

`stripToolResultDetails()` removes `details` sub-fields from `tool_result` messages while preserving
the text summary. Called at two points:
- In `estimateMessagesTokens()` for accurate estimation without verbose payloads.
- In `summarizeChunks()` before every `generateSummary()` LLM call.

### 4.8 Memory Flush Pipeline

**Location**: `src/auto-reply/reply/memory-flush.ts`

The memory flush is a **silent pre-compaction agentic turn** that runs when tokens approach the
compaction threshold. Its purpose: let the agent write important information to `memory/YYYY-MM-DD.md`
before the transcript is summarized and old messages are lost.

#### Preconditions (flush is SKIPPED if):

1. `agents.defaults.compaction.memoryFlush.enabled === false`
2. Sandbox workspace access is `"ro"` or `"none"` (read-only or no workspace access)
3. `entry.memoryFlushCompactionCount === entry.compactionCount` — already ran a flush for this
   compaction cycle (one flush per compaction cycle)

#### Flush Turn Details

- **Default prompt** (`DEFAULT_MEMORY_FLUSH_PROMPT`): Instructs agent to store durable memories
  in `memory/YYYY-MM-DD.md` (creates `memory/` subdirectory if needed), append-only, not to
  overwrite bootstrap files, not to create timestamped variants. Uses `SILENT_REPLY_TOKEN` if
  nothing to store.
- **Default system prompt** (`DEFAULT_MEMORY_FLUSH_SYSTEM_PROMPT`): Frames the turn as a
  "pre-compaction memory flush turn."
- Both prompts have safety hints injected by `ensureMemoryFlushSafetyHints()`.
- **`YYYY-MM-DD`** in prompts is replaced with the actual date in the user's configured timezone.

After the flush turn completes:
- `entry.memoryFlushAt = Date.now()`
- `entry.memoryFlushCompactionCount = entry.compactionCount`

These are written to `sessions.json` so the next run knows a flush already happened for this
compaction cycle.

**Soft threshold**: `softThresholdTokens` (default 4000) — flush fires when remaining headroom
before compaction is below this value. Configurable via `agents.defaults.compaction.memoryFlush.softThresholdTokens`.

### 4.9 Post-Compaction Sync Modes

**Location**: `src/agents/pi-embedded-runner/compact.ts:291-297` (`resolvePostCompactionIndexSyncMode`)

```typescript
function resolvePostCompactionIndexSyncMode(config?: OpenClawConfig): "off" | "async" | "await" {
  const mode = config?.agents?.defaults?.compaction?.postIndexSync;
  if (mode === "off" || mode === "async" || mode === "await") {
    return mode;
  }
  return "async";  // default
}
```

| Mode | Behavior |
|---|---|
| `"off"` | No post-compaction memory index sync |
| `"async"` | **(default)** Sync fires but is not awaited. Compaction response returns immediately. |
| `"await"` | Sync is awaited before compaction response returns. Use when downstream reads must see fresh index. |

The sync fires `manager.sync({ reason: "post-compaction", sessionFiles: [sessionFile] })`.
Only runs if `sources.includes("sessions")` and `sync.sessions.postCompactionForce=true` are both
true in the resolved memory config.

After sync (regardless of mode), `emitSessionTranscriptUpdate(sessionFile)` is called to notify
any active WebSocket subscribers of the transcript change.

### 4.10 `before_compaction` / `after_compaction` Hooks

**Location**: `src/plugins/types.ts:1371-1372` (hook name constants)

Plugin subscribers can register handlers for these two lifecycle hooks:

```typescript
before_compaction: (event: PluginHookBeforeCompactionEvent, ctx: PluginHookAgentContext) => Promise<void> | void
after_compaction:  (event: PluginHookAfterCompactionEvent,  ctx: PluginHookAgentContext) => Promise<void> | void
```

**Firing rules**:
- `before_compaction` fires before `generateSummary` is called. Fires even if compaction later
  fails. Hook failures are caught and logged as warnings; they do **not** abort compaction.
- `after_compaction` fires only if `result.ok === true && result.compacted === true`.
  Does not fire on failure, skip, or no-op.
- Both hooks are awaited (not fire-and-forget within `compactEmbeddedPiSessionDirect`).

### 4.11 `EmbeddedPiCompactResult` Type

**Location**: `src/agents/pi-embedded-runner/types.ts:79-90`

```typescript
type EmbeddedPiCompactResult = {
  ok: boolean;        // true = no fatal error (even if nothing was compacted)
  compacted: boolean; // true = transcript was actually rewritten
  reason?: string;    // human-readable reason for skip/failure
  result?: {
    summary: string;          // the generated summary text injected into transcript
    firstKeptEntryId: string; // JSONL entry ID of first kept message after compaction
    tokensBefore: number;     // estimated tokens before compaction
    tokensAfter?: number;     // estimated tokens after compaction (optional)
    details?: unknown;        // provider-specific diagnostic data
  };
};
```

`ok=true, compacted=false` means compaction was attempted but skipped (e.g., below threshold,
already compacted recently). `ok=false` means a fatal error occurred (API call failed, model not
resolved, etc.).

### 4.12 Safety Timeout Mechanism

**Location**: `src/agents/pi-embedded-runner/compaction-safety-timeout.ts`

`compactWithSafetyTimeout(compact, timeoutMs, opts)` wraps the compaction function with:

1. A hard timeout (`withTimeout()` from `src/node-host/with-timeout.js`). Default: 15 minutes.
2. An external abort signal (`opts.abortSignal`) — if the parent request is cancelled, compaction
   is also cancelled.
3. An `opts.onCancel()` callback for cleanup (e.g., closing the pi session).

On timeout or abort:
- `cancel()` is called (calls `opts.onCancel()`)
- `withTimeout` rejects with a timeout error
- Compaction returns `{ ok: false, compacted: false, reason: "Compaction timed out." }`

The timeout value is configurable: `agents.defaults.compaction.timeoutSeconds` in `openclaw.json`.
It falls back to `EMBEDDED_COMPACTION_TIMEOUT_MS = 900_000` (900 seconds / 15 minutes).

### 4.13 Compaction Model Configurability

**Location**: `src/agents/pi-embedded-runner/compact.ts:401-424`

The compaction LLM can differ from the conversation LLM:

```
agents.defaults.compaction.model = "anthropic/claude-3-5-haiku-20241022"
```

Format: `"<provider>/<modelId>"` or just `"<modelId>"` (inherits caller's provider).

If the provider changes (e.g., main uses Anthropic, compaction uses OpenRouter), the primary
`authProfileId` is dropped so `getApiKeyForModel` resolves credentials fresh for the override
provider — prevents sending wrong credentials.

If no override is set, compaction uses the same provider and model as the conversation turn.

---

## Section 5: Personality & System Prompt Assembly

**Primary sources**:
- `src/agents/system-prompt.ts` (`buildAgentSystemPrompt`, `PromptMode`)
- `src/agents/bootstrap-files.ts` (`resolveBootstrapContextForRun`, `BootstrapContextMode`)
- `src/agents/workspace.ts` (`loadWorkspaceBootstrapFiles`, `filterBootstrapFilesForSession`, `MINIMAL_BOOTSTRAP_ALLOWLIST`)
- `src/agents/identity.ts` (`resolveAckReaction`, `resolveMessagePrefix`, `resolveResponsePrefix`)

### 5.1 `PromptMode` Enum

**Location**: `src/agents/system-prompt.ts:17`

```typescript
export type PromptMode = "full" | "minimal" | "none";
```

| Value | Use case | Sections included |
|---|---|---|
| `"full"` | Default — main agent sessions, DMs, group chats | All sections (see 5.2) |
| `"minimal"` | Subagent sessions (spawned via `sessions_spawn`) | Tooling, Workspace, Runtime only; `extraSystemPrompt` rendered as `## Subagent Context` header |
| `"none"` | Bare identity only (no sections at all) | Returns exactly: `"You are a personal assistant running inside OpenClaw."` |

The `isMinimal` flag in the builder is `true` when `promptMode === "minimal" || promptMode === "none"`.
Sections gated on `!isMinimal`: Memory Recall, Authorized Senders, Reply Tags, Messaging, Voice,
OpenClaw Self-Update, Model Aliases, Silent Replies, Heartbeats.

### 5.2 Full Mode Section Order

**Location**: `src/agents/system-prompt.ts:423-679` (`buildAgentSystemPrompt`)

Sections are assembled in this exact order for `promptMode === "full"`:

1. `"You are a personal assistant running inside OpenClaw."` (identity line)
2. **`## Tooling`** — tool list filtered by policy, tool call style guidelines
3. **`## Safety`** — no self-preservation/replication; human oversight priority
4. **`## OpenClaw CLI Quick Reference`** — gateway start/stop/restart commands
5. **`## Skills (mandatory)`** (only if `skillsPrompt` is set) — `buildSkillsSection()`
6. **`## Memory Recall`** (only if `memory_search`/`memory_get` tools available) — `buildMemorySection()`
7. **`## OpenClaw Self-Update`** (only if `gateway` tool available)
8. **`## Model Aliases`** (only if `modelAliasLines` provided)
9. **`## Workspace`** — working directory path and guidance
10. **`## Documentation`** (only if `docsPath` configured)
11. **`## Sandbox`** (only if sandbox enabled)
12. **`## Authorized Senders`** — `buildUserIdentitySection()` with allowlisted sender IDs
13. **`## Current Date & Time`** — user timezone (only if `userTimezone` set)
14. **`## Workspace Files (injected)`** — header announcing bootstrap context files
15. **`## Reply Tags`** — `[[reply_to_current]]` and `[[reply_to:<id>]]` instructions
16. **`## Messaging`** — cross-session sends, `message` tool hints
17. **`## Voice (TTS)`** (only if `ttsHint` provided)
18. **`## Group Chat Context`** or **`## Subagent Context`** (only if `extraSystemPrompt` set)
19. **`## Reactions`** (only if `reactionGuidance` provided)
20. **`## Reasoning Format`** (only if `reasoningTagHint=true`)
21. **`# Project Context`** — bootstrap context files (SOUL.md, IDENTITY.md, etc.) each as `## <path>` subsections
22. **`## Silent Replies`** — `SILENT_REPLY_TOKEN` instructions
23. **`## Heartbeats`** — `HEARTBEAT_OK` protocol
24. **`## Runtime`** — `buildRuntimeLine()`: agent ID, host, OS, model, shell, channel, capabilities, thinking level

### 5.3 `MINIMAL_BOOTSTRAP_ALLOWLIST`

**Location**: `src/agents/workspace.ts:549-555`

```typescript
const MINIMAL_BOOTSTRAP_ALLOWLIST = new Set([
  "AGENTS.md",
  "TOOLS.md",
  "SOUL.md",
  "IDENTITY.md",
  "USER.md",
  // HEARTBEAT.md, BOOTSTRAP.md, MEMORY.md are excluded
]);
```

Applied by `filterBootstrapFilesForSession()` (`src/agents/workspace.ts:557-565`) whenever the
session key is a subagent key (starts with `subagent:`) or a cron key (starts with `cron:`).

**Rationale**: HEARTBEAT.md contains heartbeat polling instructions that are irrelevant to
subagents; BOOTSTRAP.md contains one-time onboarding instructions; MEMORY.md is large and subagents
don't need full long-term memory context.

### 5.4 `BootstrapContextMode` and `BootstrapContextRunKind`

**Location**: `src/agents/bootstrap-files.ts:16-18`

```typescript
export type BootstrapContextMode = "full" | "lightweight";
export type BootstrapContextRunKind = "default" | "heartbeat" | "cron";
```

`applyContextModeFilter()` (`src/agents/bootstrap-files.ts:47-62`) determines which files survive:

| `contextMode` | `runKind` | Files kept |
|---|---|---|
| `"full"` | any | All files pass through (no filter) |
| `"lightweight"` | `"heartbeat"` | Only `HEARTBEAT.md` |
| `"lightweight"` | `"cron"` or `"default"` | Empty — no bootstrap context injected |

`"lightweight"` mode is used for periodic scheduled runs where the full workspace context would
waste tokens. For a heartbeat run, only the heartbeat instructions file is needed.

### 5.5 `buildUserIdentitySection` — Authorized Senders

**Location**: `src/agents/system-prompt.ts:66-71`

```typescript
function buildUserIdentitySection(ownerLine: string | undefined, isMinimal: boolean)
```

Input: `ownerLine` is produced by `buildOwnerIdentityLine(ownerNumbers, ownerDisplay, ownerDisplaySecret)`.

- `ownerNumbers`: the `allowFrom` list for the channel (e.g., phone numbers, user IDs)
- `ownerDisplay`: `"raw"` (show IDs as-is) or `"hash"` (12-char HMAC-SHA256 truncation with optional `ownerDisplaySecret`)
- Output line format: `"Authorized senders: <id1>, <id2>. These senders are allowlisted; do not assume they are the owner."`

The section is omitted entirely if `ownerLine` is undefined (no `allowFrom` configured) or if
`isMinimal` is true (subagent mode — no need to announce allowlist to subagent).

### 5.6 The 4-Level `ackReaction` Precedence Chain

**Location**: `src/agents/identity.ts:13-46`

The emoji reaction sent when the agent acknowledges receipt of a message is resolved via a 4-level
precedence chain (first truthy value wins):

| Level | Source | Config path |
|---|---|---|
| L1 (highest) | Channel account config | `channels.<channel>.accounts.<accountId>.ackReaction` |
| L2 | Channel config | `channels.<channel>.ackReaction` |
| L3 | Global messages config | `messages.ackReaction` |
| L4 (lowest) | Agent identity emoji fallback | `agents.list[agentId].identity.emoji` or `"👀"` (default) |

```typescript
const DEFAULT_ACK_REACTION = "👀"; // src/agents/identity.ts:4
```

Empty string values at any level are treated as falsy (`.trim()` applied). If all levels yield
empty/undefined, `"👀"` is used.

### 5.7 `responsePrefix` and `messagePrefix` Logic

**Location**: `src/agents/identity.ts:64-133`

These two prefixes prepend to all outbound messages:

**`messagePrefix`** (`resolveMessagePrefix()`, line 64):
- Checked: `opts.configured` → `cfg.messages.messagePrefix` (explicit config)
- If `hasAllowFrom === true` (multi-user channel): default is `""` (empty — users know who they're talking to)
- Otherwise: `resolveIdentityNamePrefix(cfg, agentId)` → `"[<agentName>]"`, or fallback `"[openclaw]"`

**`responsePrefix`** (`resolveResponsePrefix()`, line 94):
- Also 4-level: channel account → channel → global `messages.responsePrefix` → `undefined`
- Special value `"auto"` at any level resolves to `resolveIdentityNamePrefix(cfg, agentId)` = `"[<agentName>]"`
- Returns `undefined` (not `""`) if no config is set at any level — caller decides whether to prepend

**Example**: Agent named `"Jarvis"` with no `allowFrom` and no explicit prefix config:
- `messagePrefix` = `"[Jarvis]"` (from identity name)
- `responsePrefix` = `undefined` (no prefix on replies unless configured)

### 5.8 `extraSystemPrompt` and `skillsPrompt` Injection Points

**`skillsPrompt`** is injected via `buildSkillsSection()` (`src/agents/system-prompt.ts:20-36`).
The section uses `## Skills (mandatory)` heading and instructs the agent to scan
`<available_skills>` descriptions and read the matching SKILL.md file before responding.
It wraps the caller-supplied `skillsPrompt` text after the standard instructions.

**`extraSystemPrompt`** (`src/agents/system-prompt.ts:584-589`):
- Injected near the end of the system prompt, just before reactions and reasoning format.
- In `"minimal"` mode (subagent): rendered under `## Subagent Context` heading.
- In `"full"` mode: rendered under `## Group Chat Context` heading.
- Used to inject per-session context such as: group chat metadata, subagent task description, or
  per-user identity context (e.g., "You are talking to Alice").

### 5.9 SOUL.md — Template, Seeding, and Front-Matter Stripping

**Template location**: `docs/reference/templates/SOUL.md`

The SOUL.md template is the primary personality file. It contains the agent's core character:
opinions, tone, boundaries, and interaction style. The template begins with YAML front-matter
(separated by `---` delimiters) which is **stripped before injection** via `stripFrontMatter()`
(`src/agents/workspace.ts:90-102`).

**Seeding**: When `ensureAgentWorkspace({ ensureBootstrapFiles: true })` runs on a brand-new workspace
(`src/agents/workspace.ts:327-456`), it calls `writeFileIfMissing(soulPath, soulTemplate)`. This
creates `SOUL.md` only if it does not exist yet (uses `flag: "wx"` — exclusive create). Existing
files are never overwritten.

**`bootstrapSeededAt`**: Stored in `<workspaceDir>/.openclaw/workspace-state.json`:

```typescript
type WorkspaceSetupState = {
  version: 1;
  bootstrapSeededAt?: string;  // ISO 8601 timestamp — set when SOUL.md, IDENTITY.md etc. are seeded
  setupCompletedAt?: string;   // ISO 8601 timestamp — set after interactive onboarding completes
};
```

Legacy field `onboardingCompletedAt` is migrated to `setupCompletedAt` on first read
(`src/agents/workspace.ts:220-228`).

### 5.10 Per-Person Personality Adaptation via SOUL.md

The system prompt does **not** automatically inject peer identity into the SOUL.md content. SOUL.md
is loaded as a static bootstrap context file — the same content is used for every session sharing
that workspace.

However, the agent knows **who it is talking to** through two mechanisms:

1. **`extraSystemPrompt`** parameter: The channel adapter or agent runner can pass per-session
   context (e.g., `"You are talking to Alice. She prefers concise answers."`). This appears in the
   system prompt under `## Group Chat Context` (full mode) or `## Subagent Context` (minimal mode).
   (`src/agents/system-prompt.ts:584-589`)

2. **`buildUserIdentitySection`**: The `allowFrom` list is injected as `## Authorized Senders`,
   telling the agent which sender IDs are allowlisted. The agent can infer the caller's identity
   from this list when there is only one allowed sender.

**How to write per-user adaptation rules in SOUL.md**: Add conditional instructions referencing
the sender by their canonical name (as set in `identityLinks`). Example:

```markdown
## Per-Person Style

When talking to Alice: be concise and technical. Skip pleasantries.
When talking to Bob: use casual language. He likes humor.
```

The peer ID (or canonical identity link name, e.g. `"alice"`) does **not** appear verbatim in the
system prompt. The agent must infer identity from the `## Authorized Senders` section or from
`extraSystemPrompt` context injected by the caller. For full per-person adaptation, pass the
canonical name via `extraSystemPrompt` at session routing time.

---

## Section 6: Multi-Agent Routing & Subagent Lifecycle

**Primary sources**:
- `src/agents/agent-scope.ts` (`resolveAgentConfig`, `resolveSessionAgentId`, `resolveAgentWorkspaceDir`)
- `src/agents/subagent-registry.types.ts` (`SubagentRunRecord`)
- `src/acp/control-plane/session-actor-queue.ts` (`SessionActorQueue`)
- `src/acp/control-plane/manager.identity-reconcile.ts` (`reconcileManagerRuntimeSessionIdentifiers`)

### 6.1 `agents.list[]` Configuration

**Location**: `src/agents/agent-scope.ts:26-42` (`AgentEntry` type), `resolveAgentConfig:118-145`

Each entry in `agents.list[]` defines a named agent with optional overrides:

```typescript
type ResolvedAgentConfig = {
  name?: string;           // Display name (used for messagePrefix, e.g. "[Jarvis]")
  workspace?: string;      // Custom workspace dir path (overrides default resolution)
  agentDir?: string;       // Custom agent state dir (overrides ~/.openclaw/state/agents/<id>/agent)
  model?: string | {       // Model override: string shorthand or object with primary+fallbacks
    primary?: string;
    fallbacks?: string[];
  };
  skills?: string[];       // Skills filter — only these skill IDs are available to this agent
  memorySearch?: ...;      // Agent-level memory config overrides
  humanDelay?: ...;        // Typing simulation delay config
  heartbeat?: ...;         // Heartbeat schedule and prompt config
  identity?: {             // Agent persona
    name?: string;         // Agent name (shown in messagePrefix)
    emoji?: string;        // Default ackReaction emoji (L4 fallback)
  };
  groupChat?: ...;         // Group chat activation settings
  subagents?: ...;         // Subagent spawn policy
  sandbox?: ...;           // Sandbox config overrides for this agent
  tools?: ...;             // Tool policy overrides
};
```

Additionally, `agents.list[]` entries have:
- `id: string` — normalized agent ID (used in session key prefix `agent:<id>:`)
- `default?: boolean` — marks the default agent (first `default=true` entry, or first entry overall)

### 6.2 `resolveSessionAgentId` — Routing Logic

**Location**: `src/agents/agent-scope.ts:106-111`, with core logic at `86-104`

```typescript
function resolveSessionAgentId(params: {
  sessionKey?: string;
  config?: OpenClawConfig;
}): string
```

**Algorithm**:
1. Call `resolveDefaultAgentId(config)`:
   - If `agents.list` is empty → return `"main"` (`DEFAULT_AGENT_ID`)
   - Otherwise: find first entry with `default: true`; fall back to first entry overall
   - Normalize via `normalizeAgentId()`
2. Parse `agentId` from session key via `parseAgentSessionKey(sessionKey)`:
   - Returns `{ agentId, rest }` where `agentId` = second colon-segment (e.g. `"coding"` from `"agent:coding:main"`)
3. Result: `explicitAgentId ?? parsedAgentId ?? defaultAgentId`

**Effect**: A session key of `"agent:coding:whatsapp:direct:alice"` routes to the agent with
`id: "coding"`, regardless of which agent is marked `default`. If no `"coding"` entry exists in
`agents.list`, `resolveAgentConfig(cfg, "coding")` returns `undefined` and the agent runs with
defaults only.

### 6.3 Per-Agent Workspace Resolution

**Location**: `src/agents/agent-scope.ts:256-272` (`resolveAgentWorkspaceDir`)

**Resolution priority**:
1. `agents.list[agentId].workspace` (explicit path, `~` expanded)
2. `agents.defaults.workspace` (only for the default agent)
3. `resolveDefaultAgentWorkspaceDir()` → `~/.openclaw/workspace` (only for default agent)
4. For non-default agents: `<stateDir>/workspace-<agentId>` (e.g. `~/.openclaw/state/workspace-coding`)

The state dir itself is `~/.openclaw/state/` (never affected by `OPENCLAW_PROFILE`).

**Per-agent state dir**: `<stateDir>/agents/<agentId>/` — contains `sessions/` directory.
Custom override via `agents.list[agentId].agentDir`.

### 6.4 `SubagentRunRecord` — Full Field List

**Location**: `src/agents/subagent-registry.types.ts:6-58`

```typescript
type SubagentRunRecord = {
  runId: string;                          // UUID — stable run identifier
  childSessionKey: string;                // Session key of the spawned subagent
  controllerSessionKey?: string;          // Session key of the controlling orchestrator (if different)
  requesterSessionKey: string;            // Session key of the session that requested the spawn
  requesterOrigin?: DeliveryContext;      // Channel routing context for reply delivery
  requesterDisplayKey: string;            // Human-readable key for logs/UI
  task: string;                           // Task description passed to subagent
  cleanup: "delete" | "keep";            // Whether session is deleted after completion
  label?: string;                         // Optional display label
  model?: string;                         // Model override for this run
  workspaceDir?: string;                  // Workspace dir override for this run
  runTimeoutSeconds?: number;             // Hard timeout for this run
  spawnMode?: SpawnSubagentMode;          // How the subagent was spawned
  createdAt: number;                      // epoch ms
  startedAt?: number;                     // epoch ms — when agent first responded
  endedAt?: number;                       // epoch ms — when run finished
  outcome?: SubagentRunOutcome;           // "completed" | "failed" | "killed" | "timeout"
  archiveAtMs?: number;                   // When to archive the run record
  cleanupCompletedAt?: number;            // When session cleanup finished
  cleanupHandled?: boolean;               // Whether cleanup was already performed
  suppressAnnounceReason?: "steer-restart" | "killed"; // Do not send completion to requester
  expectsCompletionMessage?: boolean;     // Whether to send a completion message
  announceRetryCount?: number;            // Number of delivery retry attempts
  lastAnnounceRetryAt?: number;           // Timestamp of last retry (for backoff)
  endedReason?: SubagentLifecycleEndedReason; // Terminal lifecycle reason
  wakeOnDescendantSettle?: boolean;       // Re-invoke run when descendants complete
  frozenResultText?: string | null;       // Latest captured completion output for delivery
  frozenResultCapturedAt?: number;        // When frozenResultText was captured
  fallbackFrozenResultText?: string | null; // Fallback completion output across wake restarts
  fallbackFrozenResultCapturedAt?: number;
  endedHookEmittedAt?: number;            // When subagent_ended hook was emitted
  attachmentsDir?: string;                // Directory for run attachments
  attachmentsRootDir?: string;            // Root for all run attachment dirs
  retainAttachmentsOnKeep?: boolean;      // Whether to keep attachments when cleanup=keep
};
```

### 6.5 Subagent Depth Detection

**Location**: `src/sessions/session-key-utils.ts:89-95`

`getSubagentDepth(sessionKey)` counts `:subagent:` occurrences in the lowercase key.

Use case: prevent runaway recursion. A subagent at depth 2 (`agent:main:subagent:a:subagent:b`)
may be blocked from spawning further subagents by checking this count against a configured maximum.

### 6.6 `SessionActorQueue` — Per-Session FIFO

**Location**: `src/acp/control-plane/session-actor-queue.ts:3-38`

```typescript
class SessionActorQueue {
  private readonly queue = new KeyedAsyncQueue();
  private readonly pendingBySession = new Map<string, number>();

  async run<T>(actorKey: string, op: () => Promise<T>): Promise<T>
  getPendingCountForSession(actorKey: string): number
  getTotalPendingCount(): number
}
```

**How it works**: `queue.enqueue(actorKey, op, { onEnqueue, onSettle })` from `KeyedAsyncQueue`
serializes all operations for the same `actorKey`. Operations for different keys run concurrently.
`pendingBySession` tracks the number of queued-but-not-yet-settled operations per key.

**Critical gotcha**: The `actorKey` passed to `SessionActorQueue.run()` is the **ACP session handle
key**, not the OpenClaw session key. These are correlated via
`reconcileManagerRuntimeSessionIdentifiers()` (`src/acp/control-plane/manager.identity-reconcile.ts:15`).
Confusing the two key types causes operations for different sessions to be serialized together (or
for the wrong session's queue to be used).

### 6.7 ACP Identity Reconciliation

**Location**: `src/acp/control-plane/manager.identity-reconcile.ts:15-159`

When an ACP (Agent Control Protocol) turn runs, the ACP backend may assign or update session
identifiers. These must be reconciled back into the OpenClaw `SessionEntry.acp.identity` field.

**Three identity fields tracked** (`SessionAcpIdentity`):
- `agentSessionId`: The ACP agent's internal session ID
- `acpxSessionId`: The ACP cross-session ID (links multiple runs)
- `acpxRecordId`: The ACP record ID (persistent across compactions)

**Snapshot/re-inject pattern** (`src/config/sessions/store.ts`):
1. Before any store mutator: `collectAcpMetadataSnapshot(store)` saves a copy of `entry.acp`
2. After mutator: `preserveExistingAcpMetadata()` re-injects the snapshot if the mutator dropped
   the `acp` field (common when a generic `mergeSessionEntry` replaces the whole entry)
3. Exception: session keys in `allowDropAcpMetaSessionKeys` bypass step 2

This guarantees ACP metadata is never silently dropped even when non-ACP code paths update the
session entry.

### 6.8 Cross-Agent Communication Tools

The agent has access to these tools for inter-agent and inter-session communication:

| Tool | Purpose | Relevant config |
|---|---|---|
| `sessions_send(sessionKey, message)` | Send a message to another session | n/a |
| `sessions_list(filters)` | List sessions, filtered by agent/state | n/a |
| `sessions_history(sessionKey)` | Fetch conversation history from another session | n/a |
| `agents_list()` | List configured agent IDs available for spawn | `agents.list[].id` |
| `sessions_spawn(agentId, task, opts)` | Spawn a subagent session | `agents.list[].subagents.*` |

These tools are described in the system prompt's `## Tooling` section
(`src/agents/system-prompt.ts:261-267`). The `sessions_spawn` description adapts based on whether
ACP harness spawning is enabled.

---

## Section 7: Context Window, Security & Configuration Reference

**Primary sources**:
- `src/agents/context-window-guard.ts` (constants, `resolveContextWindowInfo`, `evaluateContextWindowGuard`)
- `src/agents/pi-embedded-runner/history.ts` (`getHistoryLimitFromSessionKey`, `limitHistoryTurns`)
- `src/security/dm-policy-shared.ts` (`resolveDmGroupAccessDecision`)
- `src/agents/sandbox/context.ts` (`resolveSandboxContext`)

### 7.1 Context Window Resolution — 4-Step Priority Chain

**Location**: `src/agents/context-window-guard.ts:21-50` (`resolveContextWindowInfo`)

```typescript
function resolveContextWindowInfo(params: {
  cfg: OpenClawConfig | undefined;
  provider: string;
  modelId: string;
  modelContextWindow?: number;
  defaultTokens: number;  // caller passes 200_000 as the default
}): ContextWindowInfo
```

**Resolution order** (first successful source wins for base window; cap applied after):

| Step | Source | Config path | `source` tag |
|---|---|---|---|
| 1 | `modelsConfig` — explicit per-model override | `models.providers.<provider>.models[id].contextWindow` | `"modelsConfig"` |
| 2 | `model` — runtime-reported window from model SDK | `model.contextWindow` property | `"model"` |
| 3 (fallback) | `default` — caller-provided default | Hardcoded `200_000` | `"default"` |
| Cap | `agentContextTokens` — config cap (applied if less than base) | `agents.defaults.contextTokens` | `"agentContextTokens"` |

**Important**: `agents.defaults.contextTokens` is a **cap**, not a target. It can only reduce the
effective context window, never increase it (`src/agents/context-window-guard.ts:44-47`).
If `agentContextTokens > baseWindow`, the cap is ignored.

```typescript
export type ContextWindowSource = "model" | "modelsConfig" | "agentContextTokens" | "default";
```

### 7.2 Context Window Guard Constants

**Location**: `src/agents/context-window-guard.ts:3-4`

```typescript
export const CONTEXT_WINDOW_HARD_MIN_TOKENS = 16_000;
export const CONTEXT_WINDOW_WARN_BELOW_TOKENS = 32_000;
```

`evaluateContextWindowGuard(params)` (`src/agents/context-window-guard.ts:57-74`) returns:

| Threshold | Condition | Behavior |
|---|---|---|
| `shouldWarn = true` | `0 < tokens < 32,000` | Log a warning; session still runs |
| `shouldBlock = true` | `0 < tokens < 16,000` | Block the session; refuse to run |

Both thresholds are overridable via `evaluateContextWindowGuard({ warnBelowTokens, hardMinTokens })`.

### 7.3 `getHistoryLimitFromSessionKey` — DM History Limiting

**Location**: `src/agents/pi-embedded-runner/history.ts:43-115`

```typescript
function getHistoryLimitFromSessionKey(
  sessionKey: string | undefined,
  config: OpenClawConfig | undefined,
): number | undefined
```

**Algorithm**:
1. Parse `provider` from session key: third colon-segment (e.g. `"whatsapp"` from `"agent:main:whatsapp:direct:alice"`)
2. Parse `kind` from session key: fourth colon-segment (e.g. `"direct"`)
3. Parse `userId`: all remaining segments joined with `:`, with `:thread:<numericId>` or `:topic:<numericId>` suffix stripped via `THREAD_SUFFIX_REGEX` (`/^(.*)(?::(?:thread|topic):\d+)$/i` — matches only numeric IDs)
4. Resolve `providerConfig` = `config.channels.<provider>` (typed as `{ historyLimit?, dmHistoryLimit?, dms? }`)
5. If `kind === "dm"` or `kind === "direct"` (both accepted for backward compat):
   - Check `providerConfig.dms[userId].historyLimit` (per-user override, highest priority)
   - Fall back to `providerConfig.dmHistoryLimit` (provider-wide DM limit)
6. If `kind === "channel"` or `kind === "group"`:
   - Use `providerConfig.historyLimit` (group/channel session limit)

`getDmHistoryLimitFromSessionKey` is a deprecated alias for the same function (`history.ts:115`).

### 7.4 `limitHistoryTurns` — Slice Logic

**Location**: `src/agents/pi-embedded-runner/history.ts:15-36`

```typescript
function limitHistoryTurns(messages: AgentMessage[], limit: number | undefined): AgentMessage[]
```

**Algorithm**:
1. If `limit` is absent/zero, or `messages` is empty: return unchanged.
2. Walk backwards through `messages` counting `role === "user"` entries.
3. When `userCount > limit`: return `messages.slice(lastUserIndex)` — slice from the oldest
   retained user turn onward.
4. If fewer than `limit` user turns exist: return all messages unchanged.

**Effect**: Keeps the last `limit` complete user turns (each user turn plus its trailing
assistant/tool response messages). Older turns are dropped without summarization.

After calling `limitHistoryTurns`, callers should also call `repairToolUseResultPairing` to
fix any orphaned `tool_result` blocks left by the slice (Section 4.6).

### 7.5 DM Policy — All 4 Enum Values

**Location**: `src/security/dm-policy-shared.ts:105-196` (`resolveDmGroupAccessDecision`)

Default value: `"pairing"` (`src/security/dm-policy-shared.ts:117`).

| `dmPolicy` value | Decision | Outcome |
|---|---|---|
| `"disabled"` | `"block"` | All DMs rejected; no pairing possible |
| `"open"` | `"allow"` | All DMs accepted regardless of sender identity |
| `"pairing"` *(default)* | `"allow"` if sender in `effectiveAllowFrom` (config + pairing store) | `"pairing"` if not allowlisted — triggers QR pairing flow |
| `"allowlist"` | `"allow"` if sender in `effectiveAllowFrom` (config only, no pairing store) | `"block"` if not in config allowlist |

**`storeAllowFrom`**: For `dmPolicy === "pairing"`, the allowlist is the union of
`channels.<channel>.allowFrom` (config) and the pairing store entries (approved via QR pairing).
For `dmPolicy === "allowlist"`, `readStoreAllowFromForDmPolicy` returns `[]` — pairing store is
never read (`src/security/dm-policy-shared.ts:95`).

### 7.6 Group Policy

**Location**: `src/security/dm-policy-shared.ts:118-122`

```typescript
const groupPolicy: GroupPolicy =
  params.groupPolicy === "open" || params.groupPolicy === "disabled"
    ? params.groupPolicy
    : "allowlist"; // default for any unrecognized value
```

| `groupPolicy` | Outcome |
|---|---|
| `"open"` | Allow all group messages |
| `"disabled"` | Block all group messages |
| `"allowlist"` *(default)* | Allow only if sender is in `effectiveGroupAllowFrom`; block if allowlist is empty |

Group messages never trigger the pairing flow — only `"allow"` or `"block"` decisions.

### 7.7 Sandbox Workspace Access Levels

**Location**: `src/agents/sandbox/context.ts` (`resolveSandboxContext`), `src/agents/sandbox/config.ts`

The `workspaceAccess` field on a sandbox config controls how the agent accesses the workspace dir:

| Value | Behavior |
|---|---|
| `"rw"` | Agent uses the real agent workspace dir (host path). Full read/write to actual workspace. |
| `"ro"` | Agent uses a **sandboxed copy** of the workspace dir. Writes go to the copy, not the real workspace. Memory flush is skipped (cannot write to real MEMORY.md). |
| `"none"` | Agent uses a sandboxed copy. No workspace files mounted. Memory flush is skipped. |

The `workspaceAccess` value is exposed in the system prompt's `## Sandbox` section:
`"Agent workspace access: ro (mounted at /workspace)"` (`src/agents/system-prompt.ts:533-538`).

Memory flush skip condition: `workspaceAccess === "ro" || workspaceAccess === "none"`
(confirmed by Section 4.8 and `team-research.md`).

### 7.8 DM Pairing Protocol (Step-by-Step)

The pairing protocol establishes trust for a new sender when `dmPolicy === "pairing"`:

1. **Inbound message from unknown sender**: `resolveDmGroupAccessDecision()` returns `decision = "pairing"`.
2. **Pairing initiation**: Channel adapter sends a QR code or pairing PIN to the unknown sender's chat.
3. **Pairing store**: Approved senders are written to a persistent pairing store via
   `readChannelAllowFromStore(provider, env, accountId)` (`src/pairing/pairing-store.ts`).
4. **Subsequent messages**: `readStoreAllowFromForDmPolicy()` reads the pairing store and merges
   it with `config.allowFrom` into `storeAllowFrom`. The combined `effectiveAllowFrom` now
   includes the newly approved sender, so `isSenderAllowed(effectiveAllowFrom)` returns `true`.
5. **Result**: Decision becomes `"allow"` (`DM_POLICY_ALLOWLISTED`).

The pairing store entries are **not** read for `dmPolicy === "allowlist"` — that mode relies
exclusively on config.

### 7.9 Complete Configuration Reference

All configuration keys relevant to multi-user memory and session behavior:

#### Session Keys

| Config key | TypeScript type | Default | Env var | Description |
|---|---|---|---|---|
| `session.dmScope` | `"main" \| "per-peer" \| "per-channel-peer" \| "per-account-channel-peer"` | `"main"` | — | Controls session key shape for DMs. `"main"` = all DMs share one session. |
| `session.mainKey` | `string` | `"main"` | — | The session key suffix used when `dmScope = "main"` |
| `session.identityLinks` | `Record<string, string[]>` | `{}` | — | Maps canonical name to `["channel:peerId", ...]` or `["peerId"]`. Replaces peerId in session keys when `dmScope !== "main"`. |

#### Agent Configuration

| Config key | TypeScript type | Default | Env var | Description |
|---|---|---|---|---|
| `agents.list[].id` | `string` | — | — | Agent identifier; normalized to lowercase, max 64 chars. Used in `agent:<id>:` session key prefix. |
| `agents.list[].workspace` | `string` | — | — | Custom workspace dir for this agent. Overrides default resolution. |
| `agents.list[].agentDir` | `string` | — | — | Custom agent state dir (sessions, etc). Defaults to `~/.openclaw/state/agents/<id>/agent`. |
| `agents.list[].model` | `string \| { primary: string; fallbacks?: string[] }` | — | — | Model override for this agent. |
| `agents.list[].identity.name` | `string` | — | — | Agent display name; used in `messagePrefix` (`[<name>]`). |
| `agents.list[].identity.emoji` | `string` | `"👀"` | — | Default `ackReaction` emoji (L4 fallback). |
| `agents.defaults.contextTokens` | `number` | — (no cap) | — | Cap on context window. Cannot exceed model's reported window. Applied as `source="agentContextTokens"`. |
| `agents.defaults.workspace` | `string` | `"~/.openclaw/workspace"` | `OPENCLAW_PROFILE` | Default workspace dir (for default agent only). If `OPENCLAW_PROFILE` is set and not `"default"`, becomes `~/.openclaw/workspace-<profile>`. |
| `agents.defaults.sandbox.mode` | `"docker" \| "ssh"` | — (disabled) | — | Sandbox backend type. |

#### Memory Configuration

| Config key | TypeScript type | Default | Env var | Description |
|---|---|---|---|---|
| `memory.vectorWeight` | `number` | `0.7` | — | Vector score weight in hybrid search (must sum to 1 with `textWeight`). |
| `memory.textWeight` | `number` | `0.3` | — | BM25 text score weight in hybrid search. |
| `memory.maxResults` | `number` | `6` | — | Maximum search results returned per query. |
| `memory.minScore` | `number` | `0.35` | — | Minimum similarity score threshold (results below this are dropped). |
| `memory.chunks.tokens` | `number` | `400` | — | Chunk size in tokens for indexing. |
| `memory.chunks.overlap` | `number` | `80` | — | Token overlap between consecutive chunks. |
| `memory.provider` | `"auto" \| "openai" \| "gemini" \| "voyage" \| "mistral" \| "ollama" \| "local"` | `"auto"` | — | Embedding provider. `"auto"` tries providers in order. |
| `memory.store.path` | `string` | `~/.openclaw/state/memory/<agentId>.sqlite` | — | SQLite vector store path. Supports `{agentId}` token substitution. |
| `memory.experimental.sessionMemory` | `boolean` | `false` | — | Enable Layer 3 JSONL transcript indexing. Must also add `"sessions"` to `sources`. |

#### Compaction Configuration

| Config key | TypeScript type | Default | Env var | Description |
|---|---|---|---|---|
| `compaction.postIndexSync` | `"off" \| "async" \| "await"` | `"async"` | — | Post-compaction memory index sync mode. `"async"` fires without waiting; `"await"` blocks until sync completes. |
| `compaction.timeoutSeconds` | `number` | `900` (15 min) | — | Hard timeout for the compaction LLM call. |
| `compaction.model` | `string` | (same as session model) | — | Override model for compaction summarization. Format: `"<provider>/<modelId>"`. |
| `compaction.memoryFlush.enabled` | `boolean` | `true` | — | Enable pre-compaction memory flush turn. |
| `compaction.memoryFlush.softThresholdTokens` | `number` | `4000` | — | Tokens remaining before compaction that trigger the flush. |

#### Channel Security

| Config key | TypeScript type | Default | Env var | Description |
|---|---|---|---|---|
| `channels.<channel>.allowFrom` | `Array<string \| number>` | `[]` | — | Allowlisted sender IDs for DMs. Used by all DM policies. |
| `channels.<channel>.dmPolicy` | `"open" \| "disabled" \| "pairing" \| "allowlist"` | `"pairing"` | — | DM access policy. |
| `channels.<channel>.groupPolicy` | `"open" \| "disabled" \| "allowlist"` | `"allowlist"` | — | Group message access policy. |
| `channels.<channel>.dmHistoryLimit` | `number` | — (unlimited) | — | Max user turns kept for DM sessions for this channel. |
| `channels.<channel>.historyLimit` | `number` | — (unlimited) | — | Max user turns kept for group/channel sessions. |
| `channels.<channel>.dms.<userId>.historyLimit` | `number` | — | — | Per-user DM history limit (overrides `dmHistoryLimit`). |

#### Session Store & Runtime

| Config key | TypeScript type | Default | Env var | Description |
|---|---|---|---|---|
| `sessions.maintenance.mode` | `"warn" \| "enforce"` | `"warn"` | — | Maintenance mode. `"warn"` logs only; `"enforce"` applies pruning/rotation. |
| `sessions.maintenance.pruneAfter` | `string` (duration, e.g. `"30d"`) | `"30d"` | — | Prune sessions older than this. |
| `sessions.maintenance.maxEntries` | `number` | `500` | — | Max entries cap in `sessions.json`. |
| `sessions.maintenance.rotateBytes` | `number` | `10485760` (10 MB) | — | Rotate `sessions.json` when it exceeds this size. |
| *(env)* | — | `45000` (45s) | `OPENCLAW_SESSION_CACHE_TTL_MS` | In-process TTL cache duration for `sessions.json` reads. Set `0` to disable cache. |
| *(env)* | — | `~/.openclaw/workspace` | `OPENCLAW_PROFILE` | Changes the workspace dir. Does **not** affect the state dir (`~/.openclaw/state/`). Profile `"default"` is treated as unset. |

---

## Section 8: Build-It-Yourself — Multi-User Memory System

This section provides a step-by-step guide for implementing a multi-user memory system equivalent
to OpenClaw's from scratch in a new TypeScript/Node.js project.

---

### Step 1: Session Key Generator

**What to implement**: A function that takes an inbound message's metadata (channel, sender ID,
account ID, scope config) and returns a deterministic, normalized string session key.

**Key dependencies**: none (pure string manipulation)

**Pseudocode skeleton**:

```typescript
type DmScope = "main" | "per-peer" | "per-channel-peer" | "per-account-channel-peer";

function buildSessionKey(params: {
  agentId: string;               // e.g. "main"
  channel: string;               // e.g. "whatsapp"
  peerId: string;                // e.g. "919876543210"
  peerKind: "direct" | "group" | "channel";
  accountId?: string;            // e.g. "default"
  dmScope: DmScope;
  mainKey?: string;              // default "main"
  identityLinks?: Record<string, string[]>;
  threadId?: string;
}): string {
  // 1. Normalize all inputs to lowercase
  const agentId = normalizeAgentId(params.agentId);  // slug, max 64 chars
  const channel = params.channel.trim().toLowerCase();
  const peerId = params.peerId.trim().toLowerCase();
  const accountId = (params.accountId ?? "default").trim().toLowerCase();

  // 2. For groups/channels: key is always per-chat (ignore dmScope)
  if (params.peerKind !== "direct") {
    const base = `agent:${agentId}:${channel}:${params.peerKind}:${peerId}`;
    if (params.threadId) {
      return `${base}:thread:${params.threadId.toLowerCase()}`;
    }
    return base;
  }

  // 3. Resolve identity link (replaces peerId with canonical name)
  const resolvedPeerId = resolveLinkedPeerId({
    peerId,
    channel,
    identityLinks: params.identityLinks,
    dmScope: params.dmScope,
  }) ?? peerId;

  // 4. Build DM key by scope
  let base: string;
  switch (params.dmScope) {
    case "main":
      base = `agent:${agentId}:${params.mainKey ?? "main"}`;
      break;
    case "per-peer":
      base = `agent:${agentId}:direct:${resolvedPeerId}`;
      break;
    case "per-channel-peer":
      base = `agent:${agentId}:${channel}:direct:${resolvedPeerId}`;
      break;
    case "per-account-channel-peer":
      base = `agent:${agentId}:${channel}:${accountId}:direct:${resolvedPeerId}`;
      break;
  }

  // 5. Append thread suffix
  if (params.threadId && params.dmScope !== "main") {
    return `${base}:thread:${params.threadId.toLowerCase()}`;
  }
  return base;
}
```

**Edge cases**:
- `peerId` with special characters: replace invalid chars with `-`, strip leading/trailing dashes
- Empty `peerId`: fall back to `"unknown"`
- Thread IDs on `"main"` scope: ignored (no thread suffix for shared sessions)

**How to test**: Create a table of (channel, peerId, scope) inputs and assert the output key string
matches the expected format. Test each `dmScope` variant and the identity link substitution path.

---

### Step 2: Session Store

**What to implement**: A file-based store of session entries, keyed by session key.

**Key dependencies**: `node:fs/promises`, `node:crypto` (for UUID generation)

**Pseudocode skeleton**:

```typescript
// ~/.yourapp/state/agents/<agentId>/sessions/sessions.json
// Format: Record<string, SessionEntry>

async function updateSessionStore(
  storePath: string,
  sessionKey: string,
  patch: Partial<SessionEntry>,
): Promise<SessionEntry> {
  // 1. Acquire per-path async FIFO lock (prevent concurrent writes)
  return await withFileLock(storePath, async () => {
    // 2. Re-read from disk inside lock (skip any in-memory cache)
    const store = await readSessionStore(storePath, { skipCache: true });

    // 3. Normalize key to lowercase
    const normalizedKey = sessionKey.toLowerCase();

    // 4. Merge patch into existing entry (or create new)
    const existing = store[normalizedKey];
    const merged = mergeSessionEntry(existing, patch);
    store[normalizedKey] = merged;

    // 5. Atomic write: temp file -> rename
    const tmp = `${storePath}.tmp-${process.pid}-${Date.now()}`;
    await fs.writeFile(tmp, JSON.stringify(store, null, 2), { encoding: "utf-8", mode: 0o600 });
    await fs.rename(tmp, storePath);  // atomic on POSIX

    // 6. Update in-process cache
    updateCache(storePath, store);

    return merged;
  });
}
```

**Gotchas**:
- Windows: `fs.rename` over existing file can fail. Retry up to 5 times with 50ms backoff.
- Windows: A 0-byte file may be read mid-write. Retry `readFile` up to 3 times on empty result.
- `sessionId` must be a stable UUID — assign once at entry creation, never change.

**How to test**: Write two concurrent updates for the same key, assert no data loss.

---

### Step 3: Transcript Manager

**What to implement**: An append-only JSONL writer/reader for conversation history.

**Key dependencies**: `node:fs/promises`, token counting library (e.g. `tiktoken`)

**Pseudocode skeleton**:

```typescript
// File: ~/.yourapp/state/agents/<agentId>/sessions/<sessionId>.jsonl

async function appendMessage(transcriptPath: string, message: AgentMessage): Promise<void> {
  const line = JSON.stringify(message) + "\n";
  await fs.appendFile(transcriptPath, line, "utf-8");
}

async function loadMessages(
  transcriptPath: string,
  limit?: number,  // max user turns to keep
): Promise<AgentMessage[]> {
  const raw = await fs.readFile(transcriptPath, "utf-8").catch(() => "");
  const messages = raw
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as AgentMessage);

  return limit ? limitHistoryTurns(messages, limit) : messages;
}

function limitHistoryTurns(messages: AgentMessage[], limit: number): AgentMessage[] {
  // Walk backwards, count user turns, slice from oldest-kept
  let userCount = 0;
  let lastUserIndex = messages.length;
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user") {
      userCount++;
      if (userCount > limit) return messages.slice(lastUserIndex);
      lastUserIndex = i;
    }
  }
  return messages;
}
```

**Edge cases**:
- JSONL lines with invalid JSON: skip and log, do not throw
- Empty file on first session: return `[]`
- After compaction: file is rewritten from `firstKeptEntryId` onward with a prepended summary message

**How to test**: Write 10 messages, read back with `limit=3`, assert only 3 user turns returned.

---

### Step 4: Memory Manager

**What to implement**: Tools for reading/writing persistent notes (`MEMORY.md`, `USER.md`) and the
optional SQLite vector store.

**Key dependencies**: `sqlite-vec` (or `better-sqlite3` + vector extension), `tiktoken`

**Pseudocode skeleton**:

```typescript
// Workspace markdown files (Layer 1): loaded as static context
async function loadBootstrapFiles(workspaceDir: string, sessionKey?: string): Promise<ContextFile[]> {
  const filenames = isSubagentOrCronKey(sessionKey)
    ? ["AGENTS.md", "TOOLS.md", "SOUL.md", "IDENTITY.md", "USER.md"]
    : ["AGENTS.md", "SOUL.md", "TOOLS.md", "IDENTITY.md", "USER.md", "HEARTBEAT.md", "BOOTSTRAP.md", "MEMORY.md"];

  const files: ContextFile[] = [];
  for (const name of filenames) {
    const filePath = path.join(workspaceDir, name);
    try {
      const content = await fs.readFile(filePath, "utf-8");
      // Enforce 2 MB max per file
      const truncated = content.slice(0, 2 * 1024 * 1024);
      files.push({ name, path: filePath, content: truncated });
    } catch (err) {
      if ((err as { code?: string }).code !== "ENOENT") throw err;
      // Missing files are silently skipped
    }
  }
  return files;
}

// Daily notes tool (Layer 1, writable): agent writes memories here
async function appendDailyNote(workspaceDir: string, note: string): Promise<void> {
  const date = new Date().toISOString().slice(0, 10);  // YYYY-MM-DD
  const memDir = path.join(workspaceDir, "memory");
  await fs.mkdir(memDir, { recursive: true });
  await fs.appendFile(path.join(memDir, `${date}.md`), `\n${note}\n`, "utf-8");
}
```

**Gotchas**:
- `MEMORY.md` vs `memory.md`: on case-insensitive FSes, do NOT use `realpath` to dedup — try
  the uppercase name first, then the lowercase name, and use the first one found.
- Memory flush is skipped if sandbox `workspaceAccess` is `"ro"` or `"none"`.

**How to test**: Write a note, reload bootstrap files, assert note appears in context.

---

### Step 5: Compaction Engine

**What to implement**: A system that summarizes old conversation history when the context window
fills up, then rewrites the JSONL file.

**Key dependencies**: LLM client (Anthropic SDK), token counter, JSONL utils

**Pseudocode skeleton**:

```typescript
async function compactSession(params: {
  transcriptPath: string;
  contextWindowTokens: number;  // from resolveContextWindowInfo
  llmClient: LlmClient;
}): Promise<CompactResult> {
  const messages = await loadMessages(params.transcriptPath);
  const tokens = estimateTokens(messages);

  // Only compact if above threshold
  if (tokens < params.contextWindowTokens * 0.8) {
    return { ok: true, compacted: false, reason: "below threshold" };
  }

  // Step 1: Strip tool result details before LLM call (security)
  const stripped = stripToolResultDetails(messages);

  // Step 2: Split into N chunks by token share
  const chunks = splitByTokenShare(stripped, 2);  // DEFAULT_PARTS = 2

  // Step 3: Summarize each chunk independently
  const summaries = await Promise.all(
    chunks.map((chunk) => summarize(chunk, params.llmClient))
  );

  // Step 4: Merge partial summaries
  const finalSummary = await mergeSummaries(summaries, params.llmClient);

  // Step 5: Rewrite JSONL: summary message + messages after firstKeptEntryId
  const firstKeptEntry = messages[Math.floor(messages.length / 2)];
  const kept = messages.slice(messages.indexOf(firstKeptEntry));
  await rewriteTranscript(params.transcriptPath, finalSummary, kept);

  // Step 6: Repair orphaned tool_use/tool_result pairs
  const repaired = repairToolUseResultPairing(kept);

  return {
    ok: true,
    compacted: true,
    result: { summary: finalSummary, firstKeptEntryId: firstKeptEntry.id,
              tokensBefore: tokens, tokensAfter: estimateTokens(repaired.messages) }
  };
}
```

**Gotchas**:
- Always call `stripToolResultDetails()` before any compaction LLM call (prevent injection, sensitive data leakage)
- Always call `repairToolUseResultPairing()` after any chunk drop (prevent Anthropic API errors)
- Use a 15-minute safety timeout — compaction LLM calls can be slow
- One flush per compaction cycle: track `memoryFlushCompactionCount` in session entry

**How to test**: Fill a transcript past the threshold, trigger compaction, assert token count drops
and summary is prepended.

---

### Step 6: Context Assembler

**What to implement**: The function that builds the final `messages[]` array and `systemPrompt`
string for each LLM request.

**Key dependencies**: Steps 3, 4, 5 outputs; `buildAgentSystemPrompt()` equivalent

**Pseudocode skeleton**:

```typescript
async function assembleContext(params: {
  sessionKey: string;
  workspaceDir: string;
  config: Config;
  agentId: string;
}): Promise<{ systemPrompt: string; messages: AgentMessage[] }> {
  // 1. Resolve context window
  const { tokens: contextTokens } = resolveContextWindowInfo({
    cfg: params.config,
    provider: currentProvider,
    modelId: currentModelId,
    modelContextWindow: modelReportedWindow,
    defaultTokens: 200_000,
  });

  // 2. Load bootstrap context files (Layer 1)
  const contextFiles = await loadBootstrapFiles(params.workspaceDir, params.sessionKey);

  // 3. Load conversation history (JSONL)
  const historyLimit = getHistoryLimitFromSessionKey(params.sessionKey, params.config);
  const messages = await loadMessages(transcriptPath(params.sessionKey), historyLimit);

  // 4. Build system prompt
  const systemPrompt = buildSystemPrompt({
    workspaceDir: params.workspaceDir,
    promptMode: isSubagentKey(params.sessionKey) ? "minimal" : "full",
    contextFiles,
    ownerNumbers: config.channels[channel]?.allowFrom ?? [],
    agentIdentity: resolveAgentConfig(params.config, params.agentId)?.identity,
    skillsPrompt: resolvedSkillsPrompt,
    extraSystemPrompt: resolveExtraSystemPrompt(params.sessionKey),
    toolNames: availableTools,
  });

  return { systemPrompt, messages };
}
```

**Edge cases**:
- Guard against `contextTokens < 16000` (hard min) — block the session
- Warn when `contextTokens < 32000`
- If `contextFiles` total exceeds budget, truncate largest files first

**How to test**: Assert system prompt contains `## Tooling` and `# Project Context` sections.
Assert `messages` length respects `historyLimit`.

---

### Step 7: Identity Linker

**What to implement**: A config-based function that maps channel-specific peer IDs to canonical
names, enabling cross-channel session merging.

**Key dependencies**: Step 1 (used at routing time during session key construction)

**Pseudocode skeleton**:

```typescript
function resolveLinkedPeerId(params: {
  peerId: string;
  channel: string;
  identityLinks?: Record<string, string[]>;
  dmScope: DmScope;
}): string | null {
  if (!params.identityLinks || params.dmScope === "main") {
    return null;  // no substitution needed
  }

  const peerId = params.peerId.toLowerCase();
  const channelScoped = `${params.channel}:${peerId}`;
  const candidates = new Set([peerId, channelScoped]);

  for (const [canonicalName, ids] of Object.entries(params.identityLinks)) {
    for (const id of ids) {
      if (candidates.has(id.toLowerCase())) {
        return canonicalName;  // found — return canonical name
      }
    }
  }

  return null;  // no match — use original peerId
}
```

**Configuration example**:

```json
{
  "session": {
    "dmScope": "per-channel-peer",
    "identityLinks": {
      "alice": ["919876543210", "telegram:123456789"],
      "bob": ["slack:U01ABCDEF"]
    }
  }
}
```

**How to test**: Assert that WhatsApp `919876543210` and Telegram `123456789` both resolve to
`"alice"` when using `per-channel-peer` scope with the above config.

---

### Step 8: Multi-Agent Router

**What to implement**: A binding match engine that routes a session key to the correct agent
config and workspace.

**Key dependencies**: Step 1 (session key), Steps 3/4 (workspace files)

**Pseudocode skeleton**:

```typescript
function resolveSessionAgent(params: {
  sessionKey: string;
  config: Config;
}): { agentId: string; workspaceDir: string; agentConfig: ResolvedAgentConfig } {
  // 1. Parse agentId from session key prefix
  const parsed = parseAgentSessionKey(params.sessionKey);
  const agentId = parsed?.agentId ?? resolveDefaultAgentId(params.config);

  // 2. Look up agent config from agents.list[]
  const agentConfig = resolveAgentConfig(params.config, agentId) ?? {};

  // 3. Resolve workspace dir with 4-step priority
  const workspaceDir = resolveAgentWorkspaceDir(params.config, agentId);

  return { agentId, workspaceDir, agentConfig };
}
```

**Edge cases**:
- Agent ID from session key does not match any `agents.list[]` entry: run with defaults only
- Multiple agents with `default: true`: first one wins (log a warning)
- Non-default agent with no explicit workspace: use `<stateDir>/workspace-<agentId>`

**How to test**: Add two agents to config, build session keys for each, assert correct workspace dir
is resolved for each.

---

### Step 9: Security Layer

**What to implement**: DM policy check and allowlist enforcement before processing any inbound message.

**Key dependencies**: pairing store (for `"pairing"` policy), config

**Pseudocode skeleton**:

```typescript
async function checkMessageAccess(params: {
  channel: string;
  accountId: string;
  peerId: string;
  isGroup: boolean;
  config: Config;
}): Promise<"allow" | "block" | "pairing"> {
  const channelCfg = config.channels[params.channel] ?? {};
  const dmPolicy = channelCfg.dmPolicy ?? "pairing";
  const groupPolicy = channelCfg.groupPolicy ?? "allowlist";

  // Read pairing store only for non-"allowlist" DM policies
  const storeAllowFrom = (dmPolicy !== "allowlist" && !params.isGroup)
    ? await readPairingStore(params.channel, params.accountId)
    : [];

  const effectiveAllowFrom = [...(channelCfg.allowFrom ?? []), ...storeAllowFrom];
  const effectiveGroupAllowFrom = channelCfg.groupAllowFrom ?? channelCfg.allowFrom ?? [];

  const { decision } = resolveDmGroupAccessDecision({
    isGroup: params.isGroup,
    dmPolicy,
    groupPolicy,
    effectiveAllowFrom,
    effectiveGroupAllowFrom,
    isSenderAllowed: (allowFrom) => allowFrom.includes(params.peerId),
  });

  return decision;
}
```

**Gotchas**:
- Group messages never trigger pairing — only `"allow"` or `"block"`
- Pairing store entries supplement (not replace) config `allowFrom`
- Treat DM messages from unknown senders as untrusted even after pairing is approved

**How to test**: Test all four `dmPolicy` values with an allowlisted and non-allowlisted sender.
Assert `"pairing"` decision only from the `"pairing"` policy for unknown senders.

---

### Step 10: Per-Person Personality Adaptation

**What to implement**: SOUL.md rules and session routing patterns that adapt the agent's personality
per user.

**Approach — SOUL.md conditional sections**:

Write conditional personality rules in `SOUL.md` using the canonical identity link names:

```markdown
## Per-Person Style

When talking to **alice**: Technical, no-nonsense. Skip pleasantries. Use code examples.
When talking to **bob**: Casual and humorous. He likes pop culture references.
When talking to anyone else: Friendly but professional.
```

Since the peer ID or canonical name does **not** appear directly in the system prompt, use
`extraSystemPrompt` to inject this context at routing time:

```typescript
// At message routing time — after identity link resolution
const resolvedPeerId = resolveLinkedPeerId({ peerId, channel, identityLinks, dmScope });
const displayName = resolvedPeerId ?? peerId;

const extraSystemPrompt = `Current conversation partner: ${displayName}. ` +
  `Session key: ${sessionKey}. ` +
  `Apply SOUL.md per-person style rules for this user.`;
```

**Per-user USER.md** (advanced): For distinct workspace-per-user setups, assign each user their own
agent ID and workspace via `agents.list[]`. Each agent gets their own `USER.md` with user-specific
profile information:

```json
{
  "agents": {
    "list": [
      { "id": "alice-agent", "workspace": "~/.yourapp/workspaces/alice" },
      { "id": "bob-agent", "workspace": "~/.yourapp/workspaces/bob" }
    ]
  }
}
```

Session keys for Alice: `agent:alice-agent:whatsapp:direct:alice`
Session keys for Bob: `agent:bob-agent:whatsapp:direct:bob`

**How to test**: Send a message as `"alice"` (identity-linked), assert `extraSystemPrompt` contains
`"alice"`, and assert `SOUL.md` per-person section is visible in the assembled system prompt.