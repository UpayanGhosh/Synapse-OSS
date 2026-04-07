# Synapse-OSS Architecture

## Overview

Synapse-OSS is an AI personal assistant / chatbot gateway that connects multiple messaging channels (WhatsApp, Telegram, Discord, Slack) to a multi-model LLM backend. Its core value proposition is a persona engine (Soul-Brain Sync) that continuously learns the user's communication style, combined with a dual-hemisphere memory system and a "dual cognition" inner monologue layer that shapes every response.

The system is built on Python 3.11 / FastAPI (async throughout), with SQLite as the primary database layer and no external message queue (Redis/Celery) — asyncio primitives handle all concurrency.

---

## Architectural Layers

```
┌─────────────────────────────────────────────────────────────┐
│                  Channel Adapters (Inbound)                 │
│  WhatsApp (Baileys/Node.js)  Telegram  Discord  Slack  Stub │
└────────────────────────┬────────────────────────────────────┘
                         │ ChannelMessage DTO
┌────────────────────────▼────────────────────────────────────┐
│                    Gateway Pipeline                         │
│  FloodGate (3s debounce) → MessageDeduplicator → TaskQueue  │
└────────────────────────┬────────────────────────────────────┘
                         │ MessageTask
┌────────────────────────▼────────────────────────────────────┐
│               MessageWorker (x2 async workers)              │
│            process_message_pipeline() dispatcher            │
└────────────────────────┬────────────────────────────────────┘
                         │ ChatRequest
┌────────────────────────▼────────────────────────────────────┐
│                   persona_chat() Core                       │
│  Memory Retrieval → Toxicity → Dual Cognition → SBS Prompt  │
│  → Traffic Cop → LLM Call (Tool Loop) → Auto-Continue       │
└────────────────────────┬────────────────────────────────────┘
                         │ reply text
┌────────────────────────▼────────────────────────────────────┐
│             Channel Adapters (Outbound send)                │
└─────────────────────────────────────────────────────────────┘
```

---

## Entry Points

### FastAPI Application
- **`workspace/sci_fi_dashboard/api_gateway.py`** — thin orchestrator: `FastAPI` app creation, lifespan hook, middleware registration, and route inclusion. All singleton initialization moved to `_deps.py`. Business logic lives in dedicated modules.
- **`workspace/main.py`** — CLI entry point with four sub-commands: `chat`, `ingest`, `vacuum`, `verify`. The `chat` command spawns the gateway as a subprocess then connects via `aiohttp` to `POST /chat/the_creator`.

### Lifespan Sequence (startup order in `api_gateway.py`)
1. `ensure_bridge_db()` — WhatsApp bridge SQLite init
2. `gentle_worker_loop()` as asyncio task — background maintenance
3. `channel_registry.start_all()` — starts all registered channel adapters
4. `RetryQueue` wired to WhatsApp channel
5. `MessageWorker` (2 workers) consuming from `TaskQueue`
6. `ToolRegistry` + builtin tools (optional, graceful skip on ImportError)
7. `ToolHookRunner` + `ToolAuditLogger` safety pipeline (optional)
8. `SessionActorQueue` — per-session ordered execution
9. `ensure_models_catalog()` — Ollama model discovery
10. `GatewayWebSocket` — WebSocket server setup
11. `SynapseMCPClient` — connects external MCP servers if enabled
12. `ProactiveAwarenessEngine` — background polling of calendar/email/slack
13. `CronService` — scheduled proactive message delivery

---

## Singleton Registry (`_deps.py`)

All long-lived singletons are module-level variables in `workspace/sci_fi_dashboard/_deps.py`. This is the single source of truth imported by every module that needs shared state.

