# Configuration System — Gaps in Synapse-OSS

## Overview

openclaw has a deeply layered, Zod-validated configuration system with hundreds of typed fields, layered resolution (CLI > runtime > session > agent > gateway defaults), auth profile rotation, model fallback chains, per-session model overrides, and a runtime snapshot mechanism that redacts secrets for safe persistence. Synapse-OSS has a minimal flat dataclass (`SynapseConfig`) that reads a two-layer `synapse.json` + env var config. The gap is substantial in both depth and type safety.

---

## What openclaw Has

### 1. Zod-Validated Root Schema (`src/config/zod-schema.ts` + `src/config/schema.ts`)

The root Zod schema covers:
- `agents.*` — per-agent and global agent defaults: model, fallbacks, thinking level, tools, memory, context window, max tokens, temperature, image model, timeout, session, sandbox, hooks.
- `channels.*` — per-channel config for Telegram, Discord, Slack, Signal, iMessage, WhatsApp, IRC, MS Teams, Google Chat, Matrix.
- `models.*` — provider base URLs, API key secrets, model aliases.
- `tools.*` — web search, memory, media understanding (audio/image/video providers, attachment policy, scope), MCP, cron, browser, sandboxing.
- `plugins.*` — plugin enable/disable, per-plugin config blocks.
- `gateway.*` — WebSocket port, host, TLS, Tailscale bind, auth token, control UI origins.
- `secrets.*` — named secret inputs (env var, literal, file, command).
- `session.*` — DM policy, group policy, thread bindings, context window, history limits.
- `approvals.*` — approval workflow config.
- `hooks.*` — webhook handlers, Gmail hooks.
- `logging.*` — log level, max file bytes, retention.
- `memory.*` — backend (builtin SQLite-vec or QMD), index paths, session export, update interval, embedding provider.
- `cron.*` — retention, backup timing.
- `identity.*` — avatar, display name.
- `talk.*` — TTS voice, provider.

**Files:** `src/config/zod-schema.ts`, `src/config/schema.ts`, `src/config/schema.base.generated.ts`

### 2. Layered Config Resolution (`src/config/config.ts`, `src/config/runtime-overrides.ts`)

Resolution order (highest → lowest priority):

1. **CLI flags** — `--model`, `--api-key`, etc. passed at invocation.
2. **Runtime overrides** — in-process patches applied by commands like `openclaw config set`.
3. **Session-level overrides** — per-session model/tool overrides.
4. **Agent-level config** — per-agent directory `openclaw.json`.
5. **Gateway defaults** — root `~/.openclaw/openclaw.json`.

`runtime-overrides.ts` applies merge-patch semantics on the in-memory config without touching the file, enabling hot config changes without restart.

`runtime-schema.ts` validates the runtime config shape and rejects invalid patches.

**Files:** `src/config/config.ts`, `src/config/runtime-overrides.ts`, `src/config/runtime-schema.ts`

### 3. Merge-Patch Semantics (`src/config/merge-patch.ts`)

RFC 7396 JSON Merge Patch with prototype-pollution protection (`src/config/merge-patch.proto-pollution.test.ts`). Used for incremental config updates and for applying agent-level config on top of gateway defaults.

**File:** `src/config/merge-patch.ts`

### 4. Auth Profile Rotation (`src/agents/auth-profiles.*`)

- `auth-profiles.ts` — `AuthProfileStore`: loads, saves, rotates named API key profiles.
- `auth-profiles.resolve-auth-profile-order.ts` — priority ordering: last-good profile, explicit order list, round-robin.
- `auth-profiles.markauthprofilefailure.ts` — marks a profile as failed, triggers cooldown.
- `auth-profiles.cooldown-auto-expiry.ts` — auto-expires cooldowns after configured duration.
- `auth-profiles.doctor.ts` — health check across all profiles.
- `auth-profiles.getsoonestcooldownexpiry.ts` — when to retry a cooled-down profile.

**Files:** `src/agents/auth-profiles/` directory

### 5. Model Fallback Chain (`src/config/zod-schema.agent-model.ts`, `src/config/model-input.ts`)

- `AgentModelSchema` — primary model + ordered fallback list.
- `resolveAgentModelPrimaryValue` / `resolveAgentModelFallbackValues` — extract primary and fallback refs.
- `zod-schema.agent-defaults.ts` — global `imageModel`, `audioModel` fallback chains with the same schema.
- Config supports `provider/model` strings, model aliases, and thinking-level annotations.

**Files:** `src/config/zod-schema.agent-model.ts`, `src/config/model-input.ts`, `src/config/model-alias-defaults.ts`

### 6. Per-Session Model Overrides (`src/config/sessions/`)

`src/config/sessions.ts` — `SessionConfigStore`: loads/saves per-session config that overrides gateway defaults. Session config keys: `model`, `thinking`, `toolsAllow`, `toolsDeny`, `context`, `maxTokens`.

Config resolution during agent inference:
1. Session-level model override.
2. Agent-level `agents.defaults.model`.
3. Gateway-level `agents.defaults.model`.
4. Built-in default (`claude-3-5-sonnet`).

**File:** `src/config/sessions.ts`

### 7. Thinking Level Configuration

`thinking` config key accepts: `"auto"`, `"none"`, `"low"`, `"medium"`, `"high"`, or a raw `{type: "enabled", budget_tokens: N}` object. Resolved by `zod-schema.agent-runtime.ts`.

**File:** `src/config/zod-schema.agent-runtime.ts`

### 8. Secret Redaction + Runtime Snapshot (`src/config/redact-snapshot.ts`)

