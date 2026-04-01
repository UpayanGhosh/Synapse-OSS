# Hook System — Features in openclaw Missing from Synapse-OSS

## Overview

openclaw has a comprehensive, typed plugin hook system with 26 named lifecycle events spanning
agent inference, message routing, tool execution, session lifecycle, subagent spawning, and gateway
control plane. Plugins register handlers with optional priority ordering. The hook runner supports
parallel execution (void hooks), sequential merging (modifying hooks), and first-claim semantics
(claiming hooks). Synapse-OSS has no hook system.

---

## What openclaw has

### 1. 26 Named Hook Events

**File:** `src/plugins/types.ts` (lines 1796–1822)

```typescript
export type PluginHookName =
  // Agent inference pipeline
  | "before_model_resolve"   // override model/provider before model resolution
  | "before_prompt_build"    // inject system prompt, context, before LLM call
  | "before_agent_start"     // legacy combined hook (model + prompt)
  | "llm_input"              // observe exact payload sent to LLM (read-only)
  | "llm_output"             // observe exact LLM response (read-only)
  | "agent_end"              // completed conversation notification
  | "before_compaction"      // before session compaction runs
  | "after_compaction"       // after session compaction completes
  | "before_reset"           // before /new or /reset clears session messages

  // Message routing pipeline
  | "inbound_claim"          // claim inbound event before commands/agent dispatch
  | "message_received"       // inbound message received (read-only)
  | "before_dispatch"        // inspect/handle message before model dispatch
  | "message_sending"        // modify or cancel outgoing reply
  | "message_sent"           // outgoing message confirmed sent

  // Tool execution pipeline
  | "before_tool_call"       // modify tool args or block execution
  | "after_tool_call"        // observe completed tool call (read-only)
  | "tool_result_persist"    // rewrite tool result before JSONL write (sync)
  | "before_message_write"   // block or rewrite message before JSONL write (sync)

  // Session lifecycle
  | "session_start"          // new session created
  | "session_end"            // session ended

  // Subagent lifecycle
  | "subagent_spawning"      // before subagent is spawned (can veto)
  | "subagent_delivery_target" // resolve where subagent reply goes
  | "subagent_spawned"       // subagent has started
  | "subagent_ended"         // subagent has completed

  // Gateway control plane
  | "gateway_start"          // server listening
  | "gateway_stop";          // server shutting down
```

`PLUGIN_HOOK_NAMES` is a `const` array with a compile-time exhaustiveness check:
```typescript
type MissingPluginHookNames = Exclude<PluginHookName, (typeof PLUGIN_HOOK_NAMES)[number]>;
type AssertAllPluginHookNamesListed = MissingPluginHookNames extends never ? true : never;
```

---

### 2. Three Hook Execution Strategies

**File:** `src/plugins/hooks.ts`

#### 2a. Void Hooks (parallel, fire-and-forget)
Runs all registered handlers concurrently via `Promise.all`. Used for observation-only hooks
where order does not matter and no return value is consumed.

Applied to: `message_received`, `message_sent`, `agent_end`, `llm_input`, `llm_output`,
`before_compaction`, `after_compaction`, `before_reset`, `session_start`, `session_end`,
`subagent_spawned`, `subagent_ended`, `gateway_start`, `gateway_stop`, `after_tool_call`.

```typescript
async function runVoidHook<K extends PluginHookName>(hookName, event, ctx): Promise<void> {
  const hooks = getHooksForName(registry, hookName);
  const promises = hooks.map(async (hook) => {
    try { await hook.handler(event, ctx); }
    catch (err) { handleHookError({ hookName, pluginId: hook.pluginId, error: err }); }
  });
  await Promise.all(promises);
}
```

#### 2b. Modifying Hooks (sequential, result-merging)
Runs handlers in priority order (higher first). Each handler can return a partial result that
is merged with the accumulated result via a `mergeResults` function. A `shouldStop` predicate
supports early-termination (e.g., `block=true`).

Applied to: `before_model_resolve`, `before_prompt_build`, `before_agent_start`, `message_sending`,
`before_tool_call`, `subagent_spawning`, `subagent_delivery_target`.

