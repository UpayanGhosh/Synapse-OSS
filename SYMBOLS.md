# Symbol Quick Reference — Synapse-OSS

Use `grep "^SymbolName" tags` for exact line numbers. This file is for understanding what symbols do.

## Core Classes

### API & Config
- **SynapseConfig** (`synapse_config.py`) — Root config dataclass, loaded from synapse.json
- **DatabaseManager** (`sci_fi_dashboard/db.py`) — SQLite connection lifecycle, schema auto-creation, sqlite-vec extension
- **SynapseLLMRouter** (`sci_fi_dashboard/llm_router.py`) — litellm-based multi-provider LLM dispatch

### Memory & Retrieval
- **MemoryEngine** (`sci_fi_dashboard/memory_engine.py`) — `.search()`, `.inject_context()`, `.add_fact()`, `with_retry()` decorator
- **RetrievalPipeline** (`sci_fi_dashboard/retriever.py`) — `.search()` — embed + ANN + FTS + rerank
- **SQLiteGraph** (`sci_fi_dashboard/sqlite_graph.py`) — `.add_node()`, `.add_edge()`, `.get_neighbors()`, `.query()`

### Cognition
- **DualCognitionEngine** (`sci_fi_dashboard/dual_cognition.py`) — `.merge()` -> CognitiveMerge(thought, tension_level, tension_type, response_strategy, suggested_tone)
- **PresentStream** — dataclass: raw_message, sentiment, intent, topics, claims, emotional_state
- **MemoryStream** — dataclass: relevant_facts, relationship_context, contradictions
- **EmotionalTrajectory** (`emotional_trajectory.py`) — `.record()`, `.get_peak_end_summary()`
- **LazyToxicScorer** (`toxic_scorer_lazy.py`) — `.score()` — loads Toxic-BERT on demand, unloads after 30s

### Gateway Pipeline
- **FloodGate** (`gateway/flood.py`) — `.incoming()` — 3s batching window per user
- **MessageDeduplicator** (`gateway/dedup.py`) — `.is_duplicate()` — 5-min TTL cache
- **TaskQueue** (`gateway/queue.py`) — `.enqueue()`, `.dequeue()`, `.complete()`, `.fail()`, `.supersede()`
- **TaskStatus** — enum: QUEUED, PROCESSING, COMPLETED, FAILED, SUPERSEDED
- **MessageTask** — dataclass: task_id, chat_id, user_message, timestamp, status, response, error
- **MessageWorker** (`gateway/worker.py`) — `._worker_loop()`, `._get_channel()` — 2 concurrent workers

### Channels
- **BaseChannel** (`channels/base.py`) — ABC: `channel_id`, `receive()`, `send()`, `send_typing()`, `start()`, `stop()`
- **ChannelMessage** — dataclass: channel_id, user_id, chat_id, text, timestamp, is_group, message_id, sender_name, raw
- **ChannelRegistry** (`channels/registry.py`) — `.register()`, `.get()`, `.start_all()`, `.stop_all()`
- **WhatsAppChannel**, **TelegramChannel**, **DiscordChannel**, **SlackChannel**, **StubChannel**

### SBS (Soul-Brain Sync)
- **SBSOrchestrator** (`sbs/orchestrator.py`) — `.on_message()`, `.get_compiled_prompt()` — BATCH_THRESHOLD=50
- **RawMessage** (`sbs/ingestion/schema.py`) — Pydantic: msg_id, timestamp, role, content, sentiment, language, mood
- **ConversationLogger** (`sbs/ingestion/logger.py`) — `.log()`, `.fetch_range()` — dual JSONL+SQLite
- **RealtimeProcessor** (`sbs/processing/realtime.py`) — `.process()` — sentiment, mood, language detection
- **BatchProcessor** (`sbs/processing/batch.py`) — `.run()` — distills 8 profile layers
- **ExemplarSelector** (`sbs/processing/selectors/exemplar.py`) — `.select_exemplars()`
- **PromptCompiler** (`sbs/injection/compiler.py`) — `.compile()` — profile -> ~1500 token prompt
- **ProfileManager** (`sbs/profile/manager.py`) — `.load_layer()`, `.save_layer()`, `.load_full_profile()`, `.snapshot_version()`
- **ImplicitFeedbackDetector** (`sbs/feedback/implicit.py`) — `.detect()` — regex correction patterns
- **Sentinel** (`sbs/sentinel/gateway.py`) — file access permission enforcement
- **AuditLogger** (`sbs/sentinel/audit.py`) — JSONL access trail
- **ProtectionLevel** (`sbs/sentinel/manifest.py`) — enum: CRITICAL, PROTECTED, MONITORED, OPEN

### Skills & Tools
- **LLMRouter** (`skills/llm_router.py`) — `.generate()`, `.embed()` — Ollama/OpenClaw routing
- **GoogleNative** (`skills/google_native.py`) — `.authenticate()`, `.search_emails()`, `.get_calendar_events()`, `.send_email()`
- **ToolRegistry** (`db/tools.py`) — `.get_tool_schemas()`, `.search_web()` — Crawl4AI browser automation

## Key Constants
- `EMBEDDING_MODEL` = nomic-embed-text (Ollama), fallback: all-MiniLM-L6-v2
- `BATCH_THRESHOLD` = 50 messages (SBS batch trigger)
- `MAX_TOKENS_ESTIMATE` = 1500 (SBS prompt budget)
- FloodGate window = 3.0s, Dedup window = 300s (5 min)
- TaskQueue max = 100, MessageWorker count = 2
- Profile layers: core_identity, linguistic, emotional_state, domain, interaction, vocabulary, exemplars, meta

## Key External Packages
sqlite3, sqlite_vec, fastapi, litellm, ollama, flashrank, sentence-transformers, pydantic, httpx, rich, psutil, filelock, discord.py, slack_bolt, python-telegram-bot, questionary, typer
