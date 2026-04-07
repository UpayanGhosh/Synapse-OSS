---
gsd_state_version: 1.0
milestone: v3.0
milestone_name: Bioinspired Memory Architecture
status: roadmap-created
last_updated: "2026-04-08T00:00:00.000Z"
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-08)

**Core value:** An AI that knows you deeply, grows with you continuously, and reaches out to you first — on your machine, under your full control.
**Current focus:** v3.0 milestone — Bioinspired Memory Architecture — roadmap created, ready for Phase 6 planning

## Current Position

Phase: Not started (roadmap created)
Plan: —
Status: Roadmap created — ready for `/gsd-plan-phase 6`
Last activity: 2026-04-08 — v3.0 roadmap created (6 phases, 42 requirements mapped)

Progress: [░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 0/0 plans complete

## Pre-Work Checklist

Before starting Phase 6:

- [ ] Merge `refactor/optimize` → `develop` (KG async pipeline + Qdrant purge)
- [ ] Merge `develop` → `main` (PR: refactor/optimize → main)
- [ ] Verify tests pass on clean branch: `cd workspace && pytest tests/ -v`
- [ ] Confirm server starts: `cd workspace/sci_fi_dashboard && uvicorn api_gateway:app --host 0.0.0.0 --port 8000`

## Milestone Map

| Milestone | Target | Status | Description |
|-----------|--------|--------|-------------|
| v1.0 | 2026-03-03 | COMPLETE | OSS independence — all OpenClaw deps removed |
| v2.0 | 2026 | IN PROGRESS | The Adaptive Core — phases 0-2 remaining (skill system, self-mod, session persistence) |
| v3.0 | 2026 | CURRENT | Bioinspired Memory Architecture — neuroscience-inspired retrieval, consolidation, decay |
| v4.0 | 2027 | Future | Proactive Architecture Evolution |
| v5.0 | 2028 | Future | The Jarvis Threshold |

## v3.0 Phase Summary

| Phase | Name | Requirements | Status |
|-------|------|--------------|--------|
| 6 | Retrieval Foundation | RETR-01, RETR-02, RETR-04, RETR-05 | Not started |
| 7 | Memory Lifecycle Schema | MEM-01 through MEM-08 | Not started |
| 8 | Consolidation Engine | CONSOL-01–03, 07–09, RETR-03, QUERY-04–05 | Not started |
| 9 | Associative Memory | RETR-06, ASSOC-01–02, CONSOL-04, POST-01–05 | Not started |
| 10 | Query Intelligence + Contextual Retrieval | ASSOC-03–06, CONSOL-05–06, QUERY-01–03 | Not started |
| 11 | Embedding Migration | EMBED-01–03 | Not started |

**Total v3.0 requirements:** 42 across 7 categories
**Mapped:** 42/42

## Accumulated Context

### Decisions

- v2.0 initialized from GitHub Discussion #29 (vision document)
- Phase 2 (Self-Modification) MUST ship together with rollback — non-negotiable
- Skills-as-directories chosen over Python plugin system: simpler, AI-writable, no pip install
- v3.0 research basis: 29 papers, 57 Q&As, 7 follow-ups → architecture-spec.md (master spec)
- All 17 tunable parameters locked with paper-sourced defaults
- RRF k=20 (not k=60) tuned for personal scale (<100K docs)
- bge-m3 chosen over nomic-embed-text for multilingual + Matryoshka support
- Hopfield dedup threshold: 0.95 cosine (patterns above this merge, below stay distinct)
- Reconsolidation window: 0.3 < tension < 0.8 (not simple threshold; scales with memory strength)
- SM-2 adaptation: minimum 1-hour reinforcement interval prevents cramming
- Causal promotion: requires 3+ distinct contexts, not just observation count
- Schema formation and CLS consolidation are the same mechanism (single implementation)
- Mood repair for sustained negative states (boost positive memories alongside congruent ones)
- Phase ordering: schema migration (Phase 7) before all consolidation/associative work — columns must exist before logic that reads them
- Embedding migration (Phase 11) is last — all retrieval logic must be stable before changing vector representation

### Pending Todos

- Merge refactor/optimize → develop → main before execution begins
- DiaryEngine needs wiring into pipeline (pre-existing gap from v1.0)
- FlashRank token_type_ids warning (pre-existing, non-blocking)
- Hemisphere bug: session_mode computed but never passed to memory_engine.query() — FIXED in Phase 6 (RETR-04)

### Blockers/Concerns

None active. Roadmap created. Ready for phase planning.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260406-rze | Refactor EntityGate to load entity names from knowledge_graph.db instead of entities.json | 2026-04-06 | e585832 | [260406-rze](./quick/260406-rze-refactor-entitygate-to-load-entity-names/) |

## Session Continuity

Last session: 2026-04-08 (v3.0 roadmap creation — 6 phases, 42 requirements, 100% coverage)
Stopped at: Roadmap written
Resume file: None
Next step: `/gsd-plan-phase 6` — Retrieval Foundation
