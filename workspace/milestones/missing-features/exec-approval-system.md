# Exec Approval System — Missing in Synapse-OSS

## Overview

openclaw has a multi-layer command execution approval system: a persistent
allowlist, safe-binary profiles, obfuscation detection, a socket-based approval
request flow, and DM-routing for approvals. Synapse-OSS has no equivalent; it
has no notion of controlling which shell commands an agent may run.

---

## What openclaw has

### Core approval types and storage
**`src/infra/exec-approvals.ts`**
- `ExecSecurity` union: `"deny" | "allowlist" | "full"`
- `ExecAsk` union: `"off" | "on-miss" | "always"`
- `ExecHost` union: `"sandbox" | "gateway" | "node"`
- `ExecAllowlistEntry` — `{ id, pattern, lastUsedAt, lastUsedCommand, lastResolvedPath }`
- `ExecApprovalsFile` — versioned JSON file at `~/.openclaw/exec-approvals.json`
  (mode `0o600`) with per-agent allowlists and global defaults
- `resolveExecApprovals()` — merges file defaults, wildcard agent (`"*"`),
  per-agent overrides, and CLI overrides into `ExecApprovalsResolved`
- `requiresExecApproval()` — decides at call time if approval is needed
- `addAllowlistEntry()` / `recordAllowlistUse()` — mutate and persist the allowlist
- `requestExecApprovalViaSocket()` — sends an approval request over a JSONL Unix socket,
  returns `"allow-once" | "allow-always" | "deny"` with configurable timeout
- `minSecurity()` / `maxAsk()` — lattice helpers for merging policies

### Shell command analysis
**`src/infra/exec-approvals-analysis.ts`**
- `analyzeShellCommand()` — parses a shell command string into segments, resolves
  each segment's binary, and checks it against the allowlist
- `ExecCommandAnalysis` — `{ ok, reason, segments, chains }`
- `matchAllowlist()` — pattern-based allowlist matching against resolved binary paths
- `resolveCommandResolution()` — resolves a binary name to an absolute path using
  `PATH` lookup; used for allowlist candidate path generation
- Detects shell pipeline tokens (`>`, `<`, backticks, parens) that bypass simple
  binary checks

### Obfuscation detection
**`src/infra/exec-obfuscation-detect.ts`**
- `detectExecObfuscation()` — flags commands that use base64 decoding pipelines,
  `$()` subshell expansion, heredoc-encoded execution, or other obfuscation
  patterns that could hide dangerous commands from the allowlist matcher

### Safe-binary profiles
**`src/infra/exec-safe-bin-policy-profiles.ts`**
- `SAFE_BIN_PROFILE_FIXTURES` — per-binary allowed/denied flag definitions for
  `jq`, `curl`, `wget`, `git`, `npm`, `pip`, `python`, `node`, `bash`, `sh`, `cut`,
  `uniq`, `head`, `tail`, `tr`, `wc` (and more)
- Each profile specifies `minPositional`, `maxPositional`, `allowedValueFlags`,
  `deniedFlags`; long-flag GNU abbreviation resolution via prefix maps
- `DEFAULT_SAFE_BINS` — set of binaries considered safe without further review:
  `["cut", "uniq", "head", "tail", "tr", "wc"]`

**`src/infra/exec-safe-bin-policy-validator.ts`**
- `validateSafeBinArgv()` — checks a parsed `argv` against the binary's profile;
  throws with a human-readable error if denied flags are present or positional
  argument count is outside allowed range

**`src/infra/exec-safe-bin-runtime-policy.ts`**
- `resolveExecSafeBinRuntimePolicy()` — decides at runtime whether the given argv
  passes the safe-bin policy, returning an allow/deny decision with reason

**`src/infra/exec-safe-bin-trust.ts`**
- `resolveExecSafeBinTrust()` — extends safe-bin semantics to skill-installed
  binaries; auto-allows skill binaries if `autoAllowSkills` is set in config

### Approval request flow
**`src/infra/exec-approval-forwarder.ts`**
- `ExecApprovalForwarder` — bridges in-process approval requests to the gateway
  socket; queues and deduplicates requests

**`src/infra/exec-approval-channel-runtime.ts`**
- Routes approval requests to the originating channel (Telegram, Discord, Slack, …)
  via a DM to the session owner

**`src/infra/exec-approval-surface.ts`**
- `ExecApprovalSurface` — decides which surface (native UI, channel DM, or
  fallback auto-deny) handles a given approval request based on available context

