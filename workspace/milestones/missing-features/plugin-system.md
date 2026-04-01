# Plugin System — Features in openclaw Missing from Synapse-OSS

## Overview

openclaw has a first-class, structured plugin system with two-phase loading, declarative manifests,
strict security checks, NPM-based distribution, and a rich public SDK. Synapse-OSS has no plugin
system at all — extensions are ad-hoc Python modules imported directly. This document covers the
**plugin discovery, manifest parsing, loader, and registry** layers.

---

## What openclaw has

### 1. Declarative Manifest Format — `openclaw.plugin.json`

**File:** `src/plugins/manifest.ts`

Every plugin ships a single JSON manifest at its root. The schema is:

```typescript
// src/plugins/manifest.ts
export type PluginManifest = {
  id: string;                             // stable plugin id
  configSchema: Record<string, unknown>;  // JSON Schema for plugin config
  enabledByDefault?: boolean;
  legacyPluginIds?: string[];             // migration aliases
  autoEnableWhenConfiguredProviders?: string[];
  kind?: PluginKind | PluginKind[];       // "memory" | "context-engine"
  channels?: string[];                    // channel ids owned
  providers?: string[];                   // provider ids owned
  cliBackends?: string[];
  providerAuthEnvVars?: Record<string, string[]>;
  providerAuthChoices?: PluginManifestProviderAuthChoice[];
  skills?: string[];
  name?: string;
  description?: string;
  version?: string;
  uiHints?: Record<string, PluginConfigUiHint>;
  contracts?: PluginManifestContracts;    // capability ownership snapshot
  channelConfigs?: Record<string, PluginManifestChannelConfig>;
};
```

Manifests are read without loading plugin runtime (Phase 0 / manifest-only scan). This allows
cheap capability discovery, `models list`, `models configure`, and CLI help without booting JS.

**Example** (`extensions/xai/openclaw.plugin.json`):
```json
{
  "id": "xai",
  "enabledByDefault": true,
  "providers": ["xai"],
  "providerAuthEnvVars": { "xai": ["XAI_API_KEY"] },
  "contracts": { "webSearchProviders": ["grok"], "tools": ["code_execution", "x_search"] },
  "configSchema": { "type": "object", ... }
}
```

**Key functions:**
- `loadPluginManifest(rootDir, rejectHardlinks)` → `PluginManifestLoadResult`
- `resolvePluginManifestPath(rootDir)` → string
- `getPackageManifestMetadata(manifest)` → `OpenClawPackageManifest | undefined`
- `resolvePackageExtensionEntries(manifest)` → `PackageExtensionResolution`

The manifest loader uses `openBoundaryFileSync()` — it validates the file is inside the plugin
root, rejects symlinks that escape root, and refuses world-writable paths.

---

### 2. Two-Phase Pipeline: Manifest Scan → Runtime Load

**Files:** `src/plugins/manifest-registry.ts`, `src/plugins/loader.ts`

**Phase 0 (manifest-only):** `loadPluginManifestRegistry()` walks all source roots and reads
manifests without executing any plugin code. Produces `PluginManifestRecord[]`. Used by:
- Config validation (schema checks)
- `models list` / `models configure`
- Channel catalog (setup UI)
- Provider auth env-var lookup
- Startup deferral decisions

**Phase 1 (runtime load):** `resolveRuntimePluginRegistry()` / `loadPluginRuntime()` executes
actual plugin code via Jiti dynamic import. Plugins call the registration API (`registerTool`,
`registerChannel`, `on(hookName, handler)`, etc.) to populate the `PluginRegistry`.

```typescript
// src/plugins/loader.ts
export type PluginLoadOptions = {
  config?: OpenClawConfig;
  workspaceDir?: string;
  env?: NodeJS.ProcessEnv;
  mode?: "full" | "validate";
  onlyPluginIds?: string[];
  activate?: boolean;          // whether to mutate process-global state
  cache?: boolean;
  throwOnLoadError?: boolean;
};
```

Jiti is used with a per-plugin alias map (`buildPluginLoaderAliasMap`) so that each plugin's
`openclaw/plugin-sdk/*` imports resolve correctly regardless of where the plugin is installed.

---

### 3. Plugin Discovery with Security Checks

**File:** `src/plugins/discovery.ts`

`discoverOpenClawPlugins()` scans four source roots in priority order:

