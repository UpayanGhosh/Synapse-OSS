---
phase: 01-foundation-config
plan: 04
subsystem: database
tags: [sqlite, migration, wal, sha256, checksum, data-safety, conf-06, conf-07]

# Dependency graph
requires:
  - phase: 01-01
    provides: "SynapseConfig.load() with data_root / db_dir / sbs_dir paths"
provides:
  - "migrate() function: port guard + WAL checkpoint + copy-to-staging + SHA-256 checksum + row-count verify + manifest write"
  - "DATABASES constant: ['memory.db', 'knowledge_graph.db', 'emotional_trajectory.db']"
  - "CLI entry point: python workspace/scripts/migrate_openclaw.py [--source] [--dest] [--dry-run]"
  - "8 integration tests covering all migration safety properties"
affects: [phase-2-litellm, phase-4-baileys, any-feature-using-db]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Staging-directory migration: copy to tmp → verify → then copy to dest (never shutil.move)"
    - "WAL checkpoint before copy: PRAGMA wal_checkpoint(TRUNCATE) ensures clean copy"
    - "Triplet copy: always copy .db + .db-wal + .db-shm as a unit"
    - "SHA-256 streaming checksum verification on every copied file"
    - "Row-count parity check for every table in every migrated database"
    - "Port guard: fail-fast if gateway still running (port 8000)"

key-files:
  created:
    - workspace/scripts/migrate_openclaw.py
    - workspace/tests/test_migration.py
  modified: []

key-decisions:
  - "All Steps 3-9 execute inside TemporaryDirectory with-block — staging is always valid when files are read/written"
  - "manifest write (Step 10) is outside the with-block — recorded only after dest files are confirmed written"
  - "Source data is never deleted at any point — migrate() is purely additive"
  - "dry_run returns manifest early inside the with-block (staging still valid) without writing to dest"

patterns-established:
  - "Migration safety: WAL checkpoint → stage copy → checksum verify → row-count verify → final copy → manifest"
  - "Port guard pattern: check port 8000 as first step of any operation that requires exclusive DB access"

requirements-completed: [CONF-06, CONF-07]

# Metrics
duration: 8min
completed: 2026-03-02
---

# Phase 1 Plan 04: Migrate OpenClaw Data Summary

**Safe SQLite WAL migration with port guard, SHA-256 checksum, row-count parity, staging directory, and manifest — all three databases plus SBS profiles**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-02T10:10:00Z
- **Completed:** 2026-03-02T10:18:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `workspace/scripts/migrate_openclaw.py` (185 lines) implementing the full safe migration pipeline
- Created `workspace/tests/test_migration.py` (97 lines) with 8 integration tests — all passing
- Implemented 9-step sequence: port guard → collect files → manifest init → WAL checkpoint → stage copy → SHA-256 verify → row count verify → SBS profiles copy → final destination write

## Task Commits

Each task was committed atomically:

1. **Task 1: Create workspace/scripts/migrate_openclaw.py** and **Task 2: Write tests/test_migration.py** - `745ca3c` (feat: add migrate_openclaw.py migration script and tests)

**Plan metadata:** (this commit)

## Files Created/Modified

- `workspace/scripts/migrate_openclaw.py` — Safe WAL migration script: port guard, WAL checkpoint, SHA-256 checksum, row count verification, SBS profiles copy, manifest write, CLI entry point, dry-run mode
- `workspace/tests/test_migration.py` — 8 integration tests for CONF-06 and CONF-07 using real SQLite databases in pytest tmp_path

## Test Results

All 8 tests passed:

```
tests/test_migration.py::test_migrate_copies_all_databases PASSED
tests/test_migration.py::test_migrate_row_counts_match PASSED
tests/test_migration.py::test_migrate_sbs_profiles_copied PASSED
tests/test_migration.py::test_migrate_writes_manifest PASSED
tests/test_migration.py::test_migrate_source_untouched PASSED
tests/test_migration.py::test_migrate_dry_run_no_dest_written PASSED
tests/test_migration.py::test_migrate_port_8000_guard PASSED
tests/test_migration.py::test_migrate_missing_source_raises PASSED

8 passed in 3.94s
```

## Decisions Made

- All Steps 3-9 execute inside `TemporaryDirectory` with-block so staging is always valid when files are read/written
- Manifest write (Step 10) is outside the with-block — only written after dest files are confirmed in place
- Source data is never deleted at any point — `migrate()` is purely additive (copy, not move)
- `dry_run` returns manifest early inside the with-block before writing to destination
- `files_to_copy` list is built inside the with-block (after `staging_db.mkdir()`) so staging paths are valid

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Migration script is complete and fully tested — users can run `python workspace/scripts/migrate_openclaw.py` to move their data from `~/.openclaw/` to `~/.synapse/`
- Plans 01-05 and 01-06 can proceed without any dependency on this script

---
*Phase: 01-foundation-config*
*Completed: 2026-03-02*
