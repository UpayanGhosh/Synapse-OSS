# STACK.md — Synapse-OSS Technology Stack

## Project Identity
- **Name:** synapse-oss
- **Version:** 3.0.0
- **License:** MIT
- **Description:** Multi-agent AI assistant with hybrid memory, evolving personality, and privacy-first routing

---

## Languages & Runtimes

### Python (primary)
- **Version:** 3.11 (minimum; enforced in `pyproject.toml` and `Dockerfile`)
- **Runtime environment:** CPython, asyncio throughout — no threading for I/O concurrency (except embedding provider singleton lock)
- Used for: API gateway, all business logic, channel adapters, MCP servers, CLI

### JavaScript / Node.js (secondary)
- **Version:** >= 18.0.0 (enforced in `baileys-bridge/package.json`)
- Used exclusively for the WhatsApp bridge microservice at `baileys-bridge/`
- Entry point: `baileys-bridge/index.js`

---

## Web Framework & API Server

| Component | Library | Version Constraint | File |
|---|---|---|---|
| REST API framework | FastAPI | `>=0.104.0` | `workspace/sci_fi_dashboard/api_gateway.py` |
| ASGI server | Uvicorn | `>=0.24.0` | run via `uvicorn sci_fi_dashboard.api_gateway:app` |
| Request validation | Pydantic v2 | `>=2.5.0` | `workspace/sci_fi_dashboard/schemas.py` |
| Async HTTP client | httpx | `>=0.25.0` | used in WhatsApp channel, media fetch, SSRF guard |
| Sync HTTP client | requests | `>=2.31.0` | utility/scripts |
| CORS middleware | FastAPI built-in (starlette) | — | `workspace/sci_fi_dashboard/api_gateway.py` |
| Body size middleware | custom | — | `workspace/sci_fi_dashboard/middleware.py` |
| WebSocket gateway | FastAPI WebSocket | — | `workspace/sci_fi_dashboard/gateway/ws_server.py` |

**WhatsApp bridge HTTP layer (Node.js):**
- Express `^4.18.3` — HTTP server for bridge endpoints (`/send`, `/health`, `/qr`, etc.)
- Pino `^8.21.0` — structured JSON logging

---

## LLM Routing

| Library | Version | Purpose | File |
|---|---|---|---|
| litellm | `>=1.40.0` (pyproject pins `>=1.82.0,<1.83.0`) | Unified LLM dispatch (Gemini, Anthropic, OpenAI, Groq, Ollama, OpenRouter, etc.) | `workspace/sci_fi_dashboard/llm_router.py` |
| litellm.Router | — | Multi-model routing with fallback, retry, and backoff | `workspace/sci_fi_dashboard/llm_router.py` |

**Traffic-cop routing roles** (strings map to `synapse.json → model_mappings`):
- `casual` → Gemini Flash (default)
- `code` → Claude Sonnet (thinking mode)
- `analysis` → Gemini Pro
- `review` → Claude Opus
- `vault` → Local Ollama (zero cloud leakage for private content)
- `translate` → OpenRouter Llama
- `kg` → Gemini Flash Lite (knowledge graph extraction)

**GitHub Copilot shim:** `github_copilot/` model prefix is rewritten to `openai/` with Copilot API base + auth headers injected. Token auto-refreshed via `litellm.llms.github_copilot.authenticator.Authenticator`. Token path: `~/.config/litellm/github_copilot/api-key.json`.

---

## Databases

| Database | Library | Purpose | Path |
|---|---|---|---|
| SQLite + WAL | stdlib `sqlite3` | Primary document/memory store, sessions, atomic facts | `~/.synapse/workspace/db/memory.db` |
| sqlite-vec | `sqlite-vec>=0.1.1` | Vector similarity search extension for SQLite | `workspace/sci_fi_dashboard/db.py` |
| LanceDB | `lancedb>=0.6.0` | Embedded ANN (approximate nearest neighbor) vector store | `~/.synapse/workspace/db/lancedb/` |
| SQLite (knowledge graph) | stdlib `sqlite3` | Subject–predicate–object triple store | `~/.synapse/workspace/db/knowledge_graph.db` |
| SQLite (WhatsApp bridge) | stdlib `sqlite3` | Bridge message state | `workspace/sci_fi_dashboard/whatsapp_bridge.db` |
| node-cache | `node-cache ^5.1.2` | In-memory cache for Baileys bridge | `baileys-bridge/` |