- `redactSnapshot(config)` — replaces all `SecretInput` values with opaque `{type: "secret-ref", ref: "<key>"}` tokens before writing config to disk or sending to the UI.
- `restoreSnapshot(redacted, live)` — restores the opaque tokens from the live config.
- `schema.hints.ts` — UI hints (sensitive, URL, file path) for each field.
- `io.ts` — atomic config file writes with `.tmp` + `os.replace`, permission 0o600.

**Files:** `src/config/redact-snapshot.ts`, `src/config/io.ts`

### 9. Environment Variable Substitution (`src/config/env-substitution.ts`, `config-env-vars.ts`)

- `${ENV_VAR_NAME}` placeholders in config values are expanded at load time.
- `env-preserve.ts` — captures env snapshot for deterministic resolution.
- `state-dir-dotenv.ts` — loads `.env` from the state directory on startup.
- Supported in: API keys, base URLs, webhook URLs, paths.

**Files:** `src/config/env-substitution.ts`, `src/config/env-vars.ts`, `src/config/config-env-vars.ts`

### 10. Legacy Config Migration (`src/config/legacy-migrate.ts`)

Automatically migrates older config schemas to the current format on load. Covers routing → channel migration, `dmPolicy` alias, audio field changes. Migration rules defined in `legacy.migrations.ts` (channels, audio, runtime).

**File:** `src/config/legacy-migrate.ts`

### 11. Config Includes (`src/config/includes.ts`)

`$include: "./path/to/fragment.json"` in config files — merges additional config files before validation. Used for splitting large configs into per-channel files.

**File:** `src/config/includes.ts`

### 12. Group Policy (`src/config/group-policy.ts`, `runtime-group-policy.ts`)

Per-group allow/deny rules for message routing. Runtime group policy cache keyed by `(channelId, groupId)`.

**Files:** `src/config/group-policy.ts`, `src/config/runtime-group-policy.ts`

### 13. Channel Capabilities (`src/config/channel-capabilities.ts`)

Maps each channel ID to a capability set: `supportsImages`, `supportsAudio`, `supportsVideo`, `supportsFormatting`, `supportsReactions`, `supportsThreads`, etc.

**File:** `src/config/channel-capabilities.ts`

---

## What Synapse-OSS Has

`workspace/synapse_config.py` — `SynapseConfig` frozen dataclass:

- Three fields from `synapse.json`: `providers` (dict), `channels` (dict), `model_mappings` (dict).
- Three derived fields: `gateway`, `session`, `mcp` — also from `synapse.json`.
- Three path fields derived from `data_root`: `db_dir`, `sbs_dir`, `log_dir`.
- One env-var layer: `SYNAPSE_HOME` sets `data_root`.
- `write_config` — atomic write with 0o600 mode (good).
- `gateway_token` / `dm_scope` / `identity_links` helpers.

`workspace/config.py` — flat env-var reads for `SERVER_PORT`, `WHISPER_MODEL`, `GROQ_API_KEY`, `WINDOWS_PC_IP`, `ADMIN_PHONE`, `VIP_PHONE`.

| Feature | Synapse-OSS | openclaw |
|---|---|---|
| Schema validation | None (raw dicts) | Full Zod + TypeScript types |
| Layered resolution | 2 layers (env + file) | 5 layers (CLI → runtime → session → agent → gateway) |
| Model fallback chain | None | Full primary + ordered fallbacks |
| Auth profile rotation | None | Full (cooldown, round-robin, last-good) |
| Per-session overrides | None | Full (model, thinking, tools, context) |
| Thinking level config | None | Full (auto/none/low/medium/high) |
| Secret redaction | None | Full (opaque refs, restore on load) |
| Env var substitution | Partial (direct `os.getenv`) | Full (`${VAR}` in any string field) |
| Config includes | None | Yes (`$include`) |
| Merge-patch updates | None | Full RFC 7396 |
| Legacy migration | None | Automatic |
| Group policy | None | Full |
| Channel capabilities | None | Full |
| Config UI hints | None | Full (sensitive, URL, file) |
| Atomic writes | Yes (0o600) | Yes (0o600) |

---

## Gap Summary

Synapse-OSS lacks: schema validation entirely (config is opaque dicts), model fallback chains, auth profile rotation, per-session model overrides, thinking level configuration, secret redaction, env-var substitution in config values, config file includes, merge-patch semantics, legacy migration, group policy, and channel capability metadata.

---

## Implementation Notes for Porting

1. **Schema validation** — Replace raw dict access with Pydantic v2 models. Define nested models for `agents`, `channels`, `tools`, `gateway`, `memory`, `cron`. Add `model_validator` for cross-field constraints.

2. **Model fallback chain** — Add `model: str | list[str]` field. Agent inference loop: try primary, on auth failure try each fallback in order.

3. **Auth profile rotation** — Add `AuthProfileStore` class with `mark_failure(profile_id)`, `get_next_profile()`, cooldown TTL. Store state in `~/.synapse/auth-profiles.json`.

4. **Per-session overrides** — Store a `{session_key: {model, thinking, tools_allow}}` dict in `~/.synapse/sessions/` as JSON files. Merge over gateway defaults at inference time.

5. **Secret redaction** — Before writing config to disk: walk the dict, replace any field tagged as sensitive with `{"type": "secret-ref", "ref": "field.path"}`. On load: restore from live env.

6. **Env-var substitution** — Walk all string config values; expand `${VAR_NAME}` using `os.environ`. Run after file load, before Pydantic validation.
