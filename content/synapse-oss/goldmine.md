# Synapse-OSS — Content Goldmine
_Generated: 2026-03-28_
_Findings: 72_

## Summary
Synapse-OSS is a personal AI assistant built by Upayan Ghosh in Kolkata — a developer transitioning into GenAI. It runs on WhatsApp, Telegram, Discord, and Slack simultaneously, routes messages through a multi-stage pipeline, and learns the user's personality over time through a system called Soul-Brain Sync. It's designed to run on 8GB RAM with local LLMs via Ollama, with cloud fallback to Gemini/Claude/OpenRouter. The project went from a private monolith with a WhatsApp-only bridge to a fully open-source, multi-channel, hybrid RAG system over dozens of phase-gated commits.

---

## Architecture Findings

### [architecture] networkx-to-sqlite-migration
- **What:** The knowledge graph was migrated from NetworkX (in-memory graph library) to a custom SQLite implementation, cutting RAM from 155MB to 1.2MB.
- **Why interesting:** A 99.2% RAM reduction on a 8GB machine is a life-or-death decision, not an optimization.
- **Hook potential:** High
- **Depth:** 90s alone — the before/after numbers are the whole story
- **Related:** ram-pressure-optimization, sqlite-wal-tuning

### [architecture] soul-brain-sync-pipeline
- **What:** A 3-stage pipeline (realtime → batch every 50 msgs/6h → compiler) that distills conversation history into 8 profile layers injected as a ~1500-token system prompt segment.
- **Why interesting:** Most chatbots have static system prompts. This one evolves after every 50 messages and rebuilds Upayan's personality model automatically.
- **Hook potential:** High
- **Depth:** 90s alone (overview); each stage could be its own reel
- **Related:** eight-layer-profile-system, prompt-compiler

### [architecture] dual-cognition-inner-monologue
- **What:** Every response goes through a `DualCognitionEngine` that generates an internal "inner monologue" and scores tension between what the AI thinks vs what it says.
- **Why interesting:** The AI has thoughts it doesn't say out loud. That tension score influences response generation.
- **Hook potential:** High
- **Depth:** 90s alone — "my AI has thoughts it keeps to itself" is a natural hook
- **Related:** fast-phrase-bypass

### [architecture] multi-channel-basechannel-abc
- **What:** WhatsApp, Telegram, Discord, and Slack all implement the same `BaseChannel` ABC with 6 methods: `receive()`, `send()`, `send_typing()`, `start()`, `stop()`.
- **Why interesting:** Adding a 5th channel is a single file. The abstraction layer is the architecture.
- **Hook potential:** Medium
- **Depth:** Needs pairing with channel-registry-lifecycle for a full 90s
- **Related:** channel-registry-lifecycle, dm-access-control-resolution

### [architecture] lazy-toxic-bert-model
- **What:** The `LazyToxicScorer` loads a 600MB Toxic-BERT model only when needed and auto-unloads it after 30 seconds of idle time.
- **Why interesting:** On an 8GB machine, a 600MB model you never unload is a machine you eventually restart. The auto-unload pattern is the solution.
- **Hook potential:** Medium
- **Depth:** Combine with ram-pressure-optimization for a full reel
- **Related:** ram-pressure-optimization, groq-whisper-zero-ram

### [architecture] websocket-control-plane
- **What:** A WebSocket server at `ws://127.0.0.1:8000/ws` provides a real-time control plane with typed JSON frames — methods like `chat.send`, `channels.status`, `models.list`.
- **Why interesting:** It's not just a chat API — it's a full control plane for the AI's brain, accessible from any client.
- **Hook potential:** Medium
- **Depth:** 90s alone with a live demo angle
- **Related:** session-actor-queue

