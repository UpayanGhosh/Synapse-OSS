---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: in_progress
last_updated: "2026-03-02T10:36:27Z"
progress:
  total_phases: 7
  completed_phases: 1
  total_plans: 7
  completed_plans: 7
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-02)

**Core value:** A user can run Synapse-OSS on any machine, connect to their messaging apps and LLM providers, and have a fully working AI assistant — with zero dependency on any external binary or bridge service.
**Current focus:** Phase 2 — LLM Provider Layer

## Current Position

Phase: 2 of 7 (LLM Provider Layer) — In progress
Plan: 2 of 4 complete in current phase
Status: In progress
Last activity: 2026-03-02 — Plan 02-02 complete: SynapseLLMRouter implemented with litellm.Router; 19 tests GREEN, test_no_hardcoded_models XFAIL; litellm pinned in pyproject.toml

Progress: [████████████░░] 32% (2/4 plans in phase 2)

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: 2.7 min
- Total execution time: 0.09 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation-config | 6/6 | 57 min | 9.5 min |
| 02-llm-provider-layer | 2/4 | 21 min | 10.5 min |

**Recent Trend:**
- Last 5 plans: [18min, 3min, 2min, 25min, 8min, 11min]
- Trend: stable

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap: litellm as unified LLM backbone — single acompletion() call covers all 25+ OpenClaw providers
- Roadmap: Baileys Node.js microservice as WhatsApp bridge — managed subprocess, no pure-Python alternative is production-grade
- Roadmap: ~/.synapse/ as new data root, configurable via SYNAPSE_HOME env var
- Roadmap: Phased channel rollout — WhatsApp + Telegram + Discord + Slack in v1
- [Phase 01-foundation-config]: SynapseConfig placed in workspace/synapse_config.py — distinct from workspace/config.py (tools-server at port 8989)
- [Phase 01-foundation-config]: Derived paths (db_dir, sbs_dir, log_dir) always computed from data_root at load time — never read from synapse.json to prevent path drift
- [Phase 01-foundation-config]: DB_PATH resolved via _get_db_path() lazy-import pattern — allows test monkeypatching of SYNAPSE_HOME before path is evaluated
- [Phase 01-foundation-config]: whatsapp_loop_test returns HTTP 501 (Phase 4 Baileys bridge placeholder)
- [Phase 01-foundation-config]: validate_api_key() uses GEMINI_API_KEY for auth instead of OPENCLAW_GATEWAY_TOKEN
- [Phase 01-foundation-config]: migrate() Steps 3-9 all inside TemporaryDirectory with-block — staging always valid; manifest write (Step 10) outside with-block after dest files confirmed written
- [Phase 01-foundation-config]: Source data never deleted — migrate() is purely additive; dry_run returns early inside with-block before any dest writes
- [Phase 01-05]: smart_entity.py had no openclaw path references — skipped without modification
- [Phase 01-05]: state.py json import removed after subprocess block stubbed (no longer used); sessions_data placeholder returns empty list for downstream compatibility
- [Phase 01-05]: monitor.py OPENCLAW_HOME renamed to SYNAPSE_HOME using SynapseConfig.load().data_root
- [Phase 01-06]: v2_migration source path refs (~/.openclaw/) intentionally preserved — annotated with NOTE comment
- [Phase 01-06]: llm_router.py _load_gateway_config() stubbed to return (None, None) — downstream falls through to Ollama backup; full replacement in Phase 2
- [Phase 01-06]: sentinel.py process/service refs updated to synapse equivalents eagerly (pgrep synapse, ai.synapse.memory launchctl ID)
- [Phase 02-01]: Tests use pytestmark skipif (ROUTER_AVAILABLE=False) rather than per-function marks — single guard makes RED->GREEN transition a one-line edit when Plan 02 ships the router
- [Phase 02-01]: LLM-16 (no hardcoded models) marked xfail strict=False — naturally passes after Plan 04 sweeps call sites, no test rewrite needed
- [Phase 02-01]: model_mappings defaults to empty dict {} same as providers/channels — consistent three-layer precedence
- [Phase 02-02]: num_retries=0 in litellm.Router — fallback chain handles redundancy; retrying same model on RateLimitError consumes quota without benefit
- [Phase 02-02]: _inject_provider_keys() respects env var precedence — only injects if env var not already set (env Layer 1 > synapse.json Layer 2)
- [Phase 02-02]: github_copilot_fake_auth autouse fixture in conftest.py — prevents OAuth device-code flow during unit tests for github_copilot/ Router entries

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 4 (Baileys bridge): verify current @whiskeysockets/baileys API for useMultiFileAuthState() and cachedGroupMetadata before writing bridge JS — Baileys API surface changes between releases
- Phase 2 (litellm streaming): stream=False enforced in Plan 02; streaming not used in Phase 2 — blocker removed

## Session Continuity

Last session: 2026-03-02T10:36:27Z
Stopped at: Completed 02-02-PLAN.md — SynapseLLMRouter with litellm.Router; 19 tests GREEN; litellm pinned in pyproject.toml
Resume file: None
