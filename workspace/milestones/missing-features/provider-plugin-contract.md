# Provider Plugin Contract — Features in openclaw Missing from Synapse-OSS

## Overview

openclaw has a rich, typed provider plugin contract (`ProviderPlugin`) with 30+ optional hooks
covering model catalog, auth flows, dynamic model resolution, transport normalization, runtime
auth, usage/quota, embedding creation, and more. Providers are registered as structured objects,
not hardcoded in config files. Synapse-OSS uses a flat `synapse.json` providers dict and a
hardcoded `PROVIDER_LIST` in `cli/provider_steps.py` — no runtime plugin interface exists.

---

## What openclaw has

### 1. `ProviderPlugin` — The Full Provider Contract

**File:** `src/plugins/types.ts` (around line 824+)

A provider plugin is a JavaScript object with an `id`, `label`, `auth` methods, and optional
hooks. Plugins register it via `api.registerProvider(provider)`.

```typescript
export type ProviderPlugin = {
  id: string;
  pluginId?: string;
  label: string;
  docsPath?: string;
  aliases?: string[];        // user-facing alternate ids
  hookAliases?: string[];    // internal-only legacy config keys
  envVars?: string[];        // for display in setup/search/help

  // Auth
  auth: ProviderAuthMethod[];

  // Model catalog
  catalog?: ProviderPluginCatalog;

  // Model resolution hooks
  resolveDynamicModel?: (ctx) => ProviderRuntimeModel | null | undefined;
  prepareDynamicModel?: (ctx) => Promise<void>;
  normalizeResolvedModel?: (ctx) => ProviderRuntimeModel | null | undefined;
  contributeResolvedModelCompat?: (ctx) => Partial<ModelCompatConfig> | null | undefined;
  normalizeModelId?: (ctx) => string | null | undefined;
  normalizeTransport?: (ctx) => { api?, baseUrl? } | null | undefined;
  normalizeConfig?: (ctx) => ModelProviderConfig | null | undefined;
  applyNativeStreamingUsageCompat?: (ctx) => ModelProviderConfig | null | undefined;
  resolveConfigApiKey?: (ctx) => string | null | undefined;

  // Capabilities
  capabilities?: Partial<ProviderCapabilities>;

  // Runtime transport
  prepareExtraParams?: (ctx) => Record<string, unknown> | null | undefined;
  prepareRuntimeAuth?: (ctx) => Promise<ProviderPreparedRuntimeAuth | null | undefined>;
  createStreamFn?: (ctx) => StreamFn | null | undefined;
  wrapStreamFn?: (ctx) => StreamFn | null | undefined;

  // Usage/billing
  resolveUsageAuth?: (ctx) => Promise<ProviderResolvedUsageAuth | null>;
  fetchUsageSnapshot?: (ctx) => Promise<ProviderUsageSnapshot | null>;

  // Embedding
  createEmbeddingProvider?: (ctx) => Promise<PluginEmbeddingProvider | null | undefined>;

  // Policy hooks
  isCacheTtlEligible?: (ctx) => boolean | null | undefined;
  buildMissingAuthMessage?: (ctx) => string | null | undefined;
  buildUnknownModelHint?: (ctx) => string | null | undefined;
  suppressBuiltInModel?: (ctx) => ProviderBuiltInModelSuppressionResult | null | undefined;
  thinkingPolicy?: (ctx) => ProviderThinkingPolicy | null | undefined;
  defaultThinkingPolicy?: (ctx) => ThinkLevel | null | undefined;
  isModernModel?: (ctx) => boolean | null | undefined;
  augmentModelCatalog?: (ctx) => ModelCatalogEntry[] | null | undefined;
  modelSelected?: (ctx) => Promise<void> | void;

  // Auth repair
  resolveSyntheticAuth?: (ctx) => ProviderSyntheticAuthResult | null | undefined;
  oauthProfileIdRepair?: ProviderOAuthProfileIdRepair;
  authDoctorHint?: (ctx) => string | null | undefined;

  // UI
  wizard?: ProviderPluginWizard;
};
```

Every hook is optional — providers implement only what they need. Core calls each hook via the
plugin registry, iterating registered providers to find one that handles the request.

---

### 2. Auth Method Contract — Multiple Auth Flows Per Provider

**File:** `src/plugins/types.ts`

```typescript
export type ProviderAuthMethod = {
  id: string;
  label: string;
  hint?: string;
  kind: ProviderAuthKind;  // "oauth" | "api_key" | "token" | "device_code" | "custom"
  wizard?: ProviderPluginWizardSetup;
  run: (ctx: ProviderAuthContext) => Promise<ProviderAuthResult>;
  runNonInteractive?: (ctx: ProviderAuthMethodNonInteractiveContext) => Promise<OpenClawConfig | null>;
};
```

