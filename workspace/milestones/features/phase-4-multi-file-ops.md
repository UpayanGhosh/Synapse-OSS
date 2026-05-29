# Phase 4: Multi-File Operations

## Overview

OpenClaw provides three core file operation tools — `read`, `write`, and `edit` —
sourced from the `@mariozechner/pi-coding-agent` upstream library and wrapped with
OpenClaw-specific sandbox boundaries, path guards, policy layers, and adaptive paging.
Multi-file work is accomplished through sequential single-file calls, with the
sandbox's mount system and path safety guards preventing any workspace escape.

---

## Key Files

| File | Role |
|------|------|
| `src/agents/pi-tools.read.ts` | Tool factories: read, write, edit; adaptive paging; root guards |
| `src/agents/pi-tools.ts` | `createOpenClawCodingTools()` — wires all tools with policies |
| `src/agents/sandbox/types.ts` | `SandboxContext`, `SandboxFsBridge`, `SandboxWorkspaceAccess` |
| `src/agents/sandbox/fs-paths.ts` | `buildSandboxFsMounts()`, `resolveSandboxFsPathWithMounts()` |
| `src/agents/sandbox/fs-bridge-path-safety.ts` | `SandboxFsPathGuard`, `assertPathSafety()` |
| `src/agents/sandbox/fs-bridge.ts` | `SandboxFsBridge` interface + default implementation |
| `src/agents/sandbox/remote-fs-bridge.ts` | SSH/remote shell bridge |
| `src/agents/tool-fs-policy.ts` | `createToolFsPolicy()`, workspace-only enforcement |
| `src/agents/tool-policy.ts` | `ToolPolicyLike`, policy pipeline |
| `src/plugin-sdk/sandbox.ts` | Re-exported sandbox types for plugin authors |
| `extensions/openshell/src/fs-bridge.ts` | Example plugin `SandboxFsBridge` implementation |

---

## The Three File Tools

All three are created in `src/agents/pi-tools.read.ts` and registered by
`createOpenClawCodingTools()` in `src/agents/pi-tools.ts`.

| Tool | Factory | Purpose |
|------|---------|---------|
| `read` | `createOpenClawReadTool()` / `createSandboxedReadTool()` | Read file content with adaptive paging |
| `write` | `createHostWorkspaceWriteTool()` / `createSandboxedWriteTool()` | Write/create a file atomically |
| `edit` | `createHostWorkspaceEditTool()` / `createSandboxedEditTool()` | Apply multi-line patch to existing file |

> **No glob or list-files tool exists.** Directory traversal requires the `exec` tool
> (shell commands like `find`, `ls`, `rg`).

---

## Adaptive Paging (Read Tool)

The read tool pages large files instead of truncating them.

### Constants (`pi-tools.read.ts`)

```typescript
DEFAULT_READ_PAGE_MAX_BYTES  = 50 * 1024     // 50 KB default page size
MAX_ADAPTIVE_READ_MAX_BYTES  = 512 * 1024    // 512 KB max page size
ADAPTIVE_READ_CONTEXT_SHARE  = 0.2           // Use 20% of model context window
CHARS_PER_TOKEN_ESTIMATE     = 4             // Bytes per token estimate
MAX_ADAPTIVE_READ_PAGES      = 8             // Max pages per read call
```

### Page Size Calculation

```typescript
// If model context window is known:
pageBytes = modelContextTokens * 4 * 0.2
// Clamped to [50 KB, 512 KB]
```

### Pagination API

- `offset` param: byte offset to start reading from
- Returns `truncation.truncated = true` if more content exists
- Appends notice: `[Read output capped at XYZ. Use offset=N to continue.]`
- Up to 8 pages; each page read sequentially

### MIME / Image Handling

- MIME sniffed from first 16KB (`sniffMimeFromBase64()`)
- Images returned as base64 blocks
- `ImageSanitizationLimits` config enforces output size caps

