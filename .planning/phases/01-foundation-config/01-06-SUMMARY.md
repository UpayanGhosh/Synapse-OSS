---
phase: 01-foundation-config
plan: "06"
subsystem: config
tags: [synapse_config, path-migration, scripts, skills, openclaw]

requires:
  - phase: 01-01
    provides: SynapseConfig with data_root, db_dir, sbs_dir, log_dir path resolution

provides:
  - All 15 workspace/scripts/ files route DB and data paths through SynapseConfig.load()
  - workspace/scripts/v2_migration/ files annotated as migration source readers
  - workspace/skills/llm_router.py stubbed _load_gateway_config() with TODO Phase 2
  - workspace/skills/language/ingest_dict.py path migrated to SynapseConfig
  - sys.path guards at correct depth for all script locations

affects:
  - 02-litellm
  - 04-whatsapp-bridge
  - 07-packaging

tech-stack:
  added: []
  patterns:
    - "sys.path.insert guard for standalone script imports: os.path.abspath(os.path.join(__file__, ..))"
    - "SynapseConfig.load() call per path resolution, not cached module-level singleton"
    - "v2_migration source files annotated with NOTE comment, source ~/.openclaw/ paths preserved"
    - "CLI binary references (openclaw send, openclaw gateway) stubbed with TODO Phase N comments"

key-files:
  created: []
  modified:
    - workspace/scripts/db_cleanup.py
    - workspace/scripts/db_organize.py
    - workspace/scripts/debug_grep.py
    - workspace/scripts/fact_extractor.py
    - workspace/scripts/genesis.py
    - workspace/scripts/latency_watcher.py
    - workspace/scripts/memory_test.py
    - workspace/scripts/migrate_temporal.py
    - workspace/scripts/nightly_ingest.py
    - workspace/scripts/optimize_db.py
    - workspace/scripts/prune_sessions.py
    - workspace/scripts/sentinel.py
    - workspace/scripts/simulate_brain.py
    - workspace/scripts/transcribe_v2.py
    - workspace/scripts/update_memory_schema.py
    - workspace/scripts/v2_migration/graph_handler.py
    - workspace/scripts/v2_migration/migrate_vectors.py
    - workspace/skills/language/ingest_dict.py
    - workspace/skills/llm_router.py

key-decisions:
  - "v2_migration source path refs (~/.openclaw/) intentionally preserved — they read FROM openclaw as migration input; annotated with NOTE comment"
  - "CLI binary calls (openclaw message send, openclaw gateway start) commented out with TODO Phase 4 markers — Phase 4 Baileys bridge will replace these"
  - "transcribe_v2.py openclaw.json API key fallback commented out with TODO Phase 2 — synapse.json providers config replaces this in Phase 2"
  - "sentinel.py process/service refs updated to synapse equivalents (pgrep synapse, ai.synapse.memory launchctl ID)"
  - "simulate_brain.py /tmp log dir renamed from /tmp/openclaw to /tmp/synapse"
  - "llm_router.py _load_gateway_config() stubbed to return (None, None) — downstream code falls through to local Ollama backup"

requirements-completed: [CONF-01]

duration: 11min
completed: "2026-03-02"
---

# Phase 1 Plan 06: Sweep openclaw paths in workspace/scripts and workspace/skills Summary

**SynapseConfig path migration across all 19 script and skill files — DB paths, data root refs, and openclaw.json credential lookups replaced; v2_migration source refs annotated; CLI binary calls stubbed with TODO Phase markers**

## Performance

- **Duration:** 11 min
- **Started:** 2026-03-02T09:24:02Z
- **Completed:** 2026-03-02T09:35:19Z
- **Tasks:** 2
- **Files modified:** 19

## Accomplishments

- Replaced all `~/.openclaw/` path constants in 15 workspace/scripts/ files with `SynapseConfig.load()` equivalents using sys.path guards at correct depths
- Annotated workspace/scripts/v2_migration/ files as intentional migration source readers, preserving their `~/.openclaw/` source references
- Stubbed `llm_router.py` `_load_gateway_config()` with TODO Phase 2 comment — no more openclaw.json credential lookup at import time
- Migrated `ingest_dict.py` banglish dictionary path to `SynapseConfig.load().data_root`
- Updated process/service management refs in sentinel.py to synapse equivalents

## Task Commits

1. **Task 1 + Task 2: Sweep scripts/ and skills/ files** - `09dd206` (feat)

**Plan metadata:** TBD (docs commit below)

## Files Created/Modified

**workspace/scripts/ — standard path substitution:**
- `workspace/scripts/db_cleanup.py` - `OPENCLAW_HOME/DB_PATH` replaced with `SynapseConfig.load().db_dir / "memory.db"`
- `workspace/scripts/db_organize.py` - same as db_cleanup.py
- `workspace/scripts/debug_grep.py` - `/tmp/openclaw/` log path replaced with `SynapseConfig.load().log_dir`
- `workspace/scripts/fact_extractor.py` - `OPENCLAW_HOME/DB_PATH` replaced with SynapseConfig
- `workspace/scripts/genesis.py` - print string `openclaw start` replaced with `synapse_start.sh`
- `workspace/scripts/latency_watcher.py` - `openclaw message send` CLI call commented out with TODO Phase 4
- `workspace/scripts/memory_test.py` - `db_path` hardcode replaced with SynapseConfig
- `workspace/scripts/migrate_temporal.py` - `OPENCLAW_HOME/DB_PATH` replaced with SynapseConfig
- `workspace/scripts/nightly_ingest.py` - `OPENCLAW_HOME/DB_PATH` replaced with SynapseConfig
- `workspace/scripts/optimize_db.py` - `db_path` hardcode replaced with SynapseConfig
- `workspace/scripts/prune_sessions.py` - `SESSION_FILE` path replaced with `data_root / "agents" / "main" / "sessions" / "sessions.json"`
- `workspace/scripts/sentinel.py` - `STATE_FILE`, `LOG_FILE`, log glob replaced with SynapseConfig; process/service refs updated to synapse
- `workspace/scripts/simulate_brain.py` - `/tmp/openclaw` dir renamed to `/tmp/synapse`; `brain_state` path replaced with `data_root / "brain_state.json"`
- `workspace/scripts/transcribe_v2.py` - `/tmp/openclaw` log dir renamed; `openclaw.json` API key fallback commented with TODO Phase 2
- `workspace/scripts/update_memory_schema.py` - `OPENCLAW_HOME/DB_PATH` replaced with SynapseConfig

