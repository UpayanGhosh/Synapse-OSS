# Specialized Tools — Gaps in Synapse-OSS

## Overview

This file covers four specialized openclaw capabilities that have no equivalent in Synapse-OSS: (1) remote Python code execution via the xAI code interpreter, (2) context-window-aware adaptive file reading, (3) the web UI (WebChat + Canvas host), and (4) the context engine for per-agent context management. Each is described with file paths, key types, and the gap.

---

## 1. xAI Remote Code Execution (`extensions/xai/code-execution.ts`)

### What openclaw Has

The xAI plugin exposes a `code_execution` tool that sends Python code to xAI's remote interpreter and streams back structured results (stdout, stderr, files, charts).

**Key functions** (`extensions/xai/code-execution.ts` + `src/code-execution-shared.ts`):

- `buildXaiCodeExecutionPayload(params)` — builds the API request body with code, model, max_turns, and timeout.
- `requestXaiCodeExecution(payload, apiKey)` — POSTs to xAI's LiveBench endpoint, streams SSE events.
- `resolveXaiCodeExecutionModel(config)` — resolves the model ID from plugin config (`xai.config.codeExecution.model`), defaulting to xAI's code interpreter model.
- `resolveXaiCodeExecutionMaxTurns(config)` — resolves max turns (default: 1).

**Config integration:**
- `plugins.entries.xai.config.codeExecution.enabled` — toggle.
- `plugins.entries.xai.config.codeExecution.model` — model override.
- `plugins.entries.xai.config.codeExecution.maxTurns` — multi-turn cap.
- `plugins.entries.xai.config.codeExecution.timeoutSeconds` — per-execution timeout.
- API key resolution: plugin config → `plugins.entries.xai.config.webSearch.apiKey` → legacy `tools.web.search.grok.apiKey`.

**Tool registration** — The tool is registered as a standard Pi agent tool. The agent can invoke it like any other tool: the model produces a `tool_use` block, openclaw executes `requestXaiCodeExecution`, returns the result as a `tool_result` block.

**Files:**
- `extensions/xai/code-execution.ts` (plugin entry point)
- `extensions/xai/src/code-execution-shared.ts` (shared request logic)
- `extensions/xai/code-execution.test.ts` (test suite)

### What Synapse-OSS Has

Synapse-OSS has no remote code execution tool. `workspace/db/tools.py` contains only `search_web`. There is no code sandbox, no streaming result parser, and no xAI integration.

### Gap Summary

No Python code execution capability — agents cannot run code, produce charts, or process data programmatically via a tool call.

### Implementation Notes

Port as a Python async tool function registered with the tool registry:
- `async def execute_code(code: str, model: str | None = None, max_turns: int = 1, timeout_seconds: int = 30) -> dict`
- Use `httpx.AsyncClient` to stream SSE from the xAI API.
- Parse SSE events: `{type: "stdout" | "stderr" | "file" | "chart" | "error" | "done", content: str}`.
- Return structured result dict.
- Config: `plugins.xai.code_execution.{enabled, model, max_turns, timeout_seconds}` in `synapse.json`.

---

## 2. Adaptive File Reading (`src/agents/pi-tools.read.ts`)

### What openclaw Has

openclaw wraps the base Pi SDK `read` tool with context-window-aware page sizing and image sanitization.

**Key constants and logic:**

```typescript
const DEFAULT_READ_PAGE_MAX_BYTES = 50 * 1024;       // 50 KB default page
const MAX_ADAPTIVE_READ_MAX_BYTES = 512 * 1024;      // 512 KB max page
const ADAPTIVE_READ_CONTEXT_SHARE = 0.2;              // 20% of context window
const CHARS_PER_TOKEN_ESTIMATE = 4;
const MAX_ADAPTIVE_READ_PAGES = 8;
```

`resolveAdaptiveReadMaxBytes(options)`:
- If the agent has a known context window size (`modelContextWindowTokens`), the read page is set to `min(contextWindowTokens * 4 * 0.2, 512KB)` — at most 20% of the context window per read page.
- Falls back to 50 KB if context window is unknown.