### [architecture] hemisphere-memory-separation
- **What:** The memory database has two logical hemispheres: `safe` and `spicy`. The private "Vault" mode queries only the spicy hemisphere and routes to a local Ollama model, air-gapped from cloud APIs.
- **Why interesting:** Some memories are too personal for the cloud. The hemisphere tag enforces this at query time.
- **Hook potential:** High
- **Depth:** 90s alone — "my AI has a secret hemisphere" is the hook
- **Related:** hybrid-rag-retrieval, dm-access-control-resolution

### [architecture] gateway-pipeline-five-stages
- **What:** Every inbound message passes through 5 sequential stages before processing: FloodGate (3s batching) → Dedup (5-min TTL) → TaskQueue (max 100) → MessageWorker x2 → Send.
- **Why interesting:** Each stage solves a different failure mode. Remove any one and the system breaks differently.
- **Hook potential:** High
- **Depth:** Could do one reel per stage OR one overview reel
- **Related:** flood-gate-batching, dedup-ttl-filter, task-queue-asyncio

---

## Decision Findings

### [decision] sqlite-only-no-postgres
- **What:** The entire system — documents, embeddings, knowledge graph, sessions, media metadata — lives in SQLite files. No Postgres, no Qdrant, no Redis.
- **Why interesting:** Every "serious" AI project reaches for Postgres+Qdrant+Redis. This one doesn't. The trade-off is explicit: developer simplicity over operational power.
- **Hook potential:** High
- **Depth:** 90s alone — hot take content
- **Related:** sqlite-wal-tuning, networkx-to-sqlite-migration

### [decision] litellm-for-16-providers
- **What:** A single `litellm.Router` call dispatches to Gemini, Claude, Ollama, OpenRouter, Groq, Cohere, xAI, and 9 more providers without custom client code.
- **Why interesting:** litellm is the unsung hero of the GenAI ecosystem. It's the one library that makes multi-provider routing not a nightmare.
- **Hook potential:** Medium
- **Depth:** 90s alone with a code walkthrough angle
- **Related:** banglish-to-gemini-routing, llm-routing-by-intent

### [decision] llm-routing-by-intent
- **What:** Message intent determines which LLM runs: Banglish/default → Gemini Flash, code → Claude Sonnet (with thinking), deep analysis → Gemini Pro, private/Vault → local Ollama.
- **Why interesting:** Different tasks need different brains. The router makes this invisible to the user.
- **Hook potential:** High
- **Depth:** 90s alone — "I use 4 different AIs for 4 different jobs" is the hook
- **Related:** litellm-for-16-providers, hemisphere-memory-separation

### [decision] banglish-routing-default
- **What:** Banglish (Bengali written in English letters) is the default language detection case, routing to Gemini Flash because it handles code-switching better than other models.
- **Why interesting:** Most AI systems treat non-English as an edge case. Here it's the primary case, and the routing decision reflects that.
- **Hook potential:** High
- **Depth:** 90s alone — personal/cultural angle is rare in tech content
- **Related:** llm-routing-by-intent

### [decision] async-first-no-celery
- **What:** The entire system is Python asyncio — no Celery, no Redis task queue, no background workers as separate processes.
- **Why interesting:** Celery is the "enterprise" default. Pure asyncio is the bet that one event loop is enough.
- **Hook potential:** Medium
- **Depth:** Pair with task-queue-asyncio for a full reel
- **Related:** task-queue-asyncio, session-actor-queue

### [decision] atomic-shadow-table-ingestion
- **What:** Memory ingestion writes to a shadow table first, then swaps it atomically. Partial ingestion never corrupts the live table.
- **Why interesting:** SQLite doesn't have transactions the way Postgres does. This pattern gets you the same guarantee without leaving the SQLite ecosystem.
- **Hook potential:** Medium
- **Depth:** 90s alone with a "what breaks without it" angle
- **Related:** sqlite-wal-tuning, content-hash-dedup

### [decision] dm-policy-enum
- **What:** Each channel has a `DmPolicy` enum: `pairing | allowlist | open | disabled`. Who can DM your AI is a config value, not hardcoded.
- **Why interesting:** Your AI assistant can receive messages from strangers. This is the access control layer most personal-AI projects skip.
- **Hook potential:** Medium
- **Depth:** Pair with dm-access-control-resolution for a full reel
- **Related:** dm-access-control-resolution, jsonl-pairing-store

