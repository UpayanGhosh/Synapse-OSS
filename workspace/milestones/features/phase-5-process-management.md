# Phase 5: Process Management

## Overview

OpenClaw's process management system handles the full lifecycle of shell commands,
long-running services, background jobs, and interactive terminal sessions. It spans
from the moment `exec` is called to graceful or forced process cleanup — persisting
sessions across tool calls and supporting interactive stdin, output streaming, PTY
terminals, and per-OS signal strategies.

---

## Key Files

| File | Role |
|------|------|
| `src/process/supervisor/supervisor.ts` | Core orchestrator — spawn, cancel, track all runs |
| `src/process/supervisor/registry.ts` | In-memory registry of all `RunRecord` structs |
| `src/process/supervisor/types.ts` | Types: `ManagedRun`, `RunRecord`, `TerminationReason` |
| `src/process/supervisor/adapters/child.ts` | Node.js `child_process.spawn()` adapter |
| `src/process/supervisor/adapters/pty.ts` | PTY adapter via `@lydell/node-pty` |
| `src/process/kill-tree.ts` | Graceful + forced process-tree kill (Unix + Windows) |
| `src/agents/bash-process-registry.ts` | Per-session process state, output buffers, TTL |
| `src/agents/bash-tools.exec.ts` | `exec` tool — spawn entry point + backgrounding logic |
| `src/agents/bash-tools.exec-runtime.ts` | `runExecProcess()` — streaming, session assembly |
| `src/agents/bash-tools.process.ts` | `process` tool — poll, log, write, kill, send-keys |
| `src/shared/pid-alive.ts` | PID liveness check, zombie detection, PID recycling guard |
| `src/agents/bash-tools.exec-host-gateway.ts` | Gateway approval flow before exec |
| `src/agents/bash-tools.exec-host-node.ts` | Remote node execution host |

---

## Layer 1: Process Supervisor

`ProcessSupervisor` is the root coordinator. Every spawned process flows through it.

### Spawn Flow

```
supervisor.spawn(input)
│
├─ Generate runId (or use provided)
├─ Handle scope replacement:
│    replaceExistingScope: true → cancelScope(scopeKey) first
├─ Create RunRecord (state: "starting")
├─ Register in RunRegistry
│
├─ Pick adapter:
│    usePty: true  → createPtyAdapter()
│    usePty: false → createChildAdapter()
│
├─ Set up timeout watchers:
│    overallTimeoutMs → requestCancel("overall-timeout")
│    noOutputTimeoutMs → requestCancel("no-output-timeout")
│
└─ Return ManagedRun { runId, pid, wait(), cancel(), stdin }
```

### RunRecord Structure

```typescript
type RunRecord = {
  runId: string
  sessionId: string
  backendId: string
  pid?: number
  processGroupId?: number
  state: "starting" | "running" | "exiting" | "exited"
  terminationReason?: TerminationReason
  exitCode?: number
  exitSignal?: string
  startedAtMs: number
  lastOutputAtMs: number
  createdAtMs: number
  updatedAtMs: number
}
```

### Scope-Based Cancellation

Processes can be grouped by `scopeKey`:

```typescript
// Cancel all runs in a scope atomically
supervisor.cancelScope(scopeKey)
```

Used for per-agent cleanup — when a session ends, its entire scope is cancelled.

---

## Layer 2: Process Adapters

### Child Adapter (`adapters/child.ts`)

Wraps Node.js `child_process.spawn()`:

```typescript
spawn(command, args, {
  cwd, env,
  detached: !isServiceManaged,   // Unix: process group independence
  stdio: ["pipe", "pipe", "pipe"]
})
```

Service detection: if `OPENCLAW_SERVICE_MARKER` env var is set, `detached: false`
keeps children attached to systemd/launchd for clean service management.

### PTY Adapter (`adapters/pty.ts`)

Wraps `@lydell/node-pty` for interactive terminal sessions:

```typescript
spawn(shell, [shellArgs, command], {
  cwd, env,
  cols, rows,      // terminal dimensions
  name: "xterm"
})
```

PTY merges stdout and stderr into a single stream (terminal behavior).
Exposes `write()`, `onData()`, `onExit()`, `kill()`.

---

## Layer 3: Session Registry

`bash-process-registry.ts` maintains per-session process state across tool calls.

### ProcessSession Structure

```typescript
type ProcessSession = {
  id: string                          // session slug
  child?: ChildProcessWithoutNullStreams
  stdin?: SessionStdin                // writable for interactive input
  pid?: number
  startedAt: number
  cwd?: string
  pendingStdout: string[]             // buffered chunks (cap: 30KB)
  pendingStderr: string[]
  aggregated: string                  // full output (cap: 200KB default)
  tail: string                        // last 2000 chars
  truncated: boolean
  exited: boolean
  backgrounded: boolean
  cursorKeyMode: "unknown" | "normal" | "application"
}
```

### Registry Maps

```typescript
runningSessions:  Map<sessionId, ProcessSession>   // active processes
finishedSessions: Map<sessionId, FinishedSession>  // completed (TTL-pruned)
```

### Session TTL

