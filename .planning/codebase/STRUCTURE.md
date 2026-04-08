# Synapse-OSS Directory Structure

## Repository Root (`D:/Shreya/Synapse-OSS/`)

```
Synapse-OSS/
├── workspace/                  # All Python source code lives here
├── baileys-bridge/             # Node.js WhatsApp bridge (Baileys library)
├── .planning/                  # Planning docs (this file lives here)
│   ├── codebase/               # Codebase maps (ARCHITECTURE.md, STRUCTURE.md)
│   └── phases/                 # Phase-by-phase implementation plans
├── .claude/                    # Claude Code config + worktrees
├── .agents/                    # Agent skill definitions (SMS content skills)
├── content/                    # Content assets
├── mcp-handover/               # MCP server handover docs
├── synapse.json.example        # Example config (copy to synapse.json)
├── docker-compose.yml          # Docker Compose (alternative deployment)
├── Dockerfile                  # Container build
├── pyproject.toml              # Python project metadata (uv)
├── uv.lock                     # uv lockfile
├── requirements.txt            # Core requirements
├── requirements-channels.txt   # Channel adapter deps
├── requirements-dev.txt        # Dev/test deps
├── requirements-ml.txt         # ML deps (fastembed, flashrank, etc.)
├── requirements-optional.txt   # Optional feature deps
├── synapse_start.sh/.bat       # Start script (Mac/Linux / Windows)
├── synapse_stop.sh/.bat        # Stop script
├── synapse_restart.sh          # Restart helper
├── synapse_onboard.sh/.bat     # Onboarding wizard runner
├── synapse_health.sh           # Health check script
├── tags                        # ctags file (1215 symbols, for Symbol Lookup)
├── CLAUDE.md                   # Claude Code project instructions
├── README.md                   # Public project README
├── ARCHITECTURE.md             # High-level architecture overview (root-level)
├── CONTRIBUTING.md             # Contribution guidelines
├── DEPENDENCIES.md             # Dependency documentation
└── HOW_TO_RUN.md               # Run instructions
```

---

## `workspace/` — Python Package Root

```
workspace/
├── main.py                     # CLI entry point (chat | ingest | vacuum | verify)
├── synapse_config.py           # Root config — SynapseConfig frozen dataclass (imported by 50+ files)
├── synapse_cli.py              # Extended CLI (synapse_cli command)
├── config.py                   # Legacy config shim
├── personas.yaml               # Persona definitions (the_creator, the_partner, etc.)
├── personas.yaml.example       # Example personas config
├── monitor.py                  # System monitor
├── change_tracker.py           # File change tracking
├── change_viewer.py            # Change viewer UI
├── benchmark_gpu.py            # GPU benchmark script
├── gpu_verify.py               # GPU verification script
├── do_transcribe.py            # Manual transcription runner
├── finish_facts.py             # Fact finishing utility
├── purge_trash.py              # DB cleanup helper
├── scrape_threads.py           # Thread scraping utility
│
├── sci_fi_dashboard/           # Main application package (FastAPI + all logic)
├── cli/                        # CLI wizard and onboarding commands
├── config/                     # Layered config subsystem
├── db/                         # Database utility tools
├── scripts/                    # One-off maintenance and migration scripts
├── skills/                     # Skill definitions (Google native, LLM router)
├── tests/                      # All test files
└── utils/                      # Shared utilities
```

---

## `workspace/sci_fi_dashboard/` — Core Application Package

### Top-Level Modules