### [decision] modular-requirements-split
- **What:** `requirements.txt` is split into sections: core, channels, ml, optional, dev — so you can install only what you need.
- **Why interesting:** ML dependencies are massive. Making them optional means the core system installs in 30 seconds.
- **Hook potential:** Low
- **Depth:** Needs combining with another topic
- **Related:** lazy-toxic-bert-model

### [decision] no-qdrant-sqlite-vec
- **What:** Vector search uses `sqlite-vec` (a SQLite extension) instead of a dedicated vector database like Qdrant or Pinecone.
- **Why interesting:** Qdrant requires a separate server. sqlite-vec lives in the same file as your memories. The performance difference at personal-project scale is negligible.
- **Hook potential:** Medium
- **Depth:** 90s alone — "I replaced Qdrant with a SQLite extension" is a hot take
- **Related:** sqlite-only-no-postgres, hybrid-rag-retrieval

### [decision] openrouter-as-fallback
- **What:** OpenRouter is the catch-all fallback when all primary providers fail or rate-limit. It routes to whatever model is available at that moment.
- **Why interesting:** The system never goes down because of a single provider's outage. The fallback chain is the reliability guarantee.
- **Hook potential:** Medium
- **Depth:** Combine with litellm-for-16-providers for a full reel
- **Related:** litellm-for-16-providers, llm-routing-by-intent

---

## Struggle & Bug Findings

### [struggle] ram-pressure-optimization
- **What:** On an 8GB machine, the system went from consuming 81.3% RAM (v1) to under 25% (v3) through three rounds of optimization: NetworkX → SQLite, lazy model loading, and process isolation.
- **Why interesting:** This wasn't premature optimization. At 81%, the machine was unusable while the AI was running.
- **Hook potential:** High
- **Depth:** 90s alone — the three-round story arc is complete
- **Related:** networkx-to-sqlite-migration, lazy-toxic-bert-model

### [struggle] openclaw-dependency-removal
- **What:** Early versions of Synapse depended on OpenClaw (a private WhatsApp bridge binary). The commit `ad4df70` removes all OpenClaw references from the public repo, replacing it with a Baileys-based bridge.
- **Why interesting:** The entire WhatsApp integration had to be rebuilt in public after the dependency was pulled. That's a full rewrite under pressure.
- **Hook potential:** High
- **Depth:** 90s alone — dependency death is a universal developer fear
- **Related:** baileys-crash-recovery

### [struggle] baileys-crash-recovery
- **What:** The Baileys Node.js WhatsApp bridge crashes unexpectedly. The Python side implements exponential backoff reconnection to handle this gracefully.
- **Why interesting:** Two runtimes (Python + Node.js) bridged via HTTP. When Node dies, Python has to know and recover without losing the session.
- **Hook potential:** Medium
- **Depth:** 90s alone — cross-runtime crash recovery is a niche but real problem
- **Related:** openclaw-dependency-removal

### [struggle] telegram-enqueue-fn-bug
- **What:** Telegram's flood adapter was broken: the `enqueue_fn` wasn't being registered correctly because the factory pattern wasn't applied. Fixed in commit `4d59350`.
- **Why interesting:** A subtle factory pattern bug that caused messages to silently drop. The fix was one function wrapper.
- **Hook potential:** Medium
- **Depth:** Pair with flood-gate-batching for context
- **Related:** flood-gate-batching, make-flood-enqueue-factory

### [struggle] windows-ci-lint-failures
- **What:** Ruff CI kept failing on Windows due to platform-specific import patterns and noqa comment format mismatches (`# noqa: LLM-16` is invalid).
- **Why interesting:** CI is supposed to be OS-agnostic. It isn't. The fix was a series of commits before green.
- **Hook potential:** Low
- **Depth:** Combine with another struggle for a "things that actually take time" reel
- **Related:** modular-requirements-split

