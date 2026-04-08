# INTEGRATIONS.md — Synapse-OSS External Integrations

## LLM / AI Providers

All LLM calls route through litellm (`workspace/sci_fi_dashboard/llm_router.py`). Provider credentials are stored in `~/.synapse/synapse.json → providers` and injected into environment variables at startup via `_inject_provider_keys()`.

| Provider | Env Variable | Model Prefix | Default Role |
|---|---|---|---|
| Google Gemini | `GEMINI_API_KEY` | `gemini/` | casual, analysis, kg |
| Anthropic Claude | `ANTHROPIC_API_KEY` | `anthropic/` | code, review |
| OpenAI | `OPENAI_API_KEY` | `openai/` | code fallback |
| Groq | `GROQ_API_KEY` | `groq/` | casual fallback, audio transcription |
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/` | translate |
| Mistral | `MISTRAL_API_KEY` | `mistral/` | optional |
| Together AI | `TOGETHERAI_API_KEY` | `togetherai/` | optional |
| xAI (Grok) | `XAI_API_KEY` | `xai/` | optional |
| Cohere | `COHERE_API_KEY` | `cohere/` | optional |
| MiniMax | `MINIMAX_API_KEY` | `minimax/` | optional |
| Moonshot | `MOONSHOT_API_KEY` | `moonshot/` | optional |
| Z.AI (Zhipu) | `ZAI_API_KEY` | `zai/` | optional |
| Volcengine | `VOLCENGINE_API_KEY` | `volcengine/` | optional |
| HuggingFace | `HUGGINGFACE_API_KEY` | `huggingface/` | optional |
| NVIDIA NIM | `NVIDIA_NIM_API_KEY` | `nvidia_nim/` | optional |
| AWS Bedrock | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` | `bedrock/` | optional |
| Ollama (local) | none (local process) | `ollama_chat/` | vault (private content, zero cloud leakage) |

**GitHub Copilot** is also supported via a custom shim in `workspace/sci_fi_dashboard/llm_router.py`. The `github_copilot/` model prefix is rewritten to use `openai/` with the Copilot API base URL and auth headers. Token is read from `~/.config/litellm/github_copilot/api-key.json` and auto-refreshed on 403 errors via `litellm.llms.github_copilot.authenticator.Authenticator`.

Default model mappings (from `synapse.json.example`):
- casual: `gemini/gemini-2.0-flash` → fallback `groq/llama-3.3-70b-versatile`
- code: `anthropic/claude-sonnet-4-6` → fallback `openai/gpt-4o`
- analysis: `gemini/gemini-2.0-pro` → fallback `anthropic/claude-sonnet-4-6`
- review: `anthropic/claude-opus-4-6` → fallback `anthropic/claude-sonnet-4-6`
- vault: `ollama_chat/llama3.3` (no cloud fallback — by design)
- translate: `openrouter/meta-llama/llama-3.3-70b-instruct` → fallback `groq/llama-3.3-70b-versatile`
- kg: `gemini/gemini-2.5-flash-lite` → fallback `gemini/gemini-2.5-flash`

---

## Messaging / Channel APIs

### WhatsApp
- **Bridge:** `@whiskeysockets/baileys ^6.7.21` (Node.js) — unofficial WhatsApp Web API
- **Architecture:** Python (`workspace/sci_fi_dashboard/channels/whatsapp.py`) spawns `baileys-bridge/index.js` as a subprocess; communicates via HTTP on port 5010
- **Auth:** QR code pairing stored in bridge auth state directory; `WHATSAPP_BRIDGE_TOKEN` env var protects bridge endpoints (timing-safe comparison via `hmac.compare_digest`)
- **DM access control:** `PairingStore` persists approved senders at `~/.synapse/state/pairing/<channel_id>.jsonl`; `DmPolicy` enum: `pairing | allowlist | open | disabled`
- **File:** `workspace/sci_fi_dashboard/channels/whatsapp.py`, `baileys-bridge/index.js`

### Telegram
- **Library:** python-telegram-bot `>=22.0`
- **Auth:** Bot token from `synapse.json → channels.telegram.token` or `TELEGRAM_BOT_TOKEN`
- **Method:** Long polling (PTB v22+ manual lifecycle, no webhook)
- **Features:** DM messages, group @mentions, stickers, voice messages
- **File:** `workspace/sci_fi_dashboard/channels/telegram.py`

### Discord
- **Library:** discord.py `>=2.4.0`
- **Auth:** Bot token from `synapse.json → channels.discord.token`
- **Method:** Async client (never `client.run()`)
- **File:** `workspace/sci_fi_dashboard/channels/discord_channel.py`

