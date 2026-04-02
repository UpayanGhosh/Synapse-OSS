# SYNAPSE -- A Self-Hosted AI System with Hybrid Memory, Evolving Personality, and Privacy-First Architecture

**302 tests passing** | **11 subsystems** | **4 messaging channels** | **6 LLM providers** | **15,000+ lines of Python** | **24/7 on 8GB hardware**

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-302_passing-brightgreen?style=for-the-badge)
![Lines of Code](https://img.shields.io/badge/Lines_of_Code-15,000+-blueviolet?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![CI](https://img.shields.io/github/actions/workflow/status/UpayanGhosh/Synapse-OSS/tests.yml?branch=main&style=for-the-badge&logo=github&label=CI)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)

> A production AI assistant that remembers everything, develops its own personality
> from conversation patterns, thinks before replying, and routes private conversations
> to local models with zero cloud exposure -- running 24/7 on a $999 MacBook Air.

> **New here?** Jump to [Quick Start](#quick-start) or read [HOW_TO_RUN.md](HOW_TO_RUN.md) for full setup instructions.
>
> **Want the story behind the engineering?** See the [Key Engineering Decisions](#key-engineering-decisions) section below.

> **Platform Note:** Developed on macOS (Apple Silicon). Windows 11 fully supported.
> Linux should work but is less tested. If you hit issues, please
> [open an issue](https://github.com/UpayanGhosh/Synapse-OSS/issues).

> [!IMPORTANT]
> **This is an actively developing project.** You may run into bugs, broken features, or
> the agent may not even start due to recent changes -- please don't get annoyed!
> I'm a solo developer with a full-time job, so progress comes in evenings and weekends.
>
> - **Found a bug?** [Open an issue](https://github.com/UpayanGhosh/Synapse-OSS/issues)
> - **Have a question or idea?** [Start a discussion](https://github.com/UpayanGhosh/Synapse-OSS/discussions)
> - **Want to contribute?** Please read [CONTRIBUTING.md](CONTRIBUTING.md) first
>
> Your patience and feedback are genuinely appreciated. Thank you for checking this out!

---

## What Makes This Different

Most AI chatbot projects are a system prompt and an API call. Synapse is an **11-subsystem, 15,000+ line architecture** that solves problems most chatbots never even acknowledge -- built under a hard constraint: everything must run on a single 8GB consumer laptop.

Here is what that looks like in practice:

| Problem | How Most Bots Handle It | How Synapse Handles It |
| --- | --- | --- |
| **Memory** | Stuff messages into context window until it overflows | Hybrid RAG -- SQLite knowledge graph + sqlite-vec embeddings + Qdrant vector search + FlashRank reranking. 37,868+ vocabulary terms, **<350ms P95 retrieval**, 3.4x faster than v1. |
| **Personality** | Static system prompt, same tone forever | Soul-Brain Sync -- a 3-stage pipeline (realtime sentiment capture, batch distillation every 50 messages, prompt injection) continuously builds a living **2KB behavioral profile**. Personality is not configured. It is learned. |
| **Model selection** | One model for everything (expensive or dumb) | Mixture of Agents -- intent classifier routes to **6 providers** (Gemini, Claude, Ollama, OpenRouter, Groq, local Vault) through `litellm.Router`. Casual chat does not burn expensive API credits. Swap providers by editing JSON config, zero code changes. |
| **Privacy** | Everything goes to cloud APIs | The Vault -- sensitive conversations route to a local Ollama model. **Hemisphere-enforced memory separation**: "safe" (cloud) and "spicy" (local-only) are physically partitioned. Zero cross-contamination, verified by automated integrity tests. |
| **Thinking** | Generate first token immediately | Dual Cognition -- generates an inner monologue, calculates a tension score (0.0--1.0) between memory and current message, then responds. It thinks before it speaks. |
| **Channels** | One messaging platform, tightly coupled | **4 channels** (WhatsApp, Telegram, Discord, Slack) normalized to a single `ChannelMessage` DTO. Memory, persona, and model routing are completely channel-blind. Adding a 5th channel requires ~100 lines -- just implement `BaseChannel`. |
| **Message reliability** | Webhook timeout, lost messages, duplicates | Async pipeline -- 3-second FloodGate batching, 5-minute deduplication window, bounded 100-task async queue, 2 concurrent MessageWorkers. **Zero dropped messages** under real load. |
| **RAM on consumer hardware** | "Just buy a bigger server" | Replaced NetworkX (155MB in-RAM graph) with SQLite (<1.2MB) after profiling showed 81% RAM pressure on 8GB hardware. Lazy-loading ToxicScorer (unloads after 30s idle), `OLLAMA_KEEP_ALIVE=0` model eviction, thermal-aware background workers. **99.2% memory reduction.** |
| **Voice** | Ignore or crash | Groq Whisper -- 2-4s cloud transcription, zero local RAM impact, then processed through the full cognitive pipeline like any other message. |

These are not theoretical capabilities. This system processes real messages, from a real user, every day, on real hardware.

---

## By The Numbers

> `302 tests` | `24 test files` | `99.2% RAM reduction` | `<350ms P95 retrieval` | `6 LLM providers` | `4 messaging channels` | `Zero dropped messages` | `24/7 on $999 hardware`

| Metric | Before (v1.0) | After (Phoenix v3) | What Changed |
| --- | --- | :---: | --- |
| **Knowledge Graph Footprint** | ~155MB in-RAM (NetworkX) | **<1.2MB** (SQLite) | NetworkX loaded the entire graph into RAM, causing 81% memory pressure on an 8GB host. SQLite reads from disk on demand. **99.2% reduction.** |
| **Host RAM Usage** | 81.3% | **<25%** | Consolidated 4 separate processes (Qdrant, NetworkX, memory server, gateway) into a single FastAPI app. **3.3x lower.** |
| **Retrieval Latency (P95)** | ~1.2s | **<350ms** | High-confidence results (>0.80) bypass FlashRank reranker entirely. Only ambiguous queries pay the reranking overhead. **3.4x faster.** |
| **Vocabulary Diversity** | ~5,000 static terms | **37,868+** | Continuous ingestion from 4 years of conversation logs via the SBS batch pipeline. **7.6x richer.** |
| **Message Pipeline** | Synchronous (webhook timeout) | **Async queue** (202 Accepted) | FloodGate batching (3s window) + deduplication (5-min window) + bounded TaskQueue (max 100) + 2 concurrent MessageWorkers. **Zero dropped messages** under single-user load. |
| **Behavioral Profile** | None (static system prompt) | **2KB, rebuilt every 50 messages** | Soul-Brain Sync: 3-stage pipeline (realtime → batch → injection). 8 profile layers distilled from conversation patterns. |
| **Cognitive Overhead (TTFT)** | N/A | **2-5s** | Dual Cognition pipeline: inner monologue generation + tension scoring before response. Quality-for-speed trade-off. |
| **Test Coverage** | Manual | **302 tests across 24 files** | Unit, integration, smoke, performance, end-to-end, and acceptance tests. Async-native (`asyncio_mode = auto`). |
| **Channel Support** | WhatsApp only | **4 channels** | WhatsApp, Telegram, Discord, Slack -- all normalized to a single DTO through `BaseChannel` ABC. |
| **Bridge Recovery** | Manual restart | **5s auto-restart** | Exponential backoff (up to 5 attempts) on Baileys bridge crash. |

---

## Demo

### Conversation

> *Synapse responding to a real message with memory context, persona adaptation, and model routing visible in the footer stats.*

### Architecture Overview

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system diagram with Mermaid source.

---

## System Architecture

> *For the full interactive diagram with Mermaid breakdowns of each subsystem, see [ARCHITECTURE.md](ARCHITECTURE.md).*

The system consists of 11 interconnected subsystems:

```
┌─────────────────────────────────────────────────────────────────┐
│               Multi-Channel Inbound (WhatsApp / Telegram /      │
│                        Discord / Slack)                         │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Async Gateway Pipeline                     │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────────┐    │
│  │FloodGate│→│ Dedup   │→│  Queue   │→│ MessageWorker │    │
│  │  (3s)   │  │ (5-min) │  │(max 100)│  │    (x2)      │    │
│  └─────────┘  └─────────┘  └─────────┘  └──────────────┘    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Cognitive Pipeline                          │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐  ┌───────────┐   │
│  │ Memory   │→│   SBS    │→│DualCognition│→│ TrafficCop│   │
│  │  (RAG)   │  │(Persona) │  │(Monologue) │  │ (Intent)  │   │
│  └──────────┘  └──────────┘  └───────────┘  └───────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              Multi-Model Router (litellm.Router)                │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────┐   │
│  │ Gemini │ │ Claude │ │ Ollama │ │  Vault │ │ Fallback │   │
│  │ Flash  │ │ Sonnet │ │ Local  │ │Air-gap │ │OpenRouter│   │
│  └────────┘ └────────┘ └────────┘ └────────┘ └──────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### Request Flow

```
Inbound message (any channel)
  → ChannelRegistry normalizes to ChannelMessage DTO
  → FloodGate (3-second batching window)
  → MessageDeduplicator (5-minute seen-set, exact match)
  → TaskQueue (asyncio FIFO, bounded at 100)
  → MessageWorker (2 concurrent instances)
  → Memory retrieval (sqlite-vec ANN + FTS + FlashRank reranking)
  → SBS profile injection (2KB behavioral profile → system prompt)
  → Dual Cognition (inner monologue + tension scoring)
  → Traffic Cop (intent classification)
  → litellm.Router → best-fit model (Gemini / Claude / Ollama / Vault / fallback)
  → Response delivered back through originating channel
```

---

## Key Engineering Decisions

These are the decisions that separate Synapse from a typical chatbot project. Each one was made in response to a real problem encountered in production.

**1. Replaced NetworkX with SQLite for the knowledge graph.**
NetworkX loaded the entire graph into RAM. On an 8GB host, this consumed 155MB and pushed total memory pressure to 81.3%. The SQLite replacement reads from disk on demand, uses <1.2MB, and brought host RAM usage under 25%. This was not a premature optimization -- it was the difference between the system running and not running.

**2. Built a vendor-agnostic LLM router on litellm.**
All 6 LLM providers (Gemini, Claude, Ollama, OpenRouter, Groq, local Vault) are configured through `synapse.json` model mappings with provider-prefixed strings. The `SynapseLLMRouter` class wraps `litellm.Router` with per-role fallback configuration. Swapping from Gemini to Claude for a given role requires changing one line of JSON, zero lines of Python. Provider API keys are injected from config at startup, not hardcoded.

**3. Designed a channel-agnostic message pipeline from scratch.**
All 4 messaging channels (WhatsApp, Telegram, Discord, Slack) implement a `BaseChannel` abstract base class with 6 methods (`receive`, `send`, `send_typing`, `mark_read`, `health_check`, `channel_id`). Every inbound message is normalized into a `ChannelMessage` dataclass before entering the pipeline. The entire cognitive stack -- memory, persona, model routing -- has no knowledge of which channel a message came from. Adding a 5th channel means writing one class file that implements `BaseChannel`.

**4. Built an evolving personality system instead of a static prompt.**
Most AI assistants use a fixed system prompt. Synapse maintains a living behavioral profile through Soul-Brain Sync: a `RealtimeProcessor` captures sentiment and language signals on every message, a `BatchProcessor` distills conversation patterns into 8 structured JSON layers every 50 messages (or 6 hours), and a `PromptCompiler` injects the compiled profile into the system prompt at inference time. The profile adapts regardless of which LLM is active because injection is model-agnostic and costs zero training compute.

**5. Implemented hemisphere-enforced memory isolation for privacy.**
Memory is physically partitioned into "safe" (cloud-accessible) and "spicy" (local-only) hemispheres. The Vault does not just use a different model -- it uses a different memory space. There is zero cross-contamination between hemispheres, verified by automated integrity tests. This is not a flag in a database row. It is an architectural boundary.

**6. Designed for the constraint, not around it.**
Lazy-loading ToxicScorer (Toxic-BERT loads on demand, auto-unloads after 30 seconds idle). `OLLAMA_KEEP_ALIVE=0` to evict models from RAM immediately after use. Thermal-aware `GentleWorker` that checks CPU load and power state before running background maintenance -- no database optimization on battery, no maintenance when CPU exceeds 20%. Every design choice was made under real resource pressure on a machine with 8GB of RAM.

---

## Quick Start

> **Full setup guide** (API keys, Qdrant, Ollama, channel linking): [HOW_TO_RUN.md](HOW_TO_RUN.md)

**1. Clone**

```bash
git clone https://github.com/UpayanGhosh/Synapse-OSS.git
cd Synapse-OSS
```

**2. Set up Python environment**

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Windows
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

**3. Run the onboarding script**

```bash
# macOS / Linux
chmod +x synapse_onboard.sh
./synapse_onboard.sh

# Windows -- double-click or run from a terminal:
synapse_onboard.bat
```

The onboarding script creates `~/.synapse/`, walks you through adding your API keys
to `~/.synapse/synapse.json`, and connects your first channel (WhatsApp QR scan,
Telegram bot token, Discord bot token, or Slack app token).

> **After first setup:** use `synapse_start.sh` / `synapse_start.bat` for daily use.

**4. Run tests**

```bash
cd workspace
pytest tests/ -v              # All 302 tests
pytest tests/ -m unit         # Unit tests only
pytest tests/ -m integration  # Integration tests only
```

---

## Usage Examples

### Chat with Synapse

```bash
# macOS/Linux
curl -X POST http://localhost:8000/chat/the_creator \
  -H "Content-Type: application/json" \
  -d '{"message": "What do you remember about our last conversation?"}'

# Windows
curl.exe -X POST http://localhost:8000/chat/the_creator -H "Content-Type: application/json" -d "{\"message\": \"What do you remember about our last conversation?\"}"
```

### Query Memory

```bash
# macOS/Linux
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"text": "What is the user'\''s favorite programming language?"}'

# Windows
curl.exe -X POST http://localhost:8000/query -H "Content-Type: application/json" -d "{\"text\": \"What is the user's favorite programming language?\"}"
```

### Add Memory

```bash
# macOS/Linux
curl -X POST http://localhost:8000/add \
  -H "Content-Type: application/json" \
  -d '{"content": "The user prefers Python over JavaScript", "category": "tech_preferences"}'

# Windows
curl.exe -X POST http://localhost:8000/add -H "Content-Type: application/json" -d "{\"content\": \"The user prefers Python over JavaScript\", \"category\": \"tech_preferences\"}"
```

### Check System Health

```bash
curl http://localhost:8000/health
```

### Rebuild Persona Profile

```bash
curl -X POST http://localhost:8000/persona/rebuild
```

> **Full setup guide** (Qdrant, Ollama, channel configuration, persona config): [HOW_TO_RUN.md](HOW_TO_RUN.md)
>
> **Persona customization** (how to make Synapse yours): [SETUP_PERSONA.md](SETUP_PERSONA.md)

---

## Key Features

### Multi-Channel Support (WhatsApp, Telegram, Discord, Slack)

All messaging channels implement a `BaseChannel` ABC, managed by a `ChannelRegistry` that runs each adapter as an `asyncio.create_task()` within the FastAPI lifespan. Every channel normalizes inbound events into a unified `ChannelMessage` DTO before they enter the shared pipeline -- memory, persona, and model routing work identically regardless of which channel a message arrives from.

- **WhatsApp** -- self-managed Baileys Node.js bridge (spawned and supervised as a subprocess, port 5010 internal). QR pairing on first boot. Auto-restarts on crash with exponential backoff (5-second initial delay, up to 5 attempts). Requires Node.js 18+.
- **Telegram** -- `python-telegram-bot` v22+ long polling. DMs and @mentions in groups both supported. Token configured via `synapse.json`.
- **Discord** -- `discord.py` v2.x. DMs always dispatched; server messages only on @mention. Requires the MESSAGE_CONTENT privileged intent.
- **Slack** -- `slack-bolt` AsyncApp with Socket Mode WebSocket transport. No public webhook URL required -- suitable for self-hosters behind NAT.

### Async Gateway Pipeline

Messages enter through a multi-stage async pipeline (`gateway/`) that prevents webhook timeouts. A `FloodGate` (3-second batch window) merges rapid-fire messages, a `MessageDeduplicator` (5-minute seen-set) absorbs retry storms, and a bounded `TaskQueue` (asyncio FIFO, max 100) feeds 2 concurrent `MessageWorker` instances. The webhook returns `202 Accepted` immediately -- the cognitive pipeline processes in the background. **Zero dropped messages** under single-user load (~50-100 messages/day).

### Multi-Model Intent Router (Mixture of Agents)

A lightweight intent classifier routes each message to the best-fit model through `litellm.Router`: Gemini Flash for casual chat, Claude Sonnet for code generation, Gemini Pro for deep analysis, Claude Opus for critical review, Groq for voice transcription, or a local Ollama instance for private conversations. All LLM calls use provider-prefixed model strings from `~/.synapse/synapse.json`. The router is completely vendor-agnostic -- swap providers by editing `model_mappings` in config, no code changes required. Per-role fallback models handle provider outages and rate limits automatically.

### Hybrid Memory Retrieval (RAG)

The `MemoryEngine` combines a SQLite knowledge graph (subject-predicate-object triples) with sqlite-vec embeddings and Qdrant vector search (`nomic-embed-text`). A temporal scoring function blends semantic similarity with recency. High-confidence results (>0.80) skip the FlashRank reranker (ms-marco-TinyBERT) for speed; lower-confidence candidates pass through for precision. Result: **<350ms P95 retrieval** across 37,868+ vocabulary terms.

### Soul-Brain Sync (Continuous Behavioral Profiling)

Rather than static system prompts, the SBS pipeline continuously builds and evolves a 2KB behavioral profile per conversation target:

- **RealtimeProcessor**: rule-based sentiment + language detection on every message
- **BatchProcessor**: triggers every 50 messages or 6 hours, distills patterns into 8 structured JSON layers (core_identity, linguistic, emotional_state, domain, interaction, vocabulary, exemplars, meta)
- **PromptCompiler**: injects the compiled profile into the system prompt at inference time
- **ImplicitFeedbackDetector**: watches for conversational corrections ("too long", "be more casual") and adjusts persona in real-time -- no explicit configuration needed

Why not fine-tuning? Profile injection is model-agnostic and costs zero training compute. The persona adapts regardless of which LLM is active.

### Dual Cognition Engine

Before generating a reply, the `DualCognitionEngine` produces an inner monologue (chain-of-thought via Gemini Flash) and calculates a tension score (0.0--1.0) to detect emotional conflicts between retrieved memory and the current message. This cognitive context is injected into the prompt alongside memories and persona. The `LazyToxicScorer` (Toxic-BERT) loads on demand and auto-unloads after 30 seconds of idle to conserve RAM -- on an 8GB machine, every megabyte matters.

### Air-Gapped Local Inference (The Vault)

Sensitive conversations route to a local Ollama instance. Zero cloud API calls, zero external logging. Hemisphere integrity -- the physical separation between cloud-routed and local-only memories -- is verified by automated tests (`verify` CLI command). This is not a configuration flag. It is an architectural boundary with zero cross-contamination.

### Voice Message Transcription (Groq Whisper)

Voice notes are transcribed using the Groq API (Whisper-Large-v3). Cloud-based transcription with zero local RAM impact -- results in 2-4 seconds. Transcribed text enters the full cognitive pipeline (memory retrieval, persona injection, dual cognition) like any other message.

### Web Browsing (Platform-Aware)

The `ToolRegistry` dispatches headless browser sessions for real-time data (weather, news, live scores), extracts clean text, and feeds results back to the LLM. Content is truncated to 3,000 characters to protect context window limits. Platform-aware: **Crawl4AI** on Mac/Linux, **Playwright** on Windows -- the `search_web(url)` interface is identical on both.

### Sentinel File Governance

A fail-closed file governance system (`sbs/sentinel/`) that controls what the AI agent can read, write, or delete. Files are classified as CRITICAL (total lockout), PROTECTED (read-only), MONITORED (read-write with audit logging), or OPEN. All access decisions are logged to an immutable JSONL audit trail.

### Thermal-Aware Background Maintenance (GentleWorker)

A background worker that prunes stale knowledge graph triples and optimizes databases -- but only when the host machine is plugged in and CPU usage is below 20%. No maintenance on battery. No maintenance during active use. Designed for consumer hardware where the AI assistant shares the machine with a human.

---

## Engineering Competencies Demonstrated

| Competency | Evidence |
| :--- | :--- |
| **System Design** | Consolidated a 4-process architecture into a single FastAPI process. Replaced NetworkX (155MB) with SQLite (<1.2MB) after profiling showed 81% RAM pressure. **99.2% memory reduction.** |
| **Async Systems** | Built an async queue-push message gateway with FloodGate batching, deduplication, bounded queue, and 2 concurrent workers. **Zero dropped messages** under real load. |
| **Database Engineering** | Dual-database architecture (memory.db + knowledge_graph.db) with WAL mode, atomic transactions, sqlite-vec for ANN search, and a migration path from Qdrant to eliminate container dependencies. |
| **ML Pipeline Orchestration** | Multi-model intent router dispatching to 6 providers through `litellm.Router` with per-role fallback configuration. Vendor-agnostic -- swap providers via JSON config. |
| **Performance Optimization** | Lazy-loading patterns (Toxic-BERT on-demand, 30s idle unload), model eviction (`keep_alive: 0`), FlashRank fast-gate bypass for high-confidence queries, thermal-aware workers. |
| **Privacy Engineering** | Hemisphere-enforced memory separation with zero cross-contamination. Air-gapped local inference. Automated integrity verification. |
| **Testing** | 302 tests across 24 files: unit, integration, smoke, performance, end-to-end, and acceptance. Async-native with `asyncio_mode = auto`. |
| **DevOps** | `launchd`-managed boot sequence, idempotent service control, 5-second auto-restart with exponential backoff, 12-hour backup rotation, real-time observability dashboard. |
| **Continuous Profiling** | Soul-Brain Sync: autonomous ingestion, batch distillation, prompt injection pipeline. 8-layer behavioral profile rebuilt every 50 messages. |
| **API Design** | OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/models`), channel-specific webhooks, dynamic persona routes from `personas.yaml`. |

---

## Technical Stack

| Category | Technologies |
| :--- | :--- |
| Languages | Python 3.11, JavaScript (Node.js 18+), Bash |
| Frameworks | FastAPI, Uvicorn, asyncio |
| LLM Routing | `litellm.Router` -- provider-agnostic, config-driven, per-role fallbacks |
| Databases | SQLite (WAL mode), sqlite-vec (ANN embeddings), Qdrant (active) |
| AI/ML | Ollama, Google Gemini, Anthropic Claude, OpenRouter, Groq Whisper, Toxic-BERT, FlashRank (ms-marco-TinyBERT), sentence-transformers, Crawl4AI |
| Messaging | Baileys (WhatsApp), python-telegram-bot (Telegram), discord.py (Discord), slack-bolt + slack-sdk (Slack) |
| Infrastructure | macOS `launchd`, OrbStack/Docker, distributed compute (remote GPU node) |
| Testing | pytest, asyncio_mode=auto, 302 tests (unit / integration / smoke / performance / e2e / acceptance) |
| Config | `~/.synapse/synapse.json` -- single config file for all providers, channels, model mappings |

---

## Service Ports

| Service | Port |
| --- | --- |
| API Gateway (FastAPI) | 8000 |
| Qdrant | 6333 |
| Ollama | 11434 |
| Baileys bridge (WhatsApp, internal) | 5010 |

The Baileys bridge is spawned and managed automatically by the WhatsApp channel adapter
on gateway startup -- it is not a manually started service.

---

## Repository Layout

```
workspace/
├── sci_fi_dashboard/              # Core application
│   ├── api_gateway.py             #   Central FastAPI gateway (~1,200 lines)
│   ├── memory_engine.py           #   Hybrid RAG engine (Phoenix v3)
│   ├── sqlite_graph.py            #   SQLite knowledge graph
│   ├── dual_cognition.py          #   Inner monologue + tension engine
│   ├── toxic_scorer_lazy.py       #   Lazy-loaded Toxic-BERT scorer
│   ├── retriever.py               #   ANN + FTS + reranker pipeline
│   ├── llm_router.py              #   litellm.Router wrapper (SynapseLLMRouter)
│   ├── conflict_resolver.py       #   Conflict detection & dedup
│   ├── smart_entity.py            #   FlashText entity extraction
│   ├── chat_parser.py             #   Chat log parser
│   ├── channels/                  #   Multi-channel abstraction layer
│   │   ├── base.py                #     BaseChannel ABC + ChannelMessage DTO
│   │   ├── registry.py            #     ChannelRegistry lifecycle manager
│   │   ├── whatsapp.py            #     Baileys bridge supervisor + HTTP client
│   │   ├── telegram.py            #     python-telegram-bot v22+ adapter
│   │   ├── discord_channel.py     #     discord.py v2.x adapter
│   │   └── slack.py               #     slack-bolt Socket Mode adapter
│   ├── gateway/                   #   Async message pipeline
│   │   ├── queue.py               #     Bounded async task queue (max 100)
│   │   ├── worker.py              #     Concurrent message workers (x2)
│   │   ├── sender.py              #     Outbound message dispatch
│   │   ├── dedup.py               #     5-minute deduplication window
│   │   └── flood.py               #     3-second batch aggregator
│   └── sbs/                       #   Soul-Brain Sync persona engine
│       ├── orchestrator.py        #     SBS lifecycle manager
│       ├── ingestion/             #     Raw log → JSONL pipeline
│       ├── processing/            #     Realtime + batch analysis
│       ├── injection/             #     Profile → system prompt compiler
│       ├── profile/               #     8-layer behavioral profile store
│       ├── feedback/              #     Implicit feedback detection
│       └── sentinel/              #     File governance guardrails
├── synapse_config.py              # Config root (~/.synapse/), path contract
├── db/                            # Database tools & ingestion
│   ├── tools.py                   #   Platform-aware browser (Crawl4AI/Playwright)
│   ├── model_orchestrator.py      #   3-tier local model routing
│   ├── audio_processor.py         #   Groq Whisper transcription
│   └── ingest.py                  #   Bulk file ingestion pipeline
├── scripts/                       # Maintenance & utilities
├── tests/                         # 302 tests across 24 files
├── monitor.py                     # Real-time observability dashboard
├── main.py                        # CLI interface (chat, verify, ingest, vacuum)
└── change_tracker.py              # Auto git commit tracker
baileys-bridge/                    # Node.js WhatsApp bridge (Baileys)
│   └── index.js                   #   HTTP server: /send /typing /seen /health /qr
```

---

## API Reference

| Method | Route | Description |
| --- | --- | --- |
| `POST` | `/chat/<persona_id>` | Chat as a specific persona -- routes are dynamic, defined in `personas.yaml` |
| `POST` | `/chat` | Generic fallback chat |
| `POST` | `/channels/whatsapp/webhook` | Inbound webhook from Baileys bridge |
| `POST` | `/channels/telegram/webhook` | Inbound webhook (if webhook mode used instead of polling) |
| `GET` | `/whatsapp/status/{id}` | Poll status of enqueued message |
| `GET` | `/qr` | Fetch WhatsApp QR code for pairing |
| `POST` | `/persona/rebuild` | Rebuild persona profiles from logs |
| `GET` | `/persona/status` | Profile statistics |
| `POST` | `/ingest` | Ingest structured fact into knowledge graph |
| `POST` | `/add` | Unstructured memory -- triple extraction |
| `POST` | `/query` | Query the knowledge graph |
| `GET` | `/health` | System health check |
| `GET` | `/v1/models` | OpenAI-compatible model list |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat proxy |

---

## Functional Scope

> *This is a single-user, single-node system -- not a distributed platform. But it covers a surface area of concerns typically split across multiple tools and teams:*
>
> **Async message processing** -- **Multi-model intent routing** -- **Hybrid knowledge retrieval** (vector + graph + FTS) -- **Continuous behavioral profiling** -- **Privacy-first memory partitioning** -- **Multi-channel messaging** -- **Voice transcription** -- **Web browsing** -- **File governance** -- **Thermal-aware maintenance** -- **Service lifecycle management**
>
> *Built and maintained by a single engineer on consumer hardware.*

---

## Engineering Philosophy

- **Constraint-Driven Design.** The entire system was engineered to run on a $999 laptop with 8GB RAM. Every architectural decision was made under real resource pressure -- not theoretical, not aspirational.
- **Production Mindset.** This is not a demo. It processes real messages, from a real user, every day. Uptime, latency, and reliability are measured.
- **Iterate From Feedback.** Every major subsystem was redesigned at least once based on production observations. NetworkX was replaced after RAM profiling. The channel layer was abstracted after the second platform was added. The LLM router was rebuilt on litellm after outgrowing direct API calls.
- **End-to-End Ownership.** One engineer. Full stack. From SQLite schema design to async Python workers to shell-script orchestration to real-time monitoring dashboards.

---

## OpenClaw -- Acknowledgements and Inspiration

Synapse was originally built on top of [OpenClaw](https://github.com/nicepkg/openclaw)'s gateway infrastructure, and the influence runs deep.

OpenClaw's approach to local AI tooling -- treating the terminal as a first-class AI interface -- shaped how Synapse thinks about the relationship between the AI brain and its communication channels. The idea that your AI assistant should run on your machine, respect your data, and work through whatever interface you prefer did not originate with Synapse. It came from using OpenClaw daily and internalizing its philosophy.

As Synapse's requirements grew -- multi-channel support, custom LLM routing through litellm, self-hosted hybrid memory, evolving persona profiles -- we built our own Baileys bridge, litellm router, and channel abstraction layer. The system outgrew the original gateway dependency. But the original inspiration and architectural direction came from OpenClaw.

Deep respect and gratitude to the OpenClaw creators. The spirit of "run your own AI, control your own data" lives on in Synapse's privacy-first design: The Vault, hemisphere enforcement, the zero-cloud-leakage guarantee, and the conviction that a personal AI assistant should be exactly that -- personal.

---

## Built By

**Upayan Ghosh** -- Software engineer who built a 15,000+ line production AI system from scratch, on evenings and weekends, on consumer hardware.

This project was built using AI coding tools (Claude, ChatGPT, Gemini) for implementation, with architecture design, system integration, performance profiling, and debugging done by hand. The architectural decisions -- replacing NetworkX with SQLite after profiling RAM pressure, designing the channel abstraction layer, building hemisphere-enforced memory isolation, engineering the SBS pipeline -- those came from staring at real problems and solving them.

I believe in using every tool available to build things that work.

- GitHub: [@UpayanGhosh](https://github.com/UpayanGhosh)
- LinkedIn: [https://linkedin.com/in/upayan](https://linkedin.com/in/upayan)
- Email: [upayan1231@gmail.com](mailto:upayan1231@gmail.com)

**Currently open to:** Backend/AI engineering roles, freelance AI/chatbot projects, and conversations about RAG systems, async architectures, and privacy-first AI design.

---

## Contributors

Thanks to these people for making Synapse better:

| Contributor | Contribution |
| --- | --- |
| [@Aniruddha775](https://github.com/Aniruddha775) | Recursive CTE path search for knowledge graph ([#26](https://github.com/UpayanGhosh/Synapse-OSS/pull/26)) |

Want to contribute? Check out [CONTRIBUTING.md](CONTRIBUTING.md) to get started.

---

## Documentation

| Document | Description |
| --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Full system architecture with Mermaid diagrams |
| [HOW_TO_RUN.md](HOW_TO_RUN.md) | Complete setup and deployment guide |
| [SETUP_PERSONA.md](SETUP_PERSONA.md) | Persona customization guide |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, test commands, and PR guidelines |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Community code of conduct |