Key singletons:
- `brain` — `SQLiteGraph` (knowledge graph)
- `gate` — `EntityGate` (named entity recognition)
- `conflicts` — `ConflictManager`
- `toxic_scorer` — `LazyToxicScorer` (auto-unloads after 30s idle)
- `emotional_trajectory` — `EmotionalTrajectory`
- `memory_engine` — `MemoryEngine` (hybrid RAG, receives `brain` + `gate`)
- `dual_cognition` — `DualCognitionEngine`
- `task_queue` — `TaskQueue(max_size=100)`
- `dedup` — `MessageDeduplicator(window_seconds=300)`
- `flood` — `FloodGate(batch_window_seconds=3.0)`
- `channel_registry` — `ChannelRegistry` (pre-populated with WhatsApp + Stub)
- `sbs_registry` — `dict[persona_id → SBSOrchestrator]` (one per persona from `personas.yaml`)
- `synapse_llm_router` — `SynapseLLMRouter` (litellm.Router wrapper)
- `_synapse_cfg` — `SynapseConfig` (frozen dataclass, loaded from `synapse.json`)
- `tool_registry`, `hook_runner`, `audit_logger` — optional tool execution phase

---

## Request Lifecycle (Happy Path)

### Inbound via Channel Webhook
```
POST /channels/whatsapp/webhook
  → chat.py::chat_webhook()
      → dedup.is_duplicate(message_id)          # 5-min TTL dedup
      → flood.incoming(chat_id, message, meta)  # 3s batching debounce
          → TaskQueue.put(MessageTask)
              → MessageWorker.process()
                  → process_message_pipeline()
                      → persona_chat(request, target)
                          → registry.get(channel_id).send(reply)
```

### Inbound via Direct POST (Synchronous)
```
POST /chat/the_creator
  → chat.py::handler()
      → validate_api_key()
      → persona_chat(request, "the_creator", background_tasks)
      → return {"reply": ..., "model": ..., "memory_method": ...}
```

---

## `persona_chat()` — Core Pipeline (`chat_pipeline.py`)

All logic lives in `workspace/sci_fi_dashboard/chat_pipeline.py`. Execution order:

### 1. Memory Retrieval (Two-Layer)
- **Layer 1 — Permanent Profile**: SQL query for `relationship_memory` + latest `memory_distillation` from `memory.db`. Always injected (~500 tokens).
- **Layer 2 — Dynamic Context**: `MemoryEngine.query(user_msg, limit=5, with_graph=True)` → hybrid vector+FTS+rerank search. Result shared with Dual Cognition (no double query).

### 2. Toxicity Check
`LazyToxicScorer.score(user_msg)` using Toxic-BERT. Score > 0.8 in safe mode logs a warning but does not block.

### 3. Dual Cognition (`dual_cognition.py`)
Timeout-wrapped (`asyncio.wait_for`, default 5s). Receives `pre_cached_memory` from step 1.
- **PresentStream**: intent, sentiment, topics from current message
- **MemoryStream**: facts, graph connections, contradictions from memory
- **CognitiveMerge**: tension level/type, response strategy, suggested tone, inner monologue

### 4. Prompt Assembly
- `SBSOrchestrator.on_message("user", ...)` — logs message, triggers realtime profile update
- `SBSOrchestrator.get_system_prompt(base_instructions, proactive_block)` — compiled persona segment
- Situational awareness block (IST time, conversation gap hint)
- Message length mirroring hint (1-2 words / 1-2 sentences / 2-4 sentences)
- Permanent profile injected last (recency bias in small models)

### 5. Traffic Cop Routing (may be skipped)
`STRATEGY_TO_ROLE` maps 6 dual-cognition strategies directly to roles, skipping a Gemini Flash classification call (~50% of messages). Otherwise `route_traffic_cop()` calls Gemini Flash with a zero-temperature prompt returning CASUAL/CODING/ANALYSIS/REVIEW.

Role → Model mapping:
| Role     | Model                            | Trigger                         |
|----------|----------------------------------|---------------------------------|
| `casual` | Gemini Flash (default)           | Default / Banglish              |
| `code`   | Claude Sonnet (thinking)         | CODING classification           |
| `analysis` | Gemini Pro                     | ANALYSIS classification         |
| `vault`  | Local Ollama (Mistral)           | `session_type == "spicy"`       |
| `review` | Configurable                     | REVIEW classification           |
| `kg`     | Configurable (fallback: casual)  | Background KG extraction        |