`READ_CONTINUATION_NOTICE_RE` — detects the continuation marker appended by the base tool (`[Showing lines N-M. Use offset=K to continue.]`) to track whether a read result was truncated.

**Image sanitization wrapper** — when the read tool returns an image (e.g. reading a PNG via file-magic), it applies `sanitizeToolResultImages` which enforces dimension and byte limits before the image reaches the model context.

**File tool wrappers:**
- `createReadTool` → wrapped with adaptive page size.
- `createEditTool` → wrapped with `wrapEditToolWithRecovery` for atomic write recovery.
- `createWriteTool` → direct pass-through with workspace-root confinement.
- All tools use `readFileWithinRoot` / `writeFileWithinRoot` / `appendFileWithinRoot` from `src/infra/fs-safe.ts` — rejects symlinks, path traversal, files outside workspace root.

**File:** `src/agents/pi-tools.read.ts`

### What Synapse-OSS Has

Synapse-OSS has no file-reading tool exposed to agents. Agent turns receive the prompt text and memory context only. There is no MCP tool or custom function for reading files, and no adaptive paging logic.

The `do_transcribe.py` script reads files directly, but it is not an agent-callable tool.

### Gap Summary

Agents in Synapse-OSS cannot read files from the filesystem. The adaptive page sizing logic (which prevents a single large file from filling the context window) is completely absent.

### Implementation Notes

1. Implement `read_file(path: str, offset: int = 0, limit: int | None = None) -> dict` as an async agent tool.
2. Adaptive page size: `max_bytes = min(context_window_tokens * 4 * 0.2, 512 * 1024)` where `context_window_tokens` is resolved from the model catalog.
3. Safety: reject paths containing `..`, null bytes, or paths outside the configured workspace root.
4. Reject symlinks (`os.path.islink`).
5. Return `{text: str, truncated: bool, next_offset: int | None}`.
6. For image files detected via MIME: return as base64 with size cap.

---

## 3. Web UI — WebChat + Canvas Host (`ui/`)

### What openclaw Has

openclaw ships a full web UI built with Lit/TypeScript + Vite:

```
ui/src/ui/
├── app.ts                    Main application shell
├── app-chat.ts               Chat panel: send/receive, streaming
├── app-channels.ts           Channel switcher
├── app-settings.ts           Settings panel
├── app-tool-stream.ts        Live tool execution stream display
├── app-render.ts             Message rendering pipeline
├── app-render-usage-tab.ts   Token usage display
├── app-scroll.ts             Scroll management
├── app-events.ts             WebSocket event handling
├── app-gateway.ts            Gateway connection management
├── app-lifecycle.ts          App lifecycle (connect/disconnect)
├── app-polling.ts            Polling fallback
├── chat/
│   ├── message-extract.ts      Message parsing
│   ├── message-normalizer.ts   Normalize message shapes
│   ├── slash-commands.ts       Slash command definitions
│   ├── slash-command-executor.ts  Command dispatch
│   ├── grouped-render.ts       Grouped message rendering
│   ├── attachment-support.ts   Attachment drag-and-drop
│   ├── export.ts               Chat export (Markdown/JSON)
│   ├── input-history.ts        Up-arrow input history
│   ├── search-match.ts         In-chat search
│   ├── pinned-messages.ts      Pinned message management
│   ├── copy-as-markdown.ts     Copy message as Markdown
│   └── session-cache.ts        Session list cache
└── assistant-identity.ts       Agent avatar/name display
```

**Capabilities:**
- Real-time streaming via WebSocket to the openclaw gateway.
- Tool execution stream: shows each tool call + result as it streams.
- Token usage tab with input/output/cache token counts.
- Slash commands (`/help`, `/model`, `/clear`, etc.) with autocomplete.
- Attachment drag-and-drop with inline preview.
- Chat export to Markdown or JSON.
- Input history (up/down arrow).
- In-chat search.
- Pinned messages.
- Multi-session switcher.
- Per-message copy-as-markdown.
- i18n support (`ui/src/i18n/`).

