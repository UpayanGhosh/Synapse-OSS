# Phase 3: Execution Loop, Result Processing & Error Recovery

> Adapted from OpenClaw Phases 7-8 + Orchestrator: inference loop, parallel tool execution, result normalization, size guard, retry on error.

## Goal

Build the agentic loop inside `persona_chat()` — when the LLM returns tool_calls, execute them (in parallel where safe), normalize results, handle errors gracefully, and re-prompt until the LLM produces a final text response. Includes error recovery for mid-loop failures.

## Dependencies

- **Phase 1** (ToolRegistry — provides `resolve()`, `get_schemas()`, `execute()`)
- **Phase 2** (LLM Router — provides `call_with_tools()` returning `LLMToolResult`)

## Files

| File | Action | Why |
|------|--------|-----|
| `sci_fi_dashboard/api_gateway.py` | **MODIFY** | Insert tool loop into `persona_chat()`, error recovery |
| `sci_fi_dashboard/tool_registry.py` | READ | Use `ToolRegistry` from Phase 1 |
| `sci_fi_dashboard/llm_router.py` | READ | Use `call_with_tools()` from Phase 2 |

## Implementation

### 3.1 — Initialize ToolRegistry as singleton (in `api_gateway.py` lifespan)

```python
from sci_fi_dashboard.tool_registry import ToolRegistry, ToolContext, register_builtin_tools

tool_registry = ToolRegistry()
register_builtin_tools(tool_registry, memory_engine, PROJECT_ROOT)
```

### 3.2 — Tool execution loop in `persona_chat()`

**Location:** Replace the current single LLM call (lines ~690-738) with a loop.

```python
MAX_TOOL_ROUNDS = 5
TOOL_RESULT_MAX_CHARS = 4000
MAX_TOTAL_TOOL_RESULT_CHARS = 20_000  # context overflow guard

# Resolve tools for this session
tool_context = ToolContext(
    chat_id=chat_id,
    sender_id=request.user_id or "unknown",
    sender_is_owner=is_owner_sender(request.user_id),
    workspace_dir=str(PROJECT_ROOT),
    config=synapse_config.raw,
    channel_id=channel_id,
)

# Skip tools for vault role (local Ollama often doesn't support function calling)
use_tools = session_mode != "spicy"
session_tools = tool_registry.resolve(tool_context) if use_tools else []
tool_schemas = tool_registry.get_schemas(session_tools) if session_tools else None

reply_text = ""
tools_used: list[str] = []
total_tool_time = 0.0
total_result_chars = 0
accumulated_usage = {"prompt": 0, "completion": 0}

for round_num in range(MAX_TOOL_ROUNDS):
    # --- LLM CALL ---
    if tool_schemas:
        result = await synapse_llm_router.call_with_tools(
            role, messages, tools=tool_schemas,
            temperature=temperature, max_tokens=max_tokens,
        )
    else:
        result_simple = await synapse_llm_router.call_with_metadata(
            role, messages, temperature=temperature, max_tokens=max_tokens,
        )
        reply_text = result_simple.text
        break

    accumulated_usage["prompt"] += result.prompt_tokens
    accumulated_usage["completion"] += result.completion_tokens

    # --- NO TOOL CALLS → DONE ---
    if not result.tool_calls:
        reply_text = result.text
        break

    # --- APPEND ASSISTANT MESSAGE WITH TOOL CALLS ---
    messages.append({
        "role": "assistant",
        "content": result.text or None,
        "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in result.tool_calls
        ],
    })

    # --- EXECUTE TOOLS (parallel where safe) ---
    serial_calls = [tc for tc in result.tool_calls if _is_serial(tc.name, session_tools)]
    parallel_calls = [tc for tc in result.tool_calls if not _is_serial(tc.name, session_tools)]

    tool_results: dict[str, ToolResult] = {}

    # Parallel execution (adapted from OpenClaw Phase 8: Promise.all)
    if parallel_calls:
        tasks = [
            _execute_tool_call(tc, tool_registry, tool_context)
            for tc in parallel_calls
        ]
        parallel_results = await asyncio.gather(*tasks, return_exceptions=True)
        for tc, res in zip(parallel_calls, parallel_results):
            if isinstance(res, Exception):
                tool_results[tc.id] = ToolResult(content=f'{{"error": "{res}"}}', is_error=True)
            else:
                tool_results[tc.id] = res

    # Serial execution
    for tc in serial_calls:
        tool_results[tc.id] = await _execute_tool_call(tc, tool_registry, tool_context)

    # --- PROCESS RESULTS ---
    for tc in result.tool_calls:
        tr = tool_results[tc.id]
        t0 = time.time()

        # Truncate oversized results (adapted from OpenClaw Phase 8: MAX_RESULT_CHARS)
        content = tr.content
        if len(content) > TOOL_RESULT_MAX_CHARS:
            content = content[:TOOL_RESULT_MAX_CHARS] + "\n... [truncated]"

        total_result_chars += len(content)
        total_tool_time += time.time() - t0
        tools_used.append(tc.name)

        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": content,
        })

    # --- CONTEXT OVERFLOW GUARD ---
    if total_result_chars > MAX_TOTAL_TOOL_RESULT_CHARS:
        # Don't keep adding tools — force the LLM to respond with what it has
        tool_schemas = None  # disable tools for remaining rounds
        messages.append({
            "role": "system",
            "content": "Tool result limit reached. Respond with the information gathered so far.",
        })

    # --- TYPING INDICATOR ---
    if channel_registry and channel_id:
        channel = channel_registry.get(channel_id)
        if channel:
            await channel.send_typing(chat_id)

else:
    # Exhausted MAX_TOOL_ROUNDS
    reply_text = result.text if result.text else "I wasn't able to complete that request."
```