All SQLite DBs use WAL journal mode (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL`).

Embedding dimensions: **768** (nomic-embed-text-v1.5 family) — constant in `workspace/sci_fi_dashboard/db.py:EMBEDDING_DIMENSIONS`.

---

## Embedding Providers (cascade priority)

| Provider | Library | Model | Notes |
|---|---|---|---|
| FastEmbed (default) | `fastembed>=0.4.0` | `nomic-ai/nomic-embed-text-v1.5-Q` (CPU) / `nomic-ai/nomic-embed-text-v1.5` (GPU) | ONNX-based, local, zero Docker |
| Ollama | local Ollama process | `nomic-embed-text` | Fallback if fastembed not installed |
| Gemini Embeddings API | via litellm | configurable | Optional Phase 5 provider |

Factory: `workspace/sci_fi_dashboard/embedding/factory.py`
Provider base: `workspace/sci_fi_dashboard/embedding/base.py`

---

## ML / NLP Stack

| Component | Library | Version | Purpose | File |
|---|---|---|---|---|
| Reranker | flashrank | `>=0.2.0` | FlashRank ms-marco-TinyBERT-L-2-v2 reranking of retrieved memories | `workspace/sci_fi_dashboard/memory_engine.py` |
| Keyword extraction | flashtext | `>=2.7` | EntityGate fast keyword matching | `workspace/sci_fi_dashboard/memory_engine.py` |
| Toxicity scoring | transformers + torch | `>=4.35.0`, `>=2.0.0` | Toxic-BERT classifier, lazy-loaded, auto-unloads after 30s idle | `workspace/sci_fi_dashboard/toxic_scorer_lazy.py` |
| Sentence embeddings (fallback) | sentence-transformers | `>=2.2.0` | all-MiniLM-L6-v2, used for Toxic-BERT path only | `requirements-ml.txt` |
| Audio transcription | Groq SDK | `>=0.4.0` | Groq Whisper-Large-v3 API for voice messages | `workspace/sci_fi_dashboard/media/audio_preflight.py` |
| Local KG extraction | Qwen2.5 via GPU | — | Local GPU-based knowledge graph extraction (see recent commit) | `workspace/sci_fi_dashboard/conv_kg_extractor.py` |

---

## Channel Adapters (Python)

| Channel | Library | Version | File |
|---|---|---|---|
| Telegram | python-telegram-bot | `>=22.0` | `workspace/sci_fi_dashboard/channels/telegram.py` |
| Discord | discord.py | `>=2.4.0` | `workspace/sci_fi_dashboard/channels/discord_channel.py` |
| Slack | slack-bolt + slack-sdk | `>=1.18.0` / `>=3.26.0` | `workspace/sci_fi_dashboard/channels/slack.py` |
| WhatsApp | Baileys (Node.js bridge) | `@whiskeysockets/baileys ^6.7.21` | `workspace/sci_fi_dashboard/channels/whatsapp.py` (supervisor) + `baileys-bridge/index.js` |
| WebSocket | FastAPI WebSocket | — | `workspace/sci_fi_dashboard/gateway/ws_server.py` |

WhatsApp bridge communication: Python supervisor spawns Node.js subprocess, communicates via HTTP on port 5010. QR code rendered in terminal via `qrcode>=8.0` (Python) and `qrcode-terminal ^0.12.0` (Node.js).

---

## MCP (Model Context Protocol)

| Component | Library | Version | File |
|---|---|---|---|
| MCP Python SDK | mcp | `>=1.0.0` | all files in `workspace/sci_fi_dashboard/mcp_servers/` |

MCP servers (all run as stdio processes):

| Server | Port | File |
|---|---|---|
| Tools (web search, file ops) | 8989 | `workspace/sci_fi_dashboard/mcp_servers/tools_server.py` |
| Memory (RAG query + ingest) | stdio | `workspace/sci_fi_dashboard/mcp_servers/memory_server.py` |
| Synapse (chat pipeline) | stdio | `workspace/sci_fi_dashboard/mcp_servers/synapse_server.py` |
| Gmail | stdio | `workspace/sci_fi_dashboard/mcp_servers/gmail_server.py` |
| Calendar | stdio | `workspace/sci_fi_dashboard/mcp_servers/calendar_server.py` |
| Slack | stdio | `workspace/sci_fi_dashboard/mcp_servers/slack_server.py` |
| Browser (Playwright) | stdio | `workspace/sci_fi_dashboard/mcp_servers/browser_server.py` |
| Conversation | stdio | `workspace/sci_fi_dashboard/mcp_servers/conversation_server.py` |
| Execution | stdio | `workspace/sci_fi_dashboard/mcp_servers/execution_server.py` |

---

## CLI & Terminal UI

| Library | Version | Purpose | File |
|---|---|---|---|
| Typer | `>=0.24.0` | Main CLI framework; entry point `synapse` command | `workspace/synapse_cli.py` |
| InquirerPy | `>=0.3.4` | Preferred interactive prompts (Windows-compatible, fuzzy search) | onboarding wizard |
| questionary | `>=2.1.0` | Fallback interactive prompts | onboarding wizard |
| rich | `>=13.0.0` | Terminal formatting, progress, tables | throughout |

---

## Background Workers & Scheduling

| Component | Library | Purpose | File |
|---|---|---|---|
| GentleWorker | schedule `>=1.2.0` + psutil `>=5.9.0` | Battery/CPU-aware maintenance: graph pruning (10 min), DB VACUUM (30 min), proactive check-in (15 min) | `workspace/sci_fi_dashboard/gentle_worker.py` |
| CronService | custom | Time-based cron tasks | `workspace/sci_fi_dashboard/cron_service.py` |
| ProactiveAwarenessEngine | custom asyncio task | Background MCP polling (Gmail, Calendar, Slack) | `workspace/sci_fi_dashboard/proactive_engine.py` |
| File locking | filelock `>=3.12.0` | SBS profile write safety | `workspace/sci_fi_dashboard/sbs/` |

---

## Browser Automation

| Platform | Library | Version | Notes |
|---|---|---|---|
| Linux / macOS | crawl4ai | `>=0.2.0` | Headless browser, not available on Windows |
| Windows | playwright | `>=1.20.0` | Chromium automation, replaces crawl4ai on Windows |

Used by: `workspace/sci_fi_dashboard/mcp_servers/browser_server.py`, MCP tools server web search.
Docker image installs Playwright Chromium: `python -m playwright install chromium --with-deps`.

---

## Media Pipeline

| Component | Library | Purpose | File |
|---|---|---|---|
| MIME detection | python-magic + python-magic-bin (Win) | `>=0.4.27` / `>=0.4.14` | `workspace/sci_fi_dashboard/media/mime.py` |
| SSRF guard | stdlib (ipaddress, asyncio) | Block private/loopback IPs on media fetch | `workspace/sci_fi_dashboard/media/ssrf.py` |
| Atomic file writes | write-file-atomic `^5.0.1` (Node.js) | Bridge auth state writes | `baileys-bridge/` |

Size limits: image 6 MB / audio+video 16 MB / doc 100 MB. Media TTL cleanup: 120s.

---

## Configuration Files

| File | Purpose |
|---|---|
| `synapse.json.example` | Primary runtime config template (copy to `~/.synapse/synapse.json`) |
| `pyproject.toml` | Python project metadata, build system (setuptools), ruff + black config |
| `requirements.txt` | Core Python dependencies |
| `requirements-channels.txt` | Channel adapter dependencies (Telegram, Discord, Slack, WhatsApp QR) |
| `requirements-ml.txt` | ML/NLP dependencies (torch, transformers, flashrank, groq) |
| `requirements-optional.txt` | Optional deps (crawl4ai/playwright, python-magic) |
| `requirements-dev.txt` | Dev/test deps (pytest, pytest-asyncio, ruff, black) |
| `baileys-bridge/package.json` | Node.js bridge dependencies |
| `docker-compose.yml` | Single-service Docker Compose config |
| `Dockerfile` | Python 3.11-slim image, exposes port 8000 |
| `workspace/personas.yaml` | Persona/character definitions (YAML) |
| `workspace/sci_fi_dashboard/sbs/feedback/language_patterns.yaml` | SBS implicit feedback patterns |
| `workspace/synapse_config.py` | Root config loader (single source of truth for all paths, imported by 50+ files) |

---

## Build & Packaging

| Tool | Version | Config location |
|---|---|---|
| setuptools | `>=68.0` | `pyproject.toml [build-system]` |
| wheel | latest | `pyproject.toml [build-system]` |
| uv | — | `uv.lock` (lockfile present) |
| ruff | `>=0.1.0` | `pyproject.toml [tool.ruff]` — line-length 100, target py311 |
| black | `>=23.0.0` | `pyproject.toml [tool.black]` — line-length 100, py311 |
| npm | — | `baileys-bridge/package.json` |

---

## Testing

| Tool | Version | Config |
|---|---|---|
| pytest | `>=7.4.0` | markers: `unit`, `integration`, `smoke` |
| pytest-asyncio | `>=0.23.0` | async test support |

Test directories: `workspace/tests/`, `workspace/tests/pipeline/`, `workspace/tests/lancedb_reliability/`, `workspace/tests/reliability/`

---

## Containerization

| File | Notes |
|---|---|
| `Dockerfile` | Python 3.11-slim base, installs gcc/g++ for native extensions (sqlite-vec), optionally installs Playwright Chromium |
| `docker-compose.yml` | Mounts `synapse_data` volume to `/root/.synapse`, exposes port 8000 |

Persistent data volume: `/root/.synapse` (databases, logs, SBS profiles).

---

## Platform Notes

- **Windows:** `asyncio.WindowsProactorEventLoopPolicy` set at import of `whatsapp.py`. Emoji stripped from log strings (cp1252 limitation). `python-magic-bin` required. Playwright used instead of crawl4ai.
- **SYNAPSE_HOME** env var overrides the default `~/.synapse/` data root.
- **Ports:** API 8000 | Baileys bridge 5010 (internal) | Tools MCP 8989 | Ollama 11434 | OAuth 8080