### 6. Tool Execution Loop (Phase 3-5)
Up to `MAX_TOOL_ROUNDS=5` iterations. In each round:
- If tool schemas available: `call_with_tools()` — LLM may return `tool_calls`
- Otherwise: `call_with_metadata()` — plain text reply, break
- Parallel tool execution (`asyncio.gather`) for non-serial tools; serial for flagged tools
- Loop detection via `ToolLoopDetector` (blocks repeated identical calls)
- Context overflow guard: disables tools after `MAX_TOTAL_TOOL_RESULT_CHARS=20000`

Tools are NEVER offered to the LLM during vault (spicy) sessions.

### 7. Post-Processing
- Stats footer appended (token usage, model, latency, tools used)
- `SBSOrchestrator.on_message("assistant", ...)` — logs reply, triggers SBS update
- Auto-continue: if reply > 50 chars and lacks terminal punctuation, `continue_conversation()` fires as a `BackgroundTask`

---

## Soul-Brain Sync (SBS) Persona Engine

**Entry**: `workspace/sci_fi_dashboard/sbs/`

Two orchestrator instances run simultaneously (configurable via `personas.yaml`), defaulting to `sbs_the_creator` and `sbs_the_partner`.

### Pipeline
```
RawMessage
  → SBSOrchestrator.on_message()
      → ConversationLogger    (persist to SQLite)
      → RealtimeProcessor     (immediate profile layer updates)
      → ImplicitFeedbackDetector  (watches for correction signals)
      ↓ every 50 msgs or 6h
      → BatchProcessor
          → Vocabulary census + temporal decay
          → Linguistic style analysis
          → Interaction pattern analysis
          → Domain map update
          → ExemplarSelector (few-shot pair re-selection)
      ↓
      → ProfileManager.snapshot_version()
      ↓
      → PromptCompiler.compile() → system prompt segment (~6000 chars max)
```

### Profile Layers (8)
`core_identity`, `linguistic`, `emotional_state`, `domain`, `interaction`, `vocabulary`, `exemplars`, `meta`

`ImplicitFeedbackDetector` loads patterns from `sbs/feedback/language_patterns.yaml` (editable without Python changes) and mutates profile layers immediately on detection.

---

## Memory System

### Databases
| Database | File | Technology | Purpose |
|----------|------|-----------|---------|
| `memory.db` | `~/.synapse/workspace/db/memory.db` | SQLite + sqlite-vec, WAL | Documents, embeddings, atomic facts, relationship memories |
| `knowledge_graph.db` | `~/.synapse/workspace/db/knowledge_graph.db` | SQLiteGraph (plain SQLite) | Subject-predicate-object triples |
| LanceDB | `~/.synapse/workspace/db/lancedb/` | LanceDB embedded | High-speed ANN vector search |

### Retrieval Pipeline (`retriever.py`, `memory_engine.py`)
1. Embed query via `EmbeddingProvider` (FastEmbed ONNX > Ollama > error)
2. LanceDB ANN search (approximate nearest neighbor)
3. sqlite-vec cosine search (fallback / dual-path)
4. FTS (full-text search) fallback if no embeddings
5. FlashRank reranker (`ms-marco-TinyBERT-L-2-v2`) — skipped if ≥ limit results score > 0.80
6. Graph context injection from `SQLiteGraph`

### Hemisphere Segmentation (Air-Gap)
Every document carries `hemisphere_tag = "safe" | "spicy"`. The vault/spicy path (local Ollama) only reads spicy-tagged documents. Cloud LLMs can only see safe-tagged content. SQL enforced at query time — never at application logic level.

### Embedding Provider Cascade (`embedding/factory.py`)
```
config['embedding']['provider'] == explicit  →  use it
  ↓ else
fastembed importable?  →  FastEmbedProvider (ONNX, local, no Ollama required)
  ↓ else
OllamaProvider available?  →  OllamaProvider (nomic-embed-text)
  ↓ else
RuntimeError
```

---

## LLM Router (`llm_router.py`)

`SynapseLLMRouter` wraps `litellm.Router`. All model strings are provider-prefixed and sourced from `synapse.json → model_mappings` at startup. No hardcoded model strings in the router.

### GitHub Copilot Shim
litellm.Router does not apply Copilot auth headers natively. The router rewrites `github_copilot/` prefix → `openai/` and injects `api_base` + `extra_headers` from `~/.config/litellm/github_copilot/api-key.json`. Auto-refreshes on HTTP 403.