**Build:** Vite + `vitest` (browser + node test configs). `ui/vitest.config.ts`, `ui/vitest.node.config.ts`.

**Files:** `ui/src/`, `ui/vite.config.ts`

### What Synapse-OSS Has

`workspace/sci_fi_dashboard/ui_components.py` — `UIComponents` class:

- `create_header` — Rich terminal panel showing system name, status, uptime, CPU, memory, network health bar.
- `create_activity_stream` — terminal Rich table of recent activities.
- `create_sidebar` — quota watchdog, token usage percentage, memory tags.

This is a terminal dashboard rendered with the `rich` library — it is not a web UI and is not accessible from a browser. It has no WebSocket connection, no message streaming, no tool stream display, no settings panel, and no attachment support.

| Feature | Synapse-OSS | openclaw |
|---|---|---|
| Web UI (browser) | None (terminal only) | Full Lit/TypeScript SPA |
| WebSocket streaming | None | Full |
| Tool execution stream | None | Yes |
| Token usage display | Terminal only | Full UI tab |
| Slash commands | None | Yes with autocomplete |
| Attachment support | None | Drag-and-drop + preview |
| Chat export | None | Markdown + JSON |
| Input history | None | Up/down arrow |
| Multi-session switcher | None | Yes |
| In-chat search | None | Yes |
| Pinned messages | None | Yes |
| i18n | None | Yes |

### Gap Summary

Synapse-OSS has no browser-accessible UI. All interaction is via CLI (`main.py` interactive loop) or the Telegram/WhatsApp channel adapters. There is no session management UI, no tool stream visibility, and no way to inspect agent behavior without reading logs.

### Implementation Notes

Building a full web UI is a significant undertaking. Minimum viable steps:

1. Add a `/ui` route to `api_gateway.py` that serves a static HTML/JS SPA.
2. WebSocket endpoint at `/ws/{session_id}` that streams SSE-style events.
3. Frontend: React or plain HTML/JS chat interface that connects via WebSocket.
4. Stream tool calls and results as JSON events: `{type: "tool_start" | "tool_result" | "text" | "done", ...}`.
5. Session list endpoint: `GET /sessions` → `[{id, channel, last_message, last_at}]`.

---

## 4. Context Engine (`src/context-engine/`)

### What openclaw Has

```
src/context-engine/
├── index.ts                Main export
├── init.ts                 Engine initialization
├── delegate.ts             Context delegation (sub-agent contexts)
├── legacy.ts               Legacy context format migration
├── registry.ts             Per-agent context registry
├── types.ts                Context types
└── context-engine.test.ts  Tests
```

The context engine manages the per-agent prompt context beyond the raw conversation history. It handles:
- Context injection order (memory search results, system prompts, agent identity, tool results).
- Delegation of context from a parent agent to a sub-agent (so sub-agents see relevant parent context without the full history).
- Legacy context format migration for agents that predate the current context schema.
- A registry keyed by `agentDir` for singleton context managers per agent instance.

**File:** `src/context-engine/`

### What Synapse-OSS Has

Context management is handled inline in `api_gateway.py` — the system prompt is assembled by concatenating:
1. The persona from `SOUL.md` / `CORE.md` / `IDENTITY.md`.
2. The `ProactiveAwarenessEngine.context.compile_prompt_block()` output.
3. Retrieved memory chunks from `MemoryEngine`.

There is no delegation model, no registry, no context format migration, and no structured injection order.

### Gap Summary

Synapse-OSS has no context engine abstraction. Context assembly is ad-hoc string concatenation in the gateway. This makes it difficult to: (a) inject context in a consistent order, (b) support sub-agents with scoped context, (c) migrate context formats across versions.

### Implementation Notes

1. Create `ContextEngine` class with `inject(prompt_parts: list[ContextPart]) -> str` that applies a priority-ordered injection pipeline.
2. `ContextPart` types: `system_prompt`, `memory_results`, `proactive_context`, `agent_identity`, `tool_context`.
3. Registry: `Dict[agent_id, ContextEngine]` singleton.
4. Delegation: when spawning a sub-agent, pass a filtered context slice rather than the full history.