| Origin | Description |
|--------|-------------|
| `config` | Paths in `plugins.paths` config key |
| `workspace` | `<workspaceDir>/.openclaw/plugins/` |
| `global` | `~/.openclaw/extensions/` |
| `bundled` | `extensions/` directory in the openclaw package |

Security checks per candidate:
- **Path escape check:** `source_escapes_root` — symlink realpath must stay inside plugin root
- **World-writable gate:** `path_world_writable` — `chmod 022` is auto-applied for bundled dirs
- **Ownership check:** `path_suspicious_ownership` — uid must match process uid (skipped on Windows)

```typescript
export type CandidateBlockReason =
  | "source_escapes_root"
  | "path_stat_failed"
  | "path_world_writable"
  | "path_suspicious_ownership";
```

A time-bounded discovery cache (`DEFAULT_DISCOVERY_CACHE_MS = 1000`) collapses bursty reloads
during startup. Cache key encodes all source roots + UID.

---

### 4. Plugin Registry — Typed Registration Surface

**File:** `src/plugins/registry.ts`

`PluginRegistry` is a structured, immutable snapshot of all registered extension points:

```typescript
export type PluginRegistry = {
  plugins: PluginRecord[];
  tools: PluginToolRegistration[];          // session-scoped tool factories
  hooks: PluginHookRegistration[];          // legacy hook entries
  typedHooks: TypedPluginHookRegistration[];// typed hook entries (priority-ordered)
  channels: PluginChannelRegistration[];
  channelSetups: PluginChannelSetupRegistration[];
  providers: PluginProviderRegistration[];
  cliBackends?: PluginCliBackendRegistration[];
  speechProviders: PluginSpeechProviderRegistration[];
  mediaUnderstandingProviders: PluginMediaUnderstandingProviderRegistration[];
  imageGenerationProviders: PluginImageGenerationProviderRegistration[];
  webSearchProviders: PluginWebSearchProviderRegistration[];
  gatewayHandlers: GatewayRequestHandlers;
  gatewayMethodScopes?: Partial<Record<string, OperatorScope>>;
  httpRoutes: PluginHttpRouteRegistration[];
  cliRegistrars: PluginCliRegistration[];
  services: PluginServiceRegistration[];
  commands: PluginCommandRegistration[];
  conversationBindingResolvedHandlers: PluginConversationBindingResolvedHandlerRegistration[];
  diagnostics: PluginDiagnostic[];
};
```

Per-plugin record tracks all registered capabilities:

```typescript
export type PluginRecord = {
  id: string;
  status: "loaded" | "disabled" | "error";
  toolNames: string[];
  hookNames: string[];
  channelIds: string[];
  providerIds: string[];
  speechProviderIds: string[];
  // ... etc
};
```

`createPluginRegistry()` accepts `activateGlobalSideEffects?: boolean` — when `false`, keeps
registration local (snapshot mode) without mutating process-global command/hook state.

---

### 5. NPM-Based Install, Update, and Uninstall

**Files:** `src/plugins/install.ts`, `src/plugins/update.ts`, `src/plugins/uninstall.ts`

Plugins are distributed as npm packages. The install flow:
1. Resolves npm spec → `NpmSpecResolution`
2. Runs security scan (`scanPackageInstallSource`, `scanBundleInstallSource`)
3. Validates `openclaw.extensions` array in `package.json`
4. Checks `minHostVersion` compatibility
5. Writes to `~/.openclaw/extensions/<pluginId>/`

```typescript
export const PLUGIN_INSTALL_ERROR_CODE = {
  INVALID_NPM_SPEC: "invalid_npm_spec",
  INVALID_MIN_HOST_VERSION: "invalid_min_host_version",
  INCOMPATIBLE_HOST_VERSION: "incompatible_host_version",
  MISSING_OPENCLAW_EXTENSIONS: "missing_openclaw_extensions",
  NPM_PACKAGE_NOT_FOUND: "npm_package_not_found",
  PLUGIN_ID_MISMATCH: "plugin_id_mismatch",
  SECURITY_SCAN_BLOCKED: "security_scan_blocked",
  SECURITY_SCAN_FAILED: "security_scan_failed",
} as const;
```

Install also validates archive roots against `PLUGIN_ARCHIVE_ROOT_MARKERS` for zip/tarball
installs (`.codex-plugin/plugin.json`, `.claude-plugin/plugin.json`, `.cursor-plugin/plugin.json`).

