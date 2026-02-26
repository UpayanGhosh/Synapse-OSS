# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Start / Stop
```bash
# First-time setup
./jarvis_onboard.sh        # Mac/Linux
.\jarvis_onboard.ps1       # Windows

# Start all services (Qdrant, Ollama, API Gateway, OpenClaw)
./jarvis_start.sh          # Mac/Linux
.\jarvis_start.ps1         # Windows
```

### Run the API server directly
```bash
cd workspace/sci_fi_dashboard
uvicorn api_gateway:app --host 0.0.0.0 --port 8000 --reload
```

### CLI usage
```bash
cd workspace
python main.py chat          # Interactive chat
python main.py ingest        # Ingest facts into knowledge graph
python main.py vacuum        # Cleanup/prune graph
python main.py verify        # Verify system state
```

### Linting
```bash
ruff check workspace/        # Lint (line-length 100, py311 target)
black workspace/             # Format
```

### Tests
```bash
# Run all tests from workspace/
cd workspace
pytest tests/ -v

# Run by category
pytest tests/ -m unit
pytest tests/ -m integration
pytest tests/ -m smoke
pytest tests/ -m "not performance"   # Skip slow tests

# Run a single test file
pytest tests/test_queue.py -v

# Run a single test
pytest tests/test_queue.py::TestTaskQueue::test_enqueue -v
```

Tests use `asyncio_mode = auto` — all async tests work without `@pytest.mark.asyncio`.

### Database maintenance
```bash
python workspace/scripts/db_cleanup.py
python workspace/scripts/optimize_db.py    # VACUUM + optimize
python workspace/scripts/prune_sessions.py
```

---

## Architecture

### Request Flow (WhatsApp)

```
WhatsApp → OpenClaw bridge
  → POST /whatsapp/enqueue
  → FloodGate (3-second batching window)
  → MessageDeduplicator (5-min seen-set, exact match)
  → TaskQueue (asyncio FIFO, max 100)
  → MessageWorker × 2 (concurrent)
  → LLM routing (see below)
  → WhatsAppSender (OpenClaw CLI)
```

### LLM Routing (Mixture of Agents)

`api_gateway.py` contains an intent classifier that routes to specialist "agents":
- **Default / Banglish**: Gemini Flash
- **The Creator** (`/chat/the_creator`): Brother-mode persona, full memory context
- **The Partner** (`/chat/the_partner`): Caring PA persona
- **The Vault**: Local Ollama (Stheno) — used for air-gapped, private conversations (spicy hemisphere)
- **OpenRouter**: Fallback when primary LLM fails

The route entry point is `POST /whatsapp/enqueue` for async processing. `/chat/*` routes are synchronous fallbacks.

### Memory System (Hybrid RAG)

Two databases, both in `~/.openclaw/workspace/db/`:

1. **`memory.db`** — documents + sqlite-vec embeddings. Managed by `db.py` (WAL mode, sqlite-vec extension loaded at connection time).
2. **`knowledge_graph.db`** — subject-predicate-object triples in `nodes`/`edges` tables. Managed by `sqlite_graph.py`. Replaced NetworkX (155MB → <1.2MB).

Retrieval pipeline (`retriever.py`):
1. Embed query via Ollama `nomic-embed-text` (fallback: `all-MiniLM-L6-v2`)
2. ANN search in sqlite-vec + full-text search
3. FlashRank reranker (bypassed via high-confidence fast-gate for <350ms P95)
4. Results injected into prompt via `memory_engine.py`

**Dual hemispheres**: every document is tagged `hemisphere_tag = "safe" | "spicy"`. The Vault (local Ollama) exclusively reads/writes the spicy hemisphere.

### Soul-Brain Sync (SBS) — Persona Engine

Located in `workspace/sci_fi_dashboard/sbs/`. Continuously evolves behavioral profiles:

- **Real-time** (`processing/realtime.py`): sentiment + language detection on every message
- **Batch** (`processing/batch.py`): triggers every 50 messages OR 6 hours, distills into 8 profile layers stored as JSON in `jarvis_data/`
- **Injection** (`injection/compiler.py`): compiles profile layers into the system prompt before each LLM call

Profile layers: `core_identity`, `linguistic`, `emotional_state`, `domain`, `interaction`, `vocabulary`, `exemplars`, `meta`.

### Key Singletons (initialized once at boot in `api_gateway.py`)

- `Brain` — central LLM caller
- `memory_engine` — RAG orchestrator
- `dual_cognition` — inner monologue + tension scoring
- `sqlite_graph` — knowledge graph
- `sbs_orchestrator` — persona engine
- `task_queue` + `message_worker` — async pipeline

`ToxicScorer` (`toxic_scorer_lazy.py`) is lazy-loaded on demand and auto-unloads after 30s idle to save RAM.

### Concurrency Safety

All known race conditions resolved (see `workspace/Vulnerabilities.md`):
- SQLite in WAL mode; memory re-indexing is a single atomic transaction
- `INSERT OR IGNORE` for user registration (no TOCTOU)
- `threading.Lock()` (double-checked locking) on FlashRank model init
- `fcntl.flock` around OAuth token file writes
- WebSocket broadcast iterates `list(self.active_connections)` copy

### Service Ports

| Service | Port |
|---------|------|
| API Gateway (FastAPI) | 8000 |
| Memory/tools server | 8989 |
| Qdrant | 6333 |
| Ollama | 11434 |
| OpenClaw OAuth proxy | 8080 |

### Internal Tool Endpoints (at `http://127.0.0.1:8989`)

These are used by the Jarvis assistant persona at runtime, not by the development workflow:
- `POST /query` — semantic memory search
- `POST /add` — store a new memory
- `POST /browse` — headless browser (Playwright/Crawl4AI)
- `POST /transcribe` — Whisper audio transcription
- `POST /think` — local Llama 3.2 (3B) for cheap formatting/summarization
- `GET /logs` — tail service logs
- `GET /roast/serve` / `POST /roast/add` — roast database

### Environment

Copy `.env.example` to `.env`. Key variables:
- `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`
- `WHATSAPP_BRIDGE_TOKEN` — OpenClaw bridge auth
- `WINDOWS_PC_IP` — remote Ollama instance for distributed inference
- `OLLAMA_KEEP_ALIVE=0` — evict models immediately after use (RAM management)

### Code Style

- Python 3.11, line-length 100 (`ruff` + `black`)
- Ruff rules: `E, F, W, I, N, UP, B, C4, SIM` (E501 ignored — black handles length)
- All async I/O via `asyncio`; no Redis, no Celery
