---
phase: 02-optional-ollama
plan: 02
subsystem: infra
tags: [ollama, onboarding, shell-scripts, batch, bash, optional-dependencies]

# Dependency graph
requires: []
provides:
  - synapse_onboard.bat runs to completion on machines without Ollama installed
  - synapse_onboard.sh runs to completion on machines without Ollama installed
  - OLLAMA_FOUND flag gates ollama serve/pull commands in both scripts
  - Clear optional-feature warning ([--]) printed when Ollama is absent
affects: [03-embedding-fallback, 04-whatsapp-setup]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "OLLAMA_FOUND flag pattern: set variable on tool-found path, skip actions when unset/false"
    - "Optional dependency check: standalone block with [--] warning instead of MISSING=1 hard-fail"

key-files:
  created: []
  modified:
    - synapse_onboard.bat
    - synapse_onboard.sh

key-decisions:
  - "Ollama demoted to optional: prints warning and continues instead of blocking with MISSING=1 / all_good=false"
  - "OLLAMA_FOUND flag guards ollama pull in both scripts -- no pull attempted when Ollama absent"
  - "Shell script uses [OK]/[--] ASCII markers for Ollama lines (matching bat style) to avoid emoji concerns on non-terminal outputs"

patterns-established:
  - "Optional tool check pattern: check tool presence, set FOUND flag on success, print [--] warning on failure, never set MISSING/all_good=false"
  - "Gate pattern: wrap optional tool commands inside if defined OLLAMA_FOUND (bat) or if [ \"$OLLAMA_FOUND\" = true ] (sh)"

requirements-completed: [OLL-04]

# Metrics
duration: 2min
completed: 2026-02-27
---

# Phase 02 Plan 02: Optional Ollama Onboarding Summary

**Ollama demoted from hard-required to optional in both onboarding scripts -- absent Ollama prints a [--] warning and setup continues, with pull commands gated behind an OLLAMA_FOUND flag**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-27T16:58:48Z
- **Completed:** 2026-02-27T17:00:57Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- `synapse_onboard.bat`: Ollama check block no longer sets `MISSING=1`; now prints `[--] ollama is NOT installed -- local embedding and The Vault will be disabled` and continues
- `synapse_onboard.bat`: `ollama pull nomic-embed-text` wrapped in `if defined OLLAMA_FOUND` guard -- skipped when Ollama absent
- `synapse_onboard.sh`: `check_tool ollama || all_good=false` line removed; replaced with standalone optional check block that sets `OLLAMA_FOUND=true/false`
- `synapse_onboard.sh`: entire `[2/4] Starting Ollama...` serve+pull block wrapped in `if [ "$OLLAMA_FOUND" = true ]` with else branch printing `[2/4] Ollama not installed -- skipping (local embedding disabled)`

## Task Commits

Each task was committed atomically:

1. **Task 1: Demote Ollama to optional in synapse_onboard.bat** - `7601750` (feat)
2. **Task 2: Demote Ollama to optional in synapse_onboard.sh** - `3b26d73` (feat)

**Plan metadata:** `543670e` (docs: complete plan)

## Files Created/Modified
- `synapse_onboard.bat` - Ollama check block changed from hard-fail to optional warning; pull command gated on OLLAMA_FOUND
- `synapse_onboard.sh` - check_tool ollama removed from required list; OLLAMA_FOUND standalone block added; serve+pull block gated

## Decisions Made
- Ollama demoted to optional: onboarding must succeed without it since local embedding has a cloud/sentence-transformer fallback
- `OLLAMA_FOUND` flag pattern chosen for gating: clean, idiomatic in both bat and sh, requires no structural changes
- `.sh` Ollama output lines use `[OK]`/`[--]` ASCII markers (not emoji) matching the pattern already used in bat and consistent with the plan note about scope of the Phase 1 Unicode fix

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both onboarding scripts now pass `bash -n` syntax check
- Users without Ollama can complete full onboarding -- they will see clear `[--]` warnings and Synapse will start using the sentence-transformer fallback for embeddings
- Phase 3 (embedding fallback) is unblocked: the onboarding no longer requires Ollama to be present before the fallback logic is exercised

## Self-Check: PASSED

- FOUND: synapse_onboard.bat (modified)
- FOUND: synapse_onboard.sh (modified)
- FOUND: 02-02-SUMMARY.md (created)
- FOUND: commit 7601750 (Task 1)
- FOUND: commit 3b26d73 (Task 2)
- FOUND: commit 543670e (metadata)

---
*Phase: 02-optional-ollama*
*Completed: 2026-02-27*
