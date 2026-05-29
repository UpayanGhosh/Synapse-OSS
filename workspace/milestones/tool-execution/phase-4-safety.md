# Phase 4: Safety Pipeline — Policy, Hooks & Loop Detection

> Adapted from OpenClaw Phases 4-5: layered policy pipeline, before/after-tool-call hooks, graduated loop detection with escalation.

## Goal

Wire a multi-layered security pipeline into the tool execution path: tool policy filtering, before/after-call hooks, graduated loop detection, owner-only enforcement, and full audit trail. Defense in depth — multiple independent security layers, any one of which can block a call.

## Dependencies

- **Phase 3** (Tool Execution Loop — provides the execution path to secure)

## Files

| File | Action | Why |
|------|--------|-----|
| `sci_fi_dashboard/tool_registry.py` | **MODIFY** | Add policy pipeline, hooks, loop detection |
| `sci_fi_dashboard/api_gateway.py` | **MODIFY** | Pass sender identity, wire policy config |
| `sbs/sentinel/audit.py` | READ | Reuse `AuditLogger` for tool call audit trail |

## Implementation

### 4.1 — Tool Policy Pipeline (adapted from OpenClaw Phase 4)

OpenClaw applies 6 policy layers in priority order. Synapse adapts this to 4 layers:

```python
@dataclass
class ToolPolicy:
    allow: list[str] | None = None   # explicit allow list (None = allow all)
    deny: list[str] | None = None    # explicit deny list

@dataclass
class PolicyStep:
    policy: ToolPolicy
    label: str                        # for diagnostic logging

def apply_tool_policy_pipeline(
    tools: list[SynapseTool],
    steps: list[PolicyStep],
    sender_is_owner: bool,
) -> tuple[list[SynapseTool], list[dict]]:
    """Filter tools through layered policies. Returns (surviving_tools, removal_log)."""
    remaining = list(tools)
    removed_log = []

    for step in steps:
        keep = []
        for tool in remaining:
            # Owner-only check
            if tool.owner_only and not sender_is_owner:
                removed_log.append({"tool": tool.name, "step": step.label, "reason": "owner_only"})
                continue

            # Deny list
            if step.policy.deny and tool.name in step.policy.deny:
                removed_log.append({"tool": tool.name, "step": step.label, "reason": "denied"})
                continue

            # Allow list (if set, tool must be in it)
            if step.policy.allow is not None and tool.name not in step.policy.allow:
                removed_log.append({"tool": tool.name, "step": step.label, "reason": "not_in_allowlist"})
                continue

            keep.append(tool)
        remaining = keep

    return remaining, removed_log
```

**Policy sources for Synapse (in priority order):**

| Layer | Source | Example |
|-------|--------|---------|
| 1. Global | `synapse.json → tools.deny` | `["write_file"]` — disable writes globally |
| 2. Channel | `synapse.json → channels.{id}.tools.deny` | Block `exec` on public Telegram |
| 3. Sender | DM access level from `security.py` | Non-owner → owner_only tools removed |
| 4. Session | Runtime overrides (e.g., vault mode) | Vault → all tools removed |

### 4.2 — Before/After Tool Call Hooks (adapted from OpenClaw Phase 5)

```python
# Hook types
BeforeToolCallHook = Callable[[str, dict, ToolContext], Awaitable[tuple[str, dict | None]]]
# Returns: ("allow", modified_args) or ("block", None)

AfterToolCallHook = Callable[[str, dict, ToolResult, float], Awaitable[None]]
# Receives: tool_name, args, result, duration_ms

class ToolHookRunner:
    def __init__(self):
        self._before_hooks: list[BeforeToolCallHook] = []
        self._after_hooks: list[AfterToolCallHook] = []

    def register_before(self, hook: BeforeToolCallHook) -> None:
        self._before_hooks.append(hook)

    def register_after(self, hook: AfterToolCallHook) -> None:
        self._after_hooks.append(hook)

    async def run_before(self, tool_name: str, args: dict, context: ToolContext) -> tuple[str, dict]:
        """Run all before-hooks in order. Any hook can block or modify args."""
        effective_args = args
        for hook in self._before_hooks:
            action, modified = await hook(tool_name, effective_args, context)
            if action == "block":
                return ("block", effective_args)
            if modified is not None:
                effective_args = modified
        return ("allow", effective_args)

    async def run_after(self, tool_name: str, args: dict, result: ToolResult, duration_ms: float) -> None:
        """Run all after-hooks (non-blocking, fire-and-forget)."""
        for hook in self._after_hooks:
            try:
                await hook(tool_name, args, result, duration_ms)
            except Exception as e:
                logger.warning(f"After-tool hook error: {e}")
```

