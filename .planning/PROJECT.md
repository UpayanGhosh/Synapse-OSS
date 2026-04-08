# Synapse-OSS

## What This Is

Synapse is the nervous system for AI — a self-evolving, model-agnostic personal AI
architecture that learns how you talk, remembers everything, acts proactively, and
reshapes itself around the person it serves. You bring the model; Synapse brings the
body. The relationship survives any model change.

One-line vision: *Every Synapse instance becomes a unique, self-evolving architecture
shaped entirely by the person it serves.*

## Core Value

An AI that knows you deeply, grows with you continuously, and reaches out to you
first — all on your machine, with your data, under your full control.

## Requirements

### Validated

- ✓ All LLM calls route through litellm with zero external binary dependencies — v1.0
- ✓ WhatsApp inbound/outbound works via self-managed Baileys bridge — v1.0
- ✓ Telegram, Discord, and Slack channels operational — v1.0
- ✓ Hybrid RAG memory (vector + FTS + knowledge graph) — Phases 0-4
- ✓ Soul-Brain Sync (SBS) 8-layer behavioral profiling — Phases 0-4
- ✓ Dual Cognition Engine (inner monologue + tension scoring) — Phases 0-4
- ✓ Proactive outreach (8h gap + sleep window check) — Phase 3
- ✓ WhatsApp chat history self-seeding — Phase 0
- ✓ OSS persona generalization (zero traces of original user) — v1.0
- ✓ Onboarding wizard (provider validation, QR, migration) — v1.0
- ✓ Full health endpoint + session metrics — v1.0

### Active

<!-- v3.0 — OpenClaw Feature Harvest -->
- [ ] User can chat via any of 10+ LLM providers without code changes (OpenAI, Anthropic, DeepSeek, Mistral, Together)
- [ ] 10+ bundled skills available out of the box (weather, reminders, notes, web scrape, translate, summarize, image describe)
- [ ] User receives voice replies on WhatsApp via TTS (ElevenLabs or edge-tts)
- [ ] User can request image generation ("draw me X") and receive it in chat
- [ ] Cron jobs run in isolated agent contexts with separate memory
- [ ] Web control panel provides real-time interactive dashboard with SSE
- [ ] User can have real-time voice conversations via streaming transcription

### Out of Scope

- Real-time collaborative multi-user sessions — architecture is per-user by design
- Hosted/cloud version — fully self-hosted, user's machine only
- Mobile native app — web-first; mobile access via channels (WhatsApp, Telegram)
- Model fine-tuning — Synapse influences behavior through prompting, not weights

## Context

**What's shipped:**
- v1.0 OSS independence (10 phases, 38 plans) — all channels, memory, SBS, Dual Cognition, proactive outreach
- v2.0 Proactive Architecture (6 phases, 22 plans) — skill system, safe self-modification, subagents, onboarding wizard v2, browser tool, embedding refactor, Qdrant→LanceDB, ollama made optional, Docker removed

**Current branch:** `develop` — v2.0 merged and pushed (2026-04-08). Ready for v3.0 work.

## Current Milestone: v3.0 OpenClaw Feature Harvest

**Goal:** Port high-value design patterns from the OpenClaw TypeScript codebase (6000+ files, 47 providers, 53 skills) into Synapse-OSS Python — concepts not code, depth not breadth.

**Target features:**
- Expanded LLM provider routing (OpenAI, Anthropic native, DeepSeek, Mistral, Together)
- Bundled skills library (~10 most useful: weather, reminders, notes, translate, summarize)
- TTS / voice output (ElevenLabs or edge-tts for WhatsApp voice replies)
- Image generation (DALL-E/Flux via API)
- Cron with isolated agents (each job runs in its own agent context)
- Web control panel (interactive real-time dashboard, not just static HTML)
- Realtime voice streaming (streaming Whisper or WebRTC for live voice chat)

**Architecture zones (non-negotiable):**
- Zone 1 (immutable): API gateway, auth, keys, core message loop, self-modification
  engine itself, rollback mechanism
- Zone 2 (adaptive, with consent): cron jobs, MCP integrations, model routing, memory
  architecture, SBS profile depth, pipeline stages, proactive triggers, AI name/personality
- Consent protocol: explain → confirm → execute → snapshot. No exceptions. No silent mods.

**Key architectural gotchas:**
- `synapse_config.py` imported by 50+ files — blast radius is wide
- DualCognitionEngine `think()` coupled to `api_gateway.py` via `pre_cached_memory` param
- litellm Router ≠ litellm.acompletion for GitHub Copilot — rewrite shim is in llm_router.py
- LanceDB upsert_facts() rebuilds index per call — use table.merge_insert() for bulk ops
- Banglish ~2 chars/token — batch=16 MAX_CHARS=1000 for embedder
- asyncio.create_task() for all channel starts — NEVER asyncio.run() (uvicorn owns loop)

## Constraints

- **Tech stack:** Python 3.11, FastAPI/uvicorn, litellm, SQLite WAL, LanceDB, asyncio
- **Platform:** Windows + Linux + Mac (Windows is primary dev machine)
- **Privacy:** Zone 1 data never leaves the machine regardless of model routing
- **Rollback:** Phase 6 (self-modification) MUST ship with rollback — non-negotiable
- **Divergence:** Two instances should look structurally different after a month of use

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| litellm as LLM backbone | Single acompletion() covers all 25+ providers | ✓ Good |
| Baileys Node.js for WhatsApp | No production-grade pure-Python alternative | ✓ Good |
| ~/.synapse/ as data root | User-owned, configurable via SYNAPSE_HOME | ✓ Good |
| Skills as directories, not Python plugins | Human-readable, AI-writable, version-controllable | — Pending |
| Zone 1/Zone 2 hard split | Prevents catastrophic self-modification | — Pending |
| Phase 6 ships WITH rollback | Self-mod without rollback is not an option (Jarvis lesson) | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-08 — v3.0 milestone started (OpenClaw Feature Harvest)*
