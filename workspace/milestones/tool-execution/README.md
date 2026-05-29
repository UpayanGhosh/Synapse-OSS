# Milestone: Tool Execution for Synapse-OSS

## Problem

Synapse-OSS has tool infrastructure (MCP servers, Sentinel, ToolRegistry, MCP client) but **no active tool execution loop**. The LLM in `persona_chat()` receives `messages` only — never `tools=`. It cannot call tools, read files, search the web, or take actions during a WhatsApp conversation.

## Goal

When a user messages on WhatsApp, the LLM can autonomously decide to use tools (web search, memory query, file read, etc.), execute them, and incorporate results into its response — all governed by Sentinel and a layered policy pipeline.

## Reference Architecture

Studied from OpenClaw (`D:\Shreya\openclaw\milestones\`) — a 10-phase pipeline:

| OpenClaw Phase | What It Does | Synapse Equivalent |
|---|---|---|
| 0: Manifest Discovery | Scan disk for plugin JSON manifests | Not needed (no plugin system) |
| 1: Runtime Loading | Dynamic-import plugin entries, register tool factories | **Phase 1** — register built-in tool factories |
| 2: Tool Resolution | Invoke factories per-session, allowlist filtering | **Phase 1** — resolve tools with session context |
| 3: Core Tool Assembly | Create built-in tools, merge with plugin tools | **Phase 1** — unified `ToolRegistry` |
| 4: Tool Policy Pipeline | Layered allow/deny (global → profile → agent → group) | **Phase 4** — policy pipeline adapted for Synapse |
| 5: Hook Wiring | Before/after-tool-call middleware, loop detection | **Phase 4** — hooks + graduated loop detection |
| 6: Schema Transformation | Provider-specific schema normalization (Gemini, XAI, OpenAI quirks) | **Phase 2** — schema normalization via litellm + manual quirks |
| 7: Inference Loop | Stream response, parse tool_use, dispatch execution | **Phase 3** — core execution loop |
| 8: Result Processing | Normalize results, size guard, media extraction, parallel exec | **Phase 3** — result normalization + parallel execution |
| 9: HTTP Tool Invocation | `POST /tools/invoke` — direct tool call without LLM | **Phase 5** — HTTP tool endpoint |
| Orchestrator | Retry loop, auth rotation, context compaction, multi-agent | **Phase 3** — error recovery within the loop |

### Key Patterns Adopted from OpenClaw

1. **Factory pattern** — tools are `(context) -> Tool` callables, not static objects. Session context (sender, workspace, config) injected at resolution time.
2. **Graduated loop detection** — escalate from warning → error injection → hard block (not flat 3-strike kill).
3. **Stream normalization** — trim tool names, repair broken JSON args, handle unknown tool names gracefully.
4. **Result normalization** — heterogeneous returns (str, dict, None, exception) all map to a uniform `ToolResult` format.
5. **Parallel execution** — concurrent tool calls within a single turn via `asyncio.gather()`.
6. **Layered policy pipeline** — multiple independent security layers, each filterable.
7. **Provider schema quirks** — Gemini strips `$defs`/`default`, XAI rejects range keywords, OpenAI requires `additionalProperties: false`. litellm handles most, but not all.

## Phases

| Phase | Name | Depends On | Scope |
|-------|------|------------|-------|
| 1 | [Tool Registry & Factories](phase-1-tool-registry.md) | — | 1 created, 2 modified |
| 2 | [LLM Router Tool Support + Schema Normalization](phase-2-llm-tools.md) | — | 1 modified |
| 3 | [Execution Loop, Result Processing & Error Recovery](phase-3-execution-loop.md) | Phase 1 + 2 | 1 modified |
| 4 | [Safety Pipeline: Policy, Hooks & Loop Detection](phase-4-safety.md) | Phase 3 | 2 modified |
| 5 | [User Features & HTTP Tool Invocation](phase-5-user-features.md) | Phase 4 | 3 modified |

```
Phase 1 (Registry + Factories) ──┐
                                  ├──> Phase 3 (Loop + Results) ──> Phase 4 (Safety) ──> Phase 5 (UX + HTTP)
Phase 2 (Router + Schemas)    ──┘
```

Phases 1 and 2 can be developed in parallel. Phase 3 requires both. Phases 4 and 5 are sequential.

## Current State (as of 2026-04-01)

### What Exists
- **MCP Servers**: `tools_server.py` (web_search, read_file, write_file), `memory_server.py`, `conversation_server.py`, gmail, calendar, slack
- **MCP Client**: `mcp_client.py` — can connect to servers and call tools with timeout
- **Sentinel**: Fail-closed file governance — CRITICAL/PROTECTED/MONITORED/OPEN zones, audit trail
- **Legacy ToolRegistry**: `db/tools.py` — OpenAI-compatible `search_web` schema + Playwright/Crawl4AI impl
- **Integration Point**: `mcp_context` parameter flows through `worker.py` → `process_message_pipeline()` → `persona_chat()`

### What's Missing
- `SynapseLLMRouter.call()` has no `tools=` parameter
- `persona_chat()` has no tool execution loop
- No tool call parsing or stream normalization
- No result normalization (only basic truncation)
- No tool policy pipeline (only implicit Sentinel)
- No graduated loop detection
- No error recovery mid-loop (auth failure, context overflow)
- No parallel tool execution
- No HTTP direct tool invocation endpoint
- No user-visible tool usage feedback