A single provider can have multiple auth methods (e.g., API key + OAuth + device code). The
`run()` method handles interactive auth; `runNonInteractive()` handles `--flag`-driven setup.

**Auth result includes config patch:**
```typescript
export type ProviderAuthResult = {
  profiles: Array<{ profileId: string; credential: AuthProfileCredential }>;
  configPatch?: Partial<OpenClawConfig>;  // post-auth config defaults (model aliases, etc.)
  defaultModel?: string;
  notes?: string[];
};
```

---

### 3. Provider Catalog — Runtime Model Discovery

**File:** `src/plugins/types.ts`

```typescript
export type ProviderPluginCatalog = {
  order?: ProviderCatalogOrder;  // "simple" | "profile" | "paired" | "late"
  run: (ctx: ProviderCatalogContext) => Promise<ProviderCatalogResult>;
};

export type ProviderCatalogContext = {
  config: OpenClawConfig;
  resolveProviderApiKey: (providerId?) => { apiKey, discoveryApiKey? };
  resolveProviderAuth: (providerId?, options?) => { apiKey, mode, source, profileId? };
  ...
};

export type ProviderCatalogResult =
  | { provider: ModelProviderConfig }
  | { providers: Record<string, ModelProviderConfig> }
  | null | undefined;
```

`catalog.run()` is called at config-load time to discover available models and build the
`models.providers` config. This allows providers to fetch their model list from the API.

---

### 4. Dynamic Model Resolution Pipeline

**File:** `src/plugins/types.ts`

```typescript
// Step 1 (sync): Quick check without network I/O
resolveDynamicModel?: (ctx: ProviderResolveDynamicModelContext) =>
  ProviderRuntimeModel | null | undefined;

// Step 2 (async): Network prefetch, then retry resolveDynamicModel
prepareDynamicModel?: (ctx: ProviderPrepareDynamicModelContext) => Promise<void>;

// Step 3: Rewrite after resolution (transport normalization)
normalizeResolvedModel?: (ctx: ProviderNormalizeResolvedModelContext) =>
  ProviderRuntimeModel | null | undefined;

// Step 4: Contribute compat flags for models not directly owned by this provider
contributeResolvedModelCompat?: (ctx) => Partial<ModelCompatConfig> | null | undefined;
```

Context includes the full model registry so providers can perform look-aside resolution:
```typescript
export type ProviderResolveDynamicModelContext = {
  config?: OpenClawConfig;
  provider: string;
  modelId: string;
  modelRegistry: ModelRegistry;
  providerConfig?: ProviderRuntimeProviderConfig;
};
```

---

### 5. Provider Auth Choice Manifest Entries

**File:** `src/plugins/manifest.ts`

Provider auth choices are declared in the manifest (Phase 0, no runtime load) for CLI integration:

```typescript
export type PluginManifestProviderAuthChoice = {
  provider: string;
  method: string;
  choiceId: string;
  choiceLabel?: string;
  choiceHint?: string;
  deprecatedChoiceIds?: string[];
  groupId?: string;
  groupLabel?: string;
  groupHint?: string;
  optionKey?: string;
  cliFlag?: string;        // e.g. "--xai-api-key"
  cliOption?: string;      // e.g. "--xai-api-key <key>"
  cliDescription?: string;
  onboardingScopes?: ("text-inference" | "image-generation")[];
};
```

This allows `openclaw configure --xai-api-key <key>` to work without loading plugin runtime.

---

### 6. Provider Auth Env Var Manifest Entries

**File:** `src/plugins/manifest.ts`

```typescript
// In PluginManifest
providerAuthEnvVars?: Record<string, string[]>;
// e.g. { "xai": ["XAI_API_KEY"], "openai": ["OPENAI_API_KEY", "OPENAI_ORG_ID"] }
```

Used for cheap env-var lookup (`bundled-provider-auth-env-vars.ts`) without booting plugin
runtime. Populates `models configure --list` and auth doctor hints.

---

### 7. Non-Interactive Auth Path

**File:** `src/plugins/types.ts`

```typescript
export type ProviderAuthMethodNonInteractiveContext = {
  authChoice: string;
  config: OpenClawConfig;
  baseConfig: OpenClawConfig;
  opts: ProviderAuthOptionBag;
  resolveApiKey: (params: ProviderResolveNonInteractiveApiKeyParams) =>
    Promise<ProviderNonInteractiveApiKeyResult | null>;
  toApiKeyCredential: (params) => ApiKeyCredential | null;
};
```

Providers implement `runNonInteractive()` to support `openclaw configure --provider-api-key <key>`
without opening an interactive wizard. The `resolveApiKey` helper handles env/flag/config
precedence uniformly.

---

### 8. Provider Onboarding Wizard Metadata

