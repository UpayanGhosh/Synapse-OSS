---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-02T16:38:48.154Z"
progress:
  total_phases: 4
  completed_phases: 3
  total_plans: 18
  completed_plans: 16
---

---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-02T16:34:16.740Z"
progress:
  total_phases: 4
  completed_phases: 3
  total_plans: 18
  completed_plans: 15
---

---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: in_progress
last_updated: "2026-03-02T12:17:37Z"
progress:
  total_phases: 7
  completed_phases: 2
  total_plans: 14
  completed_plans: 14
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-02)

**Core value:** A user can run Synapse-OSS on any machine, connect to their messaging apps and LLM providers, and have a fully working AI assistant — with zero dependency on any external binary or bridge service.
**Current focus:** Phase 4 — WhatsApp Baileys Bridge

## Current Position

Phase: 4 of 7 (WhatsApp Baileys Bridge) — In Progress
Plan: 3 of 4 complete in current phase (04-01 test scaffold + 04-02 Baileys bridge + 04-03 WhatsAppChannel)
Status: Plans 04-01, 04-02, 04-03 complete — all 8 WA tests GREEN; WhatsAppChannel(BaseChannel) with supervisor+httpx; ready for Plan 04-04 (wire into api_gateway)
Last activity: 2026-03-02 — Plan 04-03 complete: WhatsAppChannel in channels/whatsapp.py + __init__.py export; all 8 WA tests GREEN (WA-01 through WA-08); 2 tasks, 2 files

Progress: [█████████████░░░░░░░] 16/18 plans complete (Phase 4 in progress)

## Performance Metrics

**Velocity:**
- Total plans completed: 15
- Average duration: 8.5 min
- Total execution time: 1.99 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation-config | 6/6 | 57 min | 9.5 min |
| 02-llm-provider-layer | 4/4 | 33 min | 8.3 min |
| 03-channel-abstraction-layer | 4/4 | 31 min | 7.8 min |
| 04-whatsapp-baileys-bridge | 3/4 | 13 min | — |

**Recent Trend:**
- Last 5 plans: [10min, 3min, 2min, 25min, 8min, 11min]
- Trend: stable

