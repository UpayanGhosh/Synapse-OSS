# Phase 1: Execution Tools (exec, process, code_execution)

## Overview

OpenClaw provides three execution tools that cover different use cases: `exec` for
synchronous and background shell command execution, `process` for managing and
interacting with backgrounded jobs, and `code_execution` for remote sandboxed
Python analysis via xAI. All three share a layered security model: sandbox isolation,
allowlist-based approval, environment sanitization, and AbortSignal propagation.

---

## Key Files

| File | Role |
|------|------|
| `src/agents/bash-tools.exec.ts` | `exec` tool factory + core logic |
| `src/agents/bash-tools.exec-types.ts` | `ExecToolDetails` discriminated union |
| `src/agents/bash-tools.exec-runtime.ts` | `runExecProcess()` — params schema, streaming |
| `src/agents/bash-tools.exec-host-gateway.ts` | Gateway (local host) execution path |
| `src/agents/bash-tools.exec-host-node.ts` | Remote node execution path |
| `src/agents/bash-tools.exec-approval-request.ts` | Approval flow registration + routing |
| `src/agents/bash-tools.exec-host-shared.ts` | Shared approval analysis helpers |
| `src/agents/bash-tools.process.ts` | `process` tool — poll, log, write, kill |
| `src/agents/bash-process-registry.ts` | Session registry + TTL sweeper |
| `src/process/supervisor/supervisor.ts` | Process supervisor (spawn, cancel, scope) |
| `src/process/supervisor/types.ts` | `ManagedRun`, `RunRecord`, `RunExit` |
| `src/infra/exec-approvals.ts` | Approval config file parsing |
| `src/infra/exec-approvals-analysis.ts` | Command analysis for approval decisions |
| `src/infra/abort-signal.ts` | `waitForAbortSignal()` utility |
| `src/agents/pi-tools.abort.ts` | `wrapToolWithAbortSignal()` — multi-signal compose |
| `src/agents/sandbox/types.ts` | `SandboxContext` type |
| `src/agents/sandbox-paths.ts` | `assertSandboxPath()` path guard |
| `extensions/xai/code-execution.ts` | `code_execution` tool factory (xAI) |
| `extensions/xai/src/code-execution-shared.ts` | xAI result types |

---

## Tool 1: `exec`

### Purpose

Runs shell commands with optional sandbox isolation, approval gating, PTY support,
and background continuation.

### Parameter Schema

```typescript
{
  command:    string                          // Required
  workdir?:   string                          // Defaults to session cwd
  env?:       Record<string, string>
  yieldMs?:   number                          // Background after N ms (default 10s)
  background?: boolean                        // Immediate background
  timeout?:   number                          // Seconds
  pty?:       boolean                         // Pseudo-terminal mode
  elevated?:  boolean                         // Elevated privilege (requires config)
  host?:      "auto" | "sandbox" | "gateway" | "node"
  security?:  "deny" | "allowlist" | "full"
  ask?:       "off" | "on-miss" | "always"
  node?:      string                          // Node ID when host=node
}
```

### Result Types (`ExecToolDetails`)

```typescript
type ExecToolDetails =
  | { status: "running";            sessionId; pid?; startedAt; cwd?; tail? }
  | { status: "completed";          exitCode; durationMs; aggregated; cwd? }
  | { status: "failed";             exitCode; durationMs; aggregated; cwd? }
  | { status: "approval-pending";   approvalId; approvalSlug; expiresAtMs; ... }
  | { status: "approval-unavailable"; reason; ... }
```

### Execution Hosts

| Host | Description |
|------|-------------|
| `sandbox` | Docker/SSH container with workspace isolation |
| `gateway` | Local host with approval gates |
| `node` | Remote paired node via companion app |
| `auto` | Selects sandbox if available, else gateway |

### Security Model

**Approval system** (`src/infra/exec-approvals.ts`):

Config at `exec-approvals.json`:
```json
{
  "version": 1,
  "socket": { "path": "...", "token": "..." },
  "defaults": { "security": "allowlist", "ask": "on-miss" },
  "agents": { "agent-id": { "allowlist": [...] } }
}
```