### Slack
- **Libraries:** slack-bolt `>=1.18.0` (AsyncApp + Socket Mode), slack-sdk `>=3.26.0` (AsyncWebClient)
- **Auth:** Bot token (`xoxb-...`) + App token (`xapp-...`) from `synapse.json → channels.slack`
- **Method:** Socket Mode (no public webhook required)
- **File:** `workspace/sci_fi_dashboard/channels/slack.py`

---

## Google APIs

All Google integrations use OAuth 2.0 via `google-auth` / `google-auth-oauthlib` / `google-api-python-client`. Token files are stored locally and referenced via `synapse.json → mcp.builtin_servers.<service>.token_path`.

### Gmail
- **Scopes:** `gmail.readonly`, `gmail.send`
- **Operations:** Search inbox, send emails
- **MCP Server:** `workspace/sci_fi_dashboard/mcp_servers/gmail_server.py`
- **Library:** `google-api-python-client>=2.100.0`

### Google Calendar
- **Scopes:** `calendar.readonly`, `calendar.events`
- **Operations:** List upcoming events, create events
- **MCP Server:** `workspace/sci_fi_dashboard/mcp_servers/calendar_server.py`
- **Library:** `google-api-python-client>=2.100.0`

### Gemini Embeddings (optional)
- **Provider:** `GeminiAPIProvider` in `workspace/sci_fi_dashboard/embedding/gemini_provider.py`
- **Config:** `synapse.json → embedding.provider: "gemini"`

---

## Audio Transcription

### Groq Whisper
- **Model:** Whisper-Large-v3 via Groq API
- **Trigger:** WhatsApp/Telegram voice messages (OGG/MP3 → text)
- **Auth:** `GROQ_API_KEY` env var
- **Size limit:** 25 MB (Groq API limit)
- **Library:** `groq>=0.4.0`
- **File:** `workspace/sci_fi_dashboard/media/audio_preflight.py`

---

## Local AI Infrastructure

### Ollama
- **Port:** 11434 (local process, not managed by Synapse)
- **Purpose (embeddings):** `nomic-embed-text` model — fallback embedding provider when fastembed not installed
- **Purpose (inference):** `vault` role LLM for private/spicy content (zero cloud leakage guarantee)
- **Purpose (KG):** Qwen2.5 for local GPU-based knowledge graph extraction
- **API:** HTTP REST at `http://localhost:11434` (configurable via `synapse.json → providers.ollama.api_base`)
- **File:** `workspace/sci_fi_dashboard/embedding/ollama_provider.py`

---

## Databases (Embedded / Local)

| Database | Location | Access Pattern |
|---|---|---|
| SQLite memory store | `~/.synapse/workspace/db/memory.db` | Read/write via stdlib `sqlite3`, WAL mode |
| SQLite knowledge graph | `~/.synapse/workspace/db/knowledge_graph.db` | Read/write via `workspace/sci_fi_dashboard/sqlite_graph.py` |
| LanceDB vector store | `~/.synapse/workspace/db/lancedb/` | Embedded (no server), via `lancedb>=0.6.0` |
| WhatsApp bridge state | `workspace/sci_fi_dashboard/whatsapp_bridge.db` | SQLite, message dedup and bridge state |

No external database servers (no Redis, no Postgres, no MongoDB). Everything is embedded SQLite or LanceDB.

---

## MCP (Model Context Protocol) — External Tool Calls

Synapse exposes and consumes MCP servers via the Anthropic MCP Python SDK (`mcp>=1.0.0`). MCP tools are NOT offered to the LLM during `persona_chat()` — they are invoked only by `ProactiveAwarenessEngine` or external MCP clients.

### MCP Servers Hosted by Synapse

| Server ID | Port/Transport | Exposed Tools |
|---|---|---|
| `synapse-tools` | 8989 (stdio) | `web_search`, `read_file` (Sentinel-gated), `write_file` (Sentinel-gated) |
| `synapse-memory` | stdio | Knowledge base query, fact ingest |
| `synapse-main` | stdio | Chat pipeline, profile queries |
| `synapse-gmail` | stdio | `search_emails`, `send_email` |
| `synapse-calendar` | stdio | List/create calendar events |
| `synapse-slack` | stdio | Read Slack channels, post messages |
| `synapse-browser` | stdio | Headless Chromium control (navigate, screenshot, snapshot, act) |
| `synapse-conversation` | stdio | Conversation queries |
| `synapse-execution` | stdio | Code execution tools |

### Sentinel File Access Security
The `read_file` and `write_file` MCP tools are gated by the Sentinel subsystem (`workspace/sci_fi_dashboard/sbs/sentinel/`). All file operations are audit-logged. A manifest controls which paths are accessible.

---

## Auth Providers

### Gateway Token Auth
- **Mechanism:** Bearer token or `x-api-key` header
- **Config:** `synapse.json → gateway_token`
- **Endpoints protected:** `POST /chat/the_creator`, WebSocket `ws://127.0.0.1:8000/ws`
- **Implementation:** `workspace/sci_fi_dashboard/middleware.py` — timing-safe via `hmac.compare_digest`

