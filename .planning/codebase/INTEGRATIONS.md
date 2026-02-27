# External Integrations

**Analysis Date:** 2026-02-27

## APIs & External Services

**Large Language Models:**
- **Google Gemini** - Primary LLM for conversational AI and reasoning
  - SDK/Client: Google Gemini API (via OpenClaw OAuth gateway or direct REST)
  - Auth: `GEMINI_API_KEY` env var
  - Models: `gemini-3-flash` (primary), `gemini-pro` (fallback)
  - Used in: `workspace/skills/llm_router.py`, `workspace/sci_fi_dashboard/api_gateway.py`

- **OpenRouter** - Fallback model routing and secondary LLM service
  - SDK/Client: OpenRouter HTTP API
  - Auth: `OPENROUTER_API_KEY` env var
  - Used in: `workspace/sci_fi_dashboard/api_gateway.py` (fallback route when Gemini fails)

- **OpenAI API** - Optional integration for specific tools and overrides
  - SDK/Client: `openai>=2.31.0` Python SDK
  - Auth: `OPENAI_API_KEY` env var
  - Used in: `workspace/db/model_orchestrator.py` (Ollama client via OpenAI SDK interface)

**Voice & Audio Transcription:**
- **Groq Whisper API** - Cloud-based audio transcription
  - SDK/Client: `groq>=0.4.0` Python SDK
  - Auth: `GROQ_API_KEY` env var
  - Model: `whisper-large-v3`
  - Latency: 2-4 seconds per audio message
  - Used in: `workspace/db/audio_processor.py` (transcribe voice messages to text)
  - Benefits: No local VRAM cost, instant results

**Web Browsing & Content Extraction:**
- **Crawl4AI** - Headless browser automation for web search and content extraction
  - SDK/Client: `crawl4ai>=0.2.0` Python async client
  - Feature: Extracts clean markdown from URLs
  - Setup command: `crawl4ai-setup` (downloads browser dependencies)
  - Used in: `workspace/db/tools.py` (ToolRegistry.search_web)
  - Purpose: Live internet search for weather, current news, factual data

**OpenClaw Gateway** - Optional WhatsApp bridge integration
  - Auth: `OPENCLAW_GATEWAY_TOKEN` env var (optional)
  - URL: `http://127.0.0.1:PORT/v1/messages` (configurable via `OPENCLAW_GATEWAY_URL`)
  - Purpose: Routes Gemini calls through OAuth-managed gateway
  - Leave blank to use Gemini API directly
  - CLI: `openclaw message send --channel whatsapp --target [phone] --message [text]`

## Data Storage

**Primary Databases:**

1. **SQLite Memory Database** (`memory.db`)
   - Location: `~/.openclaw/workspace/db/memory.db`
   - Purpose: Document store + vector embeddings + full-text search
   - Schema: `documents`, `vec_items` (vector virtual table), `documents_fts` (FTS5)
   - Client: `sqlite3` (built-in) + `sqlite-vec>=0.1.1` extension
   - Journaling: WAL mode enabled
   - Embeddings: 768-dimensional vectors from `nomic-embed-text`
   - Used in: `workspace/sci_fi_dashboard/db.py`, `workspace/sci_fi_dashboard/memory_engine.py`

2. **SQLite Knowledge Graph** (`knowledge_graph.db`)
   - Location: `~/.openclaw/workspace/db/knowledge_graph.db`
   - Purpose: Subject-predicate-object triples (RDF-like)
   - Schema: `nodes` (entities), `edges` (relationships)
   - Client: `sqlite3`
   - Journaling: WAL mode enabled
   - Used in: `workspace/sci_fi_dashboard/sqlite_graph.py` (replaces NetworkX)

**Vector Search (Optional Legacy):**
- **Qdrant** - Optional vector database for similarity search
  - Connection: `localhost:6333` (Docker container)
  - Client: `qdrant-client>=1.6.0`
  - Purpose: Hybrid search (being migrated to sqlite-vec)
  - Docker image: `qdrant/qdrant:latest`
  - Data volume: `qdrant_data`
  - Used in: `workspace/scripts/v2_migration/`, legacy retriever paths
  - Status: Can be disabled; new code uses sqlite-vec instead

**File Storage:**
- **Local filesystem only** - All data stored in `~/.openclaw/workspace/db/`
- Persistent session logs: `~/.openclaw/agents/main/sessions/` (JSONL format)
- Backup archive: `workspace/_archived_memories/persistent_log.jsonl`

**Caching:**
- **In-memory LRU cache** - Pydantic LRU cache for embeddings and model responses
- **FlashRank reranker cache** - Lazy-loaded, auto-unloaded after 30s idle
- **Redis**: Not used (memory-efficient design)

## Dual Hemispheres (Memory Segmentation)

Every document in `memory.db` has a `hemisphere_tag`:
- **"safe"** - Public/professional content (used for normal chat)
- **"spicy"** - Private/sensitive content (used by The Vault, local Ollama only)

Routing logic in `workspace/sci_fi_dashboard/retriever.py`:
- Normal sessions: Retrieve from `safe` hemisphere only
- Spicy sessions: Retrieve from both `safe` and `spicy` hemispheres

## Authentication & Identity

**Auth Provider:**
- **Custom via OpenClaw** - No OAuth/SSO; phone number + WhatsApp bridge authentication
- Implementation: Phone number stored in `ADMIN_PHONE` env var (E.164 format)
- VIP access: `VIP_PHONE` env var for elevated tool permissions
- Used in: `workspace/config.py`, `workspace/scripts/latency_watcher.py`