### [struggle] datetime-utcnow-deprecation
- **What:** Python 3.12 deprecated `datetime.utcnow()`. Finding and replacing every call across the codebase required a systematic grep pass.
- **Why interesting:** Every Python codebase that started before 3.12 has this debt. The fix is mechanical but the scope is surprising.
- **Hook potential:** Low
- **Depth:** Combine with other "boring but necessary" tasks
- **Related:** windows-ci-lint-failures

### [struggle] mac-fresh-setup-hurdles
- **What:** Commit `1d0240a` — "fix(onboarding): resolve all hurdles found during fresh Mac setup" — came after a real Mac setup attempt revealed the onboarding wizard had 6 gaps.
- **Why interesting:** You don't know what's broken until someone actually installs from scratch on a clean machine.
- **Hook potential:** Medium
- **Depth:** 90s alone — dogfooding is the only way to find onboarding bugs
- **Related:** cross-platform-daemon-install

### [struggle] cross-platform-daemon-install
- **What:** Installing Synapse as a background daemon required three different backends: `launchd` (Mac), `systemd` (Linux), and Windows Task Scheduler — all wired through one `onboard.py` wizard.
- **Why interesting:** "Just run it in the background" hides three completely different OS APIs.
- **Hook potential:** Medium
- **Depth:** 90s alone — the branching platform logic is the story
- **Related:** mac-fresh-setup-hurdles

### [struggle] mime-detection-precedence
- **What:** Media MIME type detection falls through 4 layers: python-magic (magic bytes) → HTTP Content-Type header → file extension → fallback to `application/octet-stream`.
- **Why interesting:** Every layer can lie. The precedence order is a statement about which source is least likely to lie.
- **Hook potential:** Medium
- **Depth:** 90s alone — "which liar do you trust most?" is the hook
- **Related:** media-pipeline-ssrf-guard

### [struggle] phase-based-development-story
- **What:** The entire codebase was built phase by phase (phase 06 through 09+) with explicit PLAN.md → VERIFICATION.md cycles before merging each phase.
- **Why interesting:** Most personal projects are built in bursts of chaos. This one has documented phases, gap-closure plans, and UAT verification records in git history.
- **Hook potential:** High
- **Depth:** 90s alone — "how I actually build big things alone" is high-value meta content
- **Related:** soul-brain-sync-pipeline

---

## Tool-Tip Findings

### [tool-tip] flashrank-bypass-for-speed
- **What:** When FlashRank's top result has confidence above a threshold, the reranking step is skipped entirely — dropping P95 retrieval latency from 1.2s to under 350ms.
- **Why interesting:** The most expensive operation in RAG is often reranking. Skipping it when you're confident is an obvious optimization that's easy to miss.
- **Hook potential:** Medium
- **Depth:** 90s alone
- **Related:** hybrid-rag-retrieval

### [tool-tip] fast-phrase-bypass
- **What:** Short, common phrases like "hi", "bye", "ok" bypass the full dual-cognition pipeline and return direct responses. The check is a compiled regex.
- **Why interesting:** Running a 600ms inner-monologue pipeline for "ok" is wasteful. Pattern matching before the pipeline is the fix.
- **Hook potential:** Medium
- **Depth:** Combine with dual-cognition-inner-monologue
- **Related:** dual-cognition-inner-monologue

### [tool-tip] peak-end-rule-in-sql
- **What:** The `EmotionalTrajectory` module applies the Peak-End Rule from psychology — users remember the most intense moment and the last moment, so SQL ordering weights these specifically.
- **Why interesting:** A psychology principle implemented as an ORDER BY clause. The bridge between behavioral science and SQL.
- **Hook potential:** High
- **Depth:** 90s alone — the psychology angle makes it shareable
- **Related:** eight-layer-profile-system

