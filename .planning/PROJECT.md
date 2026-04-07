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

<!-- v2.0 — The Adaptive Core (phases 0-2 remaining) -->
- [ ] User can define a skill as a directory (SKILL.md + scripts/ + references/)
- [ ] Skills are discovered at startup from ~/.synapse/skills/
- [ ] Skills are routed by description match, not hardcoded dispatch
- [ ] A skill-creator skill generates new skills from within conversation
- [ ] Every Zone 2 modification follows: explain → confirm → execute → snapshot
- [ ] User can roll back to any prior snapshot by date or natural language
- [ ] Auto-revert fires on any modification that breaks the core loop
- [ ] Zone 1 (gateway/auth/core loop) is immutable to model writes
- [ ] Sub-agents can be spawned for parallel or long-running work
- [ ] Sub-agent results return to the parent conversation
- [ ] `python -m synapse setup` completes full setup in under 5 minutes
- [ ] Browser tool provides live web access during chat

<!-- v3.0 — Bioinspired Memory Architecture -->
- [ ] Hybrid retrieval: BM25 via FTS5 + dense via LanceDB + RRF fusion
- [ ] MMR diversification prevents redundant retrieval results
- [ ] Memory strength tracks access frequency with Ebbinghaus decay curve
- [ ] Emotional state tagged at write time and used for state-dependent retrieval
- [ ] Context tags (work/health/relationships/etc.) filter retrieval via contextual integrity norms
- [ ] CLS consolidation extracts semantic patterns from episodic clusters (SWS gist pass)
- [ ] REM association pass finds cross-domain structural similarities
- [ ] Modern Hopfield co-activation returns memories that co-occur with retrieved results
- [ ] Reconsolidation updates or creates competing memory traces on prediction error
- [ ] Metamemory FOK pre-check estimates retrieval confidence before full search
- [ ] Causal edges promoted from correlations when observed across 3+ distinct contexts
- [ ] HyDE/Query2doc expands vague queries via hypothetical document embeddings
- [ ] Schema-guided encoding at write time accelerates consolidation of congruent memories
- [ ] bge-m3 multilingual embedding model replaces nomic-embed-text

### Out of Scope

- Real-time collaborative multi-user sessions — architecture is per-user by design
- Hosted/cloud version — fully self-hosted, user's machine only
- Mobile native app — web-first; mobile access via channels (WhatsApp, Telegram)
- Model fine-tuning — Synapse influences behavior through prompting, not weights

## Current Milestone: v3.0 Bioinspired Memory Architecture

**Goal:** Transform Synapse's memory from single-channel vector search into a neuroscience-inspired
system with dual retrieval, adaptive forgetting, consolidation, associative recall, and contextual
integrity — covering ~65% of human memory subsystems.

**Target features:**
- Hybrid retrieval (BM25 + dense + RRF + MMR + reranker)
- Ebbinghaus memory strength with spacing-aware reinforcement
- Emotional state tagging + state-dependent retrieval bias
- Contextual Integrity norms as retrieval filter
- CLS two-phase consolidation (SWS gist + REM association)
- Modern Hopfield co-activation layer
- Reconsolidation on prediction error
- Metamemory FOK pre-check
- Causal edge promotion
- HyDE/Query2doc query expansion
- Schema-guided encoding
- bge-m3 embedding migration

**Research basis:** 29 papers, 57 Q&As, 7 follow-ups. Master spec at
`memory-vault/research/architecture-spec.md`. 17 tunable parameters locked.

## Context

**What's shipped:** v1.0 OSS independence (10 phases, 38 plans). v2.0 phases 3-5 complete
(subagents, onboarding wizard v2, browser tool). v2.0 phases 0-2 remain (session persistence,
skill architecture, self-mod + rollback).

**Current branch:** `refactor/optimize` — KG pipeline refactored (async LLM-router
extraction, Qdrant removed). Merge to `develop` → `main` before execution begins.

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
| Bioinspired memory architecture | 29 papers consolidated into master spec; CLS, Hopfield, Ebbinghaus, CI | — Pending |
| bge-m3 replaces nomic-embed-text | Multilingual, Matryoshka-compatible, MTEB leader | — Pending |
| RRF k=20 for personal scale | Paper default k=60 is for large benchmarks; k=20 tuned for <100K docs | — Pending |

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
*Last updated: 2026-04-08 after v3.0 milestone initialization — Bioinspired Memory Architecture*
