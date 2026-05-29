# Plugin SDK — Features in openclaw Missing from Synapse-OSS

## Overview

openclaw exposes a formal public SDK (`openclaw/plugin-sdk/*`) with 50+ subpath exports,
a session-scoped tool factory contract, a WeakMap-based metadata pattern for tools, an optional-tool
allowlist system, name conflict detection, and a Jiti-based module alias resolver that makes
the SDK available to plugins regardless of their install location. Synapse-OSS has no equivalent
public SDK or plugin-facing API contract.

---

## What openclaw has

### 1. Plugin SDK — 50+ Subpath Exports

**File:** `src/plugins/sdk-alias.ts`, `src/plugin-sdk/`

The SDK is published under the `openclaw` npm package with subpath exports at
`openclaw/plugin-sdk/<name>`. Plugins import only from this path — never from `src/**` directly.

```typescript
// sdk-alias.ts
function listPluginSdkSubpathsFromPackageJson(pkg: PluginSdkPackageJson): string[] {
  return Object.keys(pkg.exports ?? {})
    .filter((key) => key.startsWith("./plugin-sdk/"))
    .map((key) => key.slice("./plugin-sdk/".length))
    .filter((subpath) => isSafePluginSdkSubpathSegment(subpath))
    .toSorted();
}
```

Example SDK subpaths (from `src/plugin-sdk/`):
- `openclaw/plugin-sdk/agent-runtime` — agent runtime API
- `openclaw/plugin-sdk/channel-contract` — channel plugin contracts
- `openclaw/plugin-sdk/approval-renderers` — human-in-the-loop approval UI
- `openclaw/plugin-sdk/allowlist-config-edit` — allowlist configuration helpers
- `openclaw/plugin-sdk/account-core` — account model and helpers
- `openclaw/plugin-sdk/fetch-auth` — provider fetch auth
- `openclaw/plugin-sdk/channel-reply-pipeline` — reply chunking/dispatch
- `openclaw/plugin-sdk/hook-runtime` — hook runtime types
- `openclaw/plugin-sdk/provider-tools` — provider tool utilities
- ... (50+ total)

This contract surface is stable — plugins published to npm depend on it across openclaw versions.

---

### 2. Plugin Registration API (`OpenClawPluginApi`)

**File:** `src/plugins/types.ts` (around line 1700+)

Every plugin receives an `OpenClawPluginApi` object when its entry function is called. This is
the sole legal way for plugins to register capabilities:

```typescript
export type OpenClawPluginApi = {
  // Tool factories
  registerTool: (factory: OpenClawPluginToolFactory, opts?: OpenClawPluginToolOptions) => void;

  // Channel adapters
  registerChannel: (plugin: ChannelPlugin, opts?: OpenClawPluginChannelRegistration) => void;

  // Providers
  registerProvider: (provider: ProviderPlugin) => void;
  registerSpeechProvider: (provider: SpeechProviderPlugin) => void;
  registerMediaUnderstandingProvider: (provider: MediaUnderstandingProviderPlugin) => void;
  registerImageGenerationProvider: (provider: ImageGenerationProviderPlugin) => void;
  registerWebSearchProvider: (provider: WebSearchProviderPlugin) => void;

  // CLI
  registerCli: (register: OpenClawPluginCliRegistrar, opts?: ...) => void;

  // Gateway HTTP routes
  registerHttpRoute: (params: OpenClawPluginHttpRouteParams) => void;

  // Commands
  registerCommand: (command: OpenClawPluginCommandDefinition) => void;

  // Services (persistent background workers)
  registerService: (service: OpenClawPluginService) => void;

  // Memory (exclusive slots)
  registerMemoryPromptSection: (builder: MemoryPromptSectionBuilder) => void;
  registerMemoryFlushPlan: (resolver: MemoryFlushPlanResolver) => void;
  registerMemoryRuntime: (runtime: MemoryPluginRuntime) => void;
  registerMemoryEmbeddingProvider: (adapter: MemoryEmbeddingProviderAdapter) => void;

  // Hook registration
  on: <K extends PluginHookName>(
    hookName: K,
    handler: PluginHookHandlerMap[K],
    opts?: { priority?: number },
  ) => void;

  // Utilities
  resolvePath: (input: string) => string;
  logger: PluginLogger;
  config?: OpenClawConfig;
};
```

---

### 3. Tool Factory Contract — Session-Scoped Instantiation

**Files:** `src/plugins/types.ts`, `src/plugins/tools.ts`, `src/plugins/registry.ts`

```typescript
// The factory function — called once per agent turn with session context
export type OpenClawPluginToolFactory = (
  ctx: OpenClawPluginToolContext,
) => AnyAgentTool | AnyAgentTool[] | null | undefined;

// Trusted ambient context passed to every tool factory call
export type OpenClawPluginToolContext = {
  config?: OpenClawConfig;
  runtimeConfig?: OpenClawConfig;    // active runtime-resolved config snapshot
  workspaceDir?: string;
  agentDir?: string;
  agentId?: string;
  sessionKey?: string;
  sessionId?: string;                // ephemeral session UUID, reset on /new
  browser?: { sandboxBridgeUrl?: string; allowHostControl?: boolean };
  messageChannel?: string;
  agentAccountId?: string;
  deliveryContext?: DeliveryContext;
  requesterSenderId?: string;        // trusted sender id (not from tool args)
  senderIsOwner?: boolean;
  sandboxed?: boolean;
};
```