### [tool-tip] sqlite-lock-retry-backoff
- **What:** SQLite WAL mode doesn't eliminate lock contention under concurrent writes. Every write path has exponential backoff retry logic for `SQLITE_BUSY` errors.
- **Why interesting:** "SQLite doesn't support concurrent writes" is wrong. It does — but only with the right retry logic.
- **Hook potential:** Medium
- **Depth:** Combine with sqlite-wal-tuning for a full reel
- **Related:** sqlite-wal-tuning

### [tool-tip] atomic-config-write
- **What:** All config writes use `tempfile + os.replace()` — write to a temp file, then atomically swap it into place. The config is never half-written.
- **Why interesting:** Config corruption on power loss is a real failure mode. This pattern costs nothing and prevents it entirely.
- **Hook potential:** Medium
- **Depth:** Combine with another tool-tip for a "defensive coding" reel
- **Related:** atomic-shadow-table-ingestion

### [tool-tip] groq-whisper-zero-ram
- **What:** Audio transcription routes to Groq's Whisper API instead of a local Whisper model, keeping local RAM free while still getting fast transcription.
- **Why interesting:** Running Whisper locally on 8GB while also running a local LLM is impossible. Cloud Whisper is the pragmatic solution.
- **Hook potential:** Medium
- **Depth:** Combine with ram-pressure-optimization
- **Related:** ram-pressure-optimization, lazy-toxic-bert-model

### [tool-tip] jsonl-audit-trail
- **What:** The DM pairing store uses append-only JSONL files — one entry per approval event. The file is the audit log and the state store simultaneously.
- **Why interesting:** JSONL is the simplest possible append-only log. No database, no schema migrations, no rollback complexity.
- **Hook potential:** Medium
- **Depth:** Combine with dm-policy-enum
- **Related:** dm-policy-enum, dm-access-control-resolution

### [tool-tip] ollama-context-window-guard
- **What:** `ModelsCatalog` validates each Ollama model's declared context window before routing a message to it. If the message would exceed the window, it routes to a cloud model instead.
- **Why interesting:** Local models silently truncate at their context limit. This guard makes the truncation visible and preventable.
- **Hook potential:** Medium
- **Depth:** 90s alone
- **Related:** litellm-for-16-providers, llm-routing-by-intent

---

## Data-Flow Findings

### [data-flow] full-request-pipeline
- **What:** WhatsApp → POST /whatsapp/enqueue → FloodGate(3s) → Dedup(5min) → TaskQueue(max100) → Worker x2 → SBS+RAG+DualCognition → LLM → Send.
- **Why interesting:** 8 stages between "user sends message" and "AI responds." Each stage has a specific job and a specific failure mode.
- **Hook potential:** High
- **Depth:** One overview reel + 8 per-stage reels
- **Related:** gateway-pipeline-five-stages, flood-gate-batching

### [data-flow] hybrid-rag-retrieval
- **What:** Memory retrieval runs in parallel: ANN search (sqlite-vec) + FTS keyword search, then merges results and reranks with FlashRank.
- **Why interesting:** Neither vector search nor keyword search alone is enough. The merge-then-rerank pattern gets the best of both.
- **Hook potential:** High
- **Depth:** 90s alone
- **Related:** flashrank-bypass-for-speed, no-qdrant-sqlite-vec

### [data-flow] sbs-distillation-cycle
- **What:** Every message updates realtime state immediately. Every 50 messages (or 6 hours), a batch distillation runs and rewrites all 8 profile layers. A compiler then converts these into a 1500-token prompt segment.
- **Why interesting:** The AI literally updates its understanding of you on a schedule. It's a learning loop, not just a chatbot.
- **Hook potential:** High
- **Depth:** 90s alone (overview); each sub-step is its own reel
- **Related:** soul-brain-sync-pipeline, eight-layer-profile-system, prompt-compiler