**Approval decision flow:**
```
Command received
│
├─ Check security mode
│    deny     → reject immediately
│    full     → execute without approval
│    allowlist → check allowlist + safe binary profiles
│
├─ Allowlist match? → execute
├─ No match + ask="off" → reject
└─ No match + ask="on-miss"/"always":
     ├─ Create ExecApprovalRequest (5 min TTL)
     ├─ Route to approval surface (DM/chat)
     └─ Poll for decision
```

**Additional security layers:**
- Environment sanitization: blocks `PATH` override and dangerous env vars on host
- Script preflight: detects shell variable injection leaks into Python/JS subprocesses
- Command analysis: strips wrappers (`env`, `command`, `exec`, `sudo`) to get canonical command
- Sandbox path guard: `assertSandboxPath()` blocks traversal and symlink escapes

### Exec Tool Creation (`src/agents/pi-tools.ts`)

```typescript
const execTool = createExecTool({
  host:     options?.exec?.host ?? execConfig.host,
  security: options?.exec?.security ?? execConfig.security,
  ask:      options?.exec?.ask ?? execConfig.ask,
  sandbox: sandbox ? {
    containerName:  sandbox.containerName,
    workspaceDir:   sandbox.workspaceDir,
    containerWorkdir: sandbox.containerWorkdir,
    env:            sandbox.backend?.env,
    buildExecSpec:  sandbox.backend?.buildExecSpec,
    finalizeExec:   sandbox.backend?.finalizeExec,
  } : undefined,
})
```

### SandboxContext

```typescript
type SandboxContext = {
  enabled: boolean
  backendId: "docker" | "ssh"
  sessionKey: string
  workspaceDir: string             // Host workspace mount point
  agentWorkspaceDir: string        // Agent's workspace (may be read-only)
  workspaceAccess: "none" | "ro" | "rw"
  runtimeId: string                // Container/VM ID
  containerName: string
  containerWorkdir: string         // Container-side path (e.g., /workspace)
  docker: SandboxDockerConfig
  tools: SandboxToolPolicy
  fsBridge?: SandboxFsBridge       // FS bridge for read-only workspaces
  backend?: SandboxBackendHandle
}
```

---

## Tool 2: `process`

### Purpose

Manages backgrounded `exec` sessions — polling output, sending stdin, killing jobs.

### Actions

| Action | Description |
|--------|-------------|
| `list` | List running + finished sessions (status, duration, pid) |
| `poll` | Wait for new output (optional timeout), returns exit status when done |
| `log` | Retrieve paginated output (offset/limit, default: last 200 lines) |
| `write` | Write data to stdin with optional EOF |
| `send-keys` | Send key sequences (arrows, special keys, hex bytes, literal text) |
| `submit` | Send carriage return (confirm in interactive shell) |
| `paste` | Paste text with bracketed-paste mode |
| `kill` | Terminate session (SIGKILL) |
| `clear` | Archive a finished session |
| `remove` | Kill running session or remove finished one |

### ProcessSession

```typescript
type ProcessSession = {
  id: string
  command: string
  pid?: number
  startedAt: number
  cwd?: string
  aggregated: string          // Full output buffer (default cap: 200KB)
  tail: string                // Last 2000 chars
  exitCode?: number
  exitSignal?: NodeJS.Signals
  exited: boolean
  backgrounded: boolean
  cursorKeyMode: "unknown" | "normal" | "application"
  maxOutputChars: number
  pendingStdout: string[]     // Buffered new output (cap: 30KB)
  pendingStderr: string[]
  truncated: boolean
}
```

### Output Limits

| Buffer | Default Cap | Env Override |
|--------|------------|--------------|
| `aggregated` | 200KB | `PI_BASH_MAX_OUTPUT_CHARS` |
| `pendingStdout/Stderr` | 30KB | `OPENCLAW_BASH_PENDING_MAX_OUTPUT_CHARS` |
| `tail` | 2000 chars | — |
| Log tail default | 200 lines | — |
| Job TTL | 30 minutes | `PI_BASH_JOB_TTL_MS` |

---

## Tool 3: `code_execution`

### Purpose

Runs Python code analysis tasks remotely using xAI's code interpreter API.
The agent submits a natural-language task; xAI generates and executes Python code
server-side in a sandboxed environment.

**Location:** `extensions/xai/code-execution.ts`

### Configuration

