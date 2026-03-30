# CLAUDE.md — Synapse-OSS (optimized for local models)

## Commands
```bash
# Start/Stop
./synapse_start.sh          # Start all (Mac/Linux)
synapse_start.bat           # Start all (Windows)
./synapse_stop.sh           # Stop all

# API server
cd workspace/sci_fi_dashboard && uvicorn api_gateway:app --host 0.0.0.0 --port 8000 --reload

# CLI
cd workspace && python main.py chat|ingest|vacuum|verify

# Tests
cd workspace && pytest tests/ -v
pytest tests/ -m unit|integration|smoke

# Lint
ruff check workspace/ && black workspace/   # line-length 100, py311
```

## File Map (workspace/)

### Entry Points
| File | Purpose |
|------|---------|
| `main.py` | CLI: chat, ingest, vacuum, verify |
| `sci_fi_dashboard/api_gateway.py` | FastAPI app (~1200 lines), all singletons init here |

### Core Modules (sci_fi_dashboard/)
| File | Class/Purpose |
|------|---------------|
| `db.py` | `DatabaseManager` — SQLite+sqlite-vec, WAL mode, schema lifecycle |
| `memory_engine.py` | `MemoryEngine` — hybrid RAG (vector+FTS+rerank) |
| `retriever.py` | `RetrievalPipeline` — embed via Ollama/sentence-transformers, ANN+FTS search |
| `llm_router.py` | `SynapseLLMRouter` — litellm dispatch (Gemini/Claude/Ollama/OpenRouter) |
| `dual_cognition.py` | `DualCognitionEngine` — inner monologue, tension scoring (self-contained) |
| `sqlite_graph.py` | `SQLiteGraph` — knowledge graph (nodes/edges, subject-predicate-object) |
| `ingest.py` | `ingest_atomic()` — shadow table swap, hash dedup |
| `conflict_resolver.py` | `ConflictManager` — relationship/context conflicts |
| `emotional_trajectory.py` | `EmotionalTrajectory` — mood tracking over time |
| `toxic_scorer_lazy.py` | `LazyToxicScorer` — Toxic-BERT, auto-unloads after 30s idle |
| `persona.py` | `PersonaManager` — system prompt, dictionary |
| `chat_parser.py` | `ChatParser` — intent/sentiment from messages |
| `models_catalog.py` | `ModelsCatalog` — Ollama discovery, context window guard, `models_catalog.json` |

### Gateway Pipeline (sci_fi_dashboard/gateway/)
Flow: FloodGate -> Dedup -> TaskQueue -> MessageWorker x2 -> Send

| File | Class | Purpose |
|------|-------|---------|
| `flood.py` | `FloodGate` | 3s message batching per user |
| `dedup.py` | `MessageDeduplicator` | 5-min TTL duplicate filter |
| `queue.py` | `TaskQueue` | asyncio FIFO, max 100 tasks |
| `worker.py` | `MessageWorker` | 2 concurrent workers, processes tasks |
| `sender.py` | `WhatsAppSender` | Legacy outbound sender |

### Channels (sci_fi_dashboard/channels/)
All implement `BaseChannel` (ABC): `receive()`, `send()`, `send_typing()`, `start()`, `stop()`

| File | Channel |
|------|---------|
| `base.py` | `BaseChannel` (ABC), `ChannelMessage` (dataclass) |
| `registry.py` | `ChannelRegistry` — register/get/start_all/stop_all |
| `whatsapp.py` | `WhatsAppChannel` — Baileys HTTP bridge |
| `telegram.py` | `TelegramChannel` — python-telegram-bot |
| `discord_channel.py` | `DiscordChannel` — discord.py |
| `slack.py` | `SlackChannel` — slack_bolt |
| `stub.py` | `StubChannel` — testing mock |
| `security.py` | DM access control — `DmPolicy`, `PairingStore`, `resolve_dm_access()` |

### Soul-Brain Sync (sci_fi_dashboard/sbs/)
Pipeline: RawMessage -> RealtimeProcessor -> BatchProcessor (every 50 msgs/6h) -> PromptCompiler -> system prompt

| File | Class | Purpose |
|------|-------|---------|
| `orchestrator.py` | `SBSOrchestrator` | Master coordinator |
| `ingestion/schema.py` | `RawMessage` | Pydantic message DTO |
| `ingestion/logger.py` | `ConversationLogger` | JSONL+SQLite message log |
| `processing/realtime.py` | `RealtimeProcessor` | Sentiment, language, mood per message |
| `processing/batch.py` | `BatchProcessor` | Distill into 8 profile layers |
| `processing/selectors/exemplar.py` | `ExemplarSelector` | Few-shot example selection |
| `injection/compiler.py` | `PromptCompiler` | Profile -> ~1500-token prompt segment |
| `profile/manager.py` | `ProfileManager` | Load/save 8 JSON profile layers |
| `feedback/implicit.py` | `ImplicitFeedbackDetector` | Regex-based correction detection |
| `sentinel/gateway.py` | `Sentinel` | Fail-closed file access control |
| `sentinel/manifest.py` | `ProtectionLevel` | CRITICAL/PROTECTED/MONITORED/OPEN zones |
| `sentinel/audit.py` | `AuditLogger` | JSONL access trail |
| `vacuum.py` | — | SBS data compaction |

