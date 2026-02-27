# Architecture

**Analysis Date:** 2026-02-27

## Pattern Overview

**Overall:** Event-driven asynchronous gateway with layered reasoning (dual-cognition) and persona injection (Soul-Brain Sync).

**Key Characteristics:**
- WhatsApp message pipeline → async task queue → concurrent workers → specialized LLM routing
- Hybrid memory system (SQLite graph + vector embeddings + full-text search)
- Real-time and batch persona profile evolution with system prompt injection
- Sentinel-based fail-closed file governance with JSONL audit trail
- Latency-optimized with lazy-loading, fast-path bypasses, and generation-based superseding

## Layers

**Gateway Layer (Message Ingestion):**
- Purpose: Accepts WhatsApp events, batches rapid messages, deduplicates, and enqueues for processing
- Location: `workspace/sci_fi_dashboard/gateway/`
- Contains: `flood.py` (batching), `dedup.py` (5-min TTL deduplication), `queue.py` (async FIFO), `worker.py` (concurrent processor), `sender.py` (CLI output)
- Depends on: OpenClaw bridge, asyncio task management
- Used by: `api_gateway.py` webhook endpoint

**Cognition Layer (Dual-Stream Analysis):**
- Purpose: Analyzes message in real-time, retrieves memory context, detects contradictions, suggests tone before LLM call
- Location: `workspace/sci_fi_dashboard/dual_cognition.py`
- Contains: `DualCognitionEngine` class that merges present message stream with memory stream into `CognitiveMerge` dataclass
- Depends on: `MemoryEngine`, `SQLiteGraph`, `ToxicScorer`, `EmotionalTrajectory`
- Used by: Message worker's response generation

**Soul-Brain Sync (Persona Engine):**
- Purpose: Continuously profiles behavioral patterns and evolves persona across 8 layers (identity, linguistic, emotional, domain, interaction, vocabulary, exemplars, metadata)
- Location: `workspace/sci_fi_dashboard/sbs/`
- Contains:
  - `orchestrator.py` — Central SBS controller
  - `processing/realtime.py` — Per-message language/sentiment/mood detection (<50ms)
  - `processing/batch.py` — Batch distillation triggered at 50-message threshold or 6-hour window
  - `feedback/implicit.py` — Detects user corrections (formality, length, language switches) via regex patterns
  - `injection/compiler.py` — Compiles 8 profile layers into ~1500-token system prompt
  - `profile/manager.py` — Loads/saves JSON profile layers from `synapse_data/` directory
- Depends on: Conversation logger, profile manager
- Used by: Before each LLM call for prompt injection

**Memory Layer (Hybrid RAG):**
- Purpose: Stores documents with hemisphere tagging (safe/spicy), provides semantic + FTS retrieval with FlashRank reranking
- Location: `workspace/sci_fi_dashboard/memory_engine.py`, `workspace/sci_fi_dashboard/retriever.py`
- Contains:
  - `MemoryEngine` — Orchestrates embedding (Ollama/sentence-transformers), vector search (sqlite-vec), and reranking
  - `retriever.py` — Query execution with fallback modes (vector → FTS → no-op)
- Depends on: `db.py` (SQLite connection + WAL mode), Ollama embeddings, FlashRank, sqlite-vec extension
- Used by: Dual cognition and worker process for context injection

**Knowledge Graph Layer:**
- Purpose: Subject-predicate-object triple store for explicit facts, relationship networks, and contradiction tracking
- Location: `workspace/sci_fi_dashboard/sqlite_graph.py`
- Contains: `SQLiteGraph` class with tables `nodes` (entities) and `edges` (relations with weight/evidence)
- Depends on: SQLite with WAL mode, indexed queries
- Used by: Memory engine for entity neighborhood lookups, conflict resolver

**LLM Routing Layer:**
- Purpose: Intelligent model selection based on message complexity/intent and execution through OpenClaw proxy or direct Gemini API
- Location: `workspace/sci_fi_dashboard/api_gateway.py` functions: `call_gateway_model()`, `call_gemini_direct()`
- Contains: Model mapping (gemini-3-flash, gemini-3-pro-high), complexity classification, streaming support
- Depends on: OpenClaw OAuth proxy (port 8080) or GEMINI_API_KEY
- Used by: Worker process response generation

**File Governance Layer (Sentinel):**
- Purpose: Fail-closed file access control with integrity verification and audit logging
- Location: `workspace/sci_fi_dashboard/sbs/sentinel/`
- Contains:
  - `manifest.py` — Declares CRITICAL_FILES, PROTECTED_FILES, WRITABLE_ZONES, FORBIDDEN_OPERATIONS
  - `gateway.py` — Permission checks with integrity hash verification before read/write/delete
  - `audit.py` — JSONL append-only audit log of all file operations
  - `tools.py` — Wrapped file operations (read, write, delete) that respect governance
- Depends on: Manifest definition
- Used by: All code paths that touch the filesystem

## Data Flow

**WhatsApp Message Processing Pipeline:**

1. **Ingestion** — OpenClaw webhook → `POST /whatsapp/enqueue` in `api_gateway.py`
2. **Batching** — `FloodGate` holds message for 3-second window, re-batching on repeated messages
3. **Deduplication** — `MessageDeduplicator` checks 5-minute TTL cache for duplicate message IDs
4. **Enqueue** — `TaskQueue` accepts `MessageTask` with FIFO ordering (max 100 tasks)
5. **Worker Pull** — 2 concurrent `MessageWorker` instances dequeue and process
6. **Cognition** — `DualCognitionEngine` analyzes message for complexity (fast/standard/deep) and retrieves memory
7. **SBS Injection** — `SBSOrchestrator` logs message, runs realtime processing, compiles persona prompt
8. **LLM Routing** — Model selected by complexity + intent, called with injected persona
9. **Response Send** — OpenClaw CLI sends response in chunks, worker marks task complete/failed
10. **Generation Superseding** — If newer message arrives during processing, task marked superseded, response dropped