`registerTool()` in the registry stores a `PluginToolRegistration`:
```typescript
export type PluginToolRegistration = {
  pluginId: string;
  pluginName?: string;
  factory: OpenClawPluginToolFactory;
  names: string[];      // declared tool names for conflict detection
  optional: boolean;    // whether tool requires explicit allowlisting
  source: string;
  rootDir?: string;
};
```

The factory is called at tool-construction time (`resolvePluginTools()`), not at plugin load
time. This means tools can be configured per-session from the `ctx` object — different agents
with different configs can get different tool instances from the same factory.

---

### 4. WeakMap Plugin Metadata Pattern (`PluginToolMeta`)

**File:** `src/plugins/tools.ts`

```typescript
type PluginToolMeta = {
  pluginId: string;
  optional: boolean;
};

const pluginToolMeta = new WeakMap<AnyAgentTool, PluginToolMeta>();

export function getPluginToolMeta(tool: AnyAgentTool): PluginToolMeta | undefined {
  return pluginToolMeta.get(tool);
}

export function copyPluginToolMeta(source: AnyAgentTool, target: AnyAgentTool): void {
  const meta = pluginToolMeta.get(source);
  if (meta) { pluginToolMeta.set(target, meta); }
}
```

After a tool is instantiated by a factory, its `pluginId` and `optional` flag are attached via
WeakMap rather than as a property on the tool object. This avoids polluting the tool interface
and allows tools to be wrapped/cloned while preserving metadata through `copyPluginToolMeta`.

---

### 5. Optional-Tool Allowlist System

**File:** `src/plugins/tools.ts`

```typescript
function isOptionalToolAllowed(params: {
  toolName: string;
  pluginId: string;
  allowlist: Set<string>;
}): boolean {
  if (params.allowlist.size === 0) { return false; }
  const toolName = normalizeToolName(params.toolName);
  if (params.allowlist.has(toolName)) { return true; }        // exact tool name
  const pluginKey = normalizeToolName(params.pluginId);
  if (params.allowlist.has(pluginKey)) { return true; }       // allow all from plugin
  return params.allowlist.has("group:plugins");               // allow all optional tools
}
```

Tools registered with `optional: true` are **not** included by default. They require explicit
listing in `toolAllowlist`. The allowlist supports three granularities:
- Exact tool name: `"code_execution"`
- Plugin-level: `"xai"` (allows all optional tools from the xai plugin)
- Group-level: `"group:plugins"` (allows all optional tools from all plugins)

This prevents plugins from silently adding capabilities that could be used for prompt injection
or unexpected side effects.

---

### 6. Name Conflict Detection

**File:** `src/plugins/tools.ts`

```typescript
// Plugin id vs core tool name conflict
if (existingNormalized.has(pluginIdKey)) {
  const message = `plugin id conflicts with core tool name (${entry.pluginId})`;
  blockedPlugins.add(entry.pluginId);
  continue;
}

// Tool name vs existing name conflict
if (nameSet.has(tool.name) || existing.has(tool.name)) {
  const message = `plugin tool name conflict (${entry.pluginId}): ${tool.name}`;
  registry.diagnostics.push({ level: "error", pluginId: entry.pluginId, ... });
  continue;
}
```

Conflicts are recorded as `PluginDiagnostic` entries. `suppressNameConflicts` option is
available for test environments. The plugin that conflicts is blocked — not just the conflicting
tool — to prevent partial plugin loads that could be harder to debug.

---

### 7. Jiti Dynamic Import with SDK Alias Resolution

**Files:** `src/plugins/sdk-alias.ts`, `src/plugins/loader.ts`

Jiti is used to transpile TypeScript plugin entry points at runtime. The SDK alias system
ensures that `import ... from "openclaw/plugin-sdk/foo"` inside a plugin always resolves to
the correct SDK file regardless of how the plugin was installed.

```typescript
// buildPluginLoaderAliasMap builds the alias map per-plugin
export function buildPluginLoaderAliasMap(
  modulePath: string,
  argv1: string | undefined,
  moduleUrl: string,
  preference: PluginSdkResolutionPreference,
): Record<string, string> { ... }

// Two resolution preferences:
export type PluginSdkResolutionPreference = "auto" | "dist" | "src";
```

`auto` mode selects `src` (TypeScript) when running from source (dev mode) or `dist`
(compiled JS) when running from the built package. This allows plugins to be developed
against the source SDK without a build step.

A trust check validates the SDK root before accepting aliases:
```typescript
function hasTrustedOpenClawRootIndicator(params: { packageRoot, packageJson }): boolean {
  // Requires ./plugin-sdk export, openclaw binary, or openclaw.mjs entrypoint
  const hasPluginSdkRootExport = ...;
  const hasOpenClawBin = ...;
  const hasOpenClawEntrypoint = fs.existsSync(path.join(params.packageRoot, "openclaw.mjs"));
  return hasCliEntryExport || hasOpenClawBin || hasOpenClawEntrypoint;
}
```