```typescript
async function runModifyingHook<K, TResult>(hookName, event, ctx, policy): Promise<TResult|undefined> {
  const hooks = getHooksForName(registry, hookName);
  let result: TResult | undefined;
  for (const hook of hooks) {
    const handlerResult = await hook.handler(event, ctx);
    if (handlerResult !== undefined && handlerResult !== null) {
      result = policy.mergeResults ? policy.mergeResults(result, handlerResult, hook) : handlerResult;
      if (result && policy.shouldStop?.(result)) { break; }
    }
  }
  return result;
}
```

**Merge semantics examples:**
- `before_model_resolve`: first defined `modelOverride`/`providerOverride` wins (higher priority wins)
- `before_prompt_build`: `systemPrompt` first-defined wins; `prependContext` / `appendSystemContext`
  concatenate across all handlers
- `message_sending`: `cancel=true` is sticky (any plugin can cancel); `content` uses last-defined
- `before_tool_call`: `block=true` is sticky, stops at first block; `requireApproval` from first
  plugin wins, args from that same plugin freeze for subsequent handlers

#### 2c. Claiming Hooks (sequential, first-claim wins)
Runs handlers in priority order and returns on the first result with `{ handled: true }`.

Applied to: `inbound_claim`, `before_dispatch`.

Also supports targeted claiming (for a specific plugin id) with structured outcomes:
```typescript
type PluginTargetedInboundClaimOutcome =
  | { status: "handled"; result: PluginHookInboundClaimResult }
  | { status: "missing_plugin" }
  | { status: "no_handler" }
  | { status: "declined" }
  | { status: "error"; error: string };
```

#### 2d. Synchronous Hooks
`tool_result_persist` and `before_message_write` are deliberately synchronous because they run
in hot transcript-write paths. The runner guards against accidental `Promise` returns.

---

### 3. Priority-Ordered Hook Dispatch

**File:** `src/plugins/hooks.ts` → `getHooksForName()`

```typescript
function getHooksForName<K extends PluginHookName>(registry, hookName): PluginHookRegistration<K>[] {
  return registry.typedHooks
    .filter((h) => h.hookName === hookName)
    .toSorted((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
}
```

Registration signature (from `PluginApi`):
```typescript
on: <K extends PluginHookName>(
  hookName: K,
  handler: PluginHookHandlerMap[K],
  opts?: { priority?: number },
) => void;
```

---

### 4. Typed Hook Event and Context Types

**File:** `src/plugins/types.ts`

Every hook has a distinct `Event` type (what changed/triggered) and a `Context` type
(read-only ambient info about the session/agent). For example:

```typescript
// before_tool_call
export type PluginHookBeforeToolCallEvent = {
  toolName: string;
  toolInput: Record<string, unknown>;
  toolCallId: string;
};
export type PluginHookBeforeToolCallResult = {
  params?: Record<string, unknown>;    // rewrite tool args
  block?: boolean;                     // block the call entirely
  blockReason?: string;
  requireApproval?: { ... };          // request human-in-the-loop approval
};

// subagent_spawning
export type PluginHookSubagentSpawningEvent = {
  subagentId: string;
  parentSessionKey: string;
  channelId?: string;
  threadId?: string;
};
export type PluginHookSubagentSpawningResult = {
  status: "ok" | "error";
  threadBindingReady?: boolean;
};
```

The full `PluginHookHandlerMap` covers all 26 hook names with exact function signatures:
```typescript
export type PluginHookHandlerMap = {
  before_model_resolve: (event, ctx: PluginHookAgentContext) =>
    Promise<PluginHookBeforeModelResolveResult | void> | PluginHookBeforeModelResolveResult | void;
  // ... all 26 hooks
};
```

---

### 5. Error Isolation per Plugin

**File:** `src/plugins/hooks.ts`

```typescript
const handleHookError = (params: { hookName, pluginId, error }): never | void => {
  const msg = `[hooks] ${params.hookName} handler from ${params.pluginId} failed: ${String(params.error)}`;
  if (catchErrors) { logger?.error(msg); return; }
  throw new Error(msg, { cause: params.error });
};
```

`HookRunnerOptions.catchErrors` defaults to `true` in production — a crashing plugin does not
take down the gateway. `catchErrors: false` is available for test environments.

---

### 6. Global Hook Runner for Gateway-Wide Events

