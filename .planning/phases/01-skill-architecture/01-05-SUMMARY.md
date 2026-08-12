---
phase: 01-skill-architecture
plan: "05"
subsystem: skills
tags: [skill-creator, self-bootstrapping, bundled-skills, tdd, exception-isolation]

# Dependency graph
requires:
  - phase: 01-skill-architecture
    plan: "01"
    provides: "SkillManifest, SkillLoader, OPTIONAL_SUBDIRS, REQUIRED_FIELDS"
  - phase: 01-skill-architecture
    plan: "02"
    provides: "SkillRegistry thread-safe singleton"
  - phase: 01-skill-architecture
    plan: "04"
    provides: "SkillRunner with exception isolation, SkillResult"
provides:
  - SkillCreator class — create() filesystem primitive + generate_from_conversation() LLM layer (SKILL-04)
  - Bundled skill-creator directory — valid skill at skills/bundled/skill-creator/ with SKILL.md + all OPTIONAL_SUBDIRS
  - SkillRunner._execute_skill_creator() — special handler for built-in skill routing
  - SkillRegistry.seed_bundled_skills() — copies bundled skills to user skills_dir on first run
  - Updated skills/__init__.py — 9 public exports including SkillCreator
  - api_gateway.py lifespan — calls seed_bundled_skills() before SkillRegistry init
affects: [skill-runner, skill-registry, api-gateway, skill-system-exports]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Self-bootstrapping: skill-creator is itself a skill discoverable by SkillRegistry"
    - "Special handler dispatch: SkillRunner.execute() checks manifest.name before generic LLM call"
    - "Bundled skill seeding: shutil.copytree from bundled/ to user skills_dir; no-overwrite guard (T-01-20)"
    - "JSON extraction: _parse_json_response() handles bare JSON, markdown code blocks, and embedded JSON"
    - "Name normalization: _normalize_name() strips to a-z, 0-9, hyphens — path traversal mitigation (T-01-16)"

key-files:
  created:
    - workspace/sci_fi_dashboard/skills/creator.py
    - workspace/sci_fi_dashboard/skills/bundled/skill-creator/SKILL.md
    - workspace/sci_fi_dashboard/skills/bundled/skill-creator/scripts/.gitkeep
    - workspace/sci_fi_dashboard/skills/bundled/skill-creator/references/.gitkeep
    - workspace/sci_fi_dashboard/skills/bundled/skill-creator/assets/.gitkeep
    - workspace/tests/test_skill_creator.py
  modified:
    - workspace/sci_fi_dashboard/skills/runner.py
    - workspace/sci_fi_dashboard/skills/registry.py
    - workspace/sci_fi_dashboard/skills/__init__.py
    - workspace/sci_fi_dashboard/api_gateway.py

key-decisions:
  - "SkillCreator.create() is a @staticmethod — consistent with SkillLoader convention"
  - "_normalize_name() uses regex to strip non-alpha chars before converting spaces to hyphens — covers edge cases like unicode, punctuation"
  - "_parse_json_response() handles three JSON extraction patterns — bare JSON, ```json blocks, and embedded JSON objects — for LLM response variability"
  - "generate_from_conversation() returns a dict (not raises) for all failure modes — consistent with SkillRunner exception isolation philosophy"
  - "_execute_skill_creator is a @staticmethod on SkillRunner, not a standalone function — keeps special handler collocated with the runner code"
  - "seed_bundled_skills() uses shutil.copytree for atomic directory copy; never overwrites to preserve user customisation (T-01-20)"

requirements-completed:
  - SKILL-04

# Metrics
duration: 25min
completed: 2026-04-07
---

# Phase 01 Plan 05: Skill Architecture — Skill Creator Summary

**SkillCreator self-bootstrapping capability + bundled skill-creator + seeding — 23 tests passing**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-04-07
- **Tasks:** 2 (Task 1: TDD RED + GREEN for SkillCreator; Task 2: bundled skill + wiring)
- **Files modified:** 4 modified, 6 created

## Accomplishments