**`src/infra/exec-approval-session-target.ts`**
- `resolveExecApprovalSessionTarget()` — given a session key and turn source,
  figures out which channel account to DM for the approval

**`src/infra/exec-approval-reply.ts`**
- `resolveExecApprovalDecisionFromReply()` — parses a user's natural-language reply
  to an approval DM ("yes", "no", "allow", "deny", "always") into a typed
  `ExecApprovalDecision`

**`src/infra/exec-approvals-store.ts`**
- Persistent in-process store for outstanding approval requests; handles expiry
  (`DEFAULT_EXEC_APPROVAL_TIMEOUT_MS = 1,800,000 ms`)

**`src/agents/bash-tools.exec-approval-request.ts`**
- `buildExecApprovalRequest()` — constructs the `ExecApprovalRequestPayload`
  including command text, preview, env-key hints, turn source metadata
- `requestExecApproval()` — orchestrates the full approval round-trip: build
  request → forward to surface → wait → return decision

**`src/agents/bash-tools.exec-approval-followup.ts`**
- `followUpExecApproval()` — handles the "allow-always" decision path; writes the
  approved pattern to the persistent allowlist and notifies the user

### Host environment security
**`src/infra/host-env-security.ts`** + **`host-env-security-policy.json`**
- `sanitizeHostExecEnvWithDiagnostics()` — strips dangerous env vars before
  passing the host environment to a spawned process
- Two-tier system: blocked keys (hard deny) and blocked prefixes (pattern deny)
- Override-key allowlist for safe pass-through (`TERM`, `LANG`, `LC_ALL`, etc.)
- Separate Windows-compatible key validation regex

**`src/infra/exec-command-resolution.ts`**
- `resolveCommandResolutionFromArgv()` — full argv-to-binary resolution pipeline:
  PATH lookup, wrapper detection, alias expansion

---

## What Synapse-OSS has (or lacks)

Synapse-OSS has a channel-level allowlist (`DmPolicy.ALLOWLIST` in
`sci_fi_dashboard/channels/security.py`) that controls which senders may DM the
bot. This is entirely separate from controlling what commands the agent itself
may execute.

There is no exec approval system:
- No `exec-approvals.json` or equivalent config file
- No `ExecSecurity` / `ExecAsk` policy knobs
- No per-agent command allowlist
- No safe-binary profiles or flag-level validation
- No approval request flow (no socket, no DM routing for approvals)
- No obfuscation detection
- `subprocess.run(...)` calls in `cli/` code do not pass through any approval gate
- The agent's tool-calling path (LLM → tool → response) has no exec interception layer

---

## Gap summary

| Feature | openclaw | Synapse-OSS |
|---|---|---|
| ExecSecurity / ExecAsk policy | Yes | No |
| Per-agent JSON allowlist | Yes | No |
| Safe-binary profiles (flag-level) | Yes | No |
| Obfuscation detection | Yes | No |
| Approval socket + request flow | Yes | No |
| Approval DM routing to channel | Yes | No |
| allow-once / allow-always decisions | Yes | No |
| Host env var sanitization before exec | Yes | No |
| Auto-allow skills binaries | Yes | No |
| Approval timeout (1,800,000 ms) | Yes | No |

---

## Implementation notes for porting

1. **Policy config**: Add `exec.security` (`"deny"`, `"allowlist"`, `"full"`) and
   `exec.ask` (`"off"`, `"on-miss"`, `"always"`) to `synapse.json`. Default
   `security` to `"deny"` and `ask` to `"on-miss"`.

2. **Allowlist file**: Persist approved patterns to
   `~/.synapse/exec-approvals.json` with the same structure (version, agents,
   defaults). Store `lastUsedAt` / `lastUsedCommand` for auditability.

3. **Command analysis**: Before running any agent-requested shell command, parse
   it with `shlex.split()`, resolve the binary via `shutil.which()`, and match
   the resolved path against the allowlist. Detect pipeline tokens that bypass
   the binary check.

4. **Safe-bin profiles**: Define a `SAFE_BIN_PROFILES` dict keyed by binary name.
   Each profile has `denied_flags` and `allowed_value_flags` sets. Validate the
   parsed argv before allowing execution.

5. **Approval flow**: When a command requires approval (`ask == "on-miss"` and
   allowlist miss), send a DM to the session owner via the originating channel.
   Parse their reply (`"yes"` / `"no"` / `"always"`) and act accordingly.
   Time out the request after 30 minutes and deny automatically.

6. **Env sanitization**: Before constructing `env=` for `subprocess`, strip all
   keys matching `*_API_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD` patterns.
