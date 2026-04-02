# Research Phase 5 — Process Management & Kill Utilities

> Generated 2026-04-02 by Claude Code file exploration.

---

## Agent 1: Existing Execution Server Audit

### File: execution_server.py

#### ProcessSession Dataclass (Lines 26-35)

**All fields and defaults:**
```python
@dataclass
class ProcessSession:
    id: str
    command: str
    pid: int | None
    started_at: float
    aggregated: str = ""
    exit_code: int | None = None
    exited: bool = False
    _task: asyncio.Task | None = field(default=None, repr=False, compare=False)
```

- id: Session identifier
- command: The shell command executed
- pid: Process ID; None for foreground sessions
- started_at: Monotonic timestamp
- aggregated: Combined stdout+stderr (capped at 100KB)
- exit_code: Process exit code or None
- exited: Boolean termination flag
- _task: Async output collection task reference

#### _collect_output() Function (Lines 41-63)

**Signature:** `async def _collect_output(session: ProcessSession, proc: asyncio.subprocess.Process) -> None`

**Output handling:**
- Streams BOTH stdout AND stderr into single `session.aggregated` buffer
- stdout and stderr NOT separated; merged via asyncio.gather
- **100KB cap mechanism:** Sliding window keeps last 100KB
  ```python
  if len(session.aggregated) > _OUTPUT_CAP:
      session.aggregated = session.aggregated[-_OUTPUT_CAP:]
  ```
- No structured stdout/stderr distinction
- Exit code captured: `session.exit_code = proc.returncode` and `session.exited = True`

#### _ttl_cleanup() Function (Lines 66-77)

**Signature:** `async def _ttl_cleanup() -> None`

**TTL Configuration:**
- SESSION_TTL: 30 * 60 = 1800 seconds (30 minutes)
- Sweeper interval: 60 seconds
- Cleanup behavior: Pops stale sessions from dict, cancels tasks

#### _handle_exec() Function (Lines 149-206)

**Signature:** `async def _handle_exec(args: dict) -> list[TextContent]`

**Foreground vs background:**
- Background (background=True): Creates UUID sessionId, wraps output collection in asyncio.create_task(), stores in _sessions, returns immediately
- Foreground (background=False): Waits with timeout (default 30s), calls proc.kill() on timeout, returns output tail

#### _handle_process() Function (Lines 209-275)

**Signature:** `async def _handle_process(args: dict) -> list[TextContent]`

**Actions:**
- list: Returns all sessions
- poll: Busy-waits on aggregated length (every 0.2s, default 10s timeout), returns delta output
- log: Returns tail of aggregated output (default 50 lines, capped at 2000 chars)
- kill: Kills PID with os.kill(pid, SIGKILL), sets exit_code to -9

#### Kill Implementation (Lines 261-273)

**Exact kill code:**
```python
if session.pid:
    try:
        os.kill(session.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
```

**Signal:** signal.SIGKILL (Unix signal 9)

**Critical bugs:**
- **CRITICAL on Windows:** os.kill(pid, SIGKILL) raises ValueError (SIGKILL not supported on Windows)
- **No child termination:** Only kills direct PID, orphans shell-spawned children
  - Example: `bash -c "sleep 100 & sleep 100"` leaves sleeps running
- Missing os.killpg() (Unix) or taskkill /T (Windows)

#### Global Constants

- _OUTPUT_CAP: 100 KB
- _LOG_TAIL: 2000 chars
- _SESSION_TTL: 30 minutes

#### Summary: Function Signatures

| Function | Signature | Returns |
|----------|-----------|---------|
| _collect_output | async (session, proc) -> None | Sets aggregated, exit_code, exited |
| _ttl_cleanup | async () -> None | Cancels stale tasks every 60s |
| _handle_exec | async (args: dict) -> list[TextContent] | {status, sessionId/output, exitCode} |
| _handle_process | async (args: dict) -> list[TextContent] | Action-specific JSON response |

---

### File: whatsapp.py (Lines 100-180)

#### start() Method (Lines 121-167)

**Signature:** `async def start(self) -> None`

- Creates subprocess and waits indefinitely
- On CancelledError: Calls stop() then re-raises
- Exponential backoff restart on crash (max 5 attempts)

#### stop() Method (Lines 169-177)

**Signature:** `async def stop(self) -> None`

**Graceful-to-forced kill sequence:**
```python
async def stop(self) -> None:
    if self._proc and self._proc.returncode is None:
        self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=5.0)
        except TimeoutError:
            self._proc.kill()
    self._status = "stopped"
    logger.info("[WA] Bridge stopped")
```

**Sequence:** Check running → terminate() → wait 5s → kill() on timeout → status update → log

**5s timeout pattern:** Hard-coded between terminate() and kill()

**Cross-platform:**
- terminate(): SIGTERM (Unix), TerminateProcess (Windows)
- kill(): SIGKILL (Unix), TerminateProcess (Windows — same as terminate)

---

### File: registry.py (Full)

#### ChannelRegistry Overview

**Purpose:** Manages channel adapter lifecycle within FastAPI lifespan

#### start_all() (Lines 74-88)

**Signature:** `async def start_all(self) -> None`

- Wraps each channel.start() in named asyncio task
- Stores in _tasks[cid]
- Uses create_task(), returns immediately (concurrent)

#### stop_all() (Lines 90-105)

**Signature:** `async def stop_all(self) -> None`

**Shutdown sequence:**
```python
for task in self._tasks.values():
    task.cancel()
if self._tasks:
    await asyncio.gather(*self._tasks.values(), return_exceptions=True)
self._tasks.clear()
for cid, channel in self._channels.items():
    await channel.stop()
```

