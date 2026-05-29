# Process Supervisor & PTY Control — Missing in Synapse-OSS

## Overview

openclaw has a structured `ProcessSupervisor` that manages spawned child processes
and PTY sessions: run-state tracking, scope-based cancellation, dual/no-output
timeouts, PTY send-keys, and a process tool with poll/log/write/kill/send-keys
actions. Synapse-OSS calls `subprocess.run()` or `subprocess.Popen()` directly
with no supervision layer.

---

## What openclaw has

### ProcessSupervisor
**`src/process/supervisor/supervisor.ts`** — `createProcessSupervisor()`

Returns a `ProcessSupervisor` object with:
- `spawn(input: SpawnInput): Promise<ManagedRun>` — starts a child process or PTY,
  registers it in the run registry, sets up stdout/stderr callbacks, and wires
  overall and no-output timeout timers
- `cancel(runId, reason?)` — transitions run to `"exiting"` state and signals the
  adapter; reasons: `"manual-cancel" | "overall-timeout" | "no-output-timeout"`
- `cancelScope(scopeKey, reason?)` — cancels all runs sharing a scope key;
  used for per-session or per-agent cleanup
- `getRecord(runId)` — returns the live `RunRecord` including state, pid, timing
- `reconcileOrphans()` — no-op in current model; designed for restart recovery

**`src/process/supervisor/types.ts`** — type surface:
- `RunState`: `"starting" | "running" | "exiting" | "exited"`
- `TerminationReason`: `"manual-cancel" | "overall-timeout" | "no-output-timeout" | "spawn-error" | "signal" | "exit"`
- `RunRecord` — `{ runId, sessionId, backendId, scopeKey, pid, state, startedAtMs, lastOutputAtMs, terminationReason, exitCode, exitSignal }`
- `RunExit` — `{ reason, exitCode, exitSignal, durationMs, stdout, stderr, timedOut, noOutputTimedOut }`
- `ManagedRun` — `{ runId, pid, startedAtMs, stdin, wait(), cancel() }`
- `SpawnInput` — discriminated union of `SpawnChildInput` (argv-based) and `SpawnPtyInput` (shell command string)
- `ProcessSupervisor` interface

**`src/process/supervisor/registry.ts`** — `createRunRegistry()`:
- In-memory map of `RunRecord`s; `add()`, `updateState()`, `touchOutput()`,
  `finalize()`, `get()` methods
- `touchOutput()` updates `lastOutputAtMs` on each chunk (used to drive
  no-output timeout reset)

### Process adapters
**`src/process/supervisor/adapters/child.ts`** — `createChildAdapter()`:
- Wraps `node:child_process.spawn` with stdin pipe modes (`"inherit" | "pipe-open" | "pipe-closed"`)
- Windows verbatim arguments support
- Returns `SpawnProcessAdapter` with `onStdout`, `onStderr`, `wait`, `kill`, `dispose`

**`src/process/supervisor/adapters/pty.ts`** — `createPtyAdapter()`:
- Creates a PTY session using the system shell (`bash` / `zsh` / PowerShell)
- Runs the command string inside the shell to get full PTY semantics (cursor
  keys, interactive prompts, terminal control sequences)
- Returns the same `SpawnProcessAdapter` interface

**`src/process/supervisor/adapters/env.ts`** — environment preparation shared
by child and PTY adapters

### Process tool (agent-facing)
**`src/agents/bash-tools.process.ts`** — `processTool`:

Schema-validated actions the agent can invoke:
- `list` — lists running and recently-finished sessions with status summaries
- `poll` — waits up to `MAX_POLL_WAIT_MS = 120,000 ms` for a session to finish;
  returns current state, exit code, last log lines
- `log` — returns a window of log output (default last 200 lines); supports
  `offset` / `limit` for paging
- `write` — writes raw data to a process's stdin
- `send-keys` — encodes named key tokens (arrow keys, Ctrl-C, Enter, Tab,
  function keys, etc.) or hex bytes and sends them to the PTY
- `paste` — sends text with optional bracketed-paste mode wrapping
- `kill` — cancels a managed run via `killProcessTree()`
- `delete` — removes a session record after it exits

