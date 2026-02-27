# Technology Stack

**Analysis Date:** 2026-02-27

## Languages

**Primary:**
- Python 3.11+ - All backend API, CLI tools, agents, and data processing

## Runtime

**Environment:**
- Python 3.11 (minimum requirement per `pyproject.toml`)
- CPython (standard Python interpreter)

**Package Manager:**
- `pip` - Python package manager
- Lockfile: Generated from `requirements.txt` (pinned versions)

## Frameworks

**Web Framework:**
- FastAPI 0.104.0+ - Async REST API gateway (`api_gateway.py`)
- Uvicorn 0.24.0+ - ASGI server (runs on port 8000)

**LLM Integration:**
- OpenAI SDK (`openai>=2.31.0`) - Unified interface for Ollama local models via `/v1` endpoint compatibility

**Data Processing & ML:**
- PyTorch 2.0.0+ - Inference engine for Toxic-BERT (toxicity scoring)
- Hugging Face Transformers 4.35.0+ - Toxic-BERT model loading and inference
- Sentence-Transformers 2.2.0+ - Fallback embedding model (`all-MiniLM-L6-v2`)

**Vector Search & Embeddings:**
- `sqlite-vec>=0.1.1` - SQLite extension for vector similarity search (replaces separate vector DB for document retrieval)
- `qdrant-client>=1.6.0` - Optional Qdrant vector database client (used in migration scripts and legacy paths)

**Web Automation & Scraping:**
- Crawl4AI 0.2.0+ - Headless browser automation for tool-based web browsing (extracts clean markdown from URLs)

**Reranking & Search:**
- FlashRank 0.2.0+ - Semantic reranker for retrieved memories (uses `ms-marco-TinyBERT-L-2-v2` model)
- FlashText 2.7+ - Fast keyword extraction for EntityGate (protects PII)

**Scheduling & Concurrency:**
- `schedule>=1.2.0` - Background task scheduling (GentleWorker)
- `filelock>=3.12.0` - File locking for SBS audit and profile writes (prevents race conditions)

**System Monitoring:**
- `psutil>=5.9.0` - System metrics collection (CPU, memory, process tracking)

**Data Formats & Validation:**
- Pydantic 2.5.0+ - Request/response validation and schema definitions
- `httpx>=0.25.0` - Async HTTP client for external API calls
- `requests>=2.31.0` - Synchronous HTTP client (fallback)

**Terminal & Display:**
- Rich 13.0.0+ - Rich terminal output, progress bars, tables (used in monitor.py and CLI)

**Database & Persistence:**
- SQLite3 (built-in) - Primary database (memory.db, knowledge_graph.db) with WAL mode enabled
- WAL (Write-Ahead Logging) - Enabled for concurrent read access without blocking

## Local LLM Runtime

**Ollama:**
- Client: `ollama>=0.1.0` - Python client for local model inference
- Models used at runtime:
  - `nomic-embed-text` - Embedding model (768-dim vectors)
  - `llama3.2:3b` - Local fallback model (The Vault, for air-gapped private conversations)
  - `llama3.1:8b` - Worker tier model (optional, for distributed inference on Windows PC)
  - `qwen2.5-coder:14b` - Architecture tier model (optional, coding tasks)
- Port: 11434 (default)
- Configuration: `OLLAMA_KEEP_ALIVE=0` (models unload immediately after inference to conserve VRAM)

## Cloud LLM Providers

**Google Gemini:**
- API: Google Gemini (via OpenClaw OAuth gateway or direct REST)
- Models: `gemini-3-flash` (primary), `gemini-pro` (fallback)
- Auth: `GEMINI_API_KEY` environment variable

**OpenRouter (Fallback):**
- Service: OpenRouter API for secondary/backup model routing
- Auth: `OPENROUTER_API_KEY` environment variable
- Used when primary LLM fails

**OpenAI (Optional):**
- Auth: `OPENAI_API_KEY` environment variable
- Used for specific tool overrides or custom integrations

**Groq (Voice):**
- Service: Groq Whisper-Large-v3 cloud transcription API
- Auth: `GROQ_API_KEY` environment variable
- Purpose: Fast transcription of voice messages (2-4 second latency)

## Vector Database

**Primary (Development/Fallback):**
- Qdrant 6333 port (optional, used in migration scripts and legacy code)
- Docker image: `qdrant/qdrant:latest`
- Purpose: Vector similarity search (being migrated to sqlite-vec)

**New (Production):**
- sqlite-vec (embedded in memory.db)
- No separate service dependency
- Stores 768-dimensional embeddings from nomic-embed-text

## Configuration & Build

**Code Quality:**
- Ruff 0.1.0+ - Fast Python linter (rules: E, F, W, I, N, UP, B, C4, SIM; ignores E501)
- Black 24.0.0+ - Code formatter (line-length: 100)
- Configuration: `pyproject.toml` (centralized)

**Build System:**
- setuptools 68.0+ - Python packaging
- wheel - Binary package format
- Build backend: `setuptools.build_meta`

**Environment:**
- Pydantic Settings (`.env` file support)
- Location: `.env` (copy from `.env.example`)

**Docker Containerization:**
- Docker 20.10+ - Containerization
- docker-compose - Multi-service orchestration
- Base image: `python:3.11-slim`
- Qdrant image: `qdrant/qdrant:latest`

## Platform Requirements

**Development:**
- Python 3.11+ (macOS, Linux, Windows)
- Git (version control)
- Docker & docker-compose (for containerized deployment)
- Ollama (local model inference, optional but recommended)
- OpenClaw CLI (WhatsApp bridge, required for WhatsApp integration)
- SQLite 3.35.0+ (built-in on macOS/Linux; Windows 10+ includes it)
- sqlite-vec extension (downloaded at first `db.py` connection or via `pip install sqlite-vec`)

**Production (Docker):**
- Docker Engine 20.10+
- 8GB+ RAM (minimum for Ollama + FastAPI + Toxic-BERT)
- Port 8000 (API Gateway)
- Port 6333 (Qdrant, if used)
- Port 11434 (Ollama, if local)

**Recommended Hardware:**
- macOS: Apple Silicon (M1/M2/M3) or Intel with 16GB RAM
- Linux: x86-64 with GPU (CUDA/ROCm) preferred, 16GB+ RAM
- Windows: x86-64 with 16GB+ RAM; GPU optional (NVIDIA CUDA or AMD ROCm)

## Architecture Decisions

**Synchronous vs Async:**
- All web I/O: async/await via FastAPI/Uvicorn
- Background tasks: `asyncio` (no Redis, no Celery)
- Local inference (Ollama): Blocking calls within async context (acceptable latency)

**Data Persistence:**
- SQLite with WAL mode (concurrent readers, atomic writes)
- No external cache layer (Redis) — memory-efficient design
- Vector embeddings: sqlite-vec (single database file)
- Knowledge graph: Separate SQLite file with RDF-like schema

**Containerization Strategy:**
- Single-service Docker image (`synapse` service)
- External services: Qdrant as separate container
- Data volumes: `qdrant_data` persisted across restarts

---

*Stack analysis: 2026-02-27*
