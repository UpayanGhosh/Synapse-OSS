# Synapse-OSS Architecture (v2.0)

> How a message travels from the user's phone to a personalized AI reply — and what happens in the background to make that reply better over time.

## Diagram 1: Message Lifecycle (User sends -> receives reply)

```
 USER (WhatsApp / Telegram / Discord / Slack)
  |
  v
 ┌─────────────────────────────────────────────────────────┐
 │  CHANNEL LAYER                                          │
 │  BaseChannel subclass receives raw message               │
 │  -> Normalizes to ChannelMessage DTO                     │
 │  -> ChannelRegistry.dispatch()                           │
 └──────────────────────┬──────────────────────────────────┘
                        |
                        v
 ┌─────────────────────────────────────────────────────────┐
 │  FLOOD GATE (3-second batching window)                  │
 │  Collects rapid-fire messages into a single batch        │
 │  -> MessageDeduplicator (5-min TTL, drops duplicates)    │
 └──────────────────────┬──────────────────────────────────┘
                        |
                        v
 ┌─────────────────────────────────────────────────────────┐
 │  TASK QUEUE (asyncio FIFO, max 100, 2 workers)         │
 │  Enqueues as MessageTask -> returns 202 Accepted         │
 │  MessageWorker picks it up                               │
 └──────────────────────┬──────────────────────────────────┘
                        |
                        v
 ┌─────────────────────────────────────────────────────────┐
 │  persona_chat() — THE BRAIN                             │
 │                                                          │
 │  1. MEMORY RETRIEVAL                                     │
 │     MemoryEngine.query()                                 │
 │     -> FastEmbed (ONNX) embeds the query                 │
 │     -> LanceDB ANN + SQLite FTS hybrid search            │
 │     -> FlashRank reranker (skipped if score > 0.80)      │
 │     -> SQLiteGraph context (related triples)             │
 │     Result: memory_context string                        │
 │                                                          │
 │  2. DUAL COGNITION (if enabled, 5s timeout)              │
 │     DualCognitionEngine.think()                          │
 │     -> Inner monologue generation                        │
 │     -> Tension score (0.0-1.0) between memory & message  │
 │     -> CognitiveMerge: response_strategy + emotional map │
 │     (receives pre_cached_memory — NO double query)       │
 │                                                          │
 │  3. SBS PERSONA PROMPT                                   │
 │     SBSOrchestrator.get_system_prompt()                  │
 │     -> 8-layer behavioral profile (~2KB)                 │
 │     -> Situational awareness (day, time, gap)            │
 │     -> Proactive context (if any scheduled nudges)       │
 │                                                          │
 │  4. TRAFFIC COP (intent classification)                  │
 │     -> If CognitiveMerge has a strategy: SKIP LLM call   │
 │        Maps strategy -> role directly                    │
 │     -> Otherwise: LLM classifies as                      │
 │        CASUAL / CODING / ANALYSIS / REVIEW / SPICY       │
 │                                                          │
 │  5. LLM ROUTING (Mixture of Agents)                      │
 │     SynapseLLMRouter (litellm.Router)                    │
 │     ┌────────────────────────────────────┐               │
 │     │ casual  -> Gemini Flash            │               │
 │     │ code    -> Claude Sonnet           │               │
 │     │ analysis-> Gemini Pro              │               │
 │     │ vault   -> Local Ollama (optional) │               │
 │     │ review  -> configurable            │               │
 │     └────────────────────────────────────┘               │
 │     All models from synapse.json -> model_mappings       │
 │     Each role has optional fallback model                 │
 │                                                          │
 │  6. REPLY ASSEMBLED                                      │
 │     -> SBS logs assistant response                       │
 │     -> ImplicitFeedbackDetector scans for corrections    │
 └──────────────────────┬──────────────────────────────────┘
                        |
                        v
 ┌─────────────────────────────────────────────────────────┐
 │  CHANNEL DELIVERY                                       │
 │  registry.get(channel_id).send(reply)                    │
 │  -> If no terminal punctuation: Auto-Continue fires      │
 │     (BackgroundTask requests continuation, sends 2nd msg)│
 └──────────────────────┬──────────────────────────────────┘
                        |
                        v
                   USER RECEIVES REPLY
```

