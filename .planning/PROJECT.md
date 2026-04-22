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

<!-- v3.1 — Reliability + OpenClaw Supervisor Patterns -->
- [ ] WhatsApp inbound messages reliably reach the reply pipeline (no silent drops)
- [ ] WhatsApp outbound retry queue flushes automatically on reconnect
- [ ] ProactiveAwarenessEngine reaches out to users after 8h+ of silence (not dead code)
- [ ] Skill-routing runs exactly once per message (no duplicate state mutations)
- [ ] Session-key is derived from a single canonical builder end-to-end
- [ ] Dead-but-connected WhatsApp sockets are detected by watchdog and force-reconnected
- [ ] Self-echoes (bot replies triggering the pipeline) are suppressed via outbound tracker
- [ ] Reconnect policy is configurable via synapse.json (initialMs/maxMs/factor/jitter/maxAttempts)
- [ ] All gateway logs carry a correlation runId and redact PII identifiers
- [ ] Baileys is upgraded to 7.x with pairing + media + groups validated
- [ ] WhatsApp creds are persisted atomically per authDir (no corruption on abrupt restart)
- [ ] Heartbeat subsystem sends configurable health pings to named recipients
- [ ] /channels/whatsapp/status surfaces a healthState enum (logged-out/conflict/reconnecting/stopped)
- [ ] Inbound access-control gate runs before the pipeline (not only at DmPolicy)
- [ ] chat_pipeline.py is decomposed into phase modules (normalize/debounce/access/enrich/route/reply)

<!-- v3.0 — OpenClaw Feature Harvest (still-in-flight, single phase pending) -->
- [ ] User can have real-time voice conversations via streaming transcription (Phase 11 — carryover)

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

## Current Milestone: v3.1 Reliability + OpenClaw Supervisor Patterns

**Goal:** Fix Synapse's WhatsApp unresponsiveness and dead proactive outreach, then port OpenClaw's battle-tested supervisor/reliability patterns (watchdog, echo tracker, heartbeat, structured logging, multi-account, configurable reconnect) into the Python stack. Derived from direct comparative analysis of OpenClaw (TypeScript, in-process Baileys) vs Synapse (Python + Node bridge).

**Target features:**

*P0 — Ship-blocking bug fixes:*
- Await the `update_connection_state()` coroutine at `routes/whatsapp.py:147`
- Wire `ProactiveAwarenessEngine.maybe_reach_out()` into the running `gentle_worker_loop()`
- Remove the duplicate skill-routing block in `chat_pipeline.py` (lines 472 + 546)
- Unify session-key derivation across `on_batch_ready()` and `process_message_pipeline()`

*P1 — OpenClaw reliability pattern ports:*
- Watchdog timer (30-min silence → force bridge restart)
- Outbound echo tracker (suppress self-echo loops)
- Configurable reconnect policy in `synapse.json`
- Structured logging with `runId` + `redact_identifier()` PII helper
- Inbound access-control gate pre-pipeline
- Baileys 6.7.21 → 7.x upgrade (bridge side)
- Atomic per-authDir creds-save queue
- Heartbeat subsystem with configurable recipients + `HEARTBEAT_TOKEN` opt-out
- `healthState` enum on `/channels/whatsapp/status`

*P2 — Architectural modernization:*
- Split monolithic `chat_pipeline.py` into phase modules (normalize → debounce → access → enrich → route → reply)
- Multi-account WhatsApp (per-account authDir, allowlists, media limits)
- Python↔Node bridge hardening (mutual heartbeat, webhook idempotency, auto-restart policy)

**Carryover from v3.0:**
- Phase 11 — Realtime Voice Streaming (96% of v3.0 complete; Phase 11 is the only open phase)

**Architecture zones (non-negotiable, unchanged from v3.0):**
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
- **v3.1 specific:** The Python↔Node HTTP bridge is a distributed-systems seam — any reliability improvement must treat it as such (no fire-and-forget coroutines, no silent drops, mutual health checks)
- **v3.1 specific:** Baileys 7.x has breaking changes in `useMultiFileAuthState` and `sendMessage` media shapes — validate pairing/media/groups before shipping

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
*Last updated: 2026-04-21 — v3.1 milestone started (Reliability + OpenClaw Supervisor Patterns)*