*Updated after each plan completion*
| Phase 03-channel-abstraction-layer P03 | 10 | 2 tasks | 2 files |
| Phase 03-channel-abstraction-layer P02 | 2 | 1 tasks | 1 files |
| Phase 03-channel-abstraction-layer P01 | 6 | 3 tasks | 4 files |
| Phase 03-channel-abstraction-layer P04 | 9 | 1 tasks | 3 files |
| Phase 04-whatsapp-baileys-bridge PP02 | 3 | 3 tasks | 4 files |
| Phase 04-whatsapp-baileys-bridge P01 | 8 | 1 tasks | 1 files |
| Phase 04-whatsapp-baileys-bridge P03 | 10 | 2 tasks | 2 files |

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
- [Phase 02-03]: _run_async() uses ThreadPoolExecutor not nest_asyncio — avoids patching asyncio internals; works in both sync (db/tools.py) and async (FastAPI handlers) contexts
- [Phase 02-03]: cloud_models defaults to ["casual"] not ["google-antigravity/gemini-3-flash"] — "casual" is a valid synapse role name for role-based routing
- [Phase 02-03]: force_kimi preserved in generate() signature for backward compat but ignored — role-based routing replaces old Kimi/NVIDIA path
- [Phase 02-04]: test_no_hardcoded_models changed from grep -r directory scan to inline file parser checking specific files — avoids false positives in llm_router.py docstrings that explain model string format
- [Phase 02-04]: synapse_llm_router initialized at module scope (not in lifespan) — SynapseLLMRouter does no I/O at init time; consistent with other module-level singletons in api_gateway.py
- [Phase 02-04]: httpx retained in api_gateway.py — translate_banglish() still uses httpx.AsyncClient for OpenRouter REST calls directly; will be addressed in a later phase
- [Phase 03-channel-abstraction-layer]: Per-method _channels_skip decorator (not pytestmark) — non-channel test classes stay independent of channels/ availability
- [Phase 03-channel-abstraction-layer]: xfail strict=False for CHAN-04/05/07 — tests auto-turn GREEN when 03-03/03-04 ship without test rewrites
- [Phase 03-channel-abstraction-layer]: asyncio.create_task() wraps channel.start() in start_all() — NEVER asyncio.run() — uvicorn already owns event loop
- [Phase 03-channel-abstraction-layer]: ChannelRegistry is an instance (not module-level singleton) — tests create independent registries without global state reset
- [Phase 03-channel-abstraction-layer]: StubChannel.start() returns immediately — callers asserting _started after start_all() must yield with await asyncio.sleep(0)
- [Phase 03-03]: StubChannel used for 'whatsapp' channel in Phase 3 — real WhatsApp bridge in Phase 4; registry slot already reserved
- [Phase 03-03]: channel_registry initialized at module scope (not in lifespan) — ChannelRegistry does no I/O at init; consistent with task_queue/flood/dedup singletons
- [Phase 03-03]: CHAN-04/05 tests remain xfail in dev env — api_gateway requires sqlite_vec which is not in the lightweight test environment; xfail(strict=False) is correct; routes are code-verified
- [Phase 03-04]: sender kept as Optional[WhatsAppSender] fallback alongside channel_registry; Phase 4 removes it when Baileys bridge ships
- [Phase 03-04]: _safe_task_done() wraps task_done() in try/except ValueError — allows _handle_task direct-call test patterns without enqueue/dequeue
- [Phase 03-04]: _split_long_message() is module-level helper — reusable by any dispatch path without importing MessageWorker
- [Phase 04-whatsapp-baileys-bridge]: baileys@6.7.21 pinned exactly (not semver range) — API surface changes between patch releases; exact pin + committed package-lock.json ensures reproducible installs
- [Phase 04-whatsapp-baileys-bridge]: No 'type: module' in baileys-bridge/package.json — baileys@6.7.21 is CommonJS; adding type=module breaks all require() calls
- [Phase 04-whatsapp-baileys-bridge]: Built-in Node 18+ fetch() used instead of node-fetch npm — WA-08 validates >=18 so built-in always available; removes one dependency
- [Phase 04-whatsapp-baileys-bridge]: pytestmark skipif WA_AVAILABLE guard applied module-wide — 8 tests SKIP until whatsapp.py exists; mirrors test_channels.py pattern
- [Phase 04-whatsapp-baileys-bridge]: _make_mock_process() two-mode factory (returncode=None for running, returncode=N for crash) — reused across WA-02 and WA-06 supervisor tests
- [Phase 04-03]: INITIAL_BACKOFF=0.0 — first restart immediate; subsequent: max(backoff*2,1.0) gives 1→2→4→8→…→60s; enables WA-06 test to assert restart within 10 asyncio.sleep(0) yields
- [Phase 04-03]: asyncio.TimeoutError → builtin TimeoutError in stop() — ruff UP041; Python 3.11+ builtin is correct alias
- [Phase 04-03]: per-request httpx.AsyncClient in async-with — avoids shared mutable connection state in async supervisor context

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 2 (litellm streaming): stream=False enforced in Plan 02; streaming not used in Phase 2 — blocker removed
- None active: Phase 4 Plan 04-03 complete; ready for 04-04 (wire WhatsAppChannel into api_gateway)

## Session Continuity

Last session: 2026-03-02T16:51:46Z
Stopped at: Completed 04-03-PLAN.md — WhatsAppChannel(BaseChannel): subprocess supervisor, Node.js 18+ validation, httpx HTTP client; all 8 WA tests GREEN; channels/__init__.py updated; 2 tasks, 2 files
Resume file: None