### [data-flow] dm-access-control-resolution
- **What:** Every DM goes through `resolve_dm_access()` — a pure function that checks policy → pairing store → returns `"allow"` / `"deny"` / `"pending_approval"`.
- **Why interesting:** A pure function for access control means it's trivially testable and has no side effects. The pairing store mutation happens elsewhere.
- **Hook potential:** Medium
- **Depth:** Combine with dm-policy-enum for a full reel
- **Related:** dm-policy-enum, jsonl-audit-trail

### [data-flow] content-hash-dedup
- **What:** Before ingesting any memory, the system hashes the content (MD5) and checks for duplicates. The shadow-table swap only happens if the hash is new.
- **Why interesting:** Without dedup, running the same ingest twice doubles your memory database. The hash check is the guard.
- **Hook potential:** Low
- **Depth:** Combine with atomic-shadow-table-ingestion
- **Related:** atomic-shadow-table-ingestion

### [data-flow] media-pipeline-ssrf-guard
- **What:** Before fetching any media URL, `is_ssrf_blocked()` checks if the target IP is private, loopback, or link-local. SSRF protection before MIME detection.
- **Why interesting:** A WhatsApp bot that fetches arbitrary URLs is an SSRF attack vector. This guard is the first line of defense.
- **Hook potential:** Medium
- **Depth:** 90s alone — security angle resonates broadly
- **Related:** mime-detection-precedence

### [data-flow] emotional-trajectory-peak-end
- **What:** The `EmotionalTrajectory` module queries conversation history ordered by intensity (peak) and recency (end), not chronologically. The SQL WHERE clause encodes the Peak-End Rule.
- **Why interesting:** Psychology in a SQL ORDER BY. The behavioral science rationale is the story, not the code.
- **Hook potential:** High
- **Depth:** 90s alone
- **Related:** peak-end-rule-in-sql

---

## Pattern Findings

### [pattern] eight-layer-profile-system
- **What:** The Soul-Brain Sync maintains 8 JSON profile layers: `core_identity`, `linguistic`, `emotional_state`, `domain`, `interaction`, `vocabulary`, `exemplars`, `meta`.
- **Why interesting:** Most personalization is a single "user preferences" object. 8 typed layers with separate update cadences is a different philosophy.
- **Hook potential:** High
- **Depth:** 90s alone — the layer names alone are the hook
- **Related:** sbs-distillation-cycle, prompt-compiler

### [pattern] channel-registry-lifecycle
- **What:** `ChannelRegistry.start_all()` and `stop_all()` are called from FastAPI's `lifespan` context manager — channels start before the first request and stop after the last.
- **Why interesting:** FastAPI lifespan is the right place for startup/shutdown. Using it for channel lifecycle means no orphaned background tasks.
- **Hook potential:** Low
- **Depth:** Combine with multi-channel-basechannel-abc
- **Related:** multi-channel-basechannel-abc

### [pattern] wizard-prompter-protocol
- **What:** The onboarding wizard uses a `WizardPrompter` Protocol instead of mocking `questionary` directly in tests — a test double defined by behavior, not inheritance.
- **Why interesting:** Protocol-based test doubles don't require mocking libraries. The interface is the contract; any object that satisfies it works.
- **Hook potential:** Medium
- **Depth:** 90s alone — testing philosophy content does well
- **Related:** cross-platform-daemon-install

### [pattern] session-actor-queue
- **What:** `SessionActorQueue` gives each session (user+channel combo) its own `asyncio.Lock`. Two messages from the same user can never be processed in parallel.
- **Why interesting:** Concurrency bugs in chatbots show up as garbled responses. Per-session locks eliminate the class of bugs where two workers race on the same user's state.
- **Hook potential:** Medium
- **Depth:** 90s alone
- **Related:** async-first-no-celery

### [pattern] type-checking-import-guard
- **What:** Circular imports in large Python codebases are resolved with `TYPE_CHECKING` guards — imports that only run at type-check time, not at runtime.
- **Why interesting:** Circular imports are one of Python's most frustrating failure modes at scale. `TYPE_CHECKING` is the idiomatic fix most people never learn.
- **Hook potential:** Medium
- **Depth:** 90s alone
- **Related:** modular-requirements-split