```
sci_fi_dashboard/
├── __init__.py
├── _deps.py                    # Singleton registry (ALL shared state lives here)
├── api_gateway.py              # FastAPI app, lifespan, route includes
├── chat_pipeline.py            # persona_chat() — core response generation pipeline
├── llm_wrappers.py             # LLM call helpers, route_traffic_cop(), STRATEGY_TO_ROLE
├── pipeline_helpers.py         # process_message_pipeline(), gentle_worker_loop(), continue_conversation()
├── pipeline_emitter.py         # Pipeline event emitter (observability hooks)
├── llm_router.py               # SynapseLLMRouter (litellm.Router wrapper), LLMResult, ToolCall
├── llm_wrappers.py             # Named LLM call functions (call_gemini_flash, call_ag_oracle, etc.)
├── memory_engine.py            # MemoryEngine — hybrid RAG (vector+FTS+rerank)
├── retriever.py                # RetrievalPipeline — embed → ANN → FTS → rerank
├── db.py                       # DatabaseManager — SQLite+sqlite-vec, WAL, schema lifecycle
├── sqlite_graph.py             # SQLiteGraph — knowledge graph (nodes/edges, S-P-O triples)
├── dual_cognition.py           # DualCognitionEngine — inner monologue + tension scoring
├── persona.py                  # PersonaManager — system prompt assembly
├── sbs_bootstrap.py            # SBS bootstrapper
├── build_persona.py            # Persona build utilities
├── schemas.py                  # Pydantic request/response models (ChatRequest, etc.)
├── middleware.py               # Auth, rate limiting, body size middleware
├── state.py                    # App state helpers
├── models_catalog.py           # ModelsCatalog — Ollama discovery, context window guard
├── toxic_scorer_lazy.py        # LazyToxicScorer — Toxic-BERT, auto-unloads after 30s idle
├── emotional_trajectory.py     # EmotionalTrajectory — 72h peak-end weighted emotional state
├── smart_entity.py             # EntityGate — named entity recognition
├── conflict_resolver.py        # ConflictManager — conflicting fact resolution
├── narrative.py                # Narrative coherence tracking
├── gentle_worker.py            # GentleWorker — thermal-aware background maintenance
├── cron_service.py             # CronService — scheduled proactive message delivery
├── proactive_engine.py         # ProactiveAwarenessEngine — background MCP polling
├── ingest.py                   # ingest_atomic() — memory ingestion pipeline
├── whatsapp_bridge.py          # WhatsApp bridge SQLite store helpers
├── channel_setup.py            # register_optional_channels() — Telegram/Discord/Slack registration
├── mcp_client.py               # SynapseMCPClient — connects external MCP servers
├── mcp_config.py               # load_mcp_config() — MCP configuration loader
├── auth_profiles.py            # Auth profile management (provider key rotation)
├── diary_engine.py             # Diary/journal engine
├── chat_parser.py              # Chat history parser (WhatsApp export format)
├── tool_registry.py            # ToolRegistry, SynapseTool ABC, register_builtin_tools()
├── tool_safety.py              # Tool policy pipeline, ToolHookRunner, ToolAuditLogger
├── tool_features.py            # Tool user-facing features (footer, model override, shortcuts)
├── conv_kg_extractor.py        # Background KG extraction from conversations
├── triple_extractor.py         # RDF triple extraction from text
├── migrate_graph.py            # Knowledge graph migration utilities
├── verify_dual_cognition.py    # Dual cognition verification script
├── verify_soul.py              # Soul profile verification script
├── auth_profiles.py            # Provider auth profile rotation
└── _deps.py                    # (see Singleton Registry)
```

### `routes/` — FastAPI Routers

```
sci_fi_dashboard/routes/
├── __init__.py
├── chat.py                     # POST /chat (async webhook), POST /chat/{persona_id} (sync)
│                               # POST /v1/chat/completions (OpenAI-compatible)
├── health.py                   # GET /health — system health endpoint
├── knowledge.py                # Knowledge base query/ingest endpoints
├── persona.py                  # Persona profile management endpoints
├── pipeline.py                 # Pipeline introspection and management
├── sessions.py                 # Session list/reset endpoints
├── websocket.py                # WebSocket endpoint registration
└── whatsapp.py                 # /channels/whatsapp/webhook — Baileys inbound
```

### `gateway/` — Message Pipeline Primitives

