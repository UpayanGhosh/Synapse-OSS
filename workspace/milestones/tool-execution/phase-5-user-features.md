# Phase 5: User Features & HTTP Tool Invocation

> Adapted from OpenClaw Phase 9: HTTP tool invocation endpoint + user-facing tool transparency.

## Goal

Make tools visible and useful to WhatsApp users (feedback footer, model switching, memory import), and add a direct HTTP tool invocation endpoint for external integrations and automation — the same tools, same policies, same hooks, different initiator.

## Dependencies

- **Phase 4** (Safety pipeline — owner gates and policy needed for `import_memory`, `switch_model`, and HTTP auth)

## Files

| File | Action | Why |
|------|--------|-----|
| `sci_fi_dashboard/api_gateway.py` | **MODIFY** | Tool footer, model override, HTTP `/tools/invoke` endpoint |
| `sci_fi_dashboard/tool_registry.py` | **MODIFY** | Register `switch_model`, `import_memory`, `list_tools` |
| `sci_fi_dashboard/gateway/worker.py` | **MODIFY** | Thread tool status for typing indicators |

## Implementation

### 5.1 — Tool usage footer

When tools are used during a response, append a compact footer (ASCII-safe for Windows cp1252):

```python
if tools_used:
    unique_tools = list(dict.fromkeys(tools_used))
    footer_parts = [f"Tools: {', '.join(unique_tools)}"]
    footer_parts.append(f"Tool time: {total_tool_time:.1f}s")
    footer_parts.append(f"Rounds: {round_num + 1}")
    footer += "\n---\n" + " | ".join(footer_parts)
```

Example WhatsApp response:
```
Here's what I found about the latest AI developments...

---
Model: gemini-2.0-flash | Tokens: 342/512 | Time: 1.8s
Tools: web_search, query_memory | Tool time: 0.9s | Rounds: 2
```

### 5.2 — Model switching tool (owner-only)

```python
# In-memory per-session model overrides
_model_overrides: dict[str, str] = {}

def _switch_model_factory(ctx: ToolContext) -> SynapseTool:
    if not ctx.sender_is_owner:
        return None  # hide from non-owners entirely

    available_roles = list(ctx.config.get("model_mappings", {}).keys())
    return SynapseTool(
        name="switch_model",
        description=f"Switch the AI model. Available roles: {', '.join(available_roles)}",
        parameters={
            "type": "object",
            "properties": {
                "model_role": {
                    "type": "string",
                    "description": "The role to switch to",
                    "enum": available_roles,
                }
            },
            "required": ["model_role"],
        },
        execute=lambda args: _handle_switch_model(args, ctx.chat_id, ctx.config),
        owner_only=True,
    )

async def _handle_switch_model(args: dict, chat_id: str, config: dict) -> ToolResult:
    role = args.get("model_role", "")
    mappings = config.get("model_mappings", {})
    if role not in mappings:
        return ToolResult(
            content=f"Unknown role '{role}'. Available: {', '.join(mappings.keys())}",
            is_error=True,
        )
    _model_overrides[chat_id] = role
    model_name = mappings[role].get("model", role)
    return ToolResult(content=f"Switched to {model_name}. This override lasts until the session restarts.")
```

**In `persona_chat()`, check override before `route_traffic_cop()`:**
```python
override_role = _model_overrides.get(chat_id)
if override_role:
    role = override_role
else:
    role = await route_traffic_cop(user_msg)
```

### 5.3 — Memory import tool (owner-only)

```python
def _import_memory_factory(ctx: ToolContext) -> SynapseTool:
    if not ctx.sender_is_owner:
        return None

    return SynapseTool(
        name="import_memory",
        description="Store a fact or piece of information in long-term memory.",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact to store"},
                "category": {"type": "string", "description": "Category (personal, fact, preference)", "default": "general"},
            },
            "required": ["content"],
        },
        execute=lambda args: _handle_import_memory(args),
        owner_only=True,
    )
```

### 5.4 — List tools (available to all)

```python
def _list_tools_factory(ctx: ToolContext) -> SynapseTool:
    return SynapseTool(
        name="list_tools",
        description="List all available tools and their capabilities.",
        parameters={"type": "object", "properties": {}},
        execute=lambda _: _handle_list_tools(ctx),
    )

async def _handle_list_tools(ctx: ToolContext) -> ToolResult:
    # This executes after policy filtering, so only shows tools available to this sender
    tools = tool_registry.resolve(ctx)
    listing = [{"name": t.name, "description": t.description} for t in tools]
    return ToolResult(content=json.dumps(listing, indent=2))
```

