# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## OSS Development Workflow (CRITICAL — read before every push)

**Testing uses personal data. Commits follow OSS standards. Never mix them.**

- **During development/testing**: Personal data is fine — real `~/.synapse/` DBs, personal `entities.json`, personal `synapse.json` tokens, real chat history. This is how features are validated.
- **Before any `git commit` or `git push`**: Apply OSS standards:
  - No personal data files (e.g., `entities.json` extracted from real chats — ~3.9MB, 110K entities)
  - No tokens, API keys, or personal credentials in committed files
  - No `synapse.json` with real `gateway_token` or `providers` keys
  - `entities.json` ships as an empty `{}` placeholder — users populate it via their own extraction
  - Config files ship with example/placeholder values, not real ones
  - Test fixtures use synthetic data, not personal messages

**Pre-push checklist:**
1. Is `entities.json` empty `{}`? (never commit real extracted entities)
2. Are all tokens/keys in `.gitignore`d files only?
3. Does the code work for a fresh OSS install, not just this personal setup?

## Code Graph (Default Behaviour)

A persistent structural knowledge graph of this codebase is available via the `code-review-graph` MCP server.
**Always prefer graph tools over reading files for orientation and impact analysis.**

| When you want to... | Use this tool | Instead of... |
|---|---|---|
| Understand what a file/function does | `semantic_search_nodes_tool` | reading the file |
| Find what calls a function | `query_graph_tool` (callers) | grep |
| Know what will break if you edit X | `get_impact_radius_tool` | reading dependents manually |
| Orient before a multi-file task | `get_review_context_tool` | reading all files |
| Get architecture overview | `get_architecture_overview_tool` | reading all modules |
| Find entry points / critical flows | `list_flows_tool` | tracing manually |

**Rules:**
1. Before reading any file to understand context, query the graph first.
2. Only read full file contents when you need to implement a specific change.
3. After any Edit/Write, the graph auto-updates via PostToolUse hooks — no manual rebuild needed.

## Commands

```bash
# Start/Stop
./synapse_start.sh          # Start all (Mac/Linux)
synapse_start.bat           # Start all (Windows)
./synapse_stop.sh           # Stop all

# API server only
cd workspace/sci_fi_dashboard && uvicorn api_gateway:app --host 0.0.0.0 --port 8000 --reload

# Baileys WhatsApp bridge only (Node.js subprocess — normally auto-spawned by WhatsAppChannel)
cd baileys-bridge && npm install && node index.js

# CLI
cd workspace && python main.py chat|ingest|vacuum|verify

# Tests — run from workspace/
cd workspace && pytest tests/ -v
pytest tests/ -m unit|integration|smoke          # filter by marker
pytest tests/test_flood.py -v                    # single file
pytest tests/test_flood.py::TestFloodGate::test_batch -v  # single test
pytest tests/test_dual_cognition.py -v            # dual cognition engine tests

# Lint
ruff check workspace/ && black workspace/   # line-length 100, py311
```

## Architecture

### Request Flow (full happy path)
```
Channel (WA/TG/Discord/Slack)
  → ChannelRegistry
  → FloodGate (3s batch)
  → MessageDeduplicator (5-min TTL)
  → TaskQueue (asyncio FIFO, max 100)
  → MessageWorker x2
  → persona_chat() in api_gateway.py
      ├── SBS: get_prompt()          # assembled ~1500-token persona segment
      ├── MemoryEngine: query()      # hybrid RAG: vector + FTS + rerank (single query, results shared)
      ├── DualCognitionEngine: think()  # inner monologue + tension score (timeout-wrapped, configurable)
      │     └── receives pre_cached_memory from MemoryEngine (no double query)
      ├── route_traffic_cop()        # classifies → CASUAL/CODING/ANALYSIS/REVIEW/SPICY
      │     └── skipped when CognitiveMerge.response_strategy maps to a known role
      └── SynapseLLMRouter: call()   # litellm.Router → cloud or local Ollama
  → registry.get(channel_id).send()
```

### LLM Routing (Traffic Cop → MoA)
`route_traffic_cop()` in `api_gateway.py` auto-classifies every message before the LLM call. The LLM is **never** given tools during `persona_chat()` — no function calling in the chat path.

| Role | Model | Trigger |
|------|-------|---------|
| casual | Gemini Flash | default / Banglish |
| code | Claude Sonnet (thinking) | code detected |
| analysis | Gemini Pro | deep reasoning |
| vault | Local Ollama | private/spicy content — zero cloud leakage |
| review | configurable | explicit review tasks |

Model strings are provider-prefixed (`gemini/gemini-2.0-flash-exp`, `anthropic/claude-3-5-sonnet-20241022`, `ollama_chat/mistral`) and come from `synapse.json → model_mappings`. Each role can declare a `fallback` model.

### Soul-Brain Sync (SBS) Persona Engine
Pipeline: `RawMessage → RealtimeProcessor → BatchProcessor (every 50 msgs or 6h) → PromptCompiler → system prompt`

