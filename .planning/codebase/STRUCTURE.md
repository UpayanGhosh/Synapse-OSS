# Codebase Structure

**Analysis Date:** 2026-02-27

## Directory Layout

```
workspace/
├── sci_fi_dashboard/           # Core Synapse AI system
│   ├── api_gateway.py         # FastAPI gateway + singleton initialization
│   ├── memory_engine.py       # RAG orchestrator
│   ├── retriever.py           # Vector/FTS query execution
│   ├── sqlite_graph.py        # Knowledge graph (SQLite-backed)
│   ├── db.py                  # Database connection management
│   ├── dual_cognition.py      # Dual-stream analysis + tension scoring
│   ├── toxic_scorer_lazy.py   # Lazy Toxic-BERT with 30s auto-unload
│   ├── emotional_trajectory.py # Sentiment tracking over time
│   ├── smart_entity.py        # FlashText-based entity extraction
│   ├── conflict_resolver.py   # Detects/resolves contradictions
│   ├── gateway/               # Message pipeline components
│   │   ├── flood.py          # 3-second message batching
│   │   ├── dedup.py          # 5-min TTL duplicate detection
│   │   ├── queue.py          # Async FIFO task queue
│   │   ├── worker.py         # Concurrent message processor (×2)
│   │   └── sender.py         # OpenClaw CLI message dispatch
│   ├── sbs/                  # Soul-Brain Sync persona engine
│   │   ├── orchestrator.py   # SBS controller + message router
│   │   ├── ingestion/        # Conversation logging
│   │   │   ├── logger.py    # JSONL conversation logger
│   │   │   └── schema.py    # RawMessage dataclass
│   │   ├── processing/       # Real-time + batch profile evolution
│   │   │   ├── realtime.py  # Per-message sentiment/language (<50ms)
│   │   │   ├── batch.py     # 50-msg/6-hr batch distillation
│   │   │   └── selectors/   # Exemplar selection logic
│   │   ├── injection/        # Persona prompt compilation
│   │   │   └── compiler.py  # 8-layer profile → system prompt (~1500 tokens)
│   │   ├── profile/          # Profile storage
│   │   │   └── manager.py   # Load/save JSON profile layers
│   │   ├── feedback/         # Implicit user corrections
│   │   │   └── implicit.py  # Regex-based formality/length/language detection
│   │   ├── sentinel/         # File governance
│   │   │   ├── manifest.py  # CRITICAL_FILES, PROTECTED_FILES, WRITABLE_ZONES
│   │   │   ├── gateway.py   # Permission checks + integrity verification
│   │   │   ├── audit.py     # JSONL append-only audit log
│   │   │   └── tools.py     # Wrapped read/write/delete operations
│   │   └── vacuum.py         # Profile compaction + pruning
│   ├── synapse_data/         # Generated persona profiles (8 JSON layers per persona)
│   ├── entities.json         # FlashText entity mappings
│   ├── conflicts.json        # Contradiction database
│   └── (other utilities)
├── db/                        # Database tools + utilities
│   ├── tools.py             # ToolRegistry (Crawl4AI web browser)
│   ├── audio_processor.py   # Groq Whisper transcription
│   ├── ingest.py            # Bulk file ingestion pipeline
│   ├── model_orchestrator.py # 3-tier local model routing via Ollama
│   └── __init__.py
├── gateway/                   # (Legacy? See sci_fi_dashboard/gateway/)
├── tests/                     # Pytest suite
│   ├── conftest.py          # Fixtures + marks (unit/integration/smoke/performance)
│   ├── test_queue.py        # MessageTask + TaskQueue lifecycle
│   ├── test_flood.py        # FloodGate batching behavior
│   ├── test_dedup.py        # Deduplicator TTL cache
│   ├── test_sqlite_graph.py # Knowledge graph queries
│   ├── test_integration.py  # End-to-end gateway flow
│   ├── test_e2e.py          # Webhook → response full cycle
│   ├── test_smoke.py        # Startup checks
│   ├── test_performance.py  # Latency + throughput benchmarks
│   └── (other test modules)
├── scripts/                  # Maintenance utilities
│   ├── db_cleanup.py        # Vacuum + defrag
│   ├── optimize_db.py       # Index rebuild
│   ├── prune_sessions.py    # Session pruning
│   ├── v2_migration/        # Qdrant → SQLite migration tools
│   │   ├── migrate_vectors.py
│   │   ├── qdrant_handler.py
│   │   └── graph_handler.py
│   └── revive_jarvis.sh     # Full system resurrection
├── skills/                   # Pluggable skill modules (optional)
│   ├── gog/                 # Game of Games integration
│   ├── language/            # Dictionary/vocabulary ingestion
│   └── memory/              # Bulk memory import
├── utils/                    # Shared utilities
│   ├── env_loader.py        # .env resolution + loading
│   └── __init__.py
├── main.py                   # CLI entry point (chat/ingest/vacuum/verify)
├── monitor.py               # System health dashboard
├── config.py                # Configuration constants
├── change_tracker.py        # Git-based change detection
└── purge_trash.py           # Cleanup utility
```