**Session Management:**
- Default session type: `SESSION_TYPE=safe` (env var)
- Session logs: JSONL files in `~/.openclaw/agents/main/sessions/`
- Session type override: Per-request via `/chat` endpoint

## Monitoring & Observability

**Error Tracking:**
- Not detected - Errors logged to console and temporary log files

**Logs:**
- Console output via Rich (colored terminal UI)
- Log files: `{TEMP_DIR}/openclaw/openclaw-*.log`
- Monitoring dashboard: `workspace/monitor.py` (real-time system metrics)
- Metrics collected: CPU %, memory, model inference latency, tool calls, token usage

**System Health:**
- `GET /health` endpoint in API Gateway (returns system status)
- Health checks: Service ports, database connectivity, model availability
- Used in: `workspace/sci_fi_dashboard/api_gateway.py`

## CI/CD & Deployment

**Hosting:**
- Docker + docker-compose (local development and containerized deployment)
- No cloud CI/CD detected
- Manual deployment via `synapse_start.sh` or `synapse_start.bat` scripts

**Local Services:**
- Ollama (11434) - Local LLM inference
- FastAPI Gateway (8000) - Main API
- Qdrant (6333) - Vector database (optional)
- OpenClaw (8080) - OAuth proxy (optional)

**Container Orchestration:**
- docker-compose.yml defines two services:
  - `synapse` - Python API Gateway (port 8000)
  - `qdrant` - Vector database (port 6333)

## Environment Configuration

**Required env vars:**
- `GEMINI_API_KEY` - Google Gemini API key (REQUIRED)
- `GROQ_API_KEY` - Groq Whisper transcription (REQUIRED for voice)
- `WHATSAPP_BRIDGE_TOKEN` - OpenClaw WhatsApp auth secret
- `ADMIN_PHONE` - Admin user phone number (E.164, e.g., +15551234567)

**Optional env vars:**
- `OPENROUTER_API_KEY` - Fallback model routing
- `OPENAI_API_KEY` - Custom OpenAI integration
- `OPENCLAW_GATEWAY_TOKEN` - OAuth gateway token (leave blank for direct API)
- `OPENCLAW_GATEWAY_URL` - Custom gateway URL (default: `http://127.0.0.1:PORT/v1/messages`)
- `WINDOWS_PC_IP` - Remote PC running Ollama (for distributed inference)
- `VIP_PHONE` - VIP user phone number (elevated access)
- `SESSION_TYPE` - Default session hemisphere (`safe` or `spicy`)
- `OLLAMA_KEEP_ALIVE` - Model eviction timeout (recommend: `0` for immediate unload)

**Secrets location:**
- `.env` file in project root (git-ignored)
- Copy from `.env.example` and fill in values
- Never commit `.env` to git

## Webhooks & Callbacks

**Incoming Webhooks:**
- `POST /whatsapp/enqueue` - WhatsApp message ingest from OpenClaw bridge
  - Payload: JSON with message text, phone number, timestamp
  - Processing: FloodGate (3s batching) → Deduplicator → TaskQueue

**Outgoing Webhooks/Callbacks:**
- `POST /whatsapp/send` via OpenClaw CLI - Asynchronous message sending
  - Command: `openclaw message send --channel whatsapp --target [phone] --message [text]`
  - Used in: `workspace/sci_fi_dashboard/api_gateway.py` (send_via_cli function)

## Model Orchestration

**Local Routing (Workspace/Skills):**
- Location: `workspace/skills/llm_router.py` (LLMRouter class)
- Primary route: OpenClaw local gateway (google-antigravity OAuth)
- Fallback: Local Ollama (llama3.2:3b)
- Safety settings: `BLOCK_NONE` (configurable via `LLM_SAFETY_LEVEL` env var)

**3-Tier Model Routing (workspace/db/model_orchestrator.py):**
- REFLEX tier: `llama3.2:3b` (instant banter, low latency)
- WORKER tier: `llama3.1:8b` (RAG, summaries, tools)
- ARCHITECT tier: `qwen2.5-coder:14b` (coding, logic, complex reasoning)
- Base URL: `http://{WINDOWS_PC_IP}:11434/v1` (via OpenAI SDK interface)

## Real-time Features

**Dual Cognition Engine:**
- Location: `workspace/sci_fi_dashboard/dual_cognition.py`
- Inner monologue before response generation
- Tension scoring (confidence vs uncertainty)
- Used in: Message processing pipeline

**Soul-Brain Sync (SBS) Persona Engine:**
- Location: `workspace/sci_fi_dashboard/sbs/`
- Real-time sentiment + language detection on every message
- Batch profile distillation (every 50 messages or 6 hours)
- 8 profile layers: core_identity, linguistic, emotional_state, domain, interaction, vocabulary, exemplars, meta
- Implicit feedback detection (formality, length, language switching)
- Stored in: `synapse_data/` (JSON profiles)

**Toxic Speech Detection:**
- Model: Toxic-BERT (via Hugging Face Transformers)
- Location: `workspace/sci_fi_dashboard/toxic_scorer_lazy.py`
- Lazy-loaded on demand, auto-unloads after 30s idle
- Used in: Message filtering before response generation

---

*Integration audit: 2026-02-27*