Two SBS instances run simultaneously: `sbs_the_creator` (primary user, casual/sibling) and `sbs_the_partner` (partner, warm/PA). Each tracks 8 profile layers: `core_identity`, `linguistic`, `emotional_state`, `domain`, `interaction`, `vocabulary`, `exemplars`, `meta`.

`ImplicitFeedbackDetector` watches every message for correction signals ("too long", "be more casual") and adjusts profile layers immediately without explicit commands. Patterns loaded from `sbs/feedback/language_patterns.yaml` — editable without touching Python.

### Memory (Hybrid RAG)
- `memory.db` — SQLite + sqlite-vec, documents + embeddings, WAL mode
- `knowledge_graph.db` — subject–predicate–object triples (SQLiteGraph)
- LanceDB (embedded, `~/.synapse/workspace/db/lancedb/`) — high-speed ANN search (zero Docker)

Retrieval: embed (Ollama `nomic-embed-text`) → LanceDB ANN+FTS → FlashRank rerank (ms-marco-TinyBERT-L-2-v2). Fast Gate skips reranker if ≥ limit results score > 0.80. DBs live at `~/.synapse/workspace/db/`.

Dual hemispheres: `hemisphere_tag = "safe"|"spicy"`. The Vault role only ever touches the `spicy` hemisphere — enforces zero cloud leakage for private sessions.

### Additional Pipeline Features
- **Auto-Continue**: if a reply has no terminal punctuation, a `BackgroundTask` requests a continuation and sends it as a second message.
- **Voice messages**: WhatsApp OGG/MP3 → `AudioProcessor` (Groq Whisper-Large-v3) → transcribed text enters the normal pipeline. Cloud transcription avoids loading local Whisper on 8 GB RAM hosts.
- **Media pipeline** (`sci_fi_dashboard/media/`): MIME detection (magic bytes > header > extension), size limits (image 6 MB / audio+video 16 MB / doc 100 MB), 120s TTL cleanup, SSRF guard rejects private/loopback IPs.
- **Gentle Worker Loop**: runs maintenance only when plugged in AND CPU < 20%. Prunes stale graph triples every 10 min, VACUUMs DBs every 30 min.

### WebSocket Gateway
- Endpoint: `ws://127.0.0.1:8000/ws`, auth via `SYNAPSE_GATEWAY_TOKEN` (optional)
- Methods: `chat.send`, `channels.status`, `models.list`, `sessions.list`, `sessions.reset`
- Heartbeat tick every 30s

### DM Access Control (`channels/security.py`)
Per-channel policy via `DmPolicy` enum: `pairing | allowlist | open | disabled`. `PairingStore` persists approved senders at `~/.synapse/state/pairing/<channel_id>.jsonl`. `resolve_dm_access()` is a pure function returning `"allow" / "deny" / "pending_approval"`.

### MCP Servers (`sci_fi_dashboard/mcp_servers/`)
| Server | Port | Purpose |
|--------|------|---------|
| `tools_server.py` | 8989 | `read_file`, `write_file` (Sentinel-gated), `web_search` |
| `memory_server.py` | — | knowledge base query + fact ingest |
| `synapse_server.py` | — | chat pipeline, profile queries |
| `gmail_server.py`, `calendar_server.py`, `slack_server.py` | — | external integrations |

MCP tools are **not** offered to the LLM during persona chat — they are only called by `ProactiveAwarenessEngine` or external MCP clients.

**Known bug in `tools_server.py`**: `read_file`/`write_file` call `Sentinel().agent_read_file()` which is incorrect — `agent_read_file` is a module-level function in `sbs/sentinel/tools.py`, not a method on `Sentinel`. These tools raise `TypeError` at runtime until fixed.

## Key Files

### Entry Points
| File | Purpose |
|------|---------|
| `workspace/main.py` | CLI: chat, ingest, vacuum, verify |
| `workspace/sci_fi_dashboard/api_gateway.py` | FastAPI app (~1200 lines), all singletons init here |
| `workspace/synapse_config.py` | Root config — imported by 50+ files, edit carefully |

### Core Modules (workspace/sci_fi_dashboard/)
| File | Class | Purpose |
|------|-------|---------|
| `llm_router.py` | `SynapseLLMRouter` | litellm.Router wrapper, copilot token shim, LLMResult dataclass |
| `memory_engine.py` | `MemoryEngine` | Hybrid RAG (vector+FTS+rerank) — affects search quality |
| `db.py` | `DatabaseManager` | SQLite+sqlite-vec, WAL mode, schema lifecycle |
| `retriever.py` | `RetrievalPipeline` | Embed via Ollama/sentence-transformers, ANN+FTS |
| `dual_cognition.py` | `DualCognitionEngine` | Inner monologue + tension scoring; accepts `pre_cached_memory` from gateway; DEEP path fully parallelized; uses `logging` module |
| `sqlite_graph.py` | `SQLiteGraph` | Knowledge graph (nodes/edges, subject-predicate-object) |
| `persona.py` | `PersonaManager` | System prompt assembly, dictionary |
| `toxic_scorer_lazy.py` | `LazyToxicScorer` | Toxic-BERT, auto-unloads after 30s idle |
| `models_catalog.py` | `ModelsCatalog` | Ollama discovery, context window guard |