```
sci_fi_dashboard/gateway/
├── __init__.py
├── flood.py                    # FloodGate — 3s debounce batching per chat_id
├── dedup.py                    # MessageDeduplicator — 5-min TTL duplicate suppression
├── queue.py                    # TaskQueue (asyncio FIFO, max 100), MessageTask dataclass
├── worker.py                   # MessageWorker — pulls from TaskQueue, dispatches via ChannelRegistry
├── sender.py                   # WhatsAppSender (deprecated, kept for compat)
├── retry_queue.py              # RetryQueue — persistent outbound delivery retry for WhatsApp
├── session_actor.py            # SessionActorQueue — per-session ordered execution
├── ws_server.py                # GatewayWebSocket — WebSocket server (heartbeat, methods)
└── ws_protocol.py              # WebSocket message protocol definitions
```

### `channels/` — Channel Adapters

```
sci_fi_dashboard/channels/
├── __init__.py
├── base.py                     # BaseChannel ABC, ChannelMessage DTO, MsgContext DTO
├── registry.py                 # ChannelRegistry — adapter lifecycle management
├── whatsapp.py                 # WhatsAppChannel — Baileys Node.js bridge adapter
├── telegram.py                 # TelegramChannel — Telegram Bot API adapter
├── telegram_offset_store.py    # Telegram update offset persistence
├── discord_channel.py          # DiscordChannel — Discord gateway adapter
├── slack.py                    # SlackChannel — Slack Events API adapter
├── stub.py                     # StubChannel — test/demo channel (no-op)
├── security.py                 # DmPolicy, PairingStore, resolve_dm_access() — DM access control
├── thread_bindings.py          # Thread-to-channel binding persistence (Discord threads, etc.)
├── ids.py                      # resolve_channel_id() — canonical channel ID resolution
├── plugin.py                   # ChannelCapabilities — feature flags per channel
├── polling_watchdog.py         # Polling-based channel health watchdog
└── network_errors.py           # Network error classification helpers
```

### `sbs/` — Soul-Brain Sync Persona Engine

```
sci_fi_dashboard/sbs/
├── __init__.py
├── orchestrator.py             # SBSOrchestrator — top-level per-persona coordinator
├── vacuum.py                   # SBS data vacuum / cleanup
│
├── ingestion/                  # Message ingestion and logging
│   ├── __init__.py
│   ├── logger.py               # ConversationLogger — SQLite conversation store
│   └── schema.py               # RawMessage dataclass
│
├── processing/                 # Profile update processing
│   ├── __init__.py
│   ├── realtime.py             # RealtimeProcessor — immediate profile layer updates per message
│   ├── batch.py                # BatchProcessor — deep analysis every 50 msgs or 6h
│   └── selectors/
│       ├── __init__.py
│       └── exemplar.py         # ExemplarSelector — few-shot example pair selection
│
├── injection/                  # Prompt compilation
│   ├── __init__.py
│   └── compiler.py             # PromptCompiler — assembles persona segment from profile layers
│
├── profile/                    # Profile state management
│   ├── __init__.py
│   └── manager.py              # ProfileManager — 8-layer profile, versioning, snapshots
│
├── feedback/                   # Implicit feedback detection
│   ├── __init__.py
│   ├── implicit.py             # ImplicitFeedbackDetector — watches for correction signals
│   └── language_patterns.yaml  # Editable feedback patterns (no Python changes needed)
│
└── sentinel/                   # File governance system
    ├── __init__.py
    ├── tools.py                # init_sentinel(), agent_read_file(), agent_write_file()
    ├── gateway.py              # Sentinel gateway — request approval for file ops
    ├── audit.py                # Audit logging for file operations
    └── manifest.py             # File manifest management
```

### `embedding/` — Embedding Provider Abstraction

```
sci_fi_dashboard/embedding/
├── __init__.py                 # get_provider() — singleton access
├── base.py                     # EmbeddingProvider ABC (embed_query, embed_documents, info)
├── factory.py                  # create_provider() — cascade: FastEmbed > Ollama > error
├── fastembed_provider.py       # FastEmbedProvider — ONNX local inference (preferred)
├── ollama_provider.py          # OllamaProvider — nomic-embed-text via Ollama
├── gemini_provider.py          # GeminiAPIProvider — Google Gemini embeddings (Phase 5)
└── migrate.py                  # Embedding migration utilities
```