---

## Sandbox & Workspace Restrictions

### SandboxContext

```typescript
type SandboxContext = {
  enabled: boolean
  backendId: "docker" | "ssh"
  sessionKey: string
  workspaceDir: string              // Host workspace mount
  agentWorkspaceDir: string         // Original agent workspace
  workspaceAccess: "none" | "ro" | "rw"
  runtimeId: string                 // Container/VM ID
  containerName: string
  containerWorkdir: string          // Container path (e.g., /workspace)
  docker: SandboxDockerConfig
  tools: SandboxToolPolicy          // Per-sandbox allow/deny lists
  fsBridge?: SandboxFsBridge
  backend?: SandboxBackendHandle
}
```

### Access Levels

| Level | Behavior |
|-------|---------|
| `rw` | Full read + write access |
| `ro` | Read tool only; write and edit tools are hard-disabled |
| `none` | No file access; scripts run in an isolated workspace copy |

### Mount System (`src/agents/sandbox/fs-paths.ts`)

```typescript
type SandboxFsMount = {
  hostRoot: string        // Host filesystem path
  containerRoot: string   // Container path (e.g., /workspace)
  writable: boolean
  source: "workspace" | "agent" | "bind"
}
```

`buildSandboxFsMounts()` creates 3 mount types:
1. **Workspace mount** — agent's configured workspace (writable per `workspaceAccess`)
2. **Agent mount** — original agent workspace if different from workspace
3. **Bind mounts** — user-configured extra paths from `docker.binds`

---

## Path Traversal Prevention

### SandboxFsPathGuard (`src/agents/sandbox/fs-bridge-path-safety.ts`)

```typescript
class SandboxFsPathGuard {
  assertPathSafety(target, options): void
  openReadableFile(target): ReadableFile
  resolveRequiredMount(containerPath): SandboxFsMount
}
```

Checks:
- `relativeParentPath.startsWith("..")` — rejects `../../etc/passwd` style escapes
- `path.posix.isAbsolute(relativeParentPath)` — rejects absolute paths in relative context
- Symlink resolution via `openBoundaryFile` — follows symlinks within mount boundaries only
- Hardlink detection on write operations

### Workspace Root Guard (`pi-tools.read.ts`)

```typescript
wrapToolWorkspaceRootGuard(tool, root)
```

Applied to host-mode tools. Maps all paths to be relative to the workspace root;
container paths (e.g., `/workspace/foo`) are translated to workspace-relative paths.

---

## Host vs Sandbox Mode

### Host Mode

```typescript
createHostWorkspaceWriteTool(root, { workspaceOnly? })
```

- `workspaceOnly: false` (default) — allows writes anywhere on host
- `workspaceOnly: true` — enforces `toRelativeWorkspacePath()` boundary

```typescript
writeFile: async (absolutePath) => {
  const relative = toRelativeWorkspacePath(root, absolutePath)
  await writeFileWithinRoot({ rootDir: root, relativePath: relative, ... })
}
```

### Sandbox Mode

```typescript
createSandboxedWriteTool({ bridge, workdir })
```

All operations go through `SandboxFsBridge`; path safety is enforced internally.

```typescript
writeFile: async (absolutePath) => {
  await bridge.writeFile({ filePath: absolutePath, cwd: workdir, data: ... })
}
```

Writes are atomic: temp file written then renamed into place.

---

## SandboxFsBridge Interface

`SandboxFsBridge` is the abstraction for all file I/O inside the sandbox:

```typescript
interface SandboxFsBridge {
  readFile(opts: { filePath: string; cwd: string; ... }): Promise<Buffer>
  writeFile(opts: { filePath: string; cwd: string; data: Buffer; ... }): Promise<void>
  stat(opts: { filePath: string; cwd: string }): Promise<SandboxFsStat>
  mkdir(opts: { dirPath: string; cwd: string; recursive?: boolean }): Promise<void>
  rename(opts: { from: string; to: string; cwd: string }): Promise<void>
  unlink(opts: { filePath: string; cwd: string }): Promise<void>
}
```