**workspace/scripts/v2_migration/ — annotation only (source refs preserved):**
- `workspace/scripts/v2_migration/graph_handler.py` - NOTE comment added at top; `OPENCLAW_HOME/DB_PATH/GRAPH_PATH` preserved as migration source
- `workspace/scripts/v2_migration/migrate_vectors.py` - NOTE comment added at top; `OPENCLAW_HOME/DB_PATH` preserved as migration source

**workspace/skills/ — path substitution + stub:**
- `workspace/skills/language/ingest_dict.py` - `banglish_dict.json` path replaced with `data_root / "workspace" / "skills" / "language" / "banglish_dict.json"`
- `workspace/skills/llm_router.py` - `_load_gateway_config()` stubbed to return `(None, None)` with TODO Phase 2; original body commented out; `OPENCLAW_CONFIG_PATH` commented with TODO Phase 2

## Decisions Made

- **v2_migration files kept as-is**: `graph_handler.py` and `migrate_vectors.py` intentionally read from `~/.openclaw/` as migration source; annotating is the correct approach, not replacing
- **CLI binary stubs**: `openclaw message send` and `openclaw gateway start` calls commented out with TODO Phase 4 markers since Phase 4 (Baileys bridge) will provide the WhatsApp send capability
- **_load_gateway_config() stub returns (None, None)**: Downstream `_call_antigravity()` checks `if not self.gateway_url or not self.gateway_token: return None` then falls through to Ollama backup — correct behavior for Phase 1
- **sentinel.py process names updated eagerly**: Even though Phase 4 will define the real process names, the references are updated to `synapse` prefix now to avoid any residual openclaw process management

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Function name mismatch — plan says `_get_openclaw_auth()`, file has `_load_gateway_config()`**
- **Found during:** Task 2 (llm_router.py)
- **Issue:** Plan described stubbing `_get_openclaw_auth()` but the actual function in llm_router.py is `_load_gateway_config()`. The function body matches the plan's description (reads openclaw.json for gateway auth).
- **Fix:** Applied the stub to `_load_gateway_config()` as that is the correct function
- **Files modified:** workspace/skills/llm_router.py
- **Committed in:** 09dd206

**2. [Rule 2 - Missing] Process/service refs in sentinel.py needed updating beyond ~/ paths**
- **Found during:** Task 1 (sentinel.py)
- **Issue:** sentinel.py had `openclaw` in process names, pgrep args, launchctl service IDs, and subprocess calls — these are not `~/.openclaw/` path refs but still needed updating for OSS portability
- **Fix:** Updated all process/service refs to synapse equivalents with TODO Phase 4 markers
- **Files modified:** workspace/scripts/sentinel.py
- **Committed in:** 09dd206

---

**Total deviations:** 2 auto-fixed (1 function name correction, 1 scope extension for service refs)
**Impact on plan:** Both corrections necessary for correctness. No scope creep.

## Verification Results

**Task 1 verification (scripts/ only, excluding v2_migration source refs):**
```
Only remaining references:
- latency_watcher.py: commented-out line (TODO Phase 4 marker) — acceptable
- transcribe_v2.py: TODO Phase 2 comment lines — acceptable
- v2_migration/graph_handler.py: OPENCLAW_HOME = ... (intentional migration source) — acceptable
- v2_migration/migrate_vectors.py: OPENCLAW_HOME = ... (intentional migration source) — acceptable
```

**Task 2 verification (skills/ only):**
```
Only remaining references (all in comments):
- llm_router.py: TODO Phase 2 comment lines in stub — acceptable
```

**Full workspace grep (this plan's scope):**
Zero active `~/.openclaw/` path references in workspace/scripts/ (outside comments and v2_migration source).
Zero active `~/.openclaw/` path references in workspace/skills/.

**Test suite:**
- test_smoke.py: 25/25 passed
- test_config.py, test_queue.py, test_dedup.py, test_flood.py, test_sqlite_graph.py: 67/67 passed

## Issues Encountered

None — plan executed cleanly.

## Next Phase Readiness

- This plan completes the scripts/ and skills/ portion of the openclaw path sweep
- Plan 05 (running in parallel) handles workspace/ root and sci_fi_dashboard/ files
- After both Plan 05 and Plan 06 complete, the full `grep -r "openclaw" workspace/ --include="*.py"` check should pass (excluding migrate_openclaw.py, tests, and v2_migration source refs)
- Phase 2 can proceed with litellm integration; llm_router.py stub will be replaced with SynapseConfig.providers config

---
*Phase: 01-foundation-config*
*Completed: 2026-03-02*
