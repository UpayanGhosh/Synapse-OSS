# Phase 2: LLM Router Tool Support + Schema Normalization

> Adapted from OpenClaw Phase 6: schema transformation for provider-specific quirks, and Phase 7: tool_call parsing from responses.

## Goal

Add `tools=` parameter to `SynapseLLMRouter`, handle provider-specific schema quirks that litellm doesn't cover, and normalize tool_call responses from different providers into a uniform format.

## Dependencies

None — can start immediately. Can be developed in parallel with Phase 1.

## Files

| File | Action | Why |
|------|--------|-----|
| `sci_fi_dashboard/llm_router.py` | **MODIFY** | Add tools support to `_do_call()`, new `call_with_tools()`, schema normalization, `LLMToolResult` dataclass |

## Implementation

### 2.1 — New dataclasses (add near line 38)

```python
@dataclass
class ToolCall:
    """Normalized tool call — provider-agnostic."""
    id: str
    name: str
    arguments: str          # raw JSON string

@dataclass
class LLMToolResult:
    text: str               # LLM's text content (may be empty if tool_calls only)
    tool_calls: list[ToolCall]
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str | None = None
```

### 2.2 — Schema normalization (adapted from OpenClaw Phase 6)

litellm handles most provider differences, but some quirks leak through:

```python
def normalize_tool_schemas(tools: list[dict], provider: str) -> list[dict]:
    """Apply provider-specific schema fixes that litellm doesn't handle."""
    if not tools:
        return tools

    normalized = []
    for tool in tools:
        t = copy.deepcopy(tool)
        schema = t.get("function", {}).get("parameters", {})

        if "gemini" in provider:
            # Gemini rejects: $schema, $id, examples, default, $defs
            _strip_keys_recursive(schema, {"$schema", "$id", "examples", "default", "$defs"})

        if "xai" in provider or "grok" in provider:
            # XAI rejects range keywords
            _strip_keys_recursive(schema, {"minLength", "maxLength", "minimum", "maximum", "multipleOf"})

        if "openai" in provider:
            # OpenAI structured outputs require additionalProperties: false
            if schema.get("type") == "object" and "additionalProperties" not in schema:
                schema["additionalProperties"] = False

        normalized.append(t)
    return normalized

def _strip_keys_recursive(obj: dict, keys: set) -> None:
    """Remove specified keys from a JSON Schema recursively."""
    if not isinstance(obj, dict):
        return
    for key in keys:
        obj.pop(key, None)
    for value in obj.values():
        if isinstance(value, dict):
            _strip_keys_recursive(value, keys)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _strip_keys_recursive(item, keys)
```

### 2.3 — Tool call normalization (adapted from OpenClaw Phase 7)

Different providers return tool calls in slightly different formats. Normalize:

```python
def normalize_tool_calls(raw_tool_calls: list | None) -> list[ToolCall]:
    """Normalize litellm tool_call objects into uniform ToolCall dataclass."""
    if not raw_tool_calls:
        return []
    calls = []
    for tc in raw_tool_calls:
        name = (tc.function.name or "").strip()  # trim whitespace (OpenClaw: wrapStreamFnTrimToolCallNames)
        if not name:
            continue  # skip empty/malformed

        args = tc.function.arguments or "{}"
        # Attempt JSON repair for malformed args
        try:
            json.loads(args)  # validate
        except json.JSONDecodeError:
            args = _attempt_json_repair(args)

        calls.append(ToolCall(
            id=tc.id or f"call_{uuid4().hex[:8]}",
            name=name,
            arguments=args,
        ))
    return calls

def _attempt_json_repair(raw: str) -> str:
    """Try basic JSON repair for common malformations."""
    # Trim trailing incomplete tokens
    raw = raw.rstrip()
    if not raw.endswith("}"):
        raw += "}"
    # Try balanced braces
    open_count = raw.count("{") - raw.count("}")
    if open_count > 0:
        raw += "}" * open_count
    try:
        json.loads(raw)
        return raw
    except json.JSONDecodeError:
        return "{}"  # fallback to empty
```

### 2.4 — Extend `_do_call()` (line ~442)

```python
async def _do_call(self, role, messages, temperature, max_tokens, tools=None, tool_choice="auto"):
    # ... existing model resolution ...
    kwargs = {"model": model_str, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        # Apply provider-specific schema normalization
        provider = self._resolve_provider(role)
        kwargs["tools"] = normalize_tool_schemas(tools, provider)
        kwargs["tool_choice"] = tool_choice
    response = await self._router.acompletion(**kwargs)
    # ... existing session tracking, error handling ...
    return response
```

### 2.5 — New `call_with_tools()` method

```python
async def call_with_tools(
    self,
    role: str,
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 1000,
    tool_choice: str = "auto",
) -> LLMToolResult:
    """Call LLM with tool schemas. Returns normalized tool_calls."""
    response = await self._do_call(
        role, messages, temperature, max_tokens,
        tools=tools, tool_choice=tool_choice,
    )
    message = response.choices[0].message
    usage = response.usage or type("U", (), {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})()
    return LLMToolResult(
        text=message.content or "",
        tool_calls=normalize_tool_calls(message.tool_calls),
        model=response.model or "unknown",
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        finish_reason=response.choices[0].finish_reason,
    )
```

### 2.6 — Provider detection helper

```python
def _resolve_provider(self, role: str) -> str:
    """Resolve provider name from role for schema normalization."""
    mapping = self._config.model_mappings.get(role, {})
    model_str = mapping.get("model", "")
    # litellm model strings are provider-prefixed: "gemini/...", "anthropic/...", "openai/..."
    return model_str.split("/")[0] if "/" in model_str else "unknown"
```

## Key Design Decisions

1. **Schema normalization happens in the router, not the registry** — the registry produces canonical schemas; the router adapts them per-provider. This keeps tools provider-agnostic.
2. **Tool call normalization handles real-world malformations** — trimmed names, repaired JSON, fallback IDs. OpenClaw does this in 5 stream wrapper layers; we do it post-response since litellm handles streaming internally.
3. **Backward compatibility** — `call()` and `call_with_metadata()` are unchanged. Only `call_with_tools()` uses the new path.

## Verification

1. **Unit test**: `normalize_tool_schemas()` with Gemini provider strips `$defs`, `default`
2. **Unit test**: `normalize_tool_schemas()` with XAI strips `minLength`, `maxLength`
3. **Unit test**: `normalize_tool_calls()` trims whitespace in tool names
4. **Unit test**: `normalize_tool_calls()` repairs broken JSON args
5. **Unit test**: `normalize_tool_calls()` returns empty list for `None` input
6. **Unit test**: `call_with_tools()` with mocked response returns `LLMToolResult`
7. **Regression test**: `call()` and `call_with_metadata()` still work without `tools=`

## Scope

- 1 file modified (`llm_router.py`, ~120 new lines)
- 2 new dataclasses, 3 new functions, 1 extended method
- ~7 unit tests