Profile layers: core_identity, linguistic, emotional_state, domain, interaction, vocabulary, exemplars, meta

### Skills (workspace/skills/)
| File | Purpose |
|------|---------|
| `llm_router.py` | `LLMRouter` — Ollama/litellm routing |
| `google_native.py` | `GoogleNative` — Gmail, Calendar, direct Google API |
| `language/ingest_dict.py` | Vocabulary ingestion |
| `memory/ingest_memories.py` | Bulk memory import to API |

### CLI (workspace/cli/)
| File | Purpose |
|------|---------|
| `onboard.py` | Interactive setup wizard (questionary+typer) |
| `channel_steps.py` | WhatsApp QR, Discord/Slack/Telegram setup |
| `provider_steps.py` | LLM provider validation |

## Architecture

### Request Flow
```
WhatsApp -> POST /whatsapp/enqueue -> FloodGate(3s) -> Dedup(5min) -> TaskQueue(max100) -> Worker x2 -> SBS+RAG+DualCognition -> LLM -> Send
```

### LLM Routing
- Default/Banglish: Gemini Flash
- Code: Claude Sonnet (thinking)
- Deep analysis: Gemini Pro
- Private (The Vault): Local Ollama — air-gapped spicy hemisphere
- Fallback: OpenRouter

### Security (DM Access Control)
Per-channel DM policy via `DmPolicy` enum (`pairing` | `allowlist` | `open` | `disabled`).
- `ChannelSecurityConfig` — dataclass with policy + allow-from lists
- `PairingStore` — JSONL-backed approved-senders at `~/.synapse/state/pairing/<channel_id>.jsonl`
- `resolve_dm_access()` — pure function returning `"allow"` / `"deny"` / `"pending_approval"`
- Source: `sci_fi_dashboard/channels/security.py`

### Media Pipeline
Inbound media handling via `sci_fi_dashboard/media/`:
- MIME detection: `python-magic` (magic bytes) > HTTP header > extension > `application/octet-stream`
- Size limits: image 6 MB, audio/video 16 MB, document 100 MB
- TTL cleanup: default 120s, storage at `~/.synapse/state/media/`
- SSRF guard: `is_ssrf_blocked()` rejects private/loopback IPs before fetch

### WebSocket Gateway
- Endpoint: `ws://127.0.0.1:8000/ws`
- Auth: `SYNAPSE_GATEWAY_TOKEN` env var (optional)
- Protocol: connect-first handshake, JSON frames (req/res/event)
- Methods: `chat.send`, `channels.status`, `models.list`, `sessions.list`, `sessions.reset`
- Heartbeat: tick event every 30s

### Memory (Hybrid RAG)
DBs in `~/.synapse/workspace/db/`:
1. `memory.db` — documents + sqlite-vec embeddings (WAL mode)
2. `knowledge_graph.db` — subject-predicate-object triples

Retrieval: embed(Ollama nomic-embed-text) -> ANN+FTS -> FlashRank rerank -> inject into prompt
Dual hemispheres: `hemisphere_tag = "safe"|"spicy"`. Vault uses spicy only.

### Key Singletons (init in api_gateway.py)
Brain, memory_engine, dual_cognition, sqlite_graph, sbs_orchestrator, task_queue, message_worker

### Ports
API:8000 | Tools:8989 | Qdrant:6333 | Ollama:11434 | OAuth:8080 | WS:18789

### Environment
Key env vars: `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `WHATSAPP_BRIDGE_TOKEN`, `SYNAPSE_GATEWAY_TOKEN` (optional WebSocket gateway auth token)

#### `synapse.json` — `session` block schema
The optional `session` top-level key controls per-user session scoping and identity linking:
```json
{
  "session": {
    "dmScope": "per-channel-peer",
    "identityLinks": {
      "alice": ["919876543210", "telegram:123456789"]
    }
  }
}
```
- `dmScope` — one of `"main"` (default), `"per-peer"`, `"per-channel-peer"`, `"per-account-channel-peer"`
- `identityLinks` — maps a canonical name to a list of raw peer IDs (bare or `channel:id` prefixed); the same person across channels resolves to one session key

## Dependencies (what breaks if you edit...)

### High-Impact Files (edit carefully)
- `synapse_config.py` -> imported by 50+ files (root config)
- `api_gateway.py` -> central hub, imports everything
- `db.py` -> all memory/vector operations funnel through here
- `memory_engine.py` -> RAG pipeline, affects search quality

### Isolated Modules (safe to edit independently)
- `dual_cognition.py` — no internal imports
- `gateway/flood.py`, `dedup.py`, `queue.py` — self-contained
- `channels/*.py` — loosely coupled via BaseChannel ABC
- `sbs/profile/manager.py` — standalone JSON CRUD
- `narrative.py`, `conflict_resolver.py` — minimal deps

### Symbol Lookup
Use `grep "^SYMBOL_NAME\t" tags` to find any class/function/variable definition instantly.
The `tags` file indexes 1215 symbols across all Python files.

## Code Style
Python 3.11 | line-length 100 | ruff + black | asyncio (no Redis/Celery) | SQLite WAL mode
