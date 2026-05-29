# Feature Implementation Phases

This folder documents how five key feature areas are implemented in OpenClaw —
from the tools exposed to agents through to the underlying infrastructure that
makes them work safely and reliably.

---

## Phases

| Phase | Title | Summary |
|-------|-------|---------|
| [Phase 1](phase-1-execution-tools.md) | Execution Tools | `exec`, `process`, and `code_execution` — shell commands, background jobs, PTY sessions, approval gates, xAI remote code interpreter |
| [Phase 2](phase-2-media.md) | Media & Document Sharing | End-to-end media pipeline: inbound CDN downloads, gateway offloading, MIME sniffing, media understanding, async delivery queue, per-channel outbound adapters |
| [Phase 3](phase-3-browser.md) | Headless Browser (Playwright) | Browser tool wrapping Playwright: click, type, fill, navigate, screenshot, snapshots, SSRF-safe navigation, session tab tracking |
| [Phase 4](phase-4-multi-file-ops.md) | Multi-File Operations | read/write/edit tools with adaptive paging, sandbox mount system, path traversal guards, policy layers, atomic writes, pluggable `SandboxFsBridge` |
| [Phase 5](phase-5-process-management.md) | Process Management | Process supervisor, PTY and child adapters, session registry, output streaming, background jobs, graceful kill strategies (Unix + Windows) |

---

## High-Level Data Flow

```
Agent Tool Call
      │
      ├─ Execution Tools (Phase 1)
      │    exec → ProcessSupervisor → PTY/child adapter → output stream
      │    process → SessionRegistry → poll / write / kill
      │    code_execution → xAI API → Python sandbox
      │
      ├─ Media Pipeline (Phase 2)
      │    inbound:  channel CDN → gateway offload → MediaUnderstanding
      │    outbound: tool result → extractMedia() → DeliveryQueue → channel adapter
      │
      ├─ Browser Tool (Phase 3)
      │    action → HTTP API → Playwright Page → SSRF guard → result
      │    snapshot → AI/ARIA tree → roleRefs cache → act refs
      │
      ├─ File Operations (Phase 4)
      │    read/write/edit → SandboxFsBridge → path guard → mount → disk
      │    paging: adaptive page size based on model context window
      │
      └─ Process Management (Phase 5)
           spawn → supervisor → adapter → RunRecord
           output: event-driven → session.aggregated → pending buffers
           cleanup: SIGTERM → grace → SIGKILL (Unix) / taskkill (Windows)
```

---

## Key Shared Concepts

| Concept | Used By | Description |
|---------|---------|-------------|
| `SandboxContext` | Phases 1, 4 | Session-scoped container config; workspace paths, access level, tool policy |
| `AbortSignal` | Phases 1, 3, 4 | Propagated from session cancel to every in-flight tool call |
| `AnyAgentTool` | All phases | Uniform tool interface; policies and hooks apply to all tools equally |
| `applyToolPolicyPipeline` | All phases | Layered allow/deny filtering before any tool executes |
| SSRF policy | Phases 2, 3 | Hostname allowlists, pinned DNS resolution, redirect chain validation |
| Approval gates | Phase 1 | Allowlist + safe-binary profiles; operator approval for exec on gateway host |
| `SandboxFsBridge` | Phases 1, 4 | Pluggable FS abstraction for Docker, SSH, OpenShell, and custom backends |
| Delivery queue | Phase 2 | Persistent retry queue for async media delivery to channels |
| WeakMap metadata | Phase 3 | Page state GC'd automatically on tab close; no explicit cleanup needed |
| Scope-based cancel | Phases 1, 5 | All processes in a session share a `scopeKey`; one call kills them all |
