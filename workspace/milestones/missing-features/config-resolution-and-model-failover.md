# Configuration Resolution & Model Failover — Missing Features in Synapse-OSS

## Overview

openclaw resolves model and provider configuration through a multi-layer priority
chain and supports runtime model failover (switching to a backup model mid-run
without losing session state). Synapse-OSS uses a flat `synapse.json` config with
a single primary + optional fallback per role and delegates all failover to
`litellm.Router`. The structural gaps are described below.

---

## 1. Multi-Layer Configuration Priority Chain

### What openclaw has

**Files:**
- `src/agents/models-config.ts` — `resolveModelsConfig()`, merges all layers
- `src/agents/models-config.plan.ts` — documents the resolution order
- `src/agents/models-config.providers.ts` — provider-specific normalization

openclaw resolves model/provider configuration in strict priority order:

1. **Per-session override** — `config.sessions[sessionKey].model`
2. **Per-agent override** — `config.agents[agentId].model`
3. **Environment variables** — `OPENCLAW_MODEL`, `OPENCLAW_PROVIDER`, etc.
4. **Plugin-injected defaults** — from loaded provider plugins
5. **Global config** — `openclaw.json` / `~/.openclaw/config.json`
6. **Built-in defaults** — `DEFAULT_MODEL`, `DEFAULT_PROVIDER`

Each layer can override any field from the layer below it. The resolution is done
at request time, not at startup, so a config file change takes effect on the next
run without restarting the gateway.

Provider normalization handles aliases: `gemini` → `google`, `anthropic-vertex` →
`vertex`, `copilot` → `github_copilot`, etc. This normalization is applied
consistently so user-facing config keys and internal provider IDs never diverge.

### What Synapse-OSS has

`SynapseConfig.load()` reads `synapse.json` once and `model_mappings` is a flat
`role → {model, fallback}` dict. There is no per-session override, no per-agent
override, and no environment variable layering beyond the basic
`${ENV_VAR}` substitution in `resolve_env_var()`.

Configuration is loaded once at startup in `SynapseLLMRouter.__init__()`. A config
change requires restarting the process.

### Gap summary

In Synapse-OSS it is not possible to route different users or sessions to different
models at runtime. All sessions share the same model role.

### Implementation notes for porting

1. Introduce a priority chain: `SessionConfig > AgentConfig > EnvVar > GlobalConfig > Defaults`.
2. Resolve the chain at request time by passing the `session_key` and `agent_id`
   to a `resolve_model_for_session(session_key, agent_id)` function.
3. Add `SYNAPSE_MODEL` and `SYNAPSE_PROVIDER` env var overrides that supersede the
   config file values.
4. Hot-reload the config on `SIGHUP` or file watcher so the gateway does not need
   to restart when `synapse.json` changes.

---

## 2. Runtime Model Failover (Mid-Run Model Switch)

### What openclaw has

**Files:**
- `src/agents/model-fallback.ts` — `resolveModelFallback()`
- `src/agents/failover-error.ts` — `FailoverError`, `resolveFailoverStatus`
- `src/agents/pi-embedded-runner/run.ts` — failover handling in the main retry loop
- `src/agents/live-model-switch.ts` — `LiveSessionModelSwitchError`, `consumeLiveSessionModelSwitch`

When an attempt fails with a classified `FailoverReason`, openclaw selects a
fallback model using `resolveModelFallback()`. The fallback lookup considers:
- Per-reason override (e.g., use model B only on `context_overflow`).
- Provider-level fallbacks (e.g., all `anthropic` failures fall back to `openai`).
- The current `thinkLevel` (a different model may be required for `high` thinking).

A `FailoverError` is a typed error carrying `reason`, `provider`, and `model`:

```ts
export class FailoverError extends Error {
  constructor(
    message: string,
    public readonly params: { reason: FailoverReason; provider: string; model: string }
  ) { ... }
}
```