### 3.3 — Tool execution helper

```python
async def _execute_tool_call(tc: ToolCall, registry: ToolRegistry, context: ToolContext) -> ToolResult:
    """Execute a single tool call with error handling."""
    try:
        args = json.loads(tc.arguments)
    except json.JSONDecodeError:
        return ToolResult(content=f'{{"error": "Invalid JSON arguments for {tc.name}"}}', is_error=True)

    return await registry.execute(tc.name, args)

def _is_serial(tool_name: str, tools: list[SynapseTool]) -> bool:
    """Check if a tool is marked as serial (no parallel execution)."""
    for t in tools:
        if t.name == tool_name:
            return t.serial
    return False
```

### 3.4 — Error recovery (adapted from OpenClaw Orchestrator)

Handle errors that occur mid-loop without crashing the entire response:

```python
# Inside the loop, wrap the LLM call:
try:
    result = await synapse_llm_router.call_with_tools(...)
except Exception as e:
    error_kind = classify_llm_error(e)

    if error_kind == "auth" and round_num == 0:
        # Try refreshing token (Copilot auto-refresh) and retry once
        await synapse_llm_router.refresh_auth(role)
        result = await synapse_llm_router.call_with_tools(...)

    elif error_kind == "context_overflow":
        # Strip tool results from messages to reduce context, retry without tools
        messages = _strip_tool_results(messages)
        tool_schemas = None
        continue

    elif error_kind == "rate_limit":
        await asyncio.sleep(2)  # brief backoff
        continue

    else:
        reply_text = "I encountered an error processing your request. Please try again."
        break
```

### 3.5 — Accumulate token usage across rounds

```python
# After the loop completes, use accumulated_usage for the footer:
total_prompt_tokens = accumulated_usage["prompt"]
total_completion_tokens = accumulated_usage["completion"]
```

## Key Design Decisions (from OpenClaw)

1. **Parallel by default, serial opt-in** — OpenClaw Phase 8: "By default, all tool calls in a single turn execute concurrently. Tools marked `serial: true` are executed one at a time." Applied here with `asyncio.gather()`.
2. **Per-result AND total truncation** — individual results capped at 4000 chars, total across all rounds capped at 20,000. OpenClaw uses 100,000 per-result; we're more conservative for WhatsApp's context.
3. **Context overflow recovery** — instead of crashing, disable tools and ask LLM to respond with gathered info. Adapted from OpenClaw Orchestrator's compaction strategy.
4. **Vault skips tools** — local Ollama models rarely support function calling. No-tools fallback path preserved.

## Verification

1. **E2E test**: "search google.com for AI news" → tool called → result in response
2. **No-tool test**: "hello" → single-round, no tool calls, unchanged behavior
3. **Max rounds test**: mock LLM always returns tool_calls → stops at 5
4. **Vault test**: `session_mode="spicy"` → tools NOT offered
5. **Parallel test**: mock 2 tool calls → verify both execute concurrently
6. **Serial test**: tool marked `serial=True` → executes alone
7. **Truncation test**: tool returns 10,000 chars → truncated to 4,000
8. **Context overflow test**: total results exceed 20,000 → tools disabled, LLM prompted to respond
9. **Error recovery test**: mock auth error → verify retry after refresh
10. **Malformed args test**: tool_call with invalid JSON → error result returned to LLM

## Scope

- 1 file modified (`api_gateway.py`, ~100 new lines replacing ~30)
- ~10 tests
