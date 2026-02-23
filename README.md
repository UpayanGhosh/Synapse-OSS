---
# 🧬 JARVIS — Production-Grade AI Assistant
---
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Lines of Code](https://img.shields.io/badge/Lines_of_Code-15,000+-blueviolet?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Production-brightgreen?style=for-the-badge)

A self-hosted, model-agnostic AI assistant with hybrid memory retrieval, multi-model routing, and an autonomous persona-evolution pipeline — running 24/7 on consumer hardware.

> **New here?** Jump to [Quick Start](#-quick-start) or read [HOW_TO_RUN.md](HOW_TO_RUN.md) for full setup instructions.
>
> **Want the story behind the engineering?** Read [MANIFESTO.md](MANIFESTO.md) — the opinionated, in-character deep-dive.

---

## 📊 By The Numbers

> `15,000+ lines of production code` · `99.2% memory reduction` · `<350ms P95 retrieval` · `6 models orchestrated` · `Zero timeout failures` · `24/7 uptime on $999 hardware` · `92 Python modules`

| Metric | Before (v1.0) | After (Phoenix v3) | Improvement |
|---|---|---|---|
| Cognitive Memory Footprint | ~155MB in-RAM graph | <1.2MB SQLite-backed | **99.2% reduction** |
| Host RAM Usage | 81.3% | <25% single-process | **3.3× lower** |
| Retrieval Latency (P95) | ~1.2s | <350ms hybrid smart gate | **3.4× faster** |
| Vocabulary Diversity | ~5,000 static terms | 37,868+ unique terms | **7.6× richer** |
| Message Pipeline | Synchronous, 30s ceiling | Async queue-push | **Zero timeouts** |

---

## 🏗️ System Architecture

![JARVIS — Project Phoenix Architecture](./architecture_diagram.png)

> *For the full interactive diagram with Mermaid breakdowns of each subsystem, see [ARCHITECTURE.md](ARCHITECTURE.md).*

```mermaid
%%{init: {'theme': 'dark', 'themeVariables': { 'primaryColor': 'transparent', 'primaryTextColor': '#ffffff', 'primaryBorderColor': '#ffffff', 'lineColor': '#ffffff', 'textColor': '#ffffff', 'nodeBorder': '#ffffff', 'mainBkg': 'transparent', 'clusterBkg': 'transparent', 'clusterBorder': '#aaaaaa'}}}%%
graph TD
    %% --- SECTION 1: INGRESS (LEFT) ---
    subgraph Inputs ["User Inputs"]
        U1["📱 WhatsApp Webhook<br/>Node Gateway"]:::user
        U2["💻 OpenClaw CLI<br/>Proxy Request"]:::user
    end

    %% --- SECTION 2: ASYNC PIPELINE (LEFT-CENTER) ---
    subgraph Async_Pipeline ["Async Gateway Pipeline"]
        FG{"🛡️ FloodGate<br/>Batch Window 3s"}:::async
        DD["🔁 MessageDeduplicator<br/>5-min window"]:::async
        Q["📦 TaskQueue<br/>max 100"]:::async
        W["⚙️ MessageWorker<br/>2 concurrent"]:::async
        
        FG --> DD
        DD --> Q
        Q --> W
    end

    %% --- SECTION 3: CORE GATEWAY (CENTER) ---
    G(("🚀 Core API Gateway<br/>FastAPI / Uvicorn<br/>:8000")):::gateway

    %% Connections into Gateway
    U1 -->|"HTTP POST /webhook"| FG
    U2 -->|"CLI Proxy"| G
    W --> G

    %% --- SECTION 4: CONTEXT & MEMORY (ABOVE GATEWAY) ---
    subgraph Brain_Context ["🤖 Context Engine"]
        subgraph SBS ["Soul-Brain Sync — Persona Engine"]
            SBS_O["🎭 SBS Orchestrator"]:::sbs
            SBS_P["📋 Profile Manager"]:::sbs
            SBS_L["📝 Conversation Logger"]:::sbs
            SBS_RT["⚡ Realtime Processor"]:::sbs
            SBS_B["🔄 Batch Processor"]:::sbs
            SBS_C["🖊️ Prompt Compiler"]:::sbs
            
            SBS_O --- SBS_P
            SBS_P --- SBS_L
            SBS_O --- SBS_RT
            SBS_RT --- SBS_B
            SBS_O --- SBS_C
        end

        subgraph Cognitive_Memory ["💾 Cognitive Memory"]
            ME["🧠 Memory Engine<br/>Hybrid Retrieval v3"]:::memory
            M1["🗃️ SQLite Graph DB"]:::memory
            M2["🔷 Qdrant Vector DB"]:::memory
            RE["🏅 FlashRank Reranker"]:::memory
            
            ME <--> M1
            ME <--> M2
            ME --> RE
        end

        subgraph Dual_Cognition ["🧩 Dual Cognition"]
            DC["🧩 DualCognitionEngine"]:::memory
            TS["☣️ LazyToxicScorer"]:::memory
            DC --- TS
        end
    end

    %% Connections from Gateway to Context
    G <-->|"Inject Persona Context"| SBS_O
    G <-->|"Semantic + Graph Query"| ME
    G -->|"Tension Check"| DC


    %% --- SECTION 5: MOA AGENTS (RIGHT) ---
    subgraph Mixture_of_Agents ["🚀 Mixture of Agents"]
        TC{"🚦 Traffic Cop<br/>Intent Classifier"}:::moa
        
        subgraph Agents ["LLM Agents"]
            LLM1["🟢 Gemini 3 Flash<br/>(CASUAL)"]:::moa
            LLM2["💻 The Hacker<br/>(CODING)"]:::moa
            LLM3["🏛️ The Architect<br/>(ANALYSIS)"]:::moa
            LLM4["🧐 The Philosopher<br/>(REVIEW)"]:::moa
            LLM5["🌶️ The Vault<br/>(SPICY)"]:::local
        end

        TC -->|"CASUAL"| LLM1
        TC -->|"CODING"| LLM2
        TC -->|"ANALYSIS"| LLM3
        TC -->|"REVIEW"| LLM4
        TC -->|"SPICY"| LLM5
    end

    %% --- SECTION 6: RETURN PATH (RIGHT) ---
    G -->|"Classify Intent"| TC
    
    LLM1 -->|"Response + Stats"| G
    LLM2 -->|"Response + Stats"| G
    LLM3 -->|"Response + Stats"| G
    LLM4 -->|"Response + Stats"| G
    LLM5 -->|"Response + Stats"| G

    G -->|"Auto-Continue if cut-off"| AC["✂️ Auto-Continue"]:::async
    G -->|"Final Output"| Out["📨 Output"]:::user

    AC -.->|"continues..."| G
```

---

## 🎯 Engineering Competencies Demonstrated

| **Competency**                   | **Evidence in This Repo**                                                                                                                                                                                      |
| :------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **System Design & Architecture** | Designed and implemented a single-process architecture (Phoenix v3) that reduced memory footprint from 155MB to <1.2MB — a **99.2% compression** — while improving retrieval speed by 3.4× |
| **Distributed Systems**          | Built an async queue-push message gateway with deduplication, flood batching, and concurrent workers — achieving **zero timeout failures** in production                                                       |
| **Database Engineering**         | Migrated from an in-memory graph (NetworkX + Qdrant) to a custom **SQLite-backed knowledge graph** with hybrid vector + full-text search, eliminating an entire infrastructure dependency                       |
| **ML Pipeline Orchestration**    | Implemented a **Mixture of Agents (MoA)** routing layer that classifies intent and dispatches to 6 specialized models (Gemini, Claude, Ollama) through a unified OpenAI SDK interface                           |
| **Performance Optimization**     | Engineered lazy-loading patterns (Toxic-BERT loads on demand, unloads after 30s), `keep_alive: 0` model eviction, and thermal-aware background workers — all to run on a MacBook Air                               |
| **Security Architecture**        | Designed an air-gapped "Vault Protocol" with hemisphere-enforced memory separation, verified by automated integrity tests                                                                                            |
| **DevOps & Reliability**         | Built a `launchd`-managed boot sequence with idempotent service control, auto-restart, 12-hour backup rotation, and a real-time observability dashboard                                                            |
| **Autonomous Data Pipelines**    | Created the "Soul-Brain Sync" — an autonomous ingestion → parsing → distillation pipeline that converts raw conversation logs into a 2KB behavioral profile, injected at inference time                           |

---

## 🛠️ Technical Stack

| **Category** | **Technologies**                                                                                               |
| :----------------- | :------------------------------------------------------------------------------------------------------------------- |
| Languages          | Python 3.11, JavaScript (Node.js), Bash                                                                              |
| Frameworks         | FastAPI, Uvicorn, OpenAI SDK                                                                                         |
| Databases          | SQLite, sqlite-vec, Qdrant                                                                           |
| AI/ML              | Ollama, Google Gemini, Anthropic Claude, OpenRouter, Toxic-BERT, FlashRank, sentence-transformers, Whisper           |
| Infrastructure     | macOS launchd, OrbStack/Docker, distributed compute (remote GPU node)                                                |
| Practices          | Async programming, queue-based architectures, model-agnostic routing, automated testing, auto-commit version control |

---

## 🏢 Industry Equivalent

> *This system — built and maintained by a single engineer — replicates functionality that typically requires a 3–5 person platform engineering team:*
>
> **Message Queuing** *(like AWS SQS)* · **Model Routing** *(like AWS Bedrock)* · **Knowledge Retrieval** *(like Pinecone)* · **Real-Time Monitoring** *(like Datadog)* · **Behavioral Pipelines** *(like custom ML Ops)* · **Service Orchestration** *(like systemd/Kubernetes)*
>
> *All running on consumer hardware. All production-tested. All in this repo.*

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/UpayanGhosh/Jarvis-OSS.git
cd Jarvis-OSS

# 2. Environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env — add at minimum one LLM API key (GEMINI_API_KEY recommended)

# 4. Boot the Gateway
cd workspace/sci_fi_dashboard
python3 api_gateway.py
# Gateway starts on http://localhost:8000

# 5. Verify
curl http://localhost:8000/health
```

> **Full setup guide** (Qdrant, Ollama, WhatsApp bridge, persona config): [HOW_TO_RUN.md](HOW_TO_RUN.md)
>
> **Persona customization** (how to make JARVIS yours): [SETUP_PERSONA.md](SETUP_PERSONA.md)

---

## ⚙️ Key Features

### Async Gateway Pipeline
Messages enter through a multi-stage async pipeline (`gateway/`) that prevents webhook timeouts. A `FloodGate` batches rapid-fire messages (3s window), a `MessageDeduplicator` absorbs retry storms (5-min window), and a bounded `TaskQueue` (max 100) feeds two concurrent `MessageWorker` instances. The webhook returns `202 Accepted` immediately — the cognitive pipeline processes at its own pace. **Zero timeout failures in production.**

### Mixture of Agents (MoA) Routing
A lightweight intent classifier ("Traffic Cop") routes each message to the best-fit model: Gemini Flash for casual chat, Claude Sonnet for code generation, Gemini Pro for deep analysis, Claude Opus for critical review, or a local Ollama instance for private conversations. All models are accessed through a unified proxy, making the system completely vendor-agnostic.

### Hybrid Memory Retrieval (RAG)
The `MemoryEngine` combines a SQLite-backed knowledge graph (subject–predicate–object triples) with Qdrant vector search (`nomic-embed-text` embeddings). A temporal scoring function blends semantic similarity with recency. High-confidence results (>0.80) skip the reranker for speed; lower-confidence candidates pass through FlashRank (ms-marco-TinyBERT) for precision. Result: **<350ms P95 retrieval** across 37,000+ vocabulary terms.

### Soul-Brain Sync (SBS) — Autonomous Persona Profiling
Rather than static system prompts, the SBS pipeline continuously builds and evolves a 2KB behavioral profile per conversation target. A `RealtimeProcessor` captures sentiment, language mix, and mood on every message. A `BatchProcessor` runs periodically (every 50 messages or 6 hours) to distill conversation patterns into structured JSON layers (emotional state, linguistic style, vocabulary). The `PromptCompiler` injects this profile into the system prompt at inference time.

### Dual Cognition Engine
Before generating a reply, a `DualCognitionEngine` produces an inner monologue and calculates a tension score (0.0–1.0) to detect emotional conflicts between retrieved memory and the current message. This cognitive context is injected into the prompt alongside memories and persona. The `LazyToxicScorer` (Toxic-BERT) loads on demand and auto-unloads after 30s of idle to conserve RAM.

### Air-Gapped Privacy ("The Vault")
Sensitive conversations route to a local Ollama instance on a dedicated compute node (RTX 3060Ti). Zero cloud, zero logging, zero leakage. Hemisphere integrity is verified by automated tests (`verify` CLI command).

---

## 📁 Repository Layout

```
workspace/
├── sci_fi_dashboard/              # Core application
│   ├── api_gateway.py             #   Central FastAPI gateway (1,188 lines)
│   ├── memory_engine.py           #   Hybrid RAG engine (Phoenix v3)
│   ├── sqlite_graph.py            #   SQLite knowledge graph
│   ├── dual_cognition.py          #   Inner monologue + tension engine
│   ├── toxic_scorer_lazy.py       #   Lazy-loaded Toxic-BERT scorer
│   ├── retriever.py               #   Qdrant + reranker utilities
│   ├── conflict_resolver.py       #   Conflict detection & dedup
│   ├── smart_entity.py            #   FlashText entity extraction
│   ├── chat_parser.py             #   WhatsApp chat log parser
│   ├── gateway/                   #   Async message pipeline
│   │   ├── queue.py               #     Bounded async task queue
│   │   ├── worker.py              #     Concurrent message workers
│   │   ├── sender.py              #     WhatsApp outbound via CLI
│   │   ├── dedup.py               #     Message deduplication
│   │   └── flood.py               #     Batch window aggregator
│   └── sbs/                       #   Soul-Brain Sync persona engine
│       ├── orchestrator.py        #     SBS lifecycle manager
│       ├── ingestion/             #     Raw log → JSONL pipeline
│       ├── processing/            #     Realtime + batch analysis
│       ├── injection/             #     Profile → system prompt
│       ├── profile/               #     Behavioral profile store
│       ├── feedback/              #     Implicit feedback detection
│       └── sentinel/              #     File governance guardrails
├── scripts/                       # Maintenance & utilities
│   ├── revive_jarvis.sh           #   Full system resurrection
│   ├── ram_watchdog.py            #   Memory pressure monitor
│   ├── latency_watcher.py         #   Response time tracker
│   ├── nightly_ingest.py          #   Scheduled memory digestion
│   ├── fact_extractor.py          #   LLM → knowledge triple extraction
│   └── transcribe_v2.py           #   Voice note → text (Whisper)
├── monitor.py                     # Real-time observability dashboard
├── main.py                        # CLI interface (chat, verify, ingest, vacuum)
└── change_tracker.py              # Auto git commit tracker
```

---

## 🔌 API Reference

| Method | Route | Description |
|---|---|---|
| `POST` | `/chat/the_creator` | Chat as primary user persona |
| `POST` | `/chat/the_partner` | Chat as partner persona |
| `POST` | `/chat` | Generic fallback chat |
| `POST` | `/whatsapp/enqueue` | Async WhatsApp message ingress |
| `GET`  | `/whatsapp/status/{id}` | Poll status of enqueued message |
| `POST` | `/persona/rebuild` | Rebuild persona profiles from logs |
| `GET`  | `/persona/status` | Profile statistics |
| `POST` | `/ingest` | Ingest structured fact into graph |
| `POST` | `/add` | Unstructured memory → triple extraction |
| `POST` | `/query` | Query the knowledge graph |
| `GET`  | `/health` | System health check |
| `GET`  | `/v1/models` | OpenAI-compatible model list |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat proxy |

---

## 📐 What This Demonstrates Beyond Code

- **Architectural Decision-Making:** Every major subsystem was redesigned at least once based on production feedback — not theoretical planning.
- **Constraint-Driven Engineering:** The entire system was optimized to run on a $999 laptop with 8GB RAM. Every design choice was made under real resource pressure.
- **Production Mindset:** This isn't a demo. It processes real messages, from real users, every day. Uptime, latency, and reliability are measured, not aspirational.
- **End-to-End Ownership:** One engineer. Full stack. From SQLite schema design to async Python workers to shell-script orchestration to real-time monitoring dashboards.

---

## 🙏 Attribution

> This entire project was built on the foundation of **[OpenClaw](https://github.com/openclaw/openclaw)**. OpenClaw provides the terminal instrumentation, browser automation, and multi-agent coordination system that made this "brain" possible. Deep respect and gratitude to the creators and maintainers of OpenClaw.

---

## 📚 Documentation

| Document | Description |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Full system architecture with Mermaid diagrams |
| [HOW_TO_RUN.md](HOW_TO_RUN.md) | Complete setup and deployment guide |
| [SETUP_PERSONA.md](SETUP_PERSONA.md) | Persona customization guide |
| [MANIFESTO.md](MANIFESTO.md) | The in-character design philosophy deep-dive |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Community code of conduct |