**File:** `src/plugins/types.ts`

```typescript
export type ProviderPluginWizard = {
  setup?: ProviderPluginWizardSetup;
  modelPicker?: ProviderPluginWizardModelPicker;
};

export type ProviderPluginWizardSetup = {
  choiceId?: string;
  choiceLabel?: string;
  choiceHint?: string;
  groupId?: string;
  groupLabel?: string;
  groupHint?: string;
  methodId?: string;
  onboardingScopes?: Array<"text-inference" | "image-generation">;
  modelAllowlist?: { allowedKeys?, initialSelections?, message? };
  modelSelection?: { promptWhenAuthChoiceProvided?, allowKeepCurrent? };
};
```

Providers control their onboarding flow — which groups they appear in, what model pickers
show, whether to force model selection after auth.

---

### 9. Provider Thinking Policy Hooks

**File:** `src/plugins/types.ts`

```typescript
thinkingPolicy?: (ctx: ProviderThinkingPolicyContext) => ProviderThinkingPolicy | null | undefined;
defaultThinkingPolicy?: (ctx: ProviderDefaultThinkingPolicyContext) => ThinkLevel | null | undefined;
```

Providers can declare whether their models support extended thinking (xhigh, binary on/off)
via plugin hooks rather than hardcoded core tables.

---

### 10. Model Catalog Augmentation

```typescript
augmentModelCatalog?: (ctx: ProviderAugmentModelCatalogContext) =>
  ModelCatalogEntry[] | null | undefined;
```

After the static model catalog loads, each provider can inject forward-compat rows. This allows
providers to support new models before the upstream pi-ai registry catches up.

---

## What Synapse-OSS has (or lacks)

Synapse-OSS handles providers as configuration, not plugins:

- **`synapse.json`** `providers` dict holds API keys keyed by provider name.
- **`cli/provider_steps.py`** has `PROVIDER_LIST` (19 hardcoded entries) and `_KEY_MAP`
  (hardcoded env var names). `PROVIDER_GROUPS` is a hardcoded display grouping.
- **`sci_fi_dashboard/llm_router.py`** routes to providers via `litellm.acompletion` with
  model strings like `"anthropic/claude-haiku-4-5"` — no plugin hooks, no catalog, no dynamic
  model resolution.
- `SynapseConfig.model_mappings` provides simple `{"casual": {"model": "..."}}` aliases.
- No auth method objects, no interactive auth flows, no OAuth, no device code flows.
- No per-provider config normalization, transport hooks, or runtime auth exchange.
- No embedding provider contract.
- No usage/quota hooks.

---

## Gap Summary

| Feature | openclaw | Synapse-OSS |
|---------|----------|-------------|
| `ProviderPlugin` contract (30+ hooks) | Yes | No |
| Multiple auth methods per provider | Yes | No |
| Runtime model catalog discovery | Yes | No |
| Dynamic model resolution pipeline (4 steps) | Yes | No |
| Provider auth choice manifest entries (Phase 0) | Yes | No |
| Provider env-var manifest entries (Phase 0) | Yes | No |
| Non-interactive auth path | Yes | No |
| Onboarding wizard metadata | Yes | No |
| Thinking policy hooks | Yes | No |
| Model catalog augmentation hook | Yes | No |
| Config patch after auth | Yes | No |
| Provider embedding contract | Yes | No |
| Usage/quota hooks | Yes | No |
| Auth repair / OAuth profile migration | Yes | No |

---

## Implementation Notes for Porting

1. **`ProviderPlugin` dataclass:**
   ```python
   @dataclass
   class ProviderPlugin:
       id: str
       label: str
       auth_methods: list[AuthMethod]
       env_vars: list[str] = field(default_factory=list)
       catalog: Callable | None = None
       resolve_dynamic_model: Callable | None = None
       normalize_model_id: Callable | None = None
       capabilities: dict = field(default_factory=dict)
   ```

2. **Auth methods:** Define `AuthMethod(id, label, kind, run, run_non_interactive?)` where
   `run(ctx)` is an `async` function returning credentials and optional config patch.

3. **Catalog:** `catalog(ctx) -> dict | None` returns model definitions to merge into config.
   Call at config-load time for each registered provider.

4. **Dynamic resolution:** Replace hardcoded model string prefix matching in `LLMRouter` with
   a provider hook chain: `resolve_dynamic_model(ctx)` → `prepare_dynamic_model(ctx)` → retry.

5. **Manifest-level entries:** Add `provider_auth_choices` and `provider_auth_env_vars` to
   `synapse.plugin.json` so the CLI onboarding wizard works without loading plugin code.

6. **Config patch:** After `auth.run()` succeeds, merge `result.config_patch` into
   `synapse.json` atomically via `write_config()`.
