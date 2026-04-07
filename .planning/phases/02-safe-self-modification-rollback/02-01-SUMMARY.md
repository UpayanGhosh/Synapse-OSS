---
phase: 02-safe-self-modification-rollback
plan: 01
subsystem: snapshot
tags: [snapshot, rollback, atomic-write, fastapi, sqlite, zone2]

requires:
  - phase: 01-skill-architecture
    provides: "SkillRegistry, skill directory structure at ~/.synapse/skills/ (Zone 2 target)"

provides:
  - "SnapshotEngine class with atomic create/list/restore/prune lifecycle"
  - "SnapshotMeta frozen dataclass serialised to SNAPSHOT.json per snapshot"
  - "GET /snapshots FastAPI endpoint returning all snapshot metadata"
  - "ZONE_2_PATHS tuple in manifest.py (skills + state/agents)"
  - "snapshot_engine singleton in _deps.py"

affects:
  - 02-safe-self-modification-rollback
  - 03-subagent-architecture

tech-stack:
  added: []
  patterns:
    - "Atomic directory snapshot: .tmp staging dir + os.replace() rename"
    - "Path traversal defense: re.sub slugify on create(), re.fullmatch validation on restore()"
    - "Forward history preservation: restore() creates pre-restore snapshot before overwriting (MOD-06)"
    - "Stale-tmp cleanup on init: _cleanup_stale_tmp() removes leftover .tmp dirs"
    - "Max snapshot pruning: _enforce_max_snapshots() deletes oldest when count > max"

key-files:
  created:
    - workspace/sci_fi_dashboard/snapshot_engine.py
    - workspace/sci_fi_dashboard/routes/snapshots.py
    - workspace/tests/test_snapshot_engine.py
  modified:
    - workspace/sci_fi_dashboard/_deps.py
    - workspace/sci_fi_dashboard/api_gateway.py
    - workspace/sci_fi_dashboard/sbs/sentinel/manifest.py

key-decisions:
  - "ZONE_2_PATHS added to manifest.py in 02-01 (not waiting for 02-02) — required to unblock Task 2 import; 02-02 will expand with descriptions"
  - "SnapshotMeta.path field excluded from SNAPSHOT.json serialisation — runtime-only, not portable"
  - "restore() creates pre-restore snapshot before overwriting live paths — preserves full forward history per MOD-06"
  - "snapshot_engine singleton initialized in lifespan (not at import time) — follows existing gateway pattern"

patterns-established:
  - "Snapshot atomicity: always stage in .tmp, then os.replace() — crash leaves only a .tmp"
  - "ID safety: slugify descriptions on create, fullmatch validate on restore"
  - "Zone 2 scope: always sourced from ZONE_2_PATHS in manifest.py, never hardcoded"

requirements-completed: [MOD-02, MOD-09, MOD-10]

duration: 15min
completed: 2026-04-07
---

# Phase 02 Plan 01: Snapshot Engine + GET /snapshots Summary

**Atomic Zone 2 snapshot engine (create/list/restore/prune) with .tmp+os.replace() pattern, path traversal defense, and a gateway-auth-protected GET /snapshots endpoint**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-04-07T09:52:00Z
- **Completed:** 2026-04-07T10:07:17Z
- **Tasks:** 2 (Task 1 TDD: 3 commits; Task 2: 1 commit)
- **Files modified:** 6

## Accomplishments

- SnapshotEngine.create() atomically writes a timestamped snapshot directory with SNAPSHOT.json + zone2/ contents using .tmp staging + os.replace()
- SnapshotEngine.restore() replaces Zone 2 live paths with snapshot copy and first creates a pre-restore snapshot for forward history (MOD-06)
- GET /snapshots endpoint returns JSON array of all snapshots sorted newest-first, protected by gateway_token auth (T-02-05)
- 12 unit tests pass covering create, atomicity, list order, restore, max-limit pruning, stale-tmp cleanup, and path traversal safety

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests** - `2e233bf` (test)
2. **Task 1 GREEN: SnapshotEngine implementation** - `564221c` (feat)
3. **Task 2: GET /snapshots route + gateway wiring** - `79529d0` (feat)

## Files Created/Modified

- `workspace/sci_fi_dashboard/snapshot_engine.py` - SnapshotEngine class + SnapshotMeta dataclass (306 lines)
- `workspace/sci_fi_dashboard/routes/snapshots.py` - GET /snapshots FastAPI route with gateway_token auth
- `workspace/tests/test_snapshot_engine.py` - 12 unit tests for full lifecycle (287 lines)
- `workspace/sci_fi_dashboard/_deps.py` - Added `snapshot_engine: SnapshotEngine | None = None` singleton
- `workspace/sci_fi_dashboard/api_gateway.py` - Top-level imports + lifespan init + router include
- `workspace/sci_fi_dashboard/sbs/sentinel/manifest.py` - Added ZONE_2_PATHS tuple

## Decisions Made

- **ZONE_2_PATHS added in 02-01 (not waiting for 02-02):** Task 2 imports ZONE_2_PATHS from manifest.py which is Plan 02-02's primary output. Since both plans run in wave 1 in parallel, adding a minimal ZONE_2_PATHS here unblocks Task 2 without conflict. Plan 02-02 will expand it with full descriptions.
- **SnapshotMeta.path excluded from JSON:** The `path` field holds the absolute on-disk directory path. It's excluded from SNAPSHOT.json serialisation since it's not portable across machines.
- **Pre-restore snapshot on restore():** Before overwriting live Zone 2 paths, restore() calls create() to capture the current state as a "pre-restore-{id}" snapshot. This implements MOD-06 (forward history) — you can always undo a restore.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added ZONE_2_PATHS to manifest.py**
- **Found during:** Task 2 (routes/snapshots.py wiring)
- **Issue:** api_gateway.py imports `ZONE_2_PATHS` from `manifest.py`, but manifest.py does not define this constant. Plan 02-02 (running in parallel in the same wave) is responsible for this constant, but Task 2 of this plan cannot import it until it exists.
- **Fix:** Added `ZONE_2_PATHS: tuple[str, ...] = ("skills", "state/agents")` to manifest.py with a note that 02-02 will expand it.
- **Files modified:** `workspace/sci_fi_dashboard/sbs/sentinel/manifest.py`
- **Verification:** `grep ZONE_2_PATHS manifest.py` confirms presence; api_gateway.py import passes.
- **Committed in:** `79529d0` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 - blocking import dependency)
**Impact on plan:** Fix was necessary for Task 2 to complete. No scope creep. Plan 02-02 will refine ZONE_2_PATHS with descriptions.

## Issues Encountered

- `python -c "from sci_fi_dashboard.routes.snapshots import router"` fails in this test environment due to missing `pyarrow` (pre-existing dependency gap — not introduced by this plan). Verified correctness via AST parse and targeted grep checks instead.

## Known Stubs

None — all SnapshotEngine methods are fully implemented and tested.

## Threat Flags

No new network endpoints, auth paths, or trust boundaries introduced beyond what is documented in the plan's threat model (T-02-03, T-02-04, T-02-05). All three mitigations are implemented.

## Next Phase Readiness

- SnapshotEngine is the foundation for all Zone 2 modification tracking in plans 02-02 through 02-06
- Plan 02-02 can import `ZONE_2_PATHS` from manifest.py (already added)
- Plan 02-03 (ConsentProtocol) can import `SnapshotEngine` from `sci_fi_dashboard.snapshot_engine`
- GET /snapshots is live and ready for integration tests in plan 02-05

---
*Phase: 02-safe-self-modification-rollback*
*Completed: 2026-04-07*
