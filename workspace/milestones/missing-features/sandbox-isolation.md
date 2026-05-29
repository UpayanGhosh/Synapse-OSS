# Sandbox Isolation — Missing in Synapse-OSS

## Overview

openclaw has a full Docker/SSH sandbox subsystem that runs agent tool calls inside
isolated containers with strict mount policies, network controls, and filesystem
path guards. Synapse-OSS has no equivalent: all agent-triggered code runs directly
in the host Python process with no isolation layer.

---

## What openclaw has

### Docker backend
- **`src/agents/sandbox/docker.ts`** — `execDockerRaw()`, `resolveDockerSpawnInvocation()`
  Wire a Docker subprocess with abort-signal support, env sanitization, and
  Windows-compatible spawn resolution.
- **`src/agents/sandbox/docker-backend.ts`** — Full lifecycle: create, start, exec,
  stop, and remove containers. Implements `SandboxBackend`.
- **`src/agents/sandbox/ssh-backend.ts`** — SSH-over-container backend for remote
  or cross-platform execution.
- **`src/agents/sandbox/backend.ts`** — `requireSandboxBackendFactory()` switches
  between Docker and SSH backends at runtime.

### Sandbox context and configuration
- **`src/agents/sandbox/context.ts`** — `resolveSandboxContext()` assembles the full
  `SandboxContext` object: workspace layout, scope key, backend, FS bridge, browser.
- **`src/agents/sandbox/config.ts`** — `resolveSandboxConfigForAgent()` reads per-agent
  sandbox settings from OpenClaw config (Zod-validated).
- **`src/agents/sandbox/types.ts`** — `SandboxContext`, `SandboxDockerConfig`,
  `SandboxWorkspaceInfo` types.

### Mount system
- **`src/agents/sandbox/workspace-mounts.ts`** — Computes the Docker bind-mount list
  from workspace roots.
- **`src/agents/sandbox/bind-spec.ts`** — `splitSandboxBindSpec()` parses
  `source:target[:mode]` strings.
- **`src/agents/sandbox/fs-paths.ts`** — `SandboxResolvedFsPath`, `SandboxFsMount`
  types; host-to-container and container-to-host path translation.
- **`src/agents/sandbox/host-paths.ts`** — `normalizeSandboxHostPath()`,
  `resolveSandboxHostPathViaExistingAncestor()` (symlink-escape hardening).

### Security validation
- **`src/agents/sandbox/validate-sandbox-security.ts`** —
  `validateSandboxSecurity()` enforces all of:
  - `BLOCKED_HOST_PATHS` (`/etc`, `/proc`, `/sys`, `/dev`, `/root`, `/boot`,
    `/run`, `/var/run/docker.sock`, `/var/lib/docker`, `/var/log`, …)
  - `BLOCKED_HOME_SUBPATHS` (`.aws`, `.config`, `.kube`, `.openclaw`, `.ssh`)
  - Non-absolute source path rejection
  - Source-path outside allowed-roots rejection
  - Reserved container target paths (`/workspace`)
  - `network: "host"` mode blocked
  - Container namespace join (`network: "container:*"`) blocked by default
  - `seccomp: "unconfined"` blocked
  - `apparmor: "unconfined"` blocked
  - Symlink-escape re-check via `resolveSandboxHostPathViaExistingAncestor()`

### FS bridge and path safety
- **`src/agents/sandbox/fs-bridge.ts`** — `createSandboxFsBridge()`: read, write,
  rename, delete, list operations that cross the host/container boundary.
- **`src/agents/sandbox/fs-bridge-path-safety.ts`** — `SandboxFsPathGuard` class:
  - `assertPathSafety()` — validates a resolved path is inside a declared mount
  - `openReadableFile()` — opens with boundary check
  - `resolvePinnedEntry()` / `resolveAnchoredSandboxEntry()` — symlink-safe entry
    resolution via in-container `readlink -f` shell script
  - Detects `..` escapes and absolute-path escapes from mounts
  - `requireWritable` check against per-mount writable flag

### Environment sanitization inside sandbox
- **`src/agents/sandbox/sanitize-env-vars.ts`** — `sanitizeEnvVars()`:
  - Explicit blocked patterns: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
    `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN`, `OPENCLAW_GATEWAY_TOKEN`,
    `AWS_SECRET_ACCESS_KEY`, `GITHUB_TOKEN`, and generic `*_API_KEY`,
    `*_TOKEN`, `*_PASSWORD`, `*_SECRET`, `*_PRIVATE_KEY` regexes
  - Strict mode: allowlist-only pass-through (`LANG`, `LC_*`, `PATH`, `HOME`,
    `USER`, `SHELL`, `TERM`, `TZ`, `NODE_ENV`)
  - Base64-credential heuristic: blocks values matching `^[A-Za-z0-9+/=]{80,}$`
  - Null-byte rejection

### Workspace scoping
- **`src/agents/sandbox/shared.ts`** — `resolveSandboxScopeKey()`: per-session vs
  shared workspace isolation.
- **`src/agents/sandbox/prune.ts`** — `maybePruneSandboxes()`: removes stale
  sandbox workspaces.

---

## What Synapse-OSS has (or lacks)

Synapse-OSS has no sandbox layer. Relevant evidence:

- `workspace/` contains no `docker`, `sandbox`, `container`, or `chroot` modules.
- Agent-invoked tools run directly via `subprocess.run()` / `asyncio.create_subprocess_*`
  in the host process.
- The only isolation-adjacent code is `cli/daemon.py` which manages the Synapse
  server process via `subprocess.run(["systemctl", ...])` — this is service
  management, not agent sandboxing.
- `Dockerfile` at the repo root is a deployment image, not an agent sandbox.

---

## Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| Docker container per agent run | Yes | No |
| SSH container backend | Yes | No |
| Blocked host path denylist | Yes (20+ paths) | No |
| Mount security validation | Yes (symlink hardening) | No |
| Container network mode restrictions | Yes | No |
| seccomp/AppArmor enforcement | Yes | No |
| FS bridge path guard (SandboxFsPathGuard) | Yes | No |
| Env var sanitization before exec | Yes | No |
| Per-session workspace scoping | Yes | No |
| Sandbox pruning | Yes | No |

---

## Implementation notes for porting

1. **Docker backend**: Implement a `SandboxManager` class in Python that wraps
   `docker run --rm` with lifecycle methods (create, exec, stop). Use
   `asyncio.create_subprocess_exec` for non-blocking invocation.

2. **Mount security**: Before constructing `docker run -v` arguments, validate
   source paths against a `BLOCKED_HOST_PATHS` set. Use `os.path.realpath()`
   to follow symlinks and re-validate. Reject paths outside a configured
   `allowed_roots` list.

3. **Network modes**: Disallow `--network host` and `--network container:*` by
   default. Add an explicit override flag if needed.

4. **Env sanitization**: Before passing `--env` to the container, run every key
   through a blocklist regex (`*_API_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`)
   and strip values that look like base64 credentials.

5. **Path guard**: After Docker exec, resolve symlinks inside the container via
   `docker exec ... sh -c 'readlink -f "$1"' -- <path>` and re-verify the
   canonical path falls within declared mounts before processing the result.

6. **Config**: Add a `sandbox` section to `synapse.json` with `enabled`, `image`,
   `workspace_root`, `scope` (session/shared), `network`, and `extra_binds` fields.