## Directory Purposes

**sci_fi_dashboard/:**
- Purpose: Core conversational AI system; all message processing, memory, and persona logic
- Contains: Python modules for gateway, cognition, memory, SBS, and file governance
- Key files: `api_gateway.py` (1,200 lines), `memory_engine.py`, `dual_cognition.py`

**gateway/ (inside sci_fi_dashboard):**
- Purpose: Async message pipeline components
- Contains: FloodGate (batching), MessageDeduplicator (5-min cache), TaskQueue (FIFO), MessageWorker (processor), WhatsAppSender (CLI dispatch)
- Key files: `worker.py`, `queue.py`

**sbs/ (inside sci_fi_dashboard):**
- Purpose: Persona evolution engine with real-time + batch processing
- Contains: Orchestrator, real-time/batch processors, feedback detector, prompt compiler, profile manager, file governance, vacuum
- Key files: `orchestrator.py`, `injection/compiler.py`, `processing/realtime.py`

**db/:**
- Purpose: Database tools and external service integrations
- Contains: Web crawler (Crawl4AI), voice transcription (Groq Whisper), bulk ingest, local model routing
- Key files: `tools.py`, `audio_processor.py`, `ingest.py`

**tests/:**
- Purpose: Pytest-based test suite with markers (unit/integration/smoke/performance)
- Contains: Gateway tests, database tests, end-to-end tests, benchmarks
- Key files: `conftest.py`, `test_queue.py`, `test_integration.py`

**scripts/:**
- Purpose: Maintenance and migration utilities
- Contains: Database cleanup, optimization, session pruning, Qdrant→SQLite migration tools
- Key files: `db_cleanup.py`, `v2_migration/migrate_vectors.py`

**utils/:**
- Purpose: Shared utilities
- Contains: Environment file loading and resolution
- Key files: `env_loader.py`

## Key File Locations

**Entry Points:**
- `workspace/sci_fi_dashboard/api_gateway.py` — FastAPI gateway server (port 8000), all singletons initialized here
- `workspace/main.py` — CLI interface for chat/ingest/vacuum/verify commands

**Configuration:**
- `workspace/config.py` — Constants (paths, model names, API endpoints)
- `.env` — Environment variables (GEMINI_API_KEY, OPENROUTER_API_KEY, WHATSAPP_BRIDGE_TOKEN, etc.)
- `.env.example` — Template for required env vars

**Core Logic:**
- `workspace/sci_fi_dashboard/memory_engine.py` — Hybrid RAG orchestrator
- `workspace/sci_fi_dashboard/dual_cognition.py` — Message analysis + memory merge
- `workspace/sci_fi_dashboard/sbs/orchestrator.py` — Persona orchestrator
- `workspace/sci_fi_dashboard/sqlite_graph.py` — Knowledge graph implementation
- `workspace/sci_fi_dashboard/gateway/worker.py` — Message processing worker

**Memory/Data:**
- `~/.openclaw/workspace/db/memory.db` — Documents + embeddings (sqlite-vec, FTS5)
- `~/.openclaw/workspace/db/knowledge_graph.db` — Knowledge graph (nodes/edges)
- `workspace/sci_fi_dashboard/synapse_data/` — Persona profiles (JSON layers)
- `workspace/sci_fi_dashboard/entities.json` — Entity name mappings
- `workspace/sci_fi_dashboard/conflicts.json` — Contradiction database

**Testing:**
- `workspace/tests/conftest.py` — Pytest configuration and shared fixtures
- `workspace/tests/test_queue.py` — Task queue lifecycle tests
- `workspace/tests/test_integration.py` — Gateway integration tests
- `workspace/tests/test_e2e.py` — Full webhook→response tests

## Naming Conventions

**Files:**
- Core modules: snake_case.py (`memory_engine.py`, `dual_cognition.py`)
- Tests: `test_<module>.py` (e.g., `test_queue.py`)
- Scripts: snake_case.py with clear purpose (`db_cleanup.py`, `prune_sessions.py`)