**File:** `src/plugins/hook-runner-global.ts`

`initializeGlobalHookRunner()` creates a singleton hook runner bound to the active plugin
registry. Used for gateway-level hooks (`gateway_start`, `gateway_stop`) that are not
per-session/per-agent.

---

### 7. Prompt Injection Hook Names (security classification)

**File:** `src/plugins/types.ts`

```typescript
export const PROMPT_INJECTION_HOOK_NAMES = [
  "before_prompt_build",
  "before_agent_start",
] as const;
```

Hooks that can modify the system prompt or prepend context are classified separately. This
enables the security layer to apply additional scrutiny to plugins using these hooks (e.g.,
for allowlist enforcement or audit logging).

---

### 8. Wired Hook Tests

**Files:** `src/plugins/wired-hooks-*.test.ts`

Comprehensive test suites verify hook wiring end-to-end:
- `wired-hooks-after-tool-call.e2e.test.ts`
- `wired-hooks-compaction.test.ts`
- `wired-hooks-gateway.test.ts`
- `wired-hooks-inbound-claim.test.ts`
- `wired-hooks-llm.test.ts`
- `wired-hooks-message.test.ts`
- `wired-hooks-session.test.ts`
- `wired-hooks-subagent.test.ts`

---

## What Synapse-OSS has (or lacks)

Synapse-OSS has **no hook system**. The closest patterns found:

- `ChannelRegistry.start_all()` / `stop_all()` in `sci_fi_dashboard/channels/registry.py` are
  lifecycle calls on statically registered channels, not a plugin hook dispatch mechanism.
- `FastAPI` lifespan context manager in `api_gateway.py` starts all channels on server boot —
  this is framework-level, not an extension hook.
- No event types, no priority ordering, no result merging, no claim semantics.

There is no mechanism for third-party code to observe or modify the inference pipeline,
tool execution, message routing, or session lifecycle.

---

## Gap Summary

| Capability | openclaw | Synapse-OSS |
|-----------|----------|-------------|
| Named lifecycle hooks | 26 | 0 |
| Parallel void hooks | Yes | No |
| Sequential modifying hooks (priority+merge) | Yes | No |
| First-claim hooks | Yes | No |
| Synchronous hot-path hooks | Yes (2) | No |
| Per-hook priority ordering | Yes | No |
| Typed event + context per hook | Yes | No |
| Error isolation per plugin | Yes | No |
| Prompt injection classification | Yes | No |
| Targeted per-plugin hook dispatch | Yes | No |
| Agent inference interception | Yes | No |
| Tool call interception + approval | Yes | No |
| Session/subagent lifecycle hooks | Yes | No |
| Gateway control plane hooks | Yes | No |

---

## Implementation Notes for Porting

1. **Define event types:** Python dataclasses (or TypedDicts) for each hook event and context.
   Start with the highest-value ones: `before_prompt_build`, `before_tool_call`, `message_received`.

2. **HookRegistry:** A dict `hook_name → list[HookEntry]` where `HookEntry` holds `(plugin_id,
   handler, priority)`. Sort by descending priority on registration or dispatch.

3. **Execution strategies:**
   ```python
   async def run_void_hook(name, event, ctx):
       await asyncio.gather(*[h.handler(event, ctx) for h in self._get(name)],
                            return_exceptions=True)

   async def run_modifying_hook(name, event, ctx, merge_fn, stop_fn=None):
       result = None
       for hook in self._get_sorted(name):
           r = await hook.handler(event, ctx)
           if r is not None:
               result = merge_fn(result, r) if result else r
               if stop_fn and stop_fn(result): break
       return result
   ```

4. **Error isolation:** Wrap every handler call in `try/except`; log to plugin-specific logger;
   do not propagate unless running in test mode.

5. **Integration points in Synapse-OSS:**
   - `sci_fi_dashboard/llm_router.py` `generate()` → call `before_prompt_build`, `llm_input`,
     `llm_output`
   - `gateway/worker.py` message processing → call `message_received`, `before_dispatch`
   - `channels/base.py` send path → call `message_sending`, `message_sent`
   - `sci_fi_dashboard/api_gateway.py` lifespan → call `gateway_start`, `gateway_stop`