### Isolated Modules (safe to edit independently)
`gateway/flood.py`, `gateway/dedup.py`, `gateway/queue.py`, `channels/*.py` (via BaseChannel ABC), `sbs/profile/manager.py`, `narrative.py`, `conflict_resolver.py`

> **Note:** `dual_cognition.py` was previously isolated but now has a coupling with `api_gateway.py` via `pre_cached_memory` parameter. Edit the `think()` signature carefully.

## Configuration

### `synapse.json`
Primary runtime config. Key sections:
- `model_mappings` — per-role model + optional fallback
- `providers` — API keys and `api_base` for each provider
- `gateway_token` — token for `POST /chat/the_creator` and WebSocket auth
- `session.dmScope` — one of `"main"` (default), `"per-peer"`, `"per-channel-peer"`, `"per-account-channel-peer"`
- `session.identityLinks` — maps canonical name to raw peer IDs across channels
- `session.dual_cognition_enabled` — boolean (default `true`), disables DualCognitionEngine when `false`
- `session.dual_cognition_timeout` — float seconds (default `5.0`), `asyncio.wait_for` timeout on `think()`

### Environment Variables
`GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `WHATSAPP_BRIDGE_TOKEN`, `SYNAPSE_GATEWAY_TOKEN`

Keys can also be stored in `synapse.json → providers` — `_inject_provider_keys()` writes them to `os.environ` at startup.

## Ports
API:8000 | Baileys Bridge:5010 (internal) | Tools MCP:8989 | Ollama:11434 | OAuth:8080

## Critical Gotchas

1. **litellm Router ≠ litellm.acompletion for GitHub Copilot** — `litellm.Router` does NOT apply Copilot auth headers. Workaround in `llm_router.py`: rewrite `github_copilot/` prefix to `openai/` + inject `api_base=GITHUB_COPILOT_API_BASE` + `extra_headers`. Token from `~/.config/litellm/github_copilot/api-key.json`. Auto-refresh on 403 is built into `_do_call()`.

2. **Copilot `ghu_` tokens are short-lived and can be revoked before `expires_at`** — don't trust the expiry timestamp; the auto-refresh handles this.

3. **`/chat` vs `/chat/{user}` endpoints** — `POST /chat` is async webhook (returns `{"status": "queued"}`). `POST /chat/the_creator` is synchronous persona chat. Always use the correct one.

4. **Kill the gateway process after code changes** — it won't reload automatically unless started with `--reload`.

5. **Windows cp1252 can't print emoji** — all preview strings in the gateway must be ASCII-encoded with `replace` error handling.

6. **Ollama models require `ollama_chat/` prefix** in `synapse.json`, not `ollama/`. The `api_base` is pulled from `providers.ollama.api_base`.

   **Ollama silent context truncation** — Ollama defaults to `num_ctx=2048` regardless of the model's native window. Synapse's identity prompt is ~7k tokens — at the default, the trailing user message gets dropped and the bot replies with generic "how can I help" boilerplate. Fix is in `llm_router.py: _OLLAMA_DEFAULT_OPTS` (sets `num_ctx=8192`). Override per-role via `model_mappings.<role>.ollama_options.num_ctx`. Verify VRAM headroom: KV cache size grows linearly with `num_ctx`; on 8 GB GPUs avoid combining a 7B+ model with `num_ctx > 12k`.

7. **`synapse_config.py` is imported by 50+ files** — even small changes there have wide blast radius.

8. **Dual Cognition timeout** — `think()` is wrapped in `asyncio.wait_for(timeout=dual_cognition_timeout)`. If it times out, `CognitiveMerge()` (empty) is used and the message still gets a response. Tune via `session.dual_cognition_timeout` in `synapse.json` (default 5s).

9. **Traffic Cop skip** — When `CognitiveMerge.response_strategy` is `"be_direct"`, `"analytical"`, or `"explore_with_care"`, the traffic cop LLM call is skipped and a role is mapped directly (`STRATEGY_TO_ROLE` constant in `api_gateway.py`). Falls back to normal traffic cop for unmapped strategies.

10. **Memory query is shared** — `MemoryEngine.query()` is called once in `persona_chat()` and results are passed to `dual_cognition.think(pre_cached_memory=...)`. Do NOT add a second memory query inside dual cognition.

## Symbol Lookup
Prefer `semantic_search_nodes_tool` (MCP) — searches 4700+ nodes by name or meaning in <2ms.

Fallback (if MCP unavailable):
```bash
grep "^SYMBOL_NAME	" workspace/tags   # 1215 symbols indexed
```

## Code Style
Python 3.11 | line-length 100 | ruff + black | asyncio throughout (no Redis/Celery) | SQLite WAL mode

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes � gives risk-scored analysis |
| `get_review_context` | Need source snippets for review � token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