### InferenceLoop Retry Logic
Wraps `_do_call()` with `classify_llm_error()`:
- Context overflow → compact history → retry
- Rate limited → exponential backoff
- Auth failed → rotate auth profile
- Server error → retry once
- Model not found → use fallback model from `model_mappings[role].fallback`

---

## Channel Abstraction (`channels/`)

`BaseChannel` (ABC) defines the interface all adapters implement:
- `channel_id: str` — unique string identifier
- `start()` / `stop()` — async lifecycle
- `send(chat_id, text, **kwargs)` — outbound delivery
- Inbound: adapters call into the gateway via HTTP webhook or push to `TaskQueue` directly

### Access Control (`channels/security.py`)
`DmPolicy` enum: `PAIRING | ALLOWLIST | OPEN | DISABLED`
- `PairingStore` — JSONL-backed approved-senders at `~/.synapse/state/pairing/<channel_id>.jsonl`
- `resolve_dm_access()` — pure function returning `"allow" / "deny" / "pending_approval"`

### WhatsApp Bridge
`WhatsAppChannel` bridges to a Node.js Baileys microservice on port 5010. Python receives inbound webhooks at `/channels/whatsapp/webhook`. `RetryQueue` handles outbound delivery failures with persistence.

---

## WebSocket Gateway (`gateway/ws_server.py`)

Endpoint: `ws://127.0.0.1:8000/ws`, auth via `SYNAPSE_GATEWAY_TOKEN`.
- Heartbeat tick every 30s
- Methods: `chat.send`, `channels.status`, `models.list`, `sessions.list`, `sessions.reset`
- Protocol handling in `gateway/ws_protocol.py`

---

## MCP Integration

### MCP Client (`mcp_client.py`, `mcp_config.py`)
`SynapseMCPClient` connects to external MCP servers configured in `synapse.json → mcp`. Tools are NOT offered to the LLM during `persona_chat()` — they are only used by `ProactiveAwarenessEngine` or external MCP clients.

### MCP Servers (`mcp_servers/`)
Synapse exposes its own capabilities as MCP servers:
| Server | Port | Purpose |
|--------|------|---------|
| `tools_server.py` | 8989 | `read_file`, `write_file` (Sentinel-gated), `web_search` |
| `memory_server.py` | — | Knowledge base query + fact ingest |
| `synapse_server.py` | — | Chat pipeline, profile queries |
| `gmail_server.py` | — | Gmail integration |
| `calendar_server.py` | — | Calendar integration |
| `slack_server.py` | — | Slack integration |

**Known bug**: `tools_server.py` `read_file`/`write_file` call `Sentinel().agent_read_file()` — incorrect, `agent_read_file` is a module-level function in `sbs/sentinel/tools.py`, not an instance method. Raises `TypeError` at runtime.

---

## Tool Execution System (Phases 3-5)

All optional — graceful skip if imports fail.

- **Phase 3** — `tool_registry.py`: `ToolRegistry` + `register_builtin_tools()`. Tools resolve based on `ToolContext` (sender ownership, channel, config). Serial/parallel execution split.
- **Phase 4** — `tool_safety.py`: `apply_tool_policy_pipeline()` filters tools by policy. `ToolHookRunner` for pre/post hooks. `ToolLoopDetector` blocks repeated identical calls. `ToolAuditLogger` writes JSONL to `~/.synapse/audit/`.
- **Phase 5** — `tool_features.py`: `format_tool_footer()`, `get_model_override()`, `parse_command_shortcut()` for user-facing features.

---

## Background Services

### GentleWorker (`gentle_worker.py`)
Thermal-aware: only runs when plugged in AND CPU < 20%.
- Prunes stale graph triples every 10 min
- VACUUMs SQLite DBs every 30 min
- Triggers background KG extraction (`conv_kg_extractor.py`)

### CronService (`cron_service.py`)
Reads job definitions from `~/.synapse/cron/jobs.json`. Each job fires `persona_chat()` at schedule and delivers output to a specified channel. Supports `every_Nh`, `every_day_at_HH:MM_IST`, `once_at_HH:MM_IST` schedule formats.