`LiveSessionModelSwitchError` handles the case where the user switches models
_while_ an inference is in progress: the current attempt is aborted and restarted
with the new model, preserving session history.

### What Synapse-OSS has

`litellm.Router` handles fallbacks at the HTTP level: if the primary model returns
a non-200 response, the router automatically retries with the fallback model
configured in `model_list[role_fallback]`. This works for simple HTTP errors but
has no awareness of:
- OpenClaw-style `FailoverReason` classification.
- Thinking/reasoning level constraints.
- Mid-stream model switches triggered by the user.
- Per-reason fallback selection.

`build_router()` in `llm_router.py` sets `num_retries=0, retry_after=0`, disabling
litellm's built-in retry logic entirely. The Router's fallback path therefore only
fires on initial-call failures, not on mid-stream errors.

### Gap summary

Synapse-OSS's failover is delegated entirely to litellm's Router, which handles
simple HTTP-level retries but not the semantic classification (auth, billing,
overflow, etc.) that openclaw uses to decide _which_ backup strategy to apply.
Per-reason model substitution is not possible.

### Implementation notes for porting

1. Define a `FailoverReason` enum (already partially present as
   `AuthProfileFailureReason` in `llm_router.py`) with values:
   `auth`, `auth_permanent`, `billing`, `rate_limit`, `overloaded`, `context_overflow`,
   `model_not_found`, `format`, `timeout`, `unknown`.
2. In the outer retry loop (Feature 1 from `agent-runtime.md`), classify each
   exception to a `FailoverReason` and route to the appropriate recovery branch.
3. Add a `resolve_model_fallback(reason, provider, model)` function that returns
   the backup model for each reason type.
4. Expose `live_model_switch_event: asyncio.Event` per session so the user can
   trigger a model switch mid-inference.

---

## 3. Model Auth Profiles — OAuth, API Key, and Token Credential Types

### What openclaw has

**Files:**
- `src/agents/auth-profiles/types.ts` — `AuthProfileStore`, `ApiKeyCredential`,
  `OAuthCredential`, `TokenCredential`
- `src/agents/auth-profiles/profiles.ts` — `upsertAuthProfile`, `listProfilesForProvider`
- `src/agents/auth-profiles/order.ts` — `resolveAuthProfileOrder`, `resolveAuthProfileEligibility`

An `AuthProfileStore` holds multiple named profiles per provider. Each profile is
one of three types:
- `ApiKeyCredential` — static API key string.
- `OAuthCredential` — OAuth access token, optional refresh token, and expiry.
- `TokenCredential` — opaque bearer token with optional expiry.

`resolveAuthProfileOrder()` sorts candidates by: explicit user preference first,
then last-used profile, then all eligible profiles in round-robin order, excluding
profiles in cooldown. This ensures organic load balancing across multiple keys
without starvation.

`resolveAuthProfileEligibility()` returns a typed reason code when a profile is
ineligible (`in_cooldown`, `no_api_key`, `wrong_provider`, `disabled`, etc.),
enabling the UI to show specific actionable messages.

### What Synapse-OSS has

`execute_with_api_key_rotation()` in `llm_router.py` accepts a flat `list[str]` of
API keys. There is no profile metadata (no type, no expiry, no OAuth flow, no
last-used tracking). The selection order is fixed at call-time by the caller.

### Gap summary

Synapse-OSS cannot represent OAuth credentials with token refresh, cannot load
balance across multiple keys for the same provider based on recency / cooldown
state, and cannot report specific eligibility reasons to the user.

### Implementation notes for porting

1. Define an `AuthProfile` dataclass: `id`, `type` (`api_key | oauth | token`),
   `provider`, `api_key | access_token`, `refresh_token`, `expires_at`.
2. Store profiles in the existing `synapse.json` under `auth_profiles[]`.
3. Implement `resolve_profile_order(store, provider)` that sorts by last-used and
   skips profiles in cooldown (from the cooldown tracking in `agent-runtime.md`
   Feature 2).