### `vector_store/` — Vector Store Abstraction

```
sci_fi_dashboard/vector_store/
├── __init__.py
├── base.py                     # VectorStore ABC
└── lancedb_store.py            # LanceDB embedded ANN store (~/.synapse/workspace/db/lancedb/)
```

### `multiuser/` — Multi-User Session Management

```
sci_fi_dashboard/multiuser/
├── __init__.py
├── session_key.py              # build_session_key(), parse_session_key() — pure functions
├── session_store.py            # Per-session conversation state persistence
├── identity_linker.py          # resolve_linked_peer_id() — cross-channel identity mapping
├── context_assembler.py        # Full context assembly for a session
├── conversation_cache.py       # In-memory conversation history cache
├── compaction.py               # Conversation history compaction/summarization
├── memory_manager.py           # Per-session memory isolation
├── transcript.py               # Transcript persistence and retrieval
└── tool_loop_detector.py       # Per-session tool loop detection
```

### `mcp_servers/` — Synapse-Exposed MCP Servers

```
sci_fi_dashboard/mcp_servers/
├── __init__.py
├── base.py                     # BaseMCPServer ABC
├── tools_server.py             # Port 8989: read_file, write_file (Sentinel-gated), web_search
├── memory_server.py            # Knowledge base query + fact ingest
├── synapse_server.py           # Chat pipeline, profile queries
├── browser_server.py           # Browser automation
├── conversation_server.py      # Conversation history access
├── execution_server.py         # Code execution
├── gmail_server.py             # Gmail integration
├── calendar_server.py          # Calendar integration
└── slack_server.py             # Slack integration
```

### `media/` — Media Processing Pipeline

```
sci_fi_dashboard/media/
├── __init__.py
├── constants.py                # Size limits: image 6MB / audio+video 16MB / doc 100MB
├── mime.py                     # MIME detection (magic bytes > header > extension)
├── fetch.py                    # Media fetch with SSRF guard
├── ssrf.py                     # SSRF guard — rejects private/loopback IPs
├── store.py                    # Temporary media store (120s TTL cleanup)
├── audio_preflight.py          # Audio pre-flight checks before transcription
├── chat_attachments.py         # Chat attachment handling
├── delivery_queue.py           # Outbound media delivery queue
└── outbound_attachment.py      # Outbound attachment processing
```

### `cron/` — Cron Job Subsystem

```
sci_fi_dashboard/cron/
├── __init__.py
├── types.py                    # CronJob dataclass, schedule types
├── store.py                    # Job store (JSON persistence)
├── schedule.py                 # Schedule parsing (every_Nh, every_day_at_HH:MM_IST, etc.)
├── service.py                  # CronService async runner
├── delivery.py                 # Job delivery logic (fire persona_chat, send to channel)
├── run_log.py                  # Execution run log
├── stagger.py                  # Stagger multiple jobs to avoid thundering herd
├── alerting.py                 # Alert on job failures
└── isolated_agent.py           # Isolated agent context for cron jobs
```

### `browser/` — Browser Automation

```
sci_fi_dashboard/browser/
├── __init__.py
├── session.py                  # BrowserSession management
├── interactions.py             # Click, type, scroll interactions
└── navigation_guard.py         # Navigation safety guard (SSRF-like for browser)
```

### `file_ops/` — File Operation Utilities

```
sci_fi_dashboard/file_ops/
├── __init__.py
├── edit.py                     # File edit operations
├── paging.py                   # Paginated file reading
└── workspace_guard.py          # Workspace boundary guard (prevent escaping workspace dir)
```

### `process/` — Process Management

```
sci_fi_dashboard/process/
├── __init__.py
└── kill_tree.py                # Process tree kill (clean subprocess termination)
```