**Key timing**: FloodGate batching (3s) + Memory retrieval (<350ms P95) + Dual Cognition (2-5s, skippable) + LLM call (1-3s) = **~4-10 seconds end-to-end**

---

## API Gateway: orchestrator + routes/ package

`api_gateway.py` is **no longer a monolith**. After the routes/ refactor it is a
~600-line orchestrator that wires FastAPI lifespan hooks, initializes singletons
in `_deps`, mounts middleware, and `include_router()`s a set of focused router
modules under `sci_fi_dashboard/routes/`. The chat pipeline itself lives in
`chat_pipeline.py` (`persona_chat`); the gateway no longer owns that logic.

See [Multiuser layer](docs/multiuser.md) for per-user keying — sessions, agent
registries, and SBS personas are scoped per agent_id via the `multiuser/`
subsystem rather than living in a single global store.

### Route modules (FastAPI APIRouter)

Each module under `workspace/sci_fi_dashboard/routes/` exports a single
`router = APIRouter()`. Path prefixes are declared inline per-route (no
constructor `prefix=`); the column below lists the dominant prefix(es) each
module owns.

| File | Path prefix | Purpose |
|------|-------------|---------|
| `routes/health.py` | `/`, `/health`, `/gateway/status`, `/memory_health` | Liveness + ingestion-health probes; root status. |
| `routes/chat.py` | `/chat`, `/v1/chat/completions` | Async chat webhook + OpenAI-compatible completions endpoint. |
| `routes/whatsapp.py` | `/channels/{channel_id}/webhook`, `/channels/whatsapp/*`, `/whatsapp/*`, `/qr` | Unified channel webhook plus WhatsApp/Baileys lifecycle (QR, status, logout, relink, retry queue, jobs). |
| `routes/persona.py` | `/persona/*`, `/sbs/status` | SBS persona rebuild + profile/status inspection. |
| `routes/knowledge.py` | `/ingest`, `/add`, `/query` | Knowledge graph fact ingest, memory add, hybrid RAG query. |
| `routes/sessions.py` | `/api/sessions` | Per-agent SessionStore listing + management (multiuser-aware). |
| `routes/websocket.py` | `/ws` | WebSocket gateway entry point (chat.send, channels.status, etc.). |
| `routes/pipeline.py` | `/pipeline/events`, `/pipeline/state`, `/pipeline/send` | SSE stream + JSON snapshot for the live pipeline visualizer dashboard. |
| `routes/agents.py` | `/api/agents`, `/api/agents/{agent_id}` | SubAgent registry: list, detail, cancel. |
| `routes/cron.py` | `/api/cron/jobs`, `/api/cron/jobs/{job_id}/run` | CronService inspection and manual job triggering. |
| `routes/snapshots.py` | `/snapshots` | Zone 2 snapshot listing (rollback metadata). |
| `routes/skills.py` | `/skills` | Skill registry inventory (loaded skills + metadata). |

> **Wiring note:** `agents`, `chat`, `cron`, `health`, `knowledge`, `persona`,
> `pipeline`, `sessions`, `websocket`, `whatsapp` are mounted via
> `app.include_router(...)` in `api_gateway.py`. `snapshots` and `skills` ship
> as routers but are not yet wired into the main app — flip them on by adding
> the corresponding `include_router` call.

---

## Diagram 2: Background Tasks (Memory, KG, Maintenance)