### [pattern] sentinel-file-access-control
- **What:** The Sentinel module controls file access by checking manifest-defined protection levels (CRITICAL/PROTECTED/MONITORED/OPEN) before any file operation in the SBS pipeline.
- **Why interesting:** An AI that can write files needs an access control layer. The Sentinel is that layer — fail-closed by default.
- **Hook potential:** High
- **Depth:** 90s alone — "my AI can't access its own config file without permission" is the hook
- **Related:** hemisphere-memory-separation

### [pattern] safe-task-done-guard
- **What:** `_safe_task_done()` checks `asyncio.Task.done()` before calling `task_done()` on a queue — preventing the `ValueError: task_done() called too many times` crash.
- **Why interesting:** asyncio task accounting bugs are invisible until production. This one-line guard prevents a silent crash.
- **Hook potential:** Low
- **Depth:** Combine with other asyncio patterns
- **Related:** session-actor-queue, async-first-no-celery

### [pattern] flood-gate-batching
- **What:** The `FloodGate` buffers all messages from the same user for 3 seconds before releasing them as a batch — preventing the "rapid-fire message" problem where each message triggers a separate LLM call.
- **Why interesting:** WhatsApp users send 5 messages in 3 seconds instead of one complete thought. The FloodGate turns that into one LLM call.
- **Hook potential:** High
- **Depth:** 90s alone — "why I buffer your messages for 3 seconds" is the hook
- **Related:** full-request-pipeline, telegram-enqueue-fn-bug

### [pattern] make-flood-enqueue-factory
- **What:** `_make_flood_enqueue()` is a factory function that returns a channel-specific enqueue callback, capturing the flood gate in a closure. This is how Discord and Slack plug into the same flood adapter.
- **Why interesting:** Closures as dependency injection. No class hierarchy needed.
- **Hook potential:** Medium
- **Depth:** Combine with flood-gate-batching
- **Related:** flood-gate-batching, telegram-enqueue-fn-bug

### [pattern] dedup-ttl-filter
- **What:** The `MessageDeduplicator` maintains a 5-minute TTL hash table of seen message IDs. Identical messages within that window are silently dropped.
- **Why interesting:** WhatsApp delivery semantics can re-deliver the same message. Without dedup, the AI responds twice to the same question.
- **Hook potential:** Medium
- **Depth:** Combine with flood-gate-batching for a "two-stage message hygiene" reel
- **Related:** flood-gate-batching, full-request-pipeline

### [pattern] task-queue-asyncio
- **What:** The `TaskQueue` is a simple `asyncio.Queue` with a max size of 100. When full, new messages are rejected rather than blocking — the backpressure is explicit.
- **Why interesting:** Most queueing tutorials show infinite queues. A bounded queue with explicit rejection is the production pattern.
- **Hook potential:** Medium
- **Depth:** Combine with async-first-no-celery
- **Related:** async-first-no-celery, session-actor-queue

### [pattern] prompt-compiler
- **What:** The `PromptCompiler` takes 8 profile layer JSON files and compiles them into a single ~1500-token system prompt segment using templates — the bridge between stored profiles and live LLM context.
- **Why interesting:** The output is not a user message — it's the AI's self-model, injected at the system level before every conversation.
- **Hook potential:** High
- **Depth:** 90s alone
- **Related:** eight-layer-profile-system, sbs-distillation-cycle

### [pattern] sqlite-wal-tuning
- **What:** The SQLite connection uses `PRAGMA journal_mode=WAL` and `PRAGMA synchronous=NORMAL` — allowing concurrent readers while a writer is active, and trading full fsync for speed.
- **Why interesting:** Default SQLite blocks all reads during a write. WAL mode doesn't. This single pragma changes the concurrency model.
- **Hook potential:** Medium
- **Depth:** 90s alone
- **Related:** sqlite-only-no-postgres, sqlite-lock-retry-backoff