### WhatsApp Bridge Token
- **Mechanism:** `x-bridge-token` header
- **Config:** `WHATSAPP_BRIDGE_TOKEN` env var
- **Implementation:** `workspace/sci_fi_dashboard/middleware.py:validate_bridge_token()`

### Google OAuth 2.0
- **Flow:** Offline access, token persisted locally
- **Libraries:** `google-auth>=2.23.0`, `google-auth-oauthlib>=1.1.0`
- **Token storage:** Local file path configured in `synapse.json → mcp.builtin_servers.<service>.token_path`
- **OAuth server port:** 8080 (for OAuth callback during initial auth setup)

---

## WebSocket Gateway

- **Endpoint:** `ws://127.0.0.1:8000/ws`
- **Auth:** Optional `SYNAPSE_GATEWAY_TOKEN`
- **Heartbeat:** Every 30 seconds
- **Methods:** `chat.send`, `channels.status`, `models.list`, `sessions.list`, `sessions.reset`
- **File:** `workspace/sci_fi_dashboard/gateway/ws_server.py`, `workspace/sci_fi_dashboard/gateway/ws_protocol.py`

---

## Web Browsing / Scraping

- **Linux/macOS:** crawl4ai `>=0.2.0` — headless browser automation
- **Windows:** playwright `>=1.20.0` — Chromium via `python -m playwright install chromium`
- **MCP exposure:** `web_search` tool in `workspace/sci_fi_dashboard/mcp_servers/tools_server.py`
- **SSRF protection:** All external URL fetches pass through `workspace/sci_fi_dashboard/media/ssrf.py` — blocks private IPs, loopback, link-local ranges; validates redirect hops

---

## Embedded ML Models (downloaded at runtime)

| Model | Source | Used by | Download trigger |
|---|---|---|---|
| `nomic-ai/nomic-embed-text-v1.5-Q` (ONNX, CPU) | HuggingFace / fastembed | Embedding provider | First embedding call |
| `nomic-ai/nomic-embed-text-v1.5` (GPU) | HuggingFace / fastembed | Embedding provider (GPU) | First embedding call |
| `ms-marco-TinyBERT-L-2-v2` | FlashRank (HuggingFace) | Memory reranker | First rerank call |
| Toxic-BERT | HuggingFace Transformers | `workspace/sci_fi_dashboard/toxic_scorer_lazy.py` | First toxicity score request |
| Qwen2.5 | Ollama pull | Local KG extraction | Manual `ollama pull` |

---

## Deployment / Infrastructure

| Component | Details |
|---|---|
| Docker | `Dockerfile` (Python 3.11-slim), `docker-compose.yml` (single service) |
| Volume | `synapse_data` → `/root/.synapse` (persists DBs, logs, SBS profiles across restarts) |
| Port exposure | 8000 (API gateway) — only port exposed in Docker |
| Process management | Uvicorn ASGI server; Baileys bridge spawned as subprocess by Python |

### Startup Scripts

| Script | Platform | Purpose |
|---|---|---|
| `synapse_start.sh` | Linux/macOS | Start all services |
| `synapse_start.bat` | Windows | Start all services |
| `synapse_stop.sh` / `.bat` | both | Stop all services |
| `synapse_restart.sh` | Linux/macOS | Restart |
| `synapse_onboard.sh` / `.bat` | both | First-run onboarding wizard |
| `synapse_health.sh` | Linux/macOS | Health check |

---

## Summary: External Network Calls at Runtime

| Call | Destination | Triggered by |
|---|---|---|
| LLM inference | Gemini API, Anthropic API, OpenAI API, Groq API, OpenRouter, Ollama (local) | Every chat message |
| Voice transcription | Groq Whisper API | Voice messages |
| Telegram polling | `api.telegram.org` | TelegramChannel running |
| Discord WebSocket | `gateway.discord.gg` | DiscordChannel running |
| Slack Socket Mode | Slack API WebSocket | SlackChannel running |
| WhatsApp Web | WhatsApp Web API (via Baileys, Node.js) | WhatsAppChannel running |
| Gmail API | `gmail.googleapis.com` | ProactiveAwarenessEngine + MCP calls |
| Calendar API | `calendar.googleapis.com` | ProactiveAwarenessEngine + MCP calls |
| Slack Web API | `slack.com/api/*` | ProactiveAwarenessEngine + MCP calls |
| Web scraping | arbitrary URLs | MCP `web_search` tool, `browser` tool |
| Embedding download | HuggingFace Hub / fastembed CDN | First run, model not cached |
| Reranker download | HuggingFace Hub (via FlashRank) | First run, model not cached |