### ProactiveAwarenessEngine (`proactive_engine.py`)
Background polling of personal MCP servers (calendar, email, Slack). Compiles context block injected into every `persona_chat()` system prompt.

---

## Configuration Architecture

### `SynapseConfig` (`synapse_config.py`)
Frozen dataclass. Single source of truth for all paths and credentials. Imported by 50+ files — edit carefully. Loads from `synapse.json` in workspace root.

Key fields:
- `data_root` — `~/.synapse/` (or `SYNAPSE_HOME` env override)
- `db_dir` — `~/.synapse/workspace/db/`
- `sbs_dir` — `~/.synapse/workspace/sbs/`
- `model_mappings` — `dict[role → {model, fallback}]`
- `providers` — API keys, written to `os.environ` at startup
- `session` — `dmScope`, `identityLinks`, `dual_cognition_enabled`, `dual_cognition_timeout`
- `mcp` — MCP server configs + proactive config

### Config Subsystem (`config/`)
- `config/schema.py` — Pydantic config schema
- `config/layered_resolution.py` — layered config resolution
- `config/includes.py` — config file includes
- `config/env_substitution.py` — `${ENV_VAR}` substitution in config values
- `config/merge_patch.py` — RFC 7396 merge patch support
- `config/group_policy.py` — group-level policy overrides
- `config/migration.py` — schema migration helpers

---

## Multi-User / Session Management (`multiuser/`)

| Module | Purpose |
|--------|---------|
| `session_key.py` | Builds canonical `agent:<id>:<channel>:dm:<peer>` keys |
| `session_store.py` | Persists per-session conversation state |
| `identity_linker.py` | Maps peer IDs across channels via `identityLinks` config |
| `context_assembler.py` | Assembles full context for a session |
| `conversation_cache.py` | In-memory conversation history cache |
| `compaction.py` | Truncates/summarizes long conversation histories |
| `memory_manager.py` | Per-session memory isolation |
| `transcript.py` | Transcript persistence and retrieval |
| `tool_loop_detector.py` | Per-session tool loop detection |

Session key shapes (`dm_scope` in `synapse.json`):
- `main` → `agent:<id>:<mainKey>` (all DMs share one session)
- `per-peer` → `agent:<id>:<channel>:dm:<peerId>`
- `per-channel-peer` → same as per-peer
- `per-account-channel-peer` → `agent:<id>:<channel>:dm:<accountId>:<peerId>`

---

## Key Abstractions

| Abstraction | Location | Pattern |
|-------------|----------|---------|
| `BaseChannel` | `channels/base.py` | ABC, all channel adapters subclass this |
| `ChannelMessage` | `channels/base.py` | DTO: unified inbound message |
| `MsgContext` | `channels/base.py` | Extended inbound DTO (superset of ChannelMessage) |
| `SynapseConfig` | `synapse_config.py` | Frozen dataclass, single config source |
| `LLMResult` | `llm_router.py` | Structured LLM response with token metadata |
| `CognitiveMerge` | `dual_cognition.py` | Output of inner monologue + tension analysis |
| `SBSOrchestrator` | `sbs/orchestrator.py` | Per-persona soul-brain sync controller |
| `EmbeddingProvider` | `embedding/base.py` | ABC, implemented by FastEmbed/Ollama/Gemini |
| `SynapseTool` | `tool_registry.py` | ABC for all registered tools |
| `ToolContext` | `tool_registry.py` | Context injected into tool resolution |
| `DmPolicy` | `channels/security.py` | StrEnum for DM access control policies |

---

## Ports & External Dependencies

| Service | Port | Notes |
|---------|------|-------|
| FastAPI (uvicorn) | 8000 | Main API gateway |
| Baileys Node.js Bridge | 5010 | WhatsApp bridge (internal only) |
| Tools MCP Server | 8989 | External MCP clients connect here |
| Ollama | 11434 | Local LLM inference |
| OAuth callback | 8080 | Google/calendar auth |

External Python dependencies (key): `litellm`, `fastapi`, `uvicorn`, `sqlite-vec`, `flashrank`, `fastembed`, `psutil`, `rich`, `schedule`, `aiohttp`