```
 ┌─────────────────────────────────────────────────────────────┐
 │                    BACKGROUND TASK SYSTEM                    │
 │         (Never blocks chat pipeline — all async)            │
 └─────────────────────────────────────────────────────────────┘

 ═══════════════════════════════════════════════════════════════
  TRIGGER: Every message processed by persona_chat()
 ═══════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────┐
  │  SBS REALTIME PROCESSOR              │
  │  Fires EVERY message                 │
  │  -> Sentiment analysis               │
  │  -> Vocabulary tracking              │
  │  -> Linguistic pattern detection     │
  │  -> ImplicitFeedbackDetector         │
  │     ("too long" -> adjusts profile)  │
  └──────────────────────────────────────┘

 ═══════════════════════════════════════════════════════════════
  TRIGGER: /new command (session reset)
 ═══════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────────────────────────┐
  │  SESSION INGEST (session_ingest.py)                      │
  │  asyncio.create_task() — runs after /new                 │
  │                                                          │
  │  Archived transcript -> batches of 5 turns each:         │
  │                                                          │
  │  For each batch:                                         │
  │    ┌────────────────────┐  ┌─────────────────────────┐   │
  │    │ VECTOR INGESTION   │  │ KG EXTRACTION           │   │
  │    │ MemoryEngine       │  │ ConvKGExtractor         │   │
  │    │ .add_memory()      │  │ .extract() via LLM      │   │
  │    │ -> FastEmbed encode │  │ -> Validated triples    │   │
  │    │ -> LanceDB insert  │  │ -> Anti-hallucination    │   │
  │    │ -> sqlite-vec write│  │    (grounded in text)   │   │
  │    └────────────────────┘  └──────────┬──────────────┘   │
  │                                        |                  │
  │                               ┌────────v────────┐        │
  │                               │ TRIPLE WRITES   │        │
  │                               │ SQLiteGraph     │        │
  │                               │ .add_relation() │        │
  │                               │ + entity_links  │        │
  │                               │   in memory.db  │        │
  │                               └─────────────────┘        │
  │                                                          │
  │  Sleep 1s between batches (rate-limit safety)            │
  └──────────────────────────────────────────────────────────┘

 ═══════════════════════════════════════════════════════════════
  TRIGGER: Every 50 messages OR 6 hours idle
 ═══════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────┐
  │  SBS BATCH PROCESSOR                 │
  │  -> Distills 8 profile layers        │
  │     from accumulated message data    │
  │  -> Rebuilds the ~2KB behavioral     │
  │     profile used in system prompts   │
  │  -> Archives old profile version     │
  └──────────────────────────────────────┘

 ═══════════════════════════════════════════════════════════════
  TRIGGER: GentleWorker (only when CPU < 20% AND plugged in)
 ═══════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────┐
  │  GENTLE WORKER LOOP                  │
  │                                      │
  │  Every 10 min:                       │
  │    -> Prune stale KG triples         │
  │       (removes expired/low-conf)     │
  │                                      │
  │  Every 30 min:                       │
  │    -> VACUUM memory.db               │
  │    -> VACUUM knowledge_graph.db      │
  │                                      │
  │  Thermal-aware: skips if hot/battery │
  └──────────────────────────────────────┘

 ═══════════════════════════════════════════════════════════════
  TRIGGER: CronService (scheduled jobs from synapse.json)
 ═══════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────┐
  │  CRON SERVICE (optional)             │
  │  Reads <data_root>/cron/jobs.json    │
  │                                      │
  │  -> Proactive check-ins              │
  │  -> Scheduled persona_chat() calls   │
  │  -> Uses system local timezone       │
  │  -> Disabled by default              │
  │     (user opts in per job)           │
  └──────────────────────────────────────┘

 ═══════════════════════════════════════════════════════════════
  DATA STORES (where everything lands)
 ═══════════════════════════════════════════════════════════════

  ~/.synapse/workspace/db/
  ├── memory.db          SQLite + sqlite-vec (documents, embeddings, entity_links)
  ├── knowledge_graph.db SQLiteGraph (subject-predicate-object triples)
  └── lancedb/           LanceDB tables (high-speed ANN vector search)

  ~/.synapse/workspace/sci_fi_dashboard/synapse_data/
  └── sbs_<persona>/profiles/   8 JSON layers per persona
```

---

## Plain English Summary

### Message flow
User sends message -> channel normalizes it -> FloodGate batches rapid messages -> dedup filter -> async queue -> persona_chat() does memory lookup + thinking + persona assembly + model routing -> reply sent back through the channel.

### Background tasks
After each session reset (`/new`), the archived conversation gets ingested into vector memory AND the knowledge graph in batches. SBS updates the persona profile in realtime (every message) and in batch (every 50 messages). A gentle background worker vacuums databases and prunes stale data, but only when the system isn't busy.

### Dependencies (v2.0)
- **Required**: Python 3.11, FastEmbed (ONNX embeddings), LanceDB, SQLite
- **Optional**: Ollama (local LLM models), any cloud provider API key (Gemini, Claude, OpenRouter, Groq)
- **Zero Docker. Zero external services required.**