- `SkillCreator` class in `skills/creator.py` (SKILL-04):
  - `create(name, description, skills_dir, ...)` — builds skill directory with SKILL.md + all `OPTIONAL_SUBDIRS` (scripts/, references/, assets/); validates with `SkillLoader.load_skill()` immediately after creation
  - `_normalize_name()` — strips to lowercase-hyphenated, only a-z/0-9/hyphens survive; path traversal impossible (T-01-16)
  - `generate_from_conversation(user_message, skills_dir, llm_router)` — async; calls LLM with `EXTRACTION_PROMPT` (analysis role, temperature=0.3), parses JSON response, calls `create()`; returns success/failure dict, never raises (T-01-17)
  - `_parse_json_response()` — handles bare JSON, markdown ```json code blocks, and embedded JSON objects
- Bundled `skill-creator` at `skills/bundled/skill-creator/`:
  - `SKILL.md` with 5 trigger phrases ("create a skill", "make a skill", etc.), `filesystem:write` permission, analysis model_hint
  - `scripts/`, `references/`, `assets/` subdirectories per SKILL-01
  - Validates cleanly via `SkillLoader.load_skill()`
- `SkillRunner._execute_skill_creator()` static method:
  - Dispatched from `execute()` when `manifest.name == "skill-creator"` (before generic LLM call)
  - Calls `SkillCreator.generate_from_conversation()`, wraps in try/except — NEVER raises
  - Returns descriptive success text including skill path and hot-reload note
- `SkillRegistry.seed_bundled_skills(skills_dir)`:
  - Uses `shutil.copytree` to copy from `bundled/` package directory to user skills_dir
  - Skips directories that already exist — preserves user customisation (T-01-20)
  - Returns count of skills seeded (0 = no-op on subsequent runs)
- `api_gateway.py` lifespan updated: calls `SkillRegistry.seed_bundled_skills()` before `SkillRegistry()` init so seeded skills are discovered on first scan
- `skills/__init__.py`: 9 public exports (added `SkillCreator`)
- 23 tests: 8 create(), 4 generate_from_conversation(), 5 bundled skill, 3 runner handler, 3 seed_bundled_skills

## Task Commits

1. **TDD RED — failing tests for SkillCreator** - `164e9c7` (test)
2. **TDD GREEN — implement SkillCreator** - `ec3eb2d` (feat)
3. **Bundled skill-creator + SkillRunner handler + seeding** - `6d90e0c` (feat)

## Files Created/Modified

- `workspace/sci_fi_dashboard/skills/creator.py` — SkillCreator class (325 lines)
- `workspace/sci_fi_dashboard/skills/bundled/skill-creator/SKILL.md` — bundled skill manifest
- `workspace/sci_fi_dashboard/skills/bundled/skill-creator/scripts/.gitkeep`
- `workspace/sci_fi_dashboard/skills/bundled/skill-creator/references/.gitkeep`
- `workspace/sci_fi_dashboard/skills/bundled/skill-creator/assets/.gitkeep`
- `workspace/tests/test_skill_creator.py` — 23 tests (TDD)
- `workspace/sci_fi_dashboard/skills/runner.py` — added _execute_skill_creator() + dispatch
- `workspace/sci_fi_dashboard/skills/registry.py` — added seed_bundled_skills() static method
- `workspace/sci_fi_dashboard/skills/__init__.py` — added SkillCreator export
- `workspace/sci_fi_dashboard/api_gateway.py` — added seed_bundled_skills() call in lifespan

## Decisions Made

- `SkillCreator.create()` is a `@staticmethod` — consistent with `SkillLoader` convention from Plan 01; no instance state required for the creation operation
- `_normalize_name()` applies regex stripping BEFORE hyphenation so "My Cool Skill!" becomes "my-cool-skill" not "my-cool-skill-" (trailing punctuation handled)
- `generate_from_conversation()` always returns a dict rather than raising — the caller (SkillRunner) should never see exceptions from skill execution, keeping the pipeline robust
- `_execute_skill_creator()` is placed on `SkillRunner` rather than as a standalone module function — colocation makes the dispatch logic and handler legible in one file
- `seed_bundled_skills()` is a `@staticmethod` on `SkillRegistry` — placement makes sense as "bundled skill management" is a registry concern; the lifespan caller only needs one import

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] SkillRunner.execute() uses @staticmethod but dispatch used `cls`**

- **Found during:** Task 2 test execution
- **Issue:** `execute()` is a `@staticmethod` so `cls` is not defined. The dispatch line `return await cls._execute_skill_creator(...)` caused `NameError: name 'cls' is not defined`.
- **Fix:** Changed to `return await SkillRunner._execute_skill_creator(...)` — direct class reference.
- **Files modified:** workspace/sci_fi_dashboard/skills/runner.py
- **Commit:** included in 6d90e0c

## Known Stubs

None — all functionality is fully implemented.

## Threat Flags

None — no new network endpoints introduced. All threat model mitigations from the plan are implemented:

- T-01-16: `_normalize_name()` strips to a-z/0-9/hyphens; path traversal mitigated
- T-01-17: LLM output JSON-parsed with error handling; invalid JSON returns failure dict
- T-01-18: Existence check in `create()` prevents overwrite DoS
- T-01-20: `seed_bundled_skills()` never overwrites existing skill directories

---
*Phase: 01-skill-architecture*
*Completed: 2026-04-07*

## Self-Check: PASSED

- FOUND: workspace/sci_fi_dashboard/skills/creator.py
- FOUND: workspace/sci_fi_dashboard/skills/bundled/skill-creator/SKILL.md
- FOUND: workspace/sci_fi_dashboard/skills/bundled/skill-creator/scripts/.gitkeep
- FOUND: workspace/sci_fi_dashboard/skills/bundled/skill-creator/references/.gitkeep
- FOUND: workspace/sci_fi_dashboard/skills/bundled/skill-creator/assets/.gitkeep
- FOUND: workspace/tests/test_skill_creator.py
- FOUND: workspace/sci_fi_dashboard/skills/runner.py (modified)
- FOUND: workspace/sci_fi_dashboard/skills/registry.py (modified)
- FOUND: workspace/sci_fi_dashboard/skills/__init__.py (modified)
- FOUND: workspace/sci_fi_dashboard/api_gateway.py (modified)
- FOUND: commit 164e9c7 (TDD RED — failing tests)
- FOUND: commit ec3eb2d (TDD GREEN — SkillCreator implementation)
- FOUND: commit 6d90e0c (bundled skill + runner handler + seeding)
- Tests: 23 passed in 0.11s
