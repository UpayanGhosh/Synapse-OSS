---
phase: standalone-verification
plan: standalone-01
subsystem: infra
tags: [shell-scripts, deprecation, openclaw, gap-closure, UAT]

# Dependency graph
requires:
  - phase: 09-verification-backfill-llm-cleanup
    provides: Phase 9 complete; UAT revealed 2 remaining gaps (tests 11 & 12)
provides:
  - DEPRECATED block headers on all 6 legacy V2 shell scripts
  - UAT tests 11 and 12 closed (12/12 pass)
  - standalone-UAT.md updated to reflect 12 passed / 0 issues
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deprecation-header pattern: insert 8-line DEPRECATED block immediately after shebang, before original content — no logic altered"

key-files:
  created:
    - .planning/phases/standalone-verification/standalone-01-SUMMARY.md
  modified:
    - workspace/scripts/metabolism_master.sh
    - workspace/scripts/revive_jarvis.sh
    - workspace/scripts/rollback.sh
    - workspace/scripts/sentinel_heal.sh
    - workspace/sci_fi_dashboard/test.sh
    - synapse_manager.sh
    - .planning/phases/standalone-verification/standalone-UAT.md

key-decisions:
  - "Deprecate rather than delete: 6 V2-specific scripts receive DEPRECATED block headers; original logic preserved intact for historical reference"
  - "test.sh gained shebang during deprecation: file had no shebang; #!/bin/bash added as line 1 before the DEPRECATED block for correctness"
  - "synapse_manager.sh deprecation explicitly names synapse_start.sh, synapse_stop.sh, synapse_health.sh as correct replacements"

patterns-established:
  - "Gap closure via deprecation: when V2-specific scripts cannot be cleaned without breaking original intent, a DEPRECATED block header satisfies 'clean or deprecate' UAT requirements"

requirements-completed: []

# Metrics
duration: 5min
completed: 2026-03-03
---

# Phase standalone-verification Plan 01: Deprecation Headers for Legacy V2 Scripts Summary

**DEPRECATED block comments added to all 6 openclaw-referencing V2 shell scripts, closing UAT tests 11 and 12 (12/12 UAT pass)**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-03-03T12:20:00Z
- **Completed:** 2026-03-03T12:25:00Z
- **Tasks:** 2
- **Files modified:** 7 (6 scripts + UAT.md)

## Accomplishments
- Inserted DEPRECATED block headers into 4 workspace/scripts/ V2-only scripts (metabolism_master.sh, revive_jarvis.sh, rollback.sh, sentinel_heal.sh)
- Inserted DEPRECATED block header into workspace/sci_fi_dashboard/test.sh (also added missing shebang) and synapse_manager.sh
- Updated standalone-UAT.md: tests 11 and 12 changed from `issue` to `pass`; summary updated to 12 passed / 0 issues; Gaps section removed
- All primary user-facing scripts (synapse_start.sh, synapse_stop.sh, synapse_health.sh) confirmed clean — 0 openclaw references

## Task Commits

Each task was committed atomically:

1. **Task SV-01: Add DEPRECATED headers to workspace/scripts/ legacy scripts (4 files)** - `4a4eb2a` (chore)
2. **Task SV-02: Add DEPRECATED header to test.sh and synapse_manager.sh** - `54ddb34` (chore)

## Files Created/Modified
- `workspace/scripts/metabolism_master.sh` - DEPRECATED block inserted after shebang (V2 openclaw binary + OPENCLAW_HOME refs)
- `workspace/scripts/revive_jarvis.sh` - DEPRECATED block inserted after shebang (calls `openclaw gateway start`)
- `workspace/scripts/rollback.sh` - DEPRECATED block inserted after shebang (uses OPENCLAW_HOME session dir)
- `workspace/scripts/sentinel_heal.sh` - DEPRECATED block inserted after shebang (OPENCLAW_HOME + /tmp/openclaw/ refs)
- `workspace/sci_fi_dashboard/test.sh` - shebang + V1 DEPRECATED block prepended to 4-line raw command snippet
- `synapse_manager.sh` - DEPRECATED block inserted after shebang with explicit pointer to synapse_start.sh/stop.sh/health.sh
- `.planning/phases/standalone-verification/standalone-UAT.md` - tests 11+12 updated to pass; summary 10→12 passed, 2→0 issues; Gaps section removed

## Decisions Made
- Deprecate rather than delete: all 6 scripts are V2-specific legacy artifacts; removing them would erase historical reference without benefit to Synapse-OSS users. A DEPRECATED block satisfies the "clean or deprecate" UAT requirement.
- test.sh received a shebang as part of the deprecation block: the file had no shebang (raw command snippet), so `#!/bin/bash` was added as line 1 of the new header for correctness — original 4 lines follow unchanged.
- synapse_manager.sh deprecation block explicitly names all three correct replacements (synapse_start.sh, synapse_stop.sh, synapse_health.sh) to eliminate contributor confusion.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All 12 UAT tests pass (12/12)
- All 6 gap scripts are now clearly marked as V2-only legacy, not applicable to Synapse-OSS
- standalone-verification phase is complete

## Self-Check: PASSED

- All 6 modified shell scripts confirmed present on disk
- standalone-01-SUMMARY.md confirmed present
- Commits 4a4eb2a and 54ddb34 confirmed in git history

---
*Phase: standalone-verification*
*Completed: 2026-03-03*