---

### 8. Plugin Config Schema Validation

**File:** `src/plugins/schema-validator.ts`

Plugin config values are validated against the `configSchema` declared in the manifest before
the plugin's runtime config is applied:

```typescript
export type OpenClawPluginConfigSchema = {
  safeParse?: (value: unknown) => { success: boolean; data?: unknown; error?: { issues? } };
  parse?: (value: unknown) => unknown;
  validate?: (value: unknown) => PluginConfigValidation;
  uiHints?: Record<string, PluginConfigUiHint>;
  jsonSchema?: Record<string, unknown>;
};
```

Plugins can provide a Zod schema (`safeParse`/`parse`), a lightweight custom validator
(`validate`), or both. UI hints (`label`, `help`, `sensitive`, `placeholder`, `advanced`,
`tags`) are carried alongside for configuration interfaces.

---

### 9. Plugin Logger Interface

**File:** `src/plugins/types.ts`

```typescript
export type PluginLogger = {
  debug?: (message: string) => void;
  info: (message: string) => void;
  warn: (message: string) => void;
  error: (message: string) => void;
};
```

Every plugin receives a structured logger pre-scoped to its plugin id. `debug` is optional —
plugins that do not use debug-level logging do not need to implement it.

---

### 10. Plugin Services (Background Workers)

**File:** `src/plugins/services.ts`

```typescript
export type OpenClawPluginService = {
  id: string;
  label?: string;
  start: (ctx: PluginServiceContext) => Promise<void>;
  stop?: () => Promise<void>;
};
```

Plugins can register long-running background services (e.g., a polling worker, a webhook
listener, a background sync job). The service lifecycle is managed by the gateway.

---

## What Synapse-OSS has (or lacks)

Synapse-OSS has **no public SDK or plugin-facing registration API**. Observations:

- `workspace/skills/` contains plain Python files with no common base class, interface, or
  registration API. `llm_router.py` is a sync wrapper around `SynapseLLMRouter`, not a
  registrable tool.
- `workspace/skills/memory/ingest_memories.py` ingests facts directly into the database —
  no registration API, no session context, no allowlisting.
- Channel adapters (`sci_fi_dashboard/channels/`) subclass `BaseChannel` (ABC), but there is
  no factory pattern, no config schema validation, and no registration API.
- No WeakMap-equivalent for attaching metadata to tools without polluting their interface.
- No allowlist system — any imported function can run without restriction.
- No name conflict detection between skill-provided and built-in capabilities.
- No config schema validation for skill/plugin configuration.
- No scoped logger per skill.

---

## Gap Summary

| Feature | openclaw | Synapse-OSS |
|---------|----------|-------------|
| Public SDK with 50+ subpath exports | Yes | No |
| Plugin registration API object | Yes | No |
| Session-scoped tool factory (`OpenClawPluginToolFactory`) | Yes | No |
| `OpenClawPluginToolContext` (trusted ambient session context) | Yes | No |
| WeakMap tool metadata (`PluginToolMeta`) | Yes | No |
| Optional-tool allowlist (3 granularities) | Yes | No |
| Tool name conflict detection + blocking | Yes | No |
| Jiti dynamic import with SDK alias resolution | Yes | No |
| Config schema validation (Zod/custom/JSON Schema) | Yes | No |
| Config UI hints (label, help, sensitive, placeholder) | Yes | No |
| Scoped plugin logger | Yes | No |
| Plugin service registration (background workers) | Yes | No |
| HTTP route registration (`registerHttpRoute`) | Yes | No |

---

## Implementation Notes for Porting

1. **Registration API:** Define a `SynapsePluginApi` dataclass/object passed to a plugin's
   `setup(api)` entry function:
   ```python
   @dataclass
   class SynapsePluginApi:
       plugin_id: str
       config: dict
       logger: logging.Logger
       def register_tool(self, factory, *, name: str, optional: bool = False): ...
       def register_channel(self, channel: BaseChannel): ...
       def on(self, hook_name: str, handler, *, priority: int = 0): ...
   ```

2. **Tool factory:** Each tool factory is a callable `(ctx: ToolContext) -> Tool | None`.
   `ToolContext` carries session-scoped data: session_id, config, sender_id, channel_id.

3. **WeakMap metadata:** Python has `weakref.WeakKeyDictionary`. Use it to attach plugin
   metadata to tool instances without modifying tool classes.

4. **Allowlist:** Store optional tool names in a config key. In `resolvePluginTools()`,
   filter optional tools through the allowlist before adding to the active tool set.

5. **Config schema:** Use Pydantic models (v2) for config validation. Accept either a
   Pydantic model class or a `validate(value) -> ValidationResult` callable.

6. **SDK boundary:** Create a `synapse_sdk` package that is the only legal import surface
   for third-party plugins. All core internals stay in `sci_fi_dashboard.*`.