```
DEFAULT_JOB_TTL_MS = 30 minutes
Sweeper interval = max(30s, TTL / 6)
```

Configurable via `PI_BASH_JOB_TTL_MS` env var or `setJobTtlMs()`.

---

## Layer 4: Output Streaming

### Stream Pipeline

```
adapter.onStdout(chunk)
│
├─ Detect PTY cursor key mode (SMKX/RMKX ANSI escapes)
├─ sanitizeBinaryOutput(chunk)
├─ appendOutput(session, "stdout", chunk)
│    ├─ Push to pendingStdout[]
│    ├─ Append to aggregated (capped at maxOutputChars)
│    ├─ Update tail (last 2000 chars)
│    └─ Set truncated: true if cap exceeded
└─ onUpdate() callback → streams chunk to UI
```

### Output Caps

| Buffer | Default Cap |
|--------|-------------|
| `pendingStdout` | 30KB |
| `pendingStderr` | 30KB |
| `aggregated` | 200KB |
| `tail` | 2000 chars |

---

## Layer 5: Backgrounding

Long-running tools can be backgrounded so the agent continues:

```
exec tool called with yieldMs=10000 (or background: true)
│
├─ Process spawns normally
├─ Output streams during yield window (10s default)
├─ yield timeout fires → markBackgrounded(session)
├─ exec tool returns { sessionId, backgrounded: true }
│
└─ Agent can later call process tool with sessionId to:
     poll    → get status + new output
     log     → paginated output with offset/limit
     write   → send stdin to process
     send-keys → terminal key sequences (arrows, ctrl+C, etc.)
     paste   → bracketed-paste mode
     submit  → send CR (confirm in interactive shell)
     kill    → request termination
     clear   → remove finished session
     remove  → kill + clear
```

`yieldMs` default from `PI_BASH_YIELD_MS` env var (default 10s).

---

## Layer 6: Signal Handling & Kill Strategy

### Unix Kill Flow (`kill-tree.ts`)

```
killProcessTree(pid, { graceMs: 3000 })
│
├─ Send SIGTERM to process group: process.kill(-pid, "SIGTERM")
├─ Wait graceMs (default 3s, clamped 0–60s)
│
├─ If still alive:
│    Send SIGKILL to process group: process.kill(-pid, "SIGKILL")
│
└─ If group already dead:
     Try direct PID kill: process.kill(pid, "SIGKILL")
```

Timeout is `unref()`d — never blocks Node.js exit.

### Windows Kill Flow (`kill-tree.ts`)

```
killProcessTree(pid, { graceMs: 3000 })
│
├─ taskkill /T /PID <pid>        (graceful, recursive children with /T)
├─ Wait graceMs (3s default)
├─ Check alive: process.kill(pid, 0)
│
└─ If still alive:
     taskkill /F /T /PID <pid>   (force kill + recursive with /F /T)
```

### Supervisor Cancellation

```typescript
supervisor.cancel(runId, reason)
// reason: "manual-cancel" | "overall-timeout" | "no-output-timeout"
//       | "spawn-error" | "signal" | "exit"
```

Always sends SIGKILL via the adapter. Grace period is handled at `killProcessTree` level.

---

## Layer 7: PID Utilities (`shared/pid-alive.ts`)

```typescript
isPidAlive(pid)
// → process.kill(pid, 0) — signal 0 is a no-op liveness check

getProcessStartTime(pid)
// → reads /proc/<pid>/stat on Linux
// → guards against PID recycling (new process reusing a dead PID)

isZombieProcess(pid)
// → reads /proc/<pid>/status for "Z" state on Linux
```

---

## Session Lifecycle (End-to-End)

```
1. SPAWN      supervisor.spawn() → RunRecord "starting"
2. RUNNING    adapter starts → pid tracked → state "running"
3. STREAMING  stdout/stderr chunks → appended to session.aggregated
4. YIELD      (if backgrounded) markBackgrounded() → tool returns
5. POLLING    agent calls process.poll() → reads new pending output
6. EXIT       process exits → wait() settles → markExited()
7. CLEANUP    stdio destroyed → listeners removed → child ref cleared
8. FINISHED   if backgrounded → moved to finishedSessions
9. TTL PRUNE  sweeper deletes finishedSessions after 30 min
```

---

## Cleanup on Session End

```typescript
// stdio destruction
child.stdin?.destroy()
child.stdout?.destroy()
child.stderr?.destroy()
child.removeAllListeners()

// PTY stdin wrapper
session.stdin?.destroy?.()

// Registry removal
delete session.child   // enables GC
runningSessions.delete(session.id)
finishedSessions.set(session.id, finishedEntry)
```

---

## Key Invariants

1. **No polling** — all output is event-driven; callbacks fire on data, exit, and error.
2. **PID recycling guard** — `getProcessStartTime()` detects reused PIDs on Linux.
3. **Cross-platform kill** — graceful SIGTERM→SIGKILL on Unix; taskkill /T→/F on Windows.
4. **Scope grouping** — processes tied to an agent session via `scopeKey`; all cancelled together on cleanup.
5. **Background persistence** — backgrounded sessions survive in `finishedSessions` for 30 min with full output available for polling.