### 4.3 — Graduated Loop Detection (adapted from OpenClaw Phase 5)

OpenClaw uses 4 escalation levels (3→5→7→10). Synapse adapts:

```python
class ToolLoopDetector:
    def __init__(self):
        self._history: list[tuple[str, str]] = []  # (name, args_hash)

    def record(self, name: str, arguments: dict) -> str:
        """Record a tool call. Returns severity level."""
        args_hash = hashlib.md5(json.dumps(arguments, sort_keys=True).encode()).hexdigest()[:12]
        key = (name, args_hash)
        self._history.append(key)

        # Count consecutive identical calls
        consecutive = 0
        for prev in reversed(self._history):
            if prev == key:
                consecutive += 1
            else:
                break

        if consecutive >= 7:
            return "block"      # hard stop — do not execute
        if consecutive >= 5:
            return "error"      # execute but inject error context for LLM
        if consecutive >= 3:
            return "warn"       # execute but log warning
        return "ok"

    def get_warning_message(self, name: str, severity: str) -> str:
        if severity == "block":
            return f"Tool loop detected: '{name}' called 7+ times with identical arguments. Stopping to prevent infinite loop. Try a different approach."
        if severity == "error":
            return f"Warning: '{name}' has been called 5+ times with the same arguments. You may be stuck in a loop. Try a different tool or approach."
        return ""
```

**Integration into the execution loop (Phase 3):**

```python
# Before executing each tool call:
severity = loop_detector.record(tc.name, args)

if severity == "block":
    tool_results[tc.id] = ToolResult(
        content=loop_detector.get_warning_message(tc.name, severity),
        is_error=True,
    )
    continue  # skip execution

result = await registry.execute(tc.name, args)

if severity == "error":
    # Append warning to result so LLM sees it
    result.content += f"\n\n⚠️ {loop_detector.get_warning_message(tc.name, severity)}"
```

### 4.4 — Full audit trail

Every tool call is logged to Sentinel's audit JSONL:

```python
# Register as an after-hook:
async def audit_tool_call(tool_name, args, result, duration_ms):
    audit_logger.log_event("TOOL_CALL", {
        "tool": tool_name,
        "args_preview": _truncate_args(args, 200),
        "result_length": len(result.content),
        "is_error": result.is_error,
        "duration_ms": round(duration_ms, 1),
        "sender": current_sender_id,
        "timestamp": datetime.utcnow().isoformat(),
    })

hook_runner.register_after(audit_tool_call)
```

### 4.5 — Diagnostic logging (adapted from OpenClaw Phase 4)

Log which tools were removed by which policy step:

```
[tool-policy] "write_file" removed by step "sender" (owner_only)
[tool-policy] "exec" removed by step "channel:telegram" (denied)
[tool-policy] 4 tools available for session chat_id=919876543210
```

## Verification

1. **Policy test**: `deny: ["write_file"]` in config → `write_file` removed from tool list
2. **Owner-only test**: non-owner sender → owner_only tools filtered out
3. **Allow list test**: `allow: ["web_search", "query_memory"]` → only those 2 tools available
4. **Before-hook block**: hook returns "block" → tool not executed, error result returned
5. **Before-hook modify**: hook modifies args → tool executes with modified args
6. **Loop detection escalation**:
   - 3 repeats → warning logged, tool still executes
   - 5 repeats → error injected into result
   - 7 repeats → tool blocked, error returned
7. **Audit test**: execute tools → verify `TOOL_CALL` entries in `sentinel_audit.jsonl`
8. **Diagnostic test**: verify removal log messages in gateway log

## Scope

- 2 files modified (~180 new lines)
- 3 new classes (`ToolPolicy`, `ToolHookRunner`, `ToolLoopDetector`)
- ~8 tests
