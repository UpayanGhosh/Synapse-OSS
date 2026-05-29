# Synapse Product Showcase Website — Handover Document

> **Purpose:** Single source of truth for building the Synapse product showcase website.
> **Audience:** Website designer/developer (you + Claude).
> **Date:** 2026-04-10

---

## Table of Contents

1. [Product Positioning](#1-product-positioning)
2. [Target Audiences](#2-target-audiences)
3. [Goals & Success Metrics](#3-goals--success-metrics)
4. [Hero Messaging & Taglines](#4-hero-messaging--taglines)
5. [Feature Catalog (Marketable)](#5-feature-catalog-marketable)
6. [Architecture Highlights](#6-architecture-highlights)
7. [Design Direction & 2026 Trends](#7-design-direction--2026-trends)
8. [Reference Sites](#8-reference-sites)
9. [Site Structure & Pages](#9-site-structure--pages)
10. [Social Proof & Community](#10-social-proof--community)
11. [Developer Experience Section](#11-developer-experience-section)
12. [Deployment & Tech Stack Notes](#12-deployment--tech-stack-notes)
13. [Content Assets Needed](#13-content-assets-needed)

---

## 1. Product Positioning

### One-Liner
**Synapse** — The AI that actually knows you. Self-hosted, multi-channel, privacy-first.

### Elevator Pitch (30 seconds)
Synapse is an open-source AI companion that runs on your machine, connects to WhatsApp, Telegram, Discord, and Slack, and builds a persistent memory of who you are. It learns your communication style in real-time, routes messages to the best AI model for each task, and keeps your private conversations completely local. Your AI relationship survives model changes — because the personality, memory, and knowledge graph belong to *you*, not a cloud provider.

### Positioning Statement
**For** developers and privacy-conscious users **who** want an AI assistant that truly understands them,
**Synapse is** a self-hosted AI companion framework
**that** provides persistent memory, adaptive personality, and multi-channel messaging with zero cloud leakage for sensitive content.
**Unlike** ChatGPT, Gemini, or Copilot, **Synapse** stores your relationship data locally, learns your style implicitly, and lets you choose exactly which models handle which conversations.

### Core Philosophy
> "Relationships should outlast models."

While frontier LLMs change every few months, your conversation history, personality profile, and behavioral continuity persist across model switches. Synapse is the *middleware* between you and AI — a brain that remembers, a soul that adapts, and a body that reaches you wherever you are.

---

## 2. Target Audiences

### Primary: Developers & Self-Hosters
- Build, extend, and customize their AI stack
- Care about data sovereignty and open-source
- Want to understand the architecture, contribute, or fork
- **Hook:** Technical depth, architecture diagrams, code snippets, GitHub stars

### Secondary: AI Enthusiasts & Power Users
- Want a personal AI that actually remembers them
- Use WhatsApp/Telegram daily and want AI integrated there
- Privacy-conscious but not necessarily technical
- **Hook:** Emotional resonance, "your AI learns you" narrative, demo videos

### Tertiary: Contributors & Community
- OSS developers looking for interesting projects
- AI/ML researchers exploring persona engines and memory systems
- **Hook:** Architecture novelty, contribution guide, community Discord/GitHub

---

## 3. Goals & Success Metrics

| Goal | Metric | Target |
|------|--------|--------|
| GitHub Stars | Star count | 1K in 3 months |
| Contributors | PRs from non-maintainers | 10+ in 6 months |
| Awareness | Unique visitors/month | 5K in 3 months |
| Adoption | Clones + forks | 500 in 3 months |
| Retention | Return visits | 30% within 30 days |

---

## 4. Hero Messaging & Taglines

### Primary Tagline Options (pick one for hero)
1. **"The AI that actually knows you."**
2. **"Your mind, your machine, your AI."**
3. **"AI that remembers. Personality that adapts. Privacy you control."**
4. **"Self-hosted intelligence that grows with you."**

### Supporting Headlines (for feature sections)
- "One brain. Every channel." (multi-channel)
- "It doesn't just respond. It thinks." (dual cognition)
- "Your style, learned — not configured." (SBS persona)
- "Private stays private. Period." (vault/hemisphere)
- "The right model for every message." (traffic cop / MoA)
- "Memory that connects the dots." (knowledge graph)
- "Roll back time. Literally." (snapshots)
- "Your AI reaches out first." (proactive awareness)

### Emotional Hook (for non-technical visitors)
> Imagine an AI that remembers your mom's birthday, knows you hate long replies on Monday mornings, switches to your native language when you're emotional, and keeps your private conversations completely off the cloud. That's Synapse.

---

## 5. Feature Catalog (Marketable)

### Tier 1 — Hero Features (above the fold / bento grid)

#### 1. Soul-Brain Sync (SBS) — Adaptive Personality Engine
**Headline:** "Your style, learned — not configured."
**Description:** Synapse builds an 8-layer behavioral profile from your conversations. By message #50, it knows your vocabulary, formality level, preferred response length, emoji habits, and emotional triggers. Say "too long" once — it adjusts permanently. No settings page required.
**Visual:** Animated profile radar chart showing 8 layers filling in over time.
**Dev angle:** JSON-based profiles survive model switches. Batch processor distills every 50 messages. YAML-configurable feedback patterns.

**8 Profile Layers:**
1. Linguistic — Banglish ratio, formal/casual balance, vocabulary complexity
2. Interaction — Response length preferences, reply speed expectations
3. Emotional State — Mood baseline, emotional triggers
4. Domain Expertise — Topics where you expect depth
5. Communication Prefs — Question format, emoji usage, formality by context
6. Memory Prefs — What to remember vs. forget
7. Temporal Awareness — Time-of-day behavior patterns
8. Relationship Context — Tone shift based on relationship history

---

#### 2. Hybrid Memory System — Vector + Graph + Full-Text
**Headline:** "Memory that connects the dots."
**Description:** Synapse doesn't just store facts — it understands relationships. A hybrid retrieval pipeline combines vector search, full-text search, knowledge graph traversal, and neural reranking to find the right context in <350ms. Your AI knows that Alice is your colleague, Bob is her husband, and you met them both at a conference in 2024.
**Visual:** Animated knowledge graph with nodes lighting up during a query.
**Dev angle:** LanceDB (embedded ANN), SQLite-vec, FlashRank cross-encoder, SQLiteGraph for S-P-O triples. Zero external services.

**Memory Types:**
- Semantic Memory — Facts about you (job, family, interests)
- Relationship Memory — How people relate (Alice --knows--> Bob)
- Emotional Memory — 72h mood arc (peak-end weighted trajectory)
- Episodic Memory — Conversation sessions with timestamps
- Knowledge Graph — Subject-predicate-object triples with confidence scores

---

#### 3. Dual Cognition Engine — Inner Monologue
**Headline:** "It doesn't just respond. It thinks."
**Description:** Before every reply, Synapse runs two parallel thought streams — "What are they saying right now?" and "What do I know about this person?" These streams merge to detect tension, alignment, or contradiction, producing an inner monologue and response strategy. The AI *reasons about you* before speaking.
**Visual:** Split-screen animation: Present Stream vs. Memory Stream merging into a response.
**Dev angle:** Complexity classifier (fast/standard/deep paths), 5s configurable timeout, pre-cached memory (no double query), tension scoring 0.0-1.0.

**Example:**
```
User: "I'm starting a new job on Monday"

Present Stream: sentiment=positive, intent=announcement
Memory Stream:  "User mentioned job search 3 weeks ago, seemed anxious"

Cognitive Merge:
  inner_monologue: "They found a job! Last time they mentioned this,
                    they were nervous about interviews."
  tension_level: 0.4
  response_strategy: "celebrate + reassure"
```

---

#### 4. Privacy Vault — Zero Cloud Leakage
**Headline:** "Private stays private. Period."
**Description:** Synapse splits memory into two hemispheres — Safe (shareable) and Spicy (private). Private content routes exclusively to local Ollama models and is enforced at the SQL query level. Not a UI toggle — a database-level guarantee. Your private conversations never touch OpenAI, Anthropic, or Google.
**Visual:** Animated hemisphere split — cloud icon on left, lock icon on right.
**Dev angle:** `hemisphere_tag` column in documents table, `WHERE hemisphere_tag = ?` bound at query time. Vault role routes to `ollama_chat/` prefix models only.

---

#### 5. Multi-Channel Messaging — One Brain, Every Platform
**Headline:** "One brain. Every channel."
**Description:** Chat with your AI on WhatsApp, Telegram, Discord, and Slack — all sharing the same memory, personality, and context. Switch platforms mid-conversation and your AI picks up exactly where you left off.
**Visual:** Animated channel icons converging into a single brain.
**Dev angle:** BaseChannel ABC, plug-and-play adapters, Baileys bridge for WhatsApp (no official API dependency), unified ChannelMessage DTO.

**Supported Channels:**
| Channel | Features |
|---------|----------|
| WhatsApp | DMs, groups, voice notes, media, QR pairing |
| Telegram | DMs, groups, inline buttons, commands |
| Discord | Servers, threads, embeds, reactions |
| Slack | Channels, DMs, threads, blocks, file sharing |

---

#### 6. Smart Model Routing (Traffic Cop / MoA)
**Headline:** "The right model for every message."
**Description:** Every message is classified by intent and routed to the optimal AI model. Casual chat? Gemini Flash. Code review? Claude Sonnet. Private content? Local Ollama. No manual switching — Synapse picks the best model automatically, with fallbacks if one is unavailable.
**Visual:** Animated routing diagram — message enters, traffic cop classifies, arrows split to different model icons.
**Dev angle:** litellm.Router supports 100+ providers. Per-role fallback chains. Token budgeting per provider. Smart parameter dropping for provider compatibility.

**Routing Map:**
| Intent | Model | Trigger |
|--------|-------|---------|
| Casual / Banglish | Gemini Flash | Default, small talk |
| Code | Claude Sonnet (thinking) | Code detected |
| Deep Analysis | Gemini Pro | Complex reasoning |
| Private / Vault | Local Ollama | Sensitive content |
| Translation | OpenRouter | Language tasks |

---

### Tier 2 — Feature Cards (scrollable section / bento grid)

#### 7. Proactive Awareness Engine
**Headline:** "Your AI reaches out first."
**Description:** Synapse polls your calendar, email, and Slack in the background. It knows you have a meeting in 30 minutes, 3 unread emails, and someone @mentioned you. It can proactively check in: "Big meeting coming up — you ready?"
**Visual:** Notification bubbles floating into the AI's context window.

#### 8. Implicit Feedback Detection
**Headline:** "Say 'too formal' once. It remembers forever."
**Description:** No settings pages. No slash commands. Just speak naturally. "Stop yapping" → permanently shorter responses. "Love this tone" → reinforces current style. Synapse detects corrections and preferences from natural language and applies them instantly.
**Visual:** Chat bubble with correction → profile layer updating in real-time.

#### 9. Emotional Trajectory Tracking
**Headline:** "Your AI reads the room."
**Description:** Synapse tracks your emotional arc over 72 hours using peak-end weighting. If you've been tense lately, it adjusts its tone to be more supportive. Your mood history influences how the AI speaks to you — not just what it says.
**Visual:** Mood line chart (72h) with tone adjustments annotated.

#### 10. Cron Service — Scheduled Check-ins
**Headline:** "Morning check-ins. Medication reminders. Weekly summaries."
**Description:** Define scheduled messages on any channel. Your AI can greet you every morning, remind you to take medication, or send weekly conversation summaries — all timezone-aware.
**Visual:** Clock icon with scheduled message cards.

#### 11. Snapshot Engine — Time Travel for Config
**Headline:** "Roll back time. Literally."
**Description:** Before any system modification, Synapse takes an atomic snapshot. If something breaks, auto-rollback restores your previous state. You can also manually restore from any of your last 50 snapshots.
**Visual:** Timeline with snapshot markers, one highlighted for restore.

#### 12. Knowledge Graph Extraction
**Headline:** "Your AI builds a relationship map."
**Description:** After every 15+ message session, Synapse automatically extracts subject-predicate-object triples into a knowledge graph. It doesn't just remember facts — it understands how people, places, and events connect.
**Visual:** Animated graph with new triples appearing as edges.

#### 13. Auto-Continue
**Headline:** "Thoughts don't get cut off."
**Description:** If a response hits the token limit mid-sentence, Synapse automatically requests a continuation and delivers it as a seamless follow-up. No "Oh wait, here's more..." — just complete thoughts.

#### 14. Gentle Worker — Thermal-Aware Maintenance
**Headline:** "Smart enough to know when to work."
**Description:** Background maintenance (DB optimization, KG pruning, profile batching) only runs when your device is plugged in and CPU is under 20%. Your AI respects your hardware.

#### 15. Diary Engine
**Headline:** "Auto-generated conversation diaries."
**Description:** After each session, Synapse generates a diary entry capturing mood, key topics, tension levels, and a natural-language summary. Browse your AI relationship history like a journal.

#### 16. DM Access Control & Pairing
**Headline:** "You choose who talks to your AI."
**Description:** Per-channel access policies — Pairing (approval required), Allowlist (pre-approved numbers), Open, or Disabled. First-time contacts trigger an approval flow with a 5-minute confirmation window.

#### 17. SubAgent System
**Headline:** "Autonomous agents that report back."
**Description:** Define specialized agents (Email Agent, Research Agent) that can run tools independently, chain multiple steps, and report results — all with owner approval before execution.

#### 18. MCP Tool Servers
**Headline:** "10 tool servers. Claude's official protocol."
**Description:** Memory, Calendar, Gmail, Slack, Browser, Execution, and more — all exposed via Claude's Model Context Protocol. Extend with your own tools using the factory-based registry.

---

### Tier 3 — Technical Depth (for developer audience)

#### 19. Flood Gate & Deduplication
3-second batching window for rapid-fire messages. 5-minute TTL deduplication. Prevents rate limit hits and reduces unnecessary LLM calls.

#### 20. Media Pipeline
MIME detection via magic bytes (not headers). Size limits enforced before download. SSRF guard rejects private/loopback IPs. Voice messages transcribed via Groq Whisper-Large-v3.

#### 21. WebSocket Gateway
`ws://127.0.0.1:8000/ws` — Stream LLM output token-by-token. Methods: `chat.send`, `channels.status`, `models.list`, `sessions.list`, `sessions.reset`. 30s heartbeat.

#### 22. Tool Safety Pipeline
ToolRegistry (factory pattern), ToolLoopDetector (prevents infinite recursion), ToolAuditLogger (full call logging), ToolHookRunner (pre/post hooks), Policy pipeline (owner-only gates, rate limits).

#### 23. Onboarding Wizard
Quickstart (5 min) or Advanced (30 min) setup flows. Non-interactive mode for CI/Docker. Risk acceptance gates. Reset options with backup.

#### 24. Multi-User Support
Per-user SBS profiles, memory stores, KG snapshots, session history, and DM pairing. Shared config (channels, providers). Each user gets their own `sbs_<persona>/` profile directory.

---

## 6. Architecture Highlights

### Full Request Flow (for architecture diagram)
```
Channel (WhatsApp / Telegram / Discord / Slack)
  -> ChannelRegistry.dispatch()
  -> FloodGate (3s batch)
  -> MessageDeduplicator (5-min TTL)
  -> TaskQueue (asyncio FIFO, max 100)
  -> MessageWorker x2
  -> persona_chat()
      |-- SBS: get_prompt()              [~1500-token persona segment]
      |-- MemoryEngine: query()          [hybrid RAG: vector + FTS + rerank]
      |-- DualCognitionEngine: think()   [inner monologue + tension score]
      |-- route_traffic_cop()            [intent -> role mapping]
      |-- SynapseLLMRouter: call()       [litellm.Router -> cloud or local]
  -> Channel.send(reply)
  -> Auto-Continue check
  -> Background: SBS update + KG extraction
```

### Zero External Dependencies
```
Embedded Stack (no Docker, no Redis, no Postgres):
  - LanceDB         (vector search, embedded)
  - SQLite + WAL     (relational + FTS, embedded)
  - sqlite-vec       (vector ops, embedded)
  - FastEmbed/ONNX   (embeddings, embedded)
  - FlashRank        (reranking, embedded)
  - asyncio          (concurrency, stdlib)

Optional:
  - Ollama           (local LLM inference)
  - Cloud providers   (Anthropic, OpenAI, Gemini, Groq, etc.)
```

### Database Architecture
```
~/.synapse/workspace/db/
  |-- memory.db              (documents + embeddings + atomic facts)
  |-- knowledge_graph.db     (S-P-O triples, nodes + edges)
  |-- emotional_trajectory.db (mood arc, tension history)
  |-- lancedb/               (ANN vector index)
```

### Tech Stack Summary
| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 (backend) + Node.js 18+ (WhatsApp bridge) |
| API | FastAPI + Pydantic |
| LLM Routing | litellm.Router (100+ providers) |
| Vector DB | LanceDB (embedded) |
| Relational DB | SQLite + WAL mode |
| Embeddings | FastEmbed ONNX / Ollama nomic-embed-text |
| Reranking | FlashRank (ms-marco-TinyBERT-L-2-v2) |
| Knowledge Graph | SQLiteGraph (custom, 1MB vs 150MB NetworkX) |
| Channels | Baileys (WA), discord.py, python-telegram-bot, slack-sdk |
| Real-time | WebSocket (native asyncio) |

---

## 7. Design Direction & 2026 Trends

### Must-Have Design Elements (Tier 1 Trends)

#### 1. Dark Mode as Default
- 9/10 top developer tool sites use dark as primary
- Signals "built for builders" instantly
- Allows accent colors and glow effects to pop
- Light mode optional/secondary

#### 2. Product-as-Hero (Show, Don't Tell)
- Put actual product UI / terminal output in the hero section
- Animated product demo > static screenshot > abstract illustration
- Interactive embedded demos reduce "what does this do?" friction
- Consider: animated terminal showing Synapse startup + first message exchange

#### 3. Code Snippets as Design Elements
- Developer audiences respond to code more than marketing copy
- Show a 3-5 line snippet demonstrating core value (e.g., `synapse.json` config)
- Syntax highlighting with brand accent colors
- Tabbed multi-language support adds credibility

#### 4. Bento Grid Feature Layout
- 47% increase in dwell time, 38% increase in CTR vs traditional layouts
- Modular, card-based sections for features, testimonials, code, metrics
- Asymmetric sizing creates visual hierarchy (larger cards for hero features)
- Perfect for Synapse's diverse feature set

### High-Impact Differentiators (Tier 2 Trends)

#### 5. GitHub Stars / Community Metrics as Social Proof
- Star count displayed prominently near hero
- Contributor avatars as mosaic
- "X developers" counter
- shields.io badges or custom animated counter

#### 6. Scroll-Triggered Animations (GSAP / Framer Motion)
- Scroll-driven storytelling keeps users engaged deeper
- Parallax product screenshots, staggered card reveals, sticky scroll sections
- Must be performant — janky animation is worse than none

#### 7. Gradient Typography and Glow Effects
- Large headlines with color gradients matching brand palette
- Subtle glow/bloom on dark backgrounds creates depth
- Custom/variable fonts (Geist, Inter, Cal Sans) over generic system fonts
- Oversized hero typography (60-120px)

#### 8. Single-Accent Color Brand Identity
- One strong color against dark/neutral background
- Synapse suggestion: **Electric cyan (#00F0FF)** or **Neural purple (#8B5CF6)** or **Synapse green (#10B981)**
- Accent appears in CTAs, code highlights, icons, hover states

### Polish Layer (Tier 3 Trends)

#### 9. Terminal/CLI Aesthetic Elements
- Monospace sections, `npm install synapse` as interactive terminal widget
- Blinking cursor, typed-out text effects
- Signals technical depth

#### 10. Glassmorphism & Frosted UI Cards
- Semi-transparent cards with backdrop blur
- Layered depth with overlapping elements
- Works well on dark backgrounds with colorful gradients underneath

#### 11. Architecture/Flow Diagrams as Visual Design
- Animated data flow showing message pipeline
- Connection lines, node graphs
- Makes technical complexity approachable

### Anti-Patterns to Avoid
- No salesy marketing-speak (devs reject it instantly)
- No generic stock 3D blobs (show real product, real code)
- No heavy page weight (performance IS design)
- No light-mode-only (dark-first for developer tools)

---

## 8. Reference Sites

Browse these and pick your vibe — the top 10 developer tool showcase sites of 2025-2026:

| # | Site | URL | What to Steal |
|---|------|-----|---------------|
| 1 | **Linear** | https://linear.app | Dark cinematic hero, glassmorphism, scroll-triggered reveals |
| 2 | **Supabase** | https://supabase.com | Bento grid features, dark + emerald accent, GitHub stars front-center |
| 3 | **Vercel** | https://vercel.com | Monochrome ultra-minimalism, custom Geist font, speed-as-design |
| 4 | **Raycast** | https://raycast.com | Product-as-hero, macOS-native glassmorphism, extensions grid |
| 5 | **Cursor** | https://cursor.com | AI-first presentation, dark + gradient glow, live product demo |
| 6 | **Warp** | https://warp.dev | Terminal aesthetic, gradient typography, developer count social proof |
| 7 | **Resend** | https://resend.com | Code-as-hero, radical minimalism, monochrome + single accent |
| 8 | **PostHog** | https://posthog.com | Playful personality, hand-drawn illustrations, irreverent tone |
| 9 | **Appwrite** | https://appwrite.io | Dark + vibrant CTA, open-source identity, multi-lang code tabs |
| 10 | **Neon** | https://neon.tech | Sci-fi glow, neon green brand, architecture diagrams as design |

### Recommended Synapse Direction
**Primary inspiration:** Neon (sci-fi glow) + Supabase (bento grid + GitHub stars) + Cursor (AI-first hero)
**Personality layer:** PostHog-style irreverence (optional, depends on brand tone)
**Technical depth:** Resend-style code-as-design + Warp-style terminal aesthetic

---

## 9. Site Structure & Pages

### Option A: Single-Page Showcase (recommended for launch)
```
[Nav: Logo | Features | Architecture | Get Started | GitHub]

[Hero Section]
  - Tagline + subtitle
  - Animated terminal / product demo
  - CTA: "Get Started" + "View on GitHub"
  - GitHub stars badge

[Feature Bento Grid]
  - 6 hero feature cards (Tier 1 from section 5)
  - Asymmetric layout: 2 large + 4 medium

[Architecture Section]
  - Animated request flow diagram
  - Tech stack badges
  - "Zero Docker" callout

[Feature Cards (Scrollable)]
  - 12 Tier 2 features as smaller cards
  - Hover reveals detail

[Code Section]
  - Tabbed: synapse.json config | CLI commands | API example
  - Terminal aesthetic

[Community Section]
  - GitHub stats (stars, forks, contributors)
  - Contributor avatars
  - "Join the community" CTA

[Get Started]
  - 3-step quickstart
  - One-liner install command
  - Link to full docs

[Footer]
  - Links: GitHub | Docs | Discord | License
```

### Option B: Multi-Page Catalog (for later)
```
/                  - Landing page (hero + overview)
/features          - Full feature catalog with deep dives
/architecture      - Interactive architecture diagrams
/docs              - Getting started, configuration, API reference
/community         - Contributors, roadmap, how to contribute
/blog              - Build-in-public posts, changelogs
```

### Option C: Hybrid (recommended long-term)
Start with Option A for launch, expand to Option B as content grows.

---

## 10. Social Proof & Community

### GitHub Metrics to Display
- Star count (live badge)
- Fork count
- Contributor count + avatar mosaic
- Open issues (shows active development)
- Last commit date (shows it's maintained)

### Testimonials / Quotes
- Early user feedback (if available)
- Reddit/HN comments (if posted)
- Your own "why I built this" quote

### Build-in-Public Signals
- Changelog / release history
- Roadmap (public, linked)
- "Built by [your name]" with social links

---

## 11. Developer Experience Section

### Quick Start (3 steps)
```bash
# 1. Clone
git clone https://github.com/[your-username]/Synapse-OSS.git
cd Synapse-OSS

# 2. Setup
pip install -r requirements.txt
python workspace/main.py onboard --flow quickstart

# 3. Chat
python workspace/main.py chat
```

### Configuration Preview
```json
{
  "model_mappings": {
    "casual": { "model": "gemini/gemini-2.0-flash" },
    "code":   { "model": "anthropic/claude-sonnet-4-6" },
    "vault":  { "model": "ollama_chat/llama3.3" }
  },
  "channels": {
    "whatsapp": {},
    "telegram": { "token": "YOUR_BOT_TOKEN" },
    "discord":  { "token": "YOUR_BOT_TOKEN" }
  }
}
```

### API Example
```python
import httpx

resp = httpx.post("http://localhost:8000/chat/the_creator", json={
    "message": "What did Alice tell me about the project deadline?",
    "session_type": "safe"
})
print(resp.json()["reply"])
```

### CLI Commands (showcase)
```bash
synapse chat                    # Interactive CLI
synapse onboard --flow advanced # Full setup wizard
synapse doctor --fix            # Diagnostics + auto-repair
synapse whatsapp status         # Check WhatsApp connection
synapse vacuum                  # Optimize databases
```

---

## 12. Deployment & Tech Stack Notes

### Deployment Options for Website
| Platform | Pros | Cons |
|----------|------|------|
| **Vercel** | Free tier, great DX, Next.js native | Vendor lock-in |
| **Netlify** | Free tier, simple deploys, form handling | Slightly less Next.js support |

### Recommended Website Tech Stack
| Choice | Why |
|--------|-----|
| **Next.js 15** (App Router) | Best React framework, Vercel-native, SSG for performance |
| **Tailwind CSS v4** | Utility-first, dark mode built-in, rapid prototyping |
| **Framer Motion** | Scroll animations, page transitions, spring physics |
| **Shiki** | Code syntax highlighting (matches VS Code themes) |
| **next-mdx-remote** | If blog/docs pages are needed later |

### Domain Options (no custom domain)
- `synapse-oss.vercel.app`
- `synapse-oss.netlify.app`
- Later: consider `synapse.dev` or `getsynapse.ai` if budget allows

---

## 13. Content Assets Needed

### Must-Have Before Build
- [ ] Final tagline selection (from section 4 options)
- [ ] Brand accent color decision
- [ ] Reference site picks (from section 8 — which 2-3 to emulate?)
- [ ] GitHub repo URL (for live star counter)
- [ ] Logo / wordmark (or generate one)
- [ ] 1-2 screenshots or terminal recordings of Synapse in action

### Nice-to-Have
- [ ] "Why I Built This" story (1-2 paragraphs)
- [ ] Architecture diagram (SVG or Figma)
- [ ] Demo video (30-60 seconds)
- [ ] Social links (Twitter/X, Discord, personal site)
- [ ] OG image for social sharing (1200x630px)

### Can Generate During Build
- [ ] Code snippet components
- [ ] Feature icons (Lucide or custom SVG)
- [ ] Animated terminal demo (typed.js or custom)
- [ ] Bento grid layout
- [ ] GitHub stats integration (via GitHub API)

---

## Appendix A: Full Feature-Benefit Matrix

| # | Feature | User Benefit | Dev Appeal | Marketing Copy |
|---|---------|--------------|------------|----------------|
| 1 | SBS 8-Layer Profiles | AI learns your style automatically | JSON profiles, YAML feedback patterns, survives model switches | "Your style, learned — not configured" |
| 2 | Hybrid Memory (Vector+Graph+FTS) | Finds relevant context in <350ms | LanceDB + SQLite-vec + FlashRank + SQLiteGraph, zero external deps | "Memory that connects the dots" |
| 3 | Dual Cognition Engine | AI reasons about you before replying | Present/memory stream merge, tension scoring, complexity classifier | "It doesn't just respond. It thinks" |
| 4 | Privacy Vault (Hemisphere Isolation) | Private content never leaves your device | SQL-level enforcement, Ollama-only routing, hemisphere_tag column | "Private stays private. Period" |
| 5 | Multi-Channel (WA/TG/Discord/Slack) | Same AI everywhere, shared memory | BaseChannel ABC, Baileys bridge, unified DTO | "One brain. Every channel" |
| 6 | Traffic Cop / MoA Routing | Best model per task, automatic | litellm.Router, intent classification, fallback chains, token budgets | "The right model for every message" |
| 7 | Proactive Awareness | AI knows your schedule and reaches out | Async MCP polling, context injection | "Your AI reaches out first" |
| 8 | Implicit Feedback | Natural corrections stick permanently | YAML regex patterns, per-persona scoping | "Say 'too formal' once. It remembers forever" |
| 9 | Emotional Trajectory | AI adjusts tone to your mood arc | 72h peak-end weighting, separate SQLite DB | "Your AI reads the room" |
| 10 | Cron Service | Scheduled messages and reminders | Timezone-aware, multi-channel delivery | "Morning check-ins. Reminders. Summaries" |
| 11 | Snapshot Engine | Roll back any config change | Atomic captures, auto-rollback, max 50 | "Roll back time. Literally" |
| 12 | Knowledge Graph | AI maps relationships between people/things | LLM-based triple extraction, confidence scoring, auto-pruning | "Your AI builds a relationship map" |
| 13 | Auto-Continue | Responses never cut off mid-thought | BackgroundTask continuation, seamless merge | "Thoughts don't get cut off" |
| 14 | Gentle Worker | Maintenance respects your device | psutil thermal awareness, plugged-in check | "Smart enough to know when to work" |
| 15 | Diary Engine | Auto-generated conversation journals | Mood extraction, LLM summary, file + DB | "AI-written conversation diaries" |
| 16 | DM Access Control | You choose who talks to your AI | Pairing/Allowlist/Open/Disabled per channel | "Your AI, your rules" |
| 17 | SubAgent System | Autonomous agents with supervision | State machine, progress tracking, owner approval | "Agents that work while you don't" |
| 18 | 10 MCP Tool Servers | Extensible AI actions via standard protocol | Claude MCP compatible, factory registry, async execution | "Tools your AI can actually use" |
| 19 | Zero External Dependencies | Runs on a Raspberry Pi | Embedded LanceDB + SQLite + FastEmbed + FlashRank | "No Docker. No Redis. No Postgres" |
| 20 | Onboarding Wizard | 5-minute or 30-minute setup | Quickstart/Advanced flows, non-interactive mode, CI-compatible | "Running in 5 minutes flat" |

---

## Appendix B: Competitive Positioning

| Feature | Synapse | ChatGPT | Gemini | Local LLM (Ollama) |
|---------|---------|---------|--------|---------------------|
| Persistent memory across sessions | Yes (local) | Limited | Limited | No |
| Multi-channel (WA/TG/Discord/Slack) | Yes | No | No | No |
| Adaptive personality (learned) | Yes (8 layers) | No | No | No |
| Privacy vault (zero cloud) | Yes | No | No | Yes (all local) |
| Knowledge graph | Yes | No | No | No |
| Inner monologue / reasoning | Yes (visible) | Hidden | Hidden | No |
| Smart model routing | Yes (per-intent) | Single model | Single model | Single model |
| Self-hosted | Yes | No | No | Yes |
| Open-source | Yes (MIT) | No | No | Yes |
| Proactive check-ins | Yes | No | No | No |

---

*This document is the single source of truth for the Synapse product showcase website. All feature descriptions, design directions, and content assets flow from here.*