Sends `encodeKeySequence()` / `encodePaste()` for PTY-aware key dispatch
(`src/agents/pty-keys.ts`).

### Graceful kill-tree
**`src/process/kill-tree.ts`** — `killProcessTree(pid, opts?)`:
- **Unix**: sends `SIGTERM` to the entire process group (`-pid`), waits
  `graceMs` (default 3,000 ms, max 60,000 ms), then sends `SIGKILL` if still alive
- **Windows**: runs `taskkill /T /PID <pid>` (graceful, tree), then after
  `graceMs` runs `taskkill /F /T /PID <pid>` only if the process is still alive
- `isProcessAlive(pid)` — checks via `process.kill(pid, 0)` before force-kill
- All `setTimeout` calls use `.unref()` so they do not block event-loop exit

### Command poll backoff
**`src/agents/command-poll-backoff.ts`** — `recordCommandPoll()` /
`resetCommandPollCount()`:
- Tracks how many consecutive `poll` calls an agent has made for the same session
- Applies exponential back-pressure hints in the tool result when polling too
  frequently (encourages the agent to add wait intervals)

### Bash process registry
**`src/agents/bash-process-registry.ts`** — higher-level session store used by
the exec tool: maps session IDs to log buffers, exit state, and TTL cleanup.

---

## What Synapse-OSS has (or lacks)

Synapse-OSS uses raw `subprocess` throughout:

- **`cli/daemon.py`**: starts/stops the Synapse server via `subprocess.run(["systemctl", ...])` or direct Python invocation. No lifecycle tracking beyond checking `returncode`.
- **`cli/channel_steps.py`**: spawns the Baileys WhatsApp bridge with `subprocess.Popen(['node', 'index.js'])`. No run registry, no timeout management, no cancel-scope.
- **`change_tracker.py`**: runs `git diff` via `subprocess.run` with a hardcoded `timeout=30`. No retry or supervisor.

There is no:
- Run registry with state machine
- Scope-based cancellation
- Overall or no-output timeout with graceful → force kill sequence
- PTY adapter or send-keys support
- Agent-facing `process` tool with poll/log/write/kill actions
- Kill-tree (Unix SIGTERM→SIGKILL, Windows taskkill /T)

---

## Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| ProcessSupervisor (spawn/cancel/cancelScope) | Yes | No |
| Run registry with RunState machine | Yes | No |
| Overall + no-output dual timeouts | Yes | No |
| Scope-based batch cancellation | Yes | No |
| Child process adapter (argv-based) | Yes | Raw subprocess |
| PTY adapter (shell-wrapped) | Yes | No |
| send-keys / paste to PTY | Yes | No |
| Graceful kill-tree (SIGTERM→SIGKILL) | Yes | No |
| Windows taskkill tree support | Yes | No |
| Agent process tool (poll/log/write/kill) | Yes | No |
| Command poll backoff hints | Yes | No |

---

## Implementation notes for porting

1. **Supervisor**: Implement a `ProcessSupervisor` class in Python using
   `asyncio.create_subprocess_exec`. Track runs in a `dict[str, RunRecord]`
   dataclass. Fire `asyncio.wait_for` for overall timeout and reset a no-output
   `asyncio.Task` on each stdout/stderr chunk.

2. **Scope cancel**: Store a `scope_key` per run. `cancel_scope(key)` iterates
   active runs and cancels all matching ones.

3. **Kill tree**:
   - Unix: `os.killpg(os.getpgid(pid), signal.SIGTERM)`, then `signal.SIGKILL`
     after `grace_ms` via `asyncio.sleep`.
   - Windows: `subprocess.run(["taskkill", "/T", "/PID", str(pid)])`, then
     `/F` after grace period if `psutil.pid_exists(pid)`.

4. **PTY**: Use `ptyprocess.PtyProcess` (or `pexpect.spawn`) to create a PTY
   session. Expose `write(data)` and `send_keys(tokens)` methods.

5. **Process tool**: Add a `process` tool to the agent tool registry with the
   same action schema (`list`, `poll`, `log`, `write`, `send-keys`, `kill`).
   Back it with the supervisor registry.

6. **Poll backoff**: Track consecutive `poll` calls per session. After N calls,
   inject a wait hint in the tool response.