1. Cancel all tasks
2. Gather with exception suppression
3. Clear task dict
4. Call stop() on channels for cleanup

#### register() (Lines 39-52)

**Signature:** `def register(self, channel: BaseChannel) -> None`

- Checks duplicate channel_id, raises ValueError
- Adds to _channels dict

#### get() and list_ids() (Lines 54-68)

**Signatures:** `def get(channel_id: str) -> BaseChannel | None` and `def list_ids() -> list[str]`

---

## Phase 5 Gaps Summary

### Missing Features

1. **Scope-based session grouping** — No scope concept; all sessions flat in _sessions dict
2. **Event-driven poll** — Busy-wait on aggregated length (every 0.2s); no event queue
3. **kill_scope()** — No action to kill all processes in a scope atomically
4. **Cross-platform kill with child termination:**
   - Windows: os.kill(SIGKILL) raises ValueError; no taskkill /T
   - Unix: No os.killpg(); only direct kill orphans children
5. **Structured stdout/stderr separation** — Merged into single buffer; no distinction
6. **Session TTL with hooks** — Hard-coded 30min/60s; no per-session override; no SIGTERM before cancel

### Specific Gaps vs Phase 5 Spec

| Gap | Severity | Impact |
|-----|----------|--------|
| Windows kill support | CRITICAL | Kill fails on Windows |
| Child process termination | HIGH | Shell-spawned processes orphaned |
| Scope-based grouping | HIGH | No multi-process lifecycle |
| Event-driven polling | MEDIUM | Inefficient polling |
| Structured stdout/stderr | MEDIUM | No error isolation |
| kill_scope() action | MEDIUM | No batch kill |
| Per-session TTL | LOW | Inflexible TTL |

---


## Agent 2: Platform Kill & PID Utilities

### Executive Summary

Synapse-OSS currently has fragmented process management with:
1. No graceful-to-forced kill pattern across platforms
2. Windows process tree kill is not implemented (taskkill /T missing)
3. Unix process group kill is ad-hoc (single os.kill calls, no SIGTERM→SIGKILL sequence)
4. Process liveness checks scattered across multiple files
5. asyncio.wait_for timeout handling exists but lacks fallback kill-tree

Critical Gap: Python's asyncio.subprocess.Process.terminate() on Windows calls TerminateProcess(), which kills ONLY the root process, NOT child processes. This leaves zombie spawned services running indefinitely.

---

## Part 1: Existing Kill Patterns in Codebase

### 1.1 Direct os.kill() Usage

**File:** workspace/sci_fi_dashboard/mcp_servers/execution_server.py
**Lines:** 194, 266

- Line 194: Uses proc.kill() on asyncio.subprocess.Process
- Line 266: Directly calls os.kill(pid, signal.SIGKILL) — UNIX ONLY, will fail on Windows
- Neither implements graceful termination (SIGTERM → wait → SIGKILL)
- No process-tree handling

### 1.2 Process.terminate() Usage (Graceful)

**File:** workspace/sci_fi_dashboard/channels/whatsapp.py
**Lines:** 171, 175

- BEST PRACTICE in codebase: graceful SIGTERM with 5s timeout, then forced SIGKILL
- BUT: On Windows, terminate() calls TerminateProcess() which does NOT kill child processes
- The Baileys WhatsApp bridge spawned by this process will remain a zombie on Windows

### 1.3 Simple terminate() with poll() liveness check

**File:** workspace/cli/channel_steps.py
**Lines:** 511, 521, 539, 565, 622

- Uses proc.poll() to check if process has exited
- terminate() is called without timeout or fallback kill
- Missing: no wait for termination, no force-kill after grace period

### 1.4 Signal Handler Registration

**File:** workspace/change_tracker.py
**Lines:** 545-546

- Registers handlers for SIGTERM and SIGINT (from systemd/OS)
- Does NOT implement process kill logic

### 1.5 asyncio.wait_for() Timeout Patterns

Used in:
- workspace/sci_fi_dashboard/gateway/sender.py Line 140
- workspace/sci_fi_dashboard/channels/whatsapp.py Line 173
- workspace/scripts/latency_watcher.py Line 71

On timeout, calling code MUST explicitly call proc.kill() or proc.terminate()
Gap: No centralized pattern; each caller responsible for cleanup

---

## Part 2: Process Liveness Checks

File: workspace/cli/channel_steps.py
- Line 511: if proc.poll() is not None
- Line 521: if proc.poll() is not None
- Line 539: if proc is not None and proc.poll() is not None
- Line 565: if proc is not None and proc.poll() is not None

File: workspace/sci_fi_dashboard/channels/whatsapp.py
- Line 151: rc = self._proc.returncode
- Line 170: if self._proc and self._proc.returncode is None
- Line 200: running = self._proc is not None and self._proc.returncode is None

Analysis:
- proc.poll() returns None if running, exit code if exited
- Both work on Windows and Unix
- Used for polling process state; NOT for forceful termination

---

## Summary Table: Every Kill/Terminate Usage

| File | Line(s) | Method | Windows Safe | Notes |
|------|---------|--------|--------------|-------|
| execution_server.py | 194 | proc.kill() | Root only | MCP timeout |
| execution_server.py | 266 | os.kill(SIGKILL) | Crashes | UNIX ONLY |
| whatsapp.py | 171 | proc.terminate() | Root only | 5s timeout |
| whatsapp.py | 175 | proc.kill() | Root only | On timeout |
| channel_steps.py | 622 | proc.terminate() | Root only | No force-kill |

Bottom Line: Only whatsapp.py has graceful→forced pattern, but unsafe for process trees on Windows. Need centralized kill_process_tree() module.