**Directories:**
- Package groups: lowercase descriptive names (`gateway`, `sbs`, `skills`, `tests`, `db`)
- Sub-packages within SBS: functional layer names (`processing`, `injection`, `ingestion`, `feedback`, `sentinel`)

**Functions:**
- Async functions: `async def <verb>_<noun>()` (e.g., `async def process_message()`, `async def _handle_task()`)
- Handlers: `<verb>_<noun>()` (e.g., `handle_task()`, `extract_entities()`)
- Internal utilities: Prefixed with `_` (e.g., `_init_embedder()`, `_wait_and_flush()`)

**Classes:**
- PascalCase for all classes (e.g., `DualCognitionEngine`, `MemoryEngine`, `TaskQueue`)
- Dataclasses for data models (e.g., `MessageTask`, `RawMessage`, `CognitiveMerge`)
- Singletons initialized in `api_gateway.py`: `brain`, `memory_engine`, `dual_cognition`, `task_queue`, `sbs_the_creator`, `sbs_the_partner`

**Variables:**
- Lazy-loaded singletons: snake_case (e.g., `toxic_scorer`, `emotional_trajectory`)
- Constants: UPPER_CASE (e.g., `EMBEDDING_MODEL`, `BATCH_THRESHOLD`, `MAX_TOKENS_ESTIMATE`)
- Private attributes: Prefixed with `_` (e.g., `_embedder`, `_ranker`, `_workers`)

## Where to Add New Code

**New Feature (Chat Processing Logic):**
- Primary code: `workspace/sci_fi_dashboard/` (new module or extend existing)
- Tests: `workspace/tests/test_<feature>.py` with `@pytest.mark.unit` or `@pytest.mark.integration`
- Example: Adding a new response strategy goes in `dual_cognition.py` or new file `response_strategy.py`

**New Component/Module:**
- Implementation: `workspace/sci_fi_dashboard/<component>/` directory (if multi-file) or `workspace/sci_fi_dashboard/<component>.py` (if single-file)
- Register in `api_gateway.py` as singleton if needed
- Example: New memory type would be in `memory_engine.py` or `workspace/sci_fi_dashboard/memory/<type>.py`

**Utilities:**
- Shared helpers: `workspace/utils/` for cross-cutting utilities
- Database tools: `workspace/db/` for integrations
- Scripts: `workspace/scripts/` for one-off maintenance tasks

**Persona/Profile Extensions:**
- Profile layers: Add JSON schema to `workspace/sci_fi_dashboard/sbs/profile/`
- Realtime processors: Extend `workspace/sci_fi_dashboard/sbs/processing/realtime.py`
- Batch processors: Extend `workspace/sci_fi_dashboard/sbs/processing/batch.py`
- Injection logic: Modify `workspace/sci_fi_dashboard/sbs/injection/compiler.py`

**Tests:**
- Fixtures: Add to `workspace/tests/conftest.py` if reusable across tests
- Test files: One per module under test (e.g., `test_memory_engine.py` for `memory_engine.py`)
- Marks: Use `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.smoke`, or `@pytest.mark.performance`

## Special Directories

**synapse_data/:**
- Purpose: Generated persona profile storage (8 JSON files per persona)
- Generated: Yes (by `SBSOrchestrator` batch processor)
- Committed: No (gitignored)
- Structure: `synapse_data/<persona_name>/core_identity.json`, `emotional_state.json`, etc.

**~/.openclaw/workspace/db/:**
- Purpose: SQLite databases (memory.db, knowledge_graph.db)
- Generated: Yes (auto-created on first boot)
- Committed: No (outside repo)
- Structure: Two WAL-mode databases with schema auto-created in `db.py::DatabaseManager._ensure_db()`

**workspace/scripts/v2_migration/:**
- Purpose: Qdrant vector database → SQLite migration tools
- Generated: No (checked in)
- Committed: Yes (but legacy, may not be active)
- Usage: Migration scripts for potential future Qdrant→SQLite transitions

**.env (root or workspace):**
- Purpose: Environment variable configuration
- Generated: No (user-created from .env.example)
- Committed: No (gitignored)
- Loaded by: `utils/env_loader.py::load_env_file()` on startup

**tests/.pytest_cache/:**
- Purpose: Pytest cache directory
- Generated: Yes (by pytest)
- Committed: No (gitignored)

---

*Structure analysis: 2026-02-27*