---

## `workspace/cli/` — Onboarding Wizard

```
cli/
├── __init__.py
├── onboard.py                  # Main onboarding wizard orchestrator
├── wizard_prompter.py          # WizardPrompter — abstract prompt interface
├── inquirerpy_prompter.py      # InquirerPy-backed interactive prompts
├── channel_steps.py            # Channel configuration wizard steps
├── gateway_steps.py            # Gateway configuration steps
├── provider_steps.py           # LLM provider configuration steps
├── whatsapp_commands.py        # WhatsApp-specific CLI commands
├── workspace_seeding.py        # Initial workspace data seeding
├── daemon.py                   # Daemon process management
├── doctor.py                   # System diagnostics (synapse doctor)
└── health.py                   # Health check commands
```

---

## `workspace/config/` — Layered Config Subsystem

```
config/
├── __init__.py
├── schema.py                   # Pydantic config schema
├── layered_resolution.py       # Layered config resolution (base + overrides)
├── includes.py                 # Config file includes (import other config files)
├── env_substitution.py         # ${ENV_VAR} substitution in config values
├── merge_patch.py              # RFC 7396 JSON Merge Patch support
├── group_policy.py             # Group-level policy overrides
└── migration.py                # Config schema migration helpers
```

---

## `workspace/tests/` — Test Suite

```
tests/
├── conftest.py                 # Pytest fixtures and shared test setup
├── test_smoke.py               # Smoke tests
├── test_acceptance.py          # Acceptance tests
├── test_e2e.py                 # End-to-end tests
├── test_integration.py         # Integration tests
├── test_functional.py          # Functional tests
├── test_api_gateway.py         # API gateway tests
├── test_dual_cognition.py      # DualCognitionEngine tests
├── test_memory_engine.py       # MemoryEngine tests
├── test_llm_router.py          # LLM router tests
├── test_llm_router_gaps.py     # LLM router edge case tests
├── test_llm_router_tools.py    # Tool call path tests
├── test_flood.py               # FloodGate tests
├── test_dedup.py               # MessageDeduplicator tests
├── test_queue.py               # TaskQueue tests
├── test_gateway_worker.py      # MessageWorker tests
├── test_channels.py            # Channel adapter tests
├── test_channel_*.py           # Per-channel extended tests (wa, tg, discord, slack)
├── test_sbs.py                 # SBS orchestrator tests
├── test_sbs_*.py               # SBS subsystem tests (bootstrap, exemplar, sentinel, vacuum)
├── test_embedding_*.py         # Embedding provider tests (config, e2e, integration, deep)
├── test_mcp_*.py               # MCP server tests (per-server)
├── test_media_*.py             # Media pipeline tests
├── test_multiuser.py           # Multi-user session tests
├── test_config.py              # Config system tests
├── test_config_*.py            # Config subsystem tests (resolution, schema)
├── test_cron_*.py              # Cron service tests
└── test_*.py                   # All other module tests (100+ test files total)
```

Test markers: `unit`, `integration`, `smoke` (filter with `pytest -m <marker>`)

---

## `workspace/scripts/` — Maintenance & Migration Scripts

```
scripts/
├── genesis.py                  # Initial database bootstrap
├── migrate_to_lancedb.py       # Migrate vectors from sqlite-vec to LanceDB
├── migrate_openclaw.py         # Migrate from OpenClaw (predecessor system)
├── import_whatsapp.py          # Import WhatsApp chat export
├── memory_test.py              # Memory system test runner
├── fact_extractor.py           # Batch fact extraction
├── nightly_ingest.py           # Nightly scheduled ingestion
├── db_cleanup.py               # Database cleanup
├── db_organize.py              # Database organization / de-duplication
├── optimize_db.py              # SQLite VACUUM + ANALYZE
├── prune_sessions.py           # Prune old session records
├── sanitizer.py                # Data sanitization
├── seed_dummy_user.py          # Seed dummy user data for testing
├── setup_native_auth.py        # Google OAuth native setup
├── simulate_brain.py           # Brain simulation test
├── transcribe_v2.py            # Audio transcription v2
├── update_memory_schema.py     # Memory schema migration
├── latency_watcher.py          # LLM call latency monitoring
├── ram_watchdog.py             # RAM usage watchdog
├── debug_grep.py               # Debug grep helper
├── dsa_logger.py               # DSA (data structure and algorithm) logger
├── change_tracker.py           # File change tracking
└── sentinel.py                 # Sentinel CLI tool
```