4. For OAuth profiles, call the refresh endpoint when `expires_at` is within the
   refresh margin (from `agent-runtime.md` Feature 3).

---

## 4. Configured Provider Fallback Chain

### What openclaw has

**File:** `src/agents/configured-provider-fallback.ts`

`resolveConfiguredProviderFallbackChain()` builds a list of `{provider, model}`
pairs from the config's `modelFallbacks` list. The caller iterates the chain in
order, and each entry is tried as a complete provider+model pair (not just a model
switch within the same provider).

This is distinct from key rotation: key rotation cycles through API keys for the
same provider/model; the fallback chain switches to an entirely different
provider (e.g., from Anthropic to Google Gemini) when all Anthropic profiles are
exhausted or disabled.

**File:** `src/agents/model-fallback.ts`

`resolveModelFallback()` selects the next entry in the chain based on the current
`provider`, `model`, and `reason`. If reason is `context_overflow` and the fallback
model has a larger context window, it is preferred even if it is not the next entry
in the configured order.

### What Synapse-OSS has

`build_router()` wires a single fallback per role (`role_fallback`). There is no
multi-provider fallback chain. If both primary and fallback are from the same
provider and that provider is down, there is no escalation to a third provider.

### Gap summary

Synapse-OSS has no way to say "if Anthropic is down, try Google Gemini, then
Groq." The fallback is a single hop within the same role, not a chain.

### Implementation notes for porting

1. Add a `provider_fallback_chain: list[{provider, model}]` key to `synapse.json`.
2. In the outer retry loop, after exhausting all keys for the current provider,
   advance to the next entry in `provider_fallback_chain`.
3. For `context_overflow`, scan the chain and prefer the first entry whose
   `context_window` (from `models_catalog.py`) is larger than the current model.
4. Persist the current chain position so a Copilot-style token refresh can resume
   at the correct entry after a proactive refresh.

---

## 5. Model Discovery and Compatibility Probing

### What openclaw has

**Files:**
- `src/agents/pi-model-discovery.ts` — `discoverModelsForProvider()`
- `src/agents/model-catalog.ts` — `resolveModelCatalogEntry()`
- `src/agents/provider-capabilities.ts` — `resolveProviderCapabilities()`

At startup (and on demand), openclaw can enumerate available models from a provider's
`/models` endpoint and populate the local model catalog with context-window sizes,
supported tool formats, and vision capabilities. This is used to:
- Validate that a configured model actually exists before starting a run.
- Pick the largest-context fallback during `context_overflow` failover.
- Warn the user if a configured model has been deprecated.

`src/agents/model-fallback.probe.test.ts` covers the probe path.

**File:** `src/agents/model-tool-support.ts` — `supportsModelTools()`

Returns whether a model supports tool/function calling. This gate prevents sending
tool definitions to models that do not understand them (which causes a
`BadRequestError`).

### What Synapse-OSS has

`models_catalog.py` in `workspace/sci_fi_dashboard/models_catalog.py` exists but
is a static lookup table. There is no dynamic model discovery from provider APIs
and no tool-support check before sending tool definitions.

### Gap summary

Synapse-OSS cannot detect a misconfigured or deprecated model before the first LLM
call. A typo in `synapse.json` causes a `BadRequestError` at runtime rather than a
startup validation error.

### Implementation notes for porting

1. Add a `probe_model(provider, model, api_key)` function that sends a minimal
   completion request and returns `{ok, error, context_window}`.
2. Call it during the onboarding wizard and on `synapse doctor` to validate all
   configured models.
3. Extend `models_catalog.py` with a `supports_tools: bool` field; filter tool
   definitions based on this flag before calling `acompletion()`.
4. Optionally fetch the provider's `/models` endpoint at startup and merge the
   results into `models_catalog.py` to pick up newly released models automatically.