**State Management:**

- **Message State** — Progresses: QUEUED → PROCESSING → COMPLETED|FAILED|SUPERSEDED
- **Generation Tracking** — Per-chat generation counter increments for each task; prevents stale responses
- **Conversation State** — SBS maintains rolling `_unbatched_count`; triggers batch at 50 messages
- **Profile Evolution** — Realtime updates to volatile layers (emotional_state); batch updates at 50-msg/6-hr threshold

## Key Abstractions

**MessageTask:**
- Purpose: Atomic unit of work with task_id, chat_id, user_message, status, generation counter
- Examples: `workspace/sci_fi_dashboard/gateway/queue.py`
- Pattern: Dataclass with status enum; moved through queue lifecycle (QUEUED → PROCESSING → terminal state)

**MemoryEngine:**
- Purpose: Unified RAG interface hiding embedding model selection (Ollama/sentence-transformers), reranking, and fallback modes
- Examples: `workspace/sci_fi_dashboard/memory_engine.py`
- Pattern: Shared singleton initialized in `api_gateway.py`; caches embeddings with LRU; lazy-loads reranker on demand

**SBSOrchestrator:**
- Purpose: Orchestrates all persona evolution components; exposed via `sbs_the_creator` / `sbs_the_partner` singletons
- Examples: `workspace/sci_fi_dashboard/sbs/orchestrator.py`
- Pattern: Composite pattern wrapping logger, realtime processor, batch processor, feedback detector, compiler; triggered on `on_message()` call

**DualCognitionEngine:**
- Purpose: Merges present message stream with memory context; produces `CognitiveMerge` with tension scoring and suggested tone
- Examples: `workspace/sci_fi_dashboard/dual_cognition.py`
- Pattern: Strategy pattern for complexity classification (fast-path phrases, word count, linguistic cues); uses lazy toxic scorer

**SQLiteGraph:**
- Purpose: Memory-efficient knowledge graph replacing NetworkX (150MB → 1MB); uses WAL mode and indexed queries
- Examples: `workspace/sci_fi_dashboard/sqlite_graph.py`
- Pattern: Thin wrapper around SQLite with schema (nodes/edges tables); atomic transactions on write

**TaskQueue:**
- Purpose: Async-safe FIFO with max size enforcement, history retention, status tracking
- Examples: `workspace/sci_fi_dashboard/gateway/queue.py`
- Pattern: Wraps `asyncio.Queue`; maintains `_active_tasks` dict and `_task_history` list

## Entry Points

**API Gateway:**
- Location: `workspace/sci_fi_dashboard/api_gateway.py`
- Triggers: Launched via `uvicorn api_gateway:app --port 8000`
- Responsibilities: Boot all singletons (brain, memory, SBS, workers), mount routes (`/chat/*`, `/ingest`, `/query`, `/health`), start message worker loop

**CLI Main:**
- Location: `workspace/main.py`
- Triggers: `python main.py chat|ingest|vacuum|verify`
- Responsibilities: Interactive chat loop (spins up gateway in subprocess), knowledge graph ingestion, profile verification, memory cleanup

**WhatsApp Webhook:**
- Location: `api_gateway.py::POST /whatsapp/enqueue`
- Triggers: Incoming WhatsApp message via OpenClaw bridge
- Responsibilities: Extract metadata, enqueue task, return 200 OK immediately (async processing)

## Error Handling

**Strategy:** Multi-tier resilience with exponential backoff, fallback models, and silent superseding.

**Patterns:**

- **SQLite Lock Contention** — `with_retry` decorator with exponential backoff (0.5s, 1s, 2s) on `OperationalError`
- **Memory Retrieval Failure** — Falls back from vector search → FTS → empty results; logs warning but continues
- **LLM Unavailability** — Tries OpenClaw proxy → direct Gemini API; returns error message in response
- **Task Superseding** — Newer message for same chat increments generation; older-generation response silently dropped (no error)
- **Worker Crash** — Exception caught in worker loop; task marked FAILED; worker resumes on next iteration
- **Sentinel Violations** — Audit-logged; operation rejected with permission error before execution

## Cross-Cutting Concerns

**Logging:**
- Print-based logging with emoji indicators (✅ ⚠️ ❌ 🚀 🔄)
- Located in multiple modules; consolidated into `workspace/monitor.py` for system dashboard
- No centralized structured logging framework

**Validation:**
- Message validation in FloodGate (non-empty, metadata present)
- Entity extraction via FlashText in `smart_entity.py` before LLM context
- Hemisphere tag enforcement in retriever (safe/spicy queries isolated)

**Authentication:**
- OPENCLAW_GATEWAY_TOKEN for OAuth proxy validation
- GEMINI_API_KEY for direct API fallback
- File access gated through Sentinel manifest

**Concurrency:**
- `asyncio` for all I/O (message processing, LLM calls, database queries)
- `threading.Lock()` on reranker initialization (double-checked locking)
- SQLite WAL mode + PRAGMA synchronous=NORMAL for atomic writes
- Generation-based task superseding prevents race conditions on per-chat basis

---

*Architecture analysis: 2026-02-27*