---

## `baileys-bridge/` — Node.js WhatsApp Bridge

```
baileys-bridge/
├── index.js                    # Main bridge entry point (Baileys → HTTP)
├── package.json                # Node.js dependencies
└── ...                         # Auth state storage (auto-created by Baileys)
```

Listens on port 5010. Python sends outbound messages via HTTP. Bridge registers a webhook back to Python at `/channels/whatsapp/webhook` for inbound.

---

## Data Directories (Runtime, not in repo)

```
~/.synapse/                     # SYNAPSE_HOME (data root, set by SynapseConfig)
├── workspace/
│   ├── db/
│   │   ├── memory.db           # SQLite + sqlite-vec: documents, embeddings, atomic facts
│   │   ├── knowledge_graph.db  # SQLiteGraph: S-P-O triples
│   │   └── lancedb/            # LanceDB embedded ANN store
│   └── sbs/
│       ├── the_creator/        # Per-persona SBS data
│       │   ├── profiles/       # Profile layer snapshots (versioned)
│       │   └── conversations/  # Conversation SQLite log
│       └── the_partner/
├── cron/
│   └── jobs.json               # Cron job definitions
├── state/
│   └── pairing/                # DM pairing approvals (JSONL per channel)
└── audit/                      # Tool execution audit logs (JSONL)
```

---

## Naming Conventions

| Convention | Description |
|-----------|-------------|
| `_deps.py` | Underscore prefix = internal/private module |
| `test_<module>.py` | Test files mirror module name |
| `test_<module>_extended.py` | Extended/edge-case tests for a module |
| `test_<module>_gaps.py` | Tests targeting known coverage gaps |
| `*_server.py` in `mcp_servers/` | MCP server implementations |
| `*_channel.py` in `channels/` | Channel adapter implementations |
| `*_provider.py` in `embedding/` | Embedding backend implementations |
| `DB_PATH` constant | Module-level SQLite path (set at import from `SynapseConfig`) |
| `_get_db_path()` | Deferred path resolver (allows test monkeypatching of `SYNAPSE_HOME`) |
| `role` strings | Lowercase: `"casual"`, `"code"`, `"analysis"`, `"vault"`, `"review"`, `"kg"` |
| `hemisphere_tag` | `"safe"` or `"spicy"` (never `"private"` or other variants) |

---

## Module Organization Principles

1. **Singleton-in-`_deps.py`**: All shared stateful singletons live in `_deps.py`. Other modules import from there — no module creates its own instance of shared services.

2. **Optional imports with graceful fallback**: Phase 3-5 features (tool system, safety pipeline) use `try/except ImportError` at module level. The system continues running if these are missing.

3. **Route modules are thin**: `routes/*.py` contain only FastAPI router definitions. All business logic is delegated to `chat_pipeline.py`, `pipeline_helpers.py`, or domain-specific modules.

4. **`synapse_config.py` is wide-blast-radius**: 50+ files import it. It must remain a pure dataclass loader with no side effects at import time.

5. **Channels are pluggable**: New channels subclass `BaseChannel` and register with `ChannelRegistry`. No gateway code needs to know about specific channel types.

6. **Tests live flat**: All tests in `workspace/tests/` (flat, no subdirectories except `pipeline/`). Conftest provides fixtures.

7. **SBS is isolated per persona**: Each `SBSOrchestrator` instance in `sbs_registry` maintains its own `ProfileManager`, `ConversationLogger`, `PromptCompiler` — personas never share profile state.