---

### 6. Registry Caching (LRU, 128 entries)

**File:** `src/plugins/loader.ts`

The plugin loader maintains an in-process LRU cache of loaded registries. Cache key is derived
from all config inputs (paths, workspace dir, env vars, uid). This prevents re-running Jiti on
every tool-construction call while still detecting config changes.

```typescript
const MAX_PLUGIN_REGISTRY_CACHE_ENTRIES = 128;
const registryCache = new Map<string, CachedPluginState>();
```

`CachedPluginState` snapshot includes:
- `registry: PluginRegistry`
- `memoryEmbeddingProviders`
- `memoryFlushPlanResolver`
- `memoryPromptBuilder`
- `memoryRuntime`

`clearPluginLoaderCache()` resets all of these atomically.

---

### 7. 90 Bundled Extensions

**Directory:** `extensions/`

openclaw ships 90 bundled plugins including full provider integrations (OpenAI, Anthropic, xAI,
Google, Mistral, Ollama, etc.), channel adapters (Telegram, Discord, Slack, WhatsApp, Signal,
Matrix, etc.), and specialized capabilities (browser automation, speech, image generation, web
search, memory engines).

Each extension is an independent npm workspace package with:
- `openclaw.plugin.json` (manifest)
- `package.json` with `openclaw.extensions` array
- TypeScript source in `src/`
- Colocated tests

---

## What Synapse-OSS has (or lacks)

Synapse-OSS has **no plugin system**. Its equivalent components are:

- **Channels** are registered in `sci_fi_dashboard/api_gateway.py` via direct Python instantiation:
  ```python
  channel_registry.register(WhatsAppChannel(...))
  channel_registry.register(TelegramChannel(...))
  ```
  `ChannelRegistry` (`sci_fi_dashboard/channels/registry.py`) is a minimal lifecycle manager —
  it has no plugin contracts, no manifest parsing, and no dynamic discovery.

- **Providers** are configured via `synapse.json` (`providers` dict) and hardcoded in
  `cli/provider_steps.py` (`PROVIDER_LIST`, `_KEY_MAP`). There is no runtime plugin interface.

- **"Skills"** (`workspace/skills/`) are plain Python files — `llm_router.py`, `memory/`,
  `language/`, `gog/`. They are imported directly, not through any loader or manifest system.

- No NPM/pip package distribution for extensions.
- No security scanning of extension code.
- No manifest-driven capability discovery.
- No typed registration surface.

---

## Gap Summary

| Feature | openclaw | Synapse-OSS |
|---------|----------|-------------|
| Declarative manifest (`openclaw.plugin.json`) | Full schema, 20+ fields | None |
| Two-phase load (manifest scan → runtime) | Yes | No |
| Multi-root plugin discovery (4 origins) | Yes | No |
| Security checks (path escape, world-writable, uid) | Yes | No |
| Typed plugin registry with all extension points | Yes | No |
| NPM-based install/update/uninstall | Yes | No |
| LRU registry cache | Yes (128 entries) | No |
| 90 bundled plugins | Yes | 4 ad-hoc skill files |
| Plugin enable/disable per config | Yes | No |
| Plugin diagnostic collection | Yes | No |

---

## Implementation Notes for Porting

1. **Manifest format:** Define a `synapse.plugin.json` schema (Python dataclass or Pydantic model).
   Minimum required fields: `id`, `config_schema`, `enabled_by_default`, `kind`.

2. **Discovery:** Walk `~/.synapse/extensions/`, `<workspace>/.synapse/plugins/`, and a bundled
   directory. Use `os.path.realpath()` for path escape checks. On POSIX, check `st_mode & 0o002`.

3. **Loader:** Use Python's `importlib.util.spec_from_file_location()` for dynamic module loading
   (equivalent to Jiti). Create a registration API object and pass it to the plugin's entry function.

4. **Registry:** A dataclass holding lists of registered tools, hooks, channels, providers. Keep
   Phase 0 (manifest-only) and Phase 1 (runtime) separate — Phase 0 should not import plugin code.

5. **Install:** `pip install --target ~/.synapse/extensions/<plugin_id>` for PyPI distribution.
   Check for a `synapse.plugin.json` in the installed package root.

6. **Security:** Validate `os.path.realpath(source).startswith(os.path.realpath(root))` before
   loading any plugin entry point.