Implementations:
- **Default** (`src/agents/sandbox/fs-bridge.ts`) — Docker exec / local calls
- **Remote** (`src/agents/sandbox/remote-fs-bridge.ts`) — SSH shell bridge
- **OpenShell** (`extensions/openshell/src/fs-bridge.ts`) — plugin example with remote sync

Plugins can provide custom implementations via the plugin SDK (`src/plugin-sdk/sandbox.ts`).

---

## Policy Layers

File tool access is filtered through 7 independent policy layers:

```
1. Profile policy        (default tool profiles: "safe", "unrestricted")
2. Provider policy       (model provider restrictions)
3. Global policy         (config-level tools.allow/deny)
4. Agent policy          (per-agent overrides)
5. Group policy          (channel/group restrictions: Slack channels, etc.)
6. Sandbox policy        (sandbox.tools.allow/deny)
7. Subagent policy       (inherited restrictions for spawned agents)
```

Applied in `createOpenClawCodingTools()`:

```typescript
const filtered = applyToolPolicyPipeline({
  tools: toolsByAuthorization,
  steps: [
    ...buildDefaultToolPolicyPipelineSteps({ ... }),
    { policy: sandboxToolPolicy, label: "sandbox tools.allow" },
    { policy: subagentPolicy,   label: "subagent tools.allow" },
  ],
})
```

### Memory Flush Restriction

When a memory-flush run is triggered, only `read` and `write` are available, and
`write` is further restricted to append-only mode:

```typescript
const MEMORY_FLUSH_ALLOWED_TOOL_NAMES = new Set(["read", "write"])

// Write restricted to append only at:
wrapToolMemoryFlushAppendOnlyWrite(writeTool, memoryFlushWritePath)
// Only memoryFlushWritePath can be written; all other paths rejected
```

### Workspace-Only Mode

```typescript
fsPolicy.workspaceOnly = isMemoryFlushRun || fsConfig.workspaceOnly
```

When active: all write/edit operations are confined to the session workspace root.

---

## End-to-End: Multi-File Edit Workflow

```
Agent reads file A
│
├─ read { path: "src/foo.ts" }
│    ├─ Resolve path within workspace root
│    ├─ Check sandbox mount + assertPathSafety()
│    ├─ Read via bridge.readFile() or fs.readFile()
│    └─ Adaptive page if > 50KB
│
Agent edits file A
│
├─ edit { path: "src/foo.ts", diff: [...] }
│    ├─ Resolve + guard path
│    ├─ Read current content
│    ├─ Apply patch (multi-line diff from pi-coding-agent)
│    └─ Atomic write via bridge.writeFile() (temp → rename)
│
Agent writes new file B
│
└─ write { path: "src/bar.ts", content: "..." }
     ├─ Resolve + guard path
     ├─ workspaceOnly check (if active)
     └─ Atomic write via bridge.writeFile()
```

For directory traversal (no native glob/list tool):
```
exec { command: "find src -name '*.ts' -type f" }
```

---

## Key Invariants

1. **No glob tool** — Directory listings and file discovery require `exec` + shell commands.
2. **Atomic writes** — All writes use a temp-file-then-rename pattern; no partial writes.
3. **Mount-bounded** — Sandbox paths are always resolved within declared mounts; escapes are rejected at the path guard layer.
4. **Context-aware paging** — Read page size scales with model context window so large files don't overwhelm the token budget.
5. **Plugin-extensible bridge** — Custom storage backends (S3, SSH, SFTP, local) plug in via `SandboxFsBridge` without changing tool code.
6. **Read-only enforcement** — `workspaceAccess: "ro"` hard-removes write and edit tools from the available set; not just policy-filtered.
