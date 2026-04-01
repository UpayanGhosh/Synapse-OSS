# Missing Features: OpenClaw vs Synapse-OSS

This folder documents features present in **OpenClaw** (TypeScript) that are absent or
significantly underdeveloped in **Synapse-OSS** (Python). Each file covers one domain.
Files are grouped by the five comparison areas.

---

## Agent Runtime & Inference

| File | Summary |
|------|---------|
| [agent-runtime.md](agent-runtime.md) | Retry loop with attempt state, per-key auth cooldowns, overflow-compaction integration, tool-loop circuit-breaker |
| [multi-agent-orchestration.md](multi-agent-orchestration.md) | Subagent registry/lifecycle, spawn depth limiting, push-based announce flow, ACP protocol, capability/scope isolation |
| [session-management.md](session-management.md) | Write-lock with PID-recycling detection, LRU conversation cache, adaptive compaction chunking, transcript repair at load time |
| [config-resolution-and-model-failover.md](config-resolution-and-model-failover.md) | 5-layer config priority chain, runtime mid-run model switch, typed auth profiles, multi-provider fallback chain, model compatibility probing |

---

## Channel & Communication Systems

| File | Summary |
|------|---------|
| [channel-system.md](channel-system.md) | Channel ID catalogue, plugin-driven registry, multi-account support, 8-tier binding resolution, identity links |
| [delivery-queue.md](delivery-queue.md) | Discord rate-limit retry, Telegram 401 circuit breaker, draft-streaming live previews, per-channel text splitting, inbound debouncing |
| [interactive-messages.md](interactive-messages.md) | Telegram inline keyboards, Slack Block Kit with tables, Discord Component V2 & modals, exec-approval flows, emoji status reactions |
| [thread-reply-support.md](thread-reply-support.md) | Telegram thread binding with idle/age expiry, Discord/Matrix auto-subagent spawn from threads, Slack threading cache |
| [media-voice-dedup.md](media-voice-dedup.md) | Discord voice messages (OGG/Opus), Telegram sticker vision pipeline, PluralKit deduplication, mention gating |
| [polling-resilience.md](polling-resilience.md) | Persisted Telegram update offset with bot-ID rotation detection, polling stall watchdog, network error classification, per-account proxy |

---

## Plugin System & Extension SDK

| File | Summary |
|------|---------|
| [plugin-system.md](plugin-system.md) | Declarative manifest format (20+ fields), two-phase load pipeline, multi-root discovery, NPM install lifecycle, 90 bundled extensions |
| [hook-system.md](hook-system.md) | 26 named hook events across 5 categories, three execution strategies, synchronous hot-path hooks, per-plugin error isolation |
| [plugin-sdk.md](plugin-sdk.md) | `openclaw/plugin-sdk/*` subpath exports (50+), session-scoped tool factory contract, optional-tool allowlist, name conflict detection |
| [plugin-install-security.md](plugin-install-security.md) | Install-time security scan, 10 structured error codes, min-host-version check, path-escape blocking, NPM integrity drift detection |
| [provider-plugin-contract.md](provider-plugin-contract.md) | `ProviderPlugin` interface (30+ hooks), multiple auth methods per provider, runtime model catalog hook, 4-step dynamic model resolution |

---

## Security, Sandbox & Process Management

| File | Summary |
|------|---------|
| [sandbox-isolation.md](sandbox-isolation.md) | Docker/SSH sandbox, SandboxContext, mount security validation, `BLOCKED_HOST_PATHS` denylist, seccomp/AppArmor, SandboxFsPathGuard |
| [exec-approval-system.md](exec-approval-system.md) | `ExecSecurity`/`ExecAsk` policies, per-agent JSON allowlist, safe-binary profiles with flag-level validation, obfuscation detection, DM approval routing |
| [process-supervisor.md](process-supervisor.md) | ProcessSupervisor run registry, scope-based cancellation, PTY adapter, send-keys, kill-tree (SIGTERM→SIGKILL / taskkill /T→/F) |
| [ssrf-protection.md](ssrf-protection.md) | Legacy IPv4 literal detection, embedded IPv4 in IPv6, two-phase DNS rebinding protection, pinned DNS, global fetch guard, transport-layer enforcement |
| [tool-loop-detection.md](tool-loop-detection.md) | 4 detectors (generic_repeat, known_poll_no_progress, ping_pong, global_circuit_breaker), sliding window of 30 calls, session blocking on critical |

---

## Media, Browser, Config & Tooling

| File | Summary |
|------|---------|
| [media-pipeline.md](media-pipeline.md) | 2 MB gateway offload (claim-check / `media://` URI), MIME sniffing, image/video understanding, FFmpeg, per-channel size enforcement, DeliveryQueue |
| [browser-tool.md](browser-tool.md) | Playwright 16-action tool, SSRF pinned DNS (TOCTOU protection), ARIA/AI snapshot formats, tab management, WeakMap page state |
| [config-system.md](config-system.md) | Zod-validated 5-layer config, auth profile rotation, model fallback chains, per-session model overrides, secret redaction, env-var substitution |
| [memory-system.md](memory-system.md) | In-process `sqlite-vec` (no external services), `.md` file indexing, session transcript auto-indexing, full sync pipeline with progress callbacks |
| [cron-scheduler.md](cron-scheduler.md) | 3 schedule kinds (at/every/cron), isolated-agent execution, multi-channel delivery routing, failure alerting with cooldown, full CRUD API |
| [specialized-tools.md](specialized-tools.md) | xAI remote Python code execution (streaming SSE), adaptive file paging (20% context-window share), web UI (Lit SPA + WebSocket), context engine |

---

## Summary: Gap Count by Domain

| Domain | Files | Gap Severity |
|--------|-------|-------------|
| Agent runtime & inference | 4 | High — no retry loop, no overflow compaction, no auth cooldowns |
| Channel & communication | 6 | High — no interactive messages, thread management, or delivery reliability |
| Plugin system & SDK | 5 | Critical — no plugin system, no hook system, no public SDK |
| Security, sandbox & process | 5 | Critical — no sandbox isolation, no exec gating, no loop detection |
| Media, browser, config & tooling | 6 | High — no browser tool, no media pipeline, flat config only |
| **Total** | **26** | |