### 5.5 — HTTP Tool Invocation Endpoint (adapted from OpenClaw Phase 9)

Add a direct tool invocation endpoint for external integrations:

```python
@app.post("/tools/invoke")
async def invoke_tool(request: Request):
    """Direct tool invocation without LLM. Same policies and hooks apply."""
    # Auth
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not validate_api_key(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.json()
    tool_name = body.get("tool")
    args = body.get("args", {})
    session_key = body.get("session_key", "default")
    dry_run = body.get("dry_run", False)

    # Resolve tools with owner context (HTTP caller = operator = owner)
    context = ToolContext(
        chat_id=session_key,
        sender_id="http_operator",
        sender_is_owner=True,
        workspace_dir=str(PROJECT_ROOT),
        config=synapse_config.raw,
    )
    session_tools = tool_registry.resolve(context)

    # Apply policy pipeline (same as chat path + HTTP-specific deny)
    http_deny = synapse_config.raw.get("gateway", {}).get("tools_http_deny", [])
    steps = _build_policy_steps(context) + [
        PolicyStep(policy=ToolPolicy(deny=http_deny), label="HTTP deny")
    ]
    filtered, removed = apply_tool_policy_pipeline(session_tools, steps, sender_is_owner=True)

    # Lookup
    tool = next((t for t in filtered if t.name == tool_name), None)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_name}' not found or not allowed")

    # Dry run (adapted from OpenClaw Phase 9)
    if dry_run:
        return {"ok": True, "dry_run": True, "would_execute": tool_name}

    # Execute with hooks
    action, effective_args = await hook_runner.run_before(tool_name, args, context)
    if action == "block":
        raise HTTPException(status_code=403, detail="Blocked by hook")

    t0 = time.time()
    result = await tool_registry.execute(tool_name, effective_args)
    duration_ms = (time.time() - t0) * 1000

    await hook_runner.run_after(tool_name, effective_args, result, duration_ms)

    return {
        "ok": True,
        "tool": tool_name,
        "result": {"content": result.content, "is_error": result.is_error},
        "duration_ms": round(duration_ms, 1),
    }
```

### 5.6 — Tool Catalog Endpoint (companion to /tools/invoke)

```python
@app.get("/tools/catalog")
async def tool_catalog(request: Request):
    """List available tools with schemas. Requires gateway auth."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not validate_api_key(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    context = ToolContext(chat_id="catalog", sender_id="http_operator", sender_is_owner=True, ...)
    tools = tool_registry.resolve(context)
    schemas = tool_registry.get_schemas(tools)
    return {"tools": schemas}
```

### 5.7 — Command shortcuts (optional, low priority)

Detect `/commands` before sending to LLM:

| Command | Action |
|---------|--------|
| `/model <role>` | Set model override, skip LLM |
| `/tools` | List tools, skip LLM |
| `/forget` | Clear model override |

## Verification

1. **Footer test**: message triggers `web_search` → response includes "Tools: web_search" footer
2. **Model switch via chat**: "switch to code model" → tool called → next message uses code role
3. **Model switch persistence**: two messages after switch → both use overridden model
4. **Memory import**: "remember my birthday is March 15" → `import_memory` called → fact stored
5. **List tools**: "what can you do?" → `list_tools` called → list returned
6. **Non-owner hidden**: non-owner resolves tools → `switch_model`, `import_memory`, `write_file` not in list
7. **HTTP invoke**: `POST /tools/invoke {"tool": "web_search", "args": {"url": "..."}}` → result returned
8. **HTTP dry run**: `POST /tools/invoke {"tool": "web_search", "dry_run": true}` → `{"would_execute": "web_search"}`
9. **HTTP deny**: tool in `gateway.tools_http_deny` → 404 on HTTP invoke, still works via chat
10. **HTTP auth**: no Bearer token → 401
11. **Tool catalog**: `GET /tools/catalog` → JSON list of all available tools with schemas

## Scope

- 3 files modified (~250 new lines)
- 3 new tool factories + 2 new API endpoints
- ~11 tests
