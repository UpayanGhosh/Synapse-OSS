# Synapse

## An open-source personalized AI companion architecture

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![LanceDB](https://img.shields.io/badge/LanceDB-Embedded-5C2D91?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![CI](https://img.shields.io/github/actions/workflow/status/UpayanGhosh/Synapse-OSS/tests.yml?branch=main&style=for-the-badge&logo=github&label=CI)

> Most AI is smart in the moment and forgetful across time.
>
> Synapse is built around a different idea: the model may change, but the
> relationship should not.

If ChatGPT often feels like a brilliant stranger, Synapse is trying to become
something closer to a familiar presence.

Not just an assistant.
Not just a chatbot.
Not just a thin wrapper around an LLM.

Synapse is an open-source architecture for hyperpersonalized AI:

- an interchangeable LLM brain
- a persistent memory heart
- an adaptive body of tools, routing, and behavioral logic around the model

The goal is not to build a better raw model than OpenAI, Anthropic, or Google.
The goal is to build a better body around any capable model so the AI feels more
personal, more continuous, more faithful to the user, and more alive over time.

## Why Synapse Can Feel More Human

Most AI can sound human for a few messages.

What usually breaks is everything after that:

- it forgets emotional context
- it loses the role it was supposed to play
- it stops feeling specific to the user
- it falls back into the same generic assistant tone

Synapse is trying to solve that break.

The human feeling does not come from pretending to be human.
It comes from continuity.

When an AI:

- remembers what matters
- stays faithful to the role you gave it
- understands how you prefer to be spoken to
- recognizes recurring patterns in your life
- responds differently because it knows *you*

then the interaction starts to feel less mechanical.

That is the experience Synapse is aiming for.

## In Plain English

Synapse is for people who want an AI that:

- remembers what matters
- gets better at understanding them over time
- stays faithful to the role and personality the user defines
- can respond naturally in everyday moments
- can think more deeply when the situation needs it
- can live across channels instead of one chat box
- can be self-hosted and controlled by the user
- can feel less like software and more like a familiar digital presence

This project is not trying to beat OpenAI, Anthropic, or Google at model
research.

It is trying to solve a different problem:

> How do you build an AI that feels personal, continuous, and deeply familiar
> instead of merely smart?

## Brain, Heart, And Body

The easiest way to understand Synapse is this:

- the LLM is the brain
- the database and memory system are the heart
- the architecture around them is the body

The brain can change.

A user might want Anthropic today, OpenAI next month, Gemini later, or a local
model in the future.

Synapse is designed so the core relationship does not have to reset every time
the brain changes.

That is why the real product is not just the model.

The real product is the persistent system around the model:

- memory
- role fidelity
- behavioral continuity
- retrieval
- channel presence
- privacy boundaries
- adaptive organization of user-important context

This is the real moat.

## Founder Note

Synapse started from a very simple frustration:

even the smartest AI still feels temporary.

It can impress you, help you, surprise you, and still feel like it does not
really know you.

The vision behind Synapse is to build something closer to a persistent digital
presence:

- a digital companion
- a digital brother or sister
- a reflective partner
- a caretaker
- a supervisor
- a deeply personalized assistant

not by pretending the model is magical, but by building the right heart and body
around it.

That means memory, continuity, role fidelity, adaptive structure, and enough
system depth for the relationship to survive changes in models, channels, and time.

## The Product Bet

The bet behind Synapse is simple:

> frontier models will keep changing, but users will still need continuity.

If personalization only lives inside the model vendor, the user is trapped.

If personalization lives inside Synapse, the user keeps:

- their memory
- their role definitions
- their behavioral alignment
- their long-term context
- their relationship continuity

even when the underlying model changes.

## Why People Might Care

Most current AI products are great at answering.

They are much weaker at:

- knowing you over time
- building relationship continuity
- adapting to your communication style
- remembering your long-term context
- balancing fast replies with deeper reflection

That gap is where Synapse lives.

## The Vision

Synapse is built around a simple idea:

> A personal AI should not only answer your messages.
>
> It should gradually learn how to be more useful, more aligned, and more
> meaningful to you.

The long-term goal is an AI that feels less like software you use and more like
a digital companion that grows in context with you.

That companion might be configured as:

- a digital friend
- a digital brother or sister
- a reflective partner
- a caretaker
- a supervisor
- a personal assistant
- a role-based long-term guide

The important part is not the label.

The important part is that the AI remains faithful to the role the user wants,
instead of collapsing back into a generic assistant voice.

## What Makes Synapse Different

| What most AI feels like | What Synapse is trying to do |
| --- | --- |
| Smart in the moment | Coherent across time |
| Generic by default | More specific to one person or relationship |
| Same mode for every interaction | Fast when casual, reflective when important |
| Mostly one interface | Built to live across multiple channels |
| Closed product logic | Open-source architecture you can inspect and shape |
| Personalization as settings | Personalization as an evolving process |

## The Two Core Ideas

### SBS

SBS is the part of Synapse that gives it continuity.

In user terms, that means:

- it can track patterns in how you speak
- it can remember what matters to you
- it can develop a more stable sense of your preferences and behavior
- it does not need to start from zero every time

In technical terms, SBS continuously distills interactions into structured
behavior and persona layers that can be injected at inference time.

### Dual Cognition

Dual Cognition is the part of Synapse that gives it depth.

In user terms, that means:

- quick and natural replies for everyday interaction
- slower, more thoughtful reasoning when the moment is more important
- less "autocomplete energy" and more reflective response quality

In technical terms, it allows Synapse to run an internal reasoning pass before
replying and weigh current input against memory and context.

Put simply:

- SBS helps Synapse stay consistent across time
- Dual Cognition helps Synapse think with more depth in the moment

## Adaptive Architecture

Synapse is not only trying to remember the user.

It is trying to adapt its architecture around the user over time.

That does not mean uncontrolled self-modification.

It means the system should become better at organizing what matters through
bounded, user-shaped evolution:

- promoting important user facts into more durable memory structures
- separating ordinary memory from high-priority memory
- preserving role rules and long-term preferences more reliably
- recognizing repeated user signals about what should matter more
- reshaping retrieval and context assembly so the AI becomes more aligned

For example, if a user says:

> this is important, remember this for the long term

the ideal Synapse behavior is not to throw that line into the same pile as
ordinary chat history.

The ideal behavior is to treat it differently:

- classify it as high-importance memory
- preserve it more durably
- retrieve it more reliably later
- keep it separate from lower-signal conversational noise

That is the kind of adaptive architecture Synapse is aiming toward.

This is one of the most important ideas in Synapse:

> the model does not need to evolve for the experience to evolve.
>
> the architecture around the model can become more personal over time.

## Why SBS Is The Heart Of Synapse

If there is one idea at the center of Synapse, it is SBS.

Most AI systems personalize in relatively shallow ways:

- a static system prompt
- saved facts or memory snippets
- custom instructions
- recent chat history

| Problem | How Most Bots Handle It | How Synapse Handles It |
| --- | --- | --- |
| **Memory** | Stuff messages into context window until it overflows | Hybrid RAG -- SQLite knowledge graph + sqlite-vec embeddings + LanceDB vector search + FlashRank reranking. 37,868+ vocabulary terms, **<350ms P95 retrieval**, 3.4x faster than v1. Zero Docker dependency. |
| **Personality** | Static system prompt, same tone forever | Soul-Brain Sync -- a 3-stage pipeline (realtime sentiment capture, batch distillation every 50 messages, prompt injection) continuously builds a living **2KB behavioral profile**. Personality is not configured. It is learned. |
| **Model selection** | One model for everything (expensive or dumb) | Mixture of Agents -- intent classifier routes to **6 providers** (Gemini, Claude, Ollama, OpenRouter, Groq, local Vault) through `litellm.Router`. Casual chat does not burn expensive API credits. Swap providers by editing JSON config, zero code changes. |
| **Privacy** | Everything goes to cloud APIs | The Vault -- sensitive conversations route to a local Ollama model. **Hemisphere-enforced memory separation**: "safe" (cloud) and "spicy" (local-only) are physically partitioned. Zero cross-contamination, verified by automated integrity tests. |
| **Thinking** | Generate first token immediately | Dual Cognition -- generates an inner monologue, calculates a tension score (0.0--1.0) between memory and current message, then responds. It thinks before it speaks. |
| **Channels** | One messaging platform, tightly coupled | **4 channels** (WhatsApp, Telegram, Discord, Slack) normalized to a single `ChannelMessage` DTO. Memory, persona, and model routing are completely channel-blind. Adding a 5th channel requires ~100 lines -- just implement `BaseChannel`. |
| **Message reliability** | Webhook timeout, lost messages, duplicates | Async pipeline -- 3-second FloodGate batching, 5-minute deduplication window, bounded 100-task async queue, 2 concurrent MessageWorkers. **Zero dropped messages** under real load. |
| **RAM on consumer hardware** | "Just buy a bigger server" | Replaced NetworkX (155MB in-RAM graph) with SQLite (<1.2MB) after profiling showed 81% RAM pressure on 8GB hardware. Lazy-loading ToxicScorer (unloads after 30s idle), `OLLAMA_KEEP_ALIVE=0` model eviction, thermal-aware background workers. **99.2% memory reduction.** |
| **Voice** | Ignore or crash | Groq Whisper -- 2-4s cloud transcription, zero local RAM impact, then processed through the full cognitive pipeline like any other message. |

SBS is different because it is not just storing facts about the user. It is
trying to build a persistent behavioral layer:

- how you prefer to be spoken to
- how you usually reason through problems
- what kinds of responses help you most
- what emotional patterns show up repeatedly
- what topics matter to you over long periods of time

That is a deeper form of personalization than "the user likes X" or "the user
works at Y."

It is personalization at the level of behavioral continuity.

| Metric | Before (v1.0) | After (Phoenix v3) | What Changed |
| --- | --- | :---: | --- |
| **Knowledge Graph Footprint** | ~155MB in-RAM (NetworkX) | **<1.2MB** (SQLite) | NetworkX loaded the entire graph into RAM, causing 81% memory pressure on an 8GB host. SQLite reads from disk on demand. **99.2% reduction.** |
| **Host RAM Usage** | 81.3% | **<25%** | Consolidated 4 separate processes (LanceDB, NetworkX, memory server, gateway) into a single FastAPI app. LanceDB provides embedded vector search with zero Docker overhead. **3.3x lower.** |
| **Retrieval Latency (P95)** | ~1.2s | **<350ms** | High-confidence results (>0.80) bypass FlashRank reranker entirely. Only ambiguous queries pay the reranking overhead. **3.4x faster.** |
| **Vocabulary Diversity** | ~5,000 static terms | **37,868+** | Continuous ingestion from 4 years of conversation logs via the SBS batch pipeline. **7.6x richer.** |
| **Message Pipeline** | Synchronous (webhook timeout) | **Async queue** (202 Accepted) | FloodGate batching (3s window) + deduplication (5-min window) + bounded TaskQueue (max 100) + 2 concurrent MessageWorkers. **Zero dropped messages** under single-user load. |
| **Behavioral Profile** | None (static system prompt) | **2KB, rebuilt every 50 messages** | Soul-Brain Sync: 3-stage pipeline (realtime -> batch -> injection). 8 profile layers distilled from conversation patterns. |
| **Cognitive Overhead (TTFT)** | N/A | **2-5s** | Dual Cognition pipeline: inner monologue generation + tension scoring before response. Quality-for-speed trade-off. |
| **Test Coverage** | Manual | **3,000+ tests across 170+ files** | Unit, integration, smoke, performance, end-to-end, and acceptance tests. Async-native (`asyncio_mode = auto`). |
| **Channel Support** | WhatsApp only | **4 channels** | WhatsApp, Telegram, Discord, Slack -- all normalized to a single DTO through `BaseChannel` ABC. |
| **Bridge Recovery** | Manual restart | **5s auto-restart** | Exponential backoff (up to 5 attempts) on Baileys bridge crash. |

## Why That Matters To The User

When SBS is working well, the user should feel:

- less need to repeat themselves
- less friction in getting useful responses
- more sense of being understood
- more continuity from one conversation to the next
- more emotional and stylistic alignment over time

The difference is subtle but important.

A normal AI can feel smart.

An SBS-shaped AI can feel familiar.

That is a much stronger product experience.

## Why This Stands Out In The Market

Synapse is not just saying "we have memory."

A lot of AI products say that.

The stronger claim is this:

> Synapse is built around an explicit evolving behavioral substrate, not just a
> prompt, a memory list, or a chat transcript.

That is what makes SBS strategically important.

Most public AI products still present personalization as some combination of:

- custom instructions
- profile settings
- saved memory items
- retrieval from old conversations

Synapse is trying to go further by maintaining a persistent layer that shapes
how the AI interprets and responds, not just what isolated facts it can recall.

I would not make the indefensible claim that no one in the world is exploring
similar ideas internally. But as an openly described product architecture, this
is not how most public AI systems are framed today.

That makes Synapse stand out.

## Practical Example: How SBS Actually Helps

Imagine a user who has been interacting with Synapse for a few months.

Over time, Synapse has learned that this person:

- prefers direct, non-fluffy answers
- gets overwhelmed before important launches
- responds well to structured plans
- values emotional honesty more than motivational language
- often asks for strategic help late at night when stressed

Now imagine the user sends this message:

> I feel like everything is slipping. I have too many things to finish before tomorrow.

A typical AI might respond with something generic like:

> I'm sorry you're feeling overwhelmed. Try breaking your work into smaller steps and take a deep breath.

That is not wrong. It is just not very personal.

With SBS, Synapse can do something more specific.

It can recognize:

- this user usually wants clarity, not comfort-first language
- this is a recurring pre-deadline stress pattern
- the most helpful response style is probably structured, calm, and decisive

So the reply can become something more like:

> You do not need reassurance right now. You need compression.
>
> Do only three things tonight:
> 1. finish the part that blocks tomorrow
> 2. cut anything non-essential
> 3. write the first hour of tomorrow before you sleep
>
> You tend to spiral when the list stays abstract. Make it concrete and the pressure drops.

That feels different because it is different.

It is not just "AI with memory."

It is AI that has started to learn how to be useful to a specific person.

## Practical Example: How SBS And Dual Cognition Work Together

Here is the same flow in system terms:

1. The user sends a message.
2. Synapse retrieves relevant memory and recent context.
3. SBS injects behavioral continuity:
   the user prefers directness, tends to spiral under deadline stress, and responds best to structured guidance.
4. Dual Cognition evaluates the moment:
   this is not casual banter, so the system should lean toward a deeper and more deliberate response.
5. The router picks the right model.
6. The final answer reflects both memory and behavioral alignment.

That is the key distinction:

- memory tells Synapse what happened
- SBS helps Synapse understand how this person tends to work and feel
- Dual Cognition helps Synapse decide how deeply to think before replying

Together, that creates a much stronger feeling of continuity than ordinary chat history alone.

## Who Synapse Is For

Synapse is especially interesting for:

- people who want a personal AI companion
- builders exploring personalized AI systems
- researchers interested in long-term memory and human-AI continuity
- users who want more than a generic chatbot
- founders or operators who want an AI that remembers how they think
- people who care about privacy and self-hosting

## For Non-Technical Visitors

You do not need to understand the architecture to understand the promise.

The promise is simple:

- your AI should remember you
- your AI should adapt to you
- your AI should not feel the same as everyone else's
- your AI should improve through relationship, not just settings

That is what Synapse is aiming at.

## For Technical Visitors

Under the hood, Synapse already includes:

- multi-channel messaging support across WhatsApp, Telegram, Discord, and Slack
- a unified async gateway pipeline
- hybrid memory retrieval
- configurable multi-model routing across cloud and local providers
- privacy-aware routing for sensitive conversations
- SBS-based persona and behavioral modeling
- Dual Cognition reasoning flow
- voice handling
- scheduling and cron infrastructure
- reliability work for long-running channel operation

For the deeper system view, see [ARCHITECTURE.md](ARCHITECTURE.md).

## How Synapse Works

The diagram below is the short version of the system:

```mermaid
flowchart TD
    A[User on Telegram / WhatsApp / Slack / Discord / API] --> B[Channel Layer<br/>Normalizes every message into one internal format]
    B --> C[Async Gateway<br/>Queues, deduplicates, batches, and safely processes inbound events]
    C --> D[Memory Layer<br/>Retrieves relevant facts, history, and relationship context]
    D --> E[SBS<br/>Updates and injects behavioral continuity over time]
    E --> F[Dual Cognition<br/>Balances fast replies with deeper reflection]
    F --> G[LLM Router<br/>Chooses the best cloud or local model for the task]
    G --> H[Response Engine<br/>Formats and delivers the reply back to the user]

    D --> I[Private Memory Boundaries]
    G --> J[Cloud + Local Model Support]
    C --> K[Reliability + Retry Logic]
    H --> L[Multi-Channel Presence]
```

In one sentence:

> Synapse takes a message, understands it in context, blends memory with
> evolving personalization, applies the right level of reasoning, routes it to
> the right model, and returns the result through the channel the user already uses.

## Brain, Heart, Body Diagram

This is the higher-level mental model behind Synapse:

```mermaid
flowchart LR
    A[Brain<br/>Any capable LLM<br/>OpenAI / Anthropic / Gemini / local] --> B[Heart<br/>Persistent memory<br/>user history<br/>importance layers]
    B --> C[Body<br/>SBS<br/>Dual Cognition<br/>retrieval<br/>routing<br/>channels<br/>privacy boundaries]
    C --> D[Experience<br/>A more personal, faithful, familiar AI]

    E[User-defined role rules<br/>personality rules<br/>long-term preferences] --> B
    E --> C
```

The important idea is simple:

- the brain can be replaced
- the heart should persist
- the body should keep adapting around the user

## A Better Mental Model

Do not think of Synapse as "another AI app."

Think of it as:

- a personalized AI architecture
- a continuity engine for human-AI interaction
- a companion system framework
- a relationship layer on top of modern language models

## Example Use Cases

Synapse could be used as:

- a personal AI companion that becomes more aligned over time
- a reflective journaling partner that remembers your patterns
- a founder copilot that tracks your ongoing context
- a private AI that lives across Telegram, Slack, and other channels
- a research platform for long-term personalization in AI

## Why Open Source Matters Here

Personalized AI is too important to exist only as black-box products.

If an AI is going to:

- remember your life
- learn your preferences
- infer patterns about how you think
- become increasingly central to your daily experience

then people should be able to inspect, self-host, modify, and question how that
system works.

That is one of the strongest reasons Synapse exists as an open-source project.

## Current Project Status

Synapse is active and evolving.

It is ambitious by design, which means:

- some ideas are ahead of the polish
- some capabilities are stronger than others
- the repo reflects a serious architecture push, not a shallow demo
- the long-term vision is bigger than the current packaging

If you try it and hit issues, that is useful feedback.

- [Open an issue](https://github.com/UpayanGhosh/Synapse-OSS/issues)
- [Start a discussion](https://github.com/UpayanGhosh/Synapse-OSS/discussions)

## Quick Start

> **Full setup guide** (API keys, Ollama, channel linking): [HOW_TO_RUN.md](HOW_TO_RUN.md)

If you want to run Synapse locally:

### 1. Clone the repo

```bash
git clone https://github.com/UpayanGhosh/Synapse-OSS.git
cd Synapse-OSS
```

### 2. Create a virtual environment and install dependencies

Dependencies are split into focused groups — install only what you need. A `uv.lock` is also committed for reproducible installs via [uv](https://github.com/astral-sh/uv).

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate

# Windows
python -m venv .venv
.venv\Scripts\activate.bat

# Core (required)
pip install -r requirements.txt

# Channels (pick the ones you'll use)
pip install -r requirements-channels.txt

# ML / NLP (embeddings, reranker, toxicity scorer)
pip install -r requirements-ml.txt

# Optional extras (OCR, scheduling, etc.)
pip install -r requirements-optional.txt
```

Alternatively, with `uv` for a fully-locked install:

```bash
uv sync
```

### 3. Run onboarding

```bash
# macOS / Linux
chmod +x synapse_onboard.sh
./synapse_onboard.sh

# Windows
synapse_onboard.bat
```

### 4. Start Synapse

```bash
# macOS / Linux
./synapse_start.sh

# Windows
synapse_start.bat
```

For the full setup guide, use [HOW_TO_RUN.md](HOW_TO_RUN.md).

## Docs

- [HOW_TO_RUN.md](HOW_TO_RUN.md) - setup and operational guide
- [ARCHITECTURE.md](ARCHITECTURE.md) - system architecture and subsystem map
- [SETUP_PERSONA.md](SETUP_PERSONA.md) - persona and behavior configuration
- [CONTRIBUTING.md](CONTRIBUTING.md) - contribution guidelines
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) - community standards

## If You Are Watching This Space

If you care about:

- personalized AI
- companion systems
- AI that develops continuity
- long-term memory architectures
- reflective AI behavior
- self-hosted alternatives to closed personal AI products

then Synapse is worth paying attention to.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) first.

## License

> **Full setup guide** (Ollama, channel configuration, persona config): [HOW_TO_RUN.md](HOW_TO_RUN.md)
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

The `MemoryEngine` combines a SQLite knowledge graph (subject-predicate-object triples) with sqlite-vec embeddings and LanceDB vector search. A temporal scoring function blends semantic similarity with recency. High-confidence results (>0.80) skip the FlashRank reranker (ms-marco-TinyBERT) for speed; lower-confidence candidates pass through for precision. Result: **<350ms P95 retrieval** across 37,868+ vocabulary terms.

Embeddings are produced through a pluggable provider layer (`sci_fi_dashboard.embedding.get_provider()`). The default uses Ollama (`nomic-embed-text`), but the interface is vendor-neutral -- swap in sentence-transformers, an OpenAI-compatible endpoint, or any embedding service without touching the ingestion code. Vector dimensions are detected from the provider at runtime, so the schema adapts to whichever model is configured.

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

The `ToolRegistry` dispatches headless browser sessions for real-time data (weather, news, live scores), extracts clean text, and feeds results back to the LLM. Content is truncated to 3,000 characters to protect context window limits. Platform-aware: **Crawl4AI** on Mac/Linux, **Playwright** on Windows -- the `search_web(url)` interface is identical on both. An SSRF guard rejects private/loopback/link-local addresses before the browser is ever launched -- the AI cannot be tricked into scraping the host's internal network.

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
| **Database Engineering** | Dual-database architecture (memory.db + knowledge_graph.db) with WAL mode, atomic transactions, sqlite-vec for ANN search, and LanceDB embedded vector store (zero Docker dependency). |
| **ML Pipeline Orchestration** | Multi-model intent router dispatching to 6 providers through `litellm.Router` with per-role fallback configuration. Vendor-agnostic -- swap providers via JSON config. |
| **Performance Optimization** | Lazy-loading patterns (Toxic-BERT on-demand, 30s idle unload), model eviction (`keep_alive: 0`), FlashRank fast-gate bypass for high-confidence queries, thermal-aware workers. |
| **Privacy Engineering** | Hemisphere-enforced memory separation with zero cross-contamination. Air-gapped local inference. Automated integrity verification. |
| **Testing** | 3,000+ tests across 170+ files: unit, integration, smoke, performance, end-to-end, and acceptance. Async-native with `asyncio_mode = auto`. Tests live on the `develop` branch; `main` stays production-only. |
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
| Databases | SQLite (WAL mode), sqlite-vec (ANN embeddings), LanceDB (embedded vector search) |
| AI/ML | Ollama, Google Gemini, Anthropic Claude, OpenRouter, Groq Whisper, Toxic-BERT, FlashRank (ms-marco-TinyBERT), sentence-transformers, Crawl4AI |
| Messaging | Baileys (WhatsApp), python-telegram-bot (Telegram), discord.py (Discord), slack-bolt + slack-sdk (Slack) |
| Infrastructure | macOS `launchd`, distributed compute (remote GPU node) |
| Testing | pytest, asyncio_mode=auto, 302 tests (unit / integration / smoke / performance / e2e / acceptance) |
| Config | `~/.synapse/synapse.json` -- single config file for all providers, channels, model mappings |

---

## Service Ports

| Service | Port |
| --- | --- |
| API Gateway (FastAPI) | 8000 |
| LanceDB | embedded (`~/.synapse/workspace/db/lancedb/`) |
| Ollama | 11434 |
| Baileys bridge (WhatsApp, internal) | 5010 |

The Baileys bridge is spawned and managed automatically by the WhatsApp channel adapter
on gateway startup -- it is not a manually started service.

---

## Repository Layout

```
workspace/
├── sci_fi_dashboard/              # Core application
│   ├── api_gateway.py             #   Central FastAPI gateway (~420 lines, trimmed from ~1,200 after extracting subsystems)
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
│   │   ├── plugin.py              #     Channel plugin discovery
│   │   ├── security.py            #     DM access control (pairing/allowlist/open/disabled)
│   │   ├── whatsapp.py            #     Baileys bridge supervisor + HTTP client
│   │   ├── telegram.py            #     python-telegram-bot v22+ adapter
│   │   ├── discord_channel.py     #     discord.py v2.x adapter
│   │   └── slack.py               #     slack-bolt Socket Mode adapter
│   ├── gateway/                   #   Async message pipeline
│   │   ├── queue.py               #     Bounded async task queue (max 100)
│   │   ├── worker.py              #     Concurrent message workers (x2)
│   │   ├── sender.py              #     Outbound message dispatch
│   │   ├── dedup.py               #     5-minute deduplication window
│   │   ├── flood.py               #     3-second batch aggregator
│   │   ├── retry_queue.py         #     Durable outbound retry queue
│   │   └── ws_server.py           #     WebSocket gateway (chat.send, sessions.*)
│   ├── routes/                    #   FastAPI route modules (split out of api_gateway.py)
│   │   ├── chat.py                #     Persona chat + OpenAI-compatible proxy
│   │   ├── knowledge.py           #     /ingest, /add, /query
│   │   ├── persona.py             #     /persona/rebuild, /persona/status
│   │   ├── whatsapp.py            #     QR, relink, logout, job status
│   │   ├── websocket.py           #     WebSocket endpoint (/ws)
│   │   └── health.py, pipeline.py, sessions.py, snapshots.py, skills.py, agents.py, cron.py
│   ├── embedding/                 #   Pluggable embedding providers
│   │   ├── base.py                #     Provider interface
│   │   ├── factory.py             #     get_provider() dispatcher
│   │   ├── fastembed_provider.py  #     Local fastembed (no Ollama required)
│   │   └── gemini_provider.py     #     Gemini cloud embeddings
│   ├── media/                     #   Audio, images, SSRF guard
│   │   ├── audio_transcriber.py   #     Groq Whisper transcription
│   │   ├── audio_preflight.py     #     Audio sanity check before transcribe
│   │   ├── ssrf.py                #     Blocks private/loopback/link-local URLs
│   │   └── mime.py                #     MIME detection (magic bytes → header → ext)
│   ├── mcp_servers/               #   MCP server processes (tools, memory, etc.)
│   └── sbs/                       #   Soul-Brain Sync persona engine
│       ├── orchestrator.py        #     SBS lifecycle manager
│       ├── ingestion/             #     Raw log → JSONL pipeline
│       ├── processing/            #     Realtime + batch analysis
│       ├── injection/             #     Profile → system prompt compiler
│       ├── profile/               #     8-layer behavioral profile store
│       ├── feedback/              #     Implicit feedback detection
│       └── sentinel/              #     File governance guardrails
├── synapse_config.py              # Config root (~/.synapse/), path contract
├── db/                            # Legacy database tools folder
│   └── tools.py                   #   Platform-aware browser (Crawl4AI/Playwright) + SSRF guard
├── scripts/                       # Maintenance & utilities
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
| `POST` | `/channels/{channel_id}/webhook` | Generic inbound webhook (Baileys, Telegram webhook mode, etc.) |
| `POST` | `/channels/whatsapp/relink` | Re-pair the WhatsApp bridge |
| `POST` | `/channels/whatsapp/logout` | Log the WhatsApp session out |
| `GET` | `/whatsapp/jobs/{message_id}` | Poll the status of an enqueued WhatsApp message |
| `GET` | `/qr` | Fetch the WhatsApp QR code for pairing |
| `POST` | `/persona/rebuild` | Rebuild persona profiles from logs |
| `GET` | `/persona/status` | Profile statistics |
| `POST` | `/ingest` | Ingest a structured fact into the knowledge graph |
| `POST` | `/add` | Unstructured memory -- triple extraction |
| `POST` | `/query` | Query the knowledge graph |
| `GET` | `/health` | System health check |
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat proxy |
| `WS` | `/ws` | WebSocket gateway -- `chat.send`, `channels.status`, `sessions.list`, heartbeat every 30s |

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

**Upayan Ghosh** -- Software engineer who built a 50,000+ line production AI system from scratch, on evenings and weekends, on consumer hardware.

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