```typescript
type CodeExecutionConfig = {
  enabled?: boolean
  model?: string            // Default: "grok-4-1-fast"
  maxTurns?: number
  timeoutSeconds?: number   // Default: 30
}
```

### Parameter Schema

```typescript
{ task: string }  // Full analysis task description with data
```

### Result

```typescript
{
  task: string
  provider: "xai"
  model: string
  tookMs: number
  content: string           // LLM text response + code output
  citations: string[]
  usedCodeExecution: boolean
  outputTypes: string[]     // Includes "code_interpreter_call"
}
```

API target: `POST https://api.x.ai/v1/responses` with `code_interpreter` tool enabled.
Language support: Python only (via xAI's hosted interpreter).

---

## Shared Infrastructure

### AbortSignal Handling

All execution tools receive and propagate abort signals:

```typescript
// Multi-signal composition
wrapToolWithAbortSignal(tool, abortSignal?)
// Uses AbortSignal.any() to combine tool-call abort + external session abort
```

When the session is cancelled:
- Signal propagates to the running subprocess
- `exec` returns `{ status: "failed", exitCode: null }`
- `process` pending polls resolve immediately
- `code_execution` HTTP request is aborted

### Process Supervisor Flow

```
exec tool called
│
├─ createExecTool() dispatches to host resolver
│
├─ Gateway host:
│    ├─ Approval check (allowlist → approve/request/deny)
│    └─ runExecProcess(command, session)
│
├─ Sandbox host:
│    ├─ buildExecSpec() maps command to container execution spec
│    └─ runExecProcess(spec, session)
│
├─ Node host:
│    ├─ node.invoke("system.run", ...) via gateway RPC
│    └─ Approval chained to node authorization
│
└─ runExecProcess():
     ├─ supervisor.spawn({ command, usePty, scopeKey })
     ├─ Adapter: PTY or child_process.spawn()
     ├─ Output streaming → session.aggregated
     ├─ yieldMs timeout → markBackgrounded(session)
     └─ Returns ManagedRun { pid, wait(), cancel() }
```

### Approval Request Lifecycle

```typescript
type ExecApprovalRequest = {
  id: string              // UUID
  request: ExecApprovalRequestPayload
  createdAtMs: number
  expiresAtMs: number     // Default: 5 minutes
}

type ExecApprovalRegistration = {
  approvalId: string
  approvalSlug: string    // Human-readable short ID
  warningText: string
  expiresAtMs: number
  initiatingSurface: ExecApprovalInitiatingSurfaceState
  sentApproverDms: boolean
  unavailableReason?: ExecApprovalUnavailableReason
}
```

---

## End-to-End Flow: `exec` → background → `process poll`

```
Agent calls exec { command: "npm run build", yieldMs: 15000 }
│
├─ createExecTool() → resolveHost() → gateway
├─ analyzeCommandForApproval() → allowlist check
├─ Allowlisted → runExecProcess()
│    ├─ supervisor.spawn({ command, scopeKey: sessionId })
│    ├─ child_process.spawn() → pid tracked
│    ├─ stdout/stderr → appendOutput(session, ...)
│    └─ yieldMs=15000ms timer starts
│
├─ 15s elapses → markBackgrounded(session)
└─ exec returns { status: "running", sessionId: "abc123", pid: 1234 }

Agent calls process { action: "poll", sessionId: "abc123", timeout: 30000 }
│
├─ getSession("abc123") → ProcessSession
├─ pendingStdout has data → return immediately with output
├─ No pending data → wait up to 30s for new output
└─ Process exits → return { status: "completed", exitCode: 0, ... }
```

---

## Key Invariants

1. **Defense in depth** — sandbox isolation + allowlist approval + env sanitization + path guards are all independent layers.
2. **Background persistence** — backgrounded sessions survive in the registry for up to 30 min (configurable) with full paginated output available.
3. **PTY when needed** — interactive applications (vim, fzf, curses) require `pty: true` to function correctly; PTY mode merges stdout/stderr into a single stream.
4. **Scope-tied cleanup** — all processes in a session share a `scopeKey`; `supervisor.cancelScope()` kills them all when the session ends.
5. **xAI isolation** — `code_execution` runs code server-side on xAI infrastructure; no local code execution occurs.
