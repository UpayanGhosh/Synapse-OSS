---
phase: 01-skill-architecture
plan: "03"
subsystem: skills
tags: [skill-router, embeddings, cosine-similarity, tdd, intent-matching]

# Dependency graph
requires:
  - SkillManifest frozen dataclass (from 01-01)
  - EmbeddingProvider infrastructure (sci_fi_dashboard/embedding/)
provides:
  - SkillRouter class with update_skills() and match()
  - _cosine_similarity() pure Python helper (no numpy)
  - Graceful no-provider fallback (trigger-only routing)
affects: [api-gateway, skill-dispatch, skill-registry]

# Tech tracking
tech-stack:
  added: []
  patterns: [TDD red-green, lazy import for testability, two-stage matching, O(1) embed per message]

key-files:
  created:
    - workspace/sci_fi_dashboard/skills/router.py
    - workspace/tests/test_skill_router.py
  modified: []

key-decisions:
  - "get_provider() lazy-imported inside a module-level wrapper function — enables patch('sci_fi_dashboard.skills.router.get_provider') in tests without import-order coupling"
  - "Two-stage matching: trigger substring always wins, embedding similarity is stage 2 — explicit user intent always takes priority"
  - "No numpy dependency for cosine similarity — pure Python math.sqrt, keeps environment requirements minimal"
  - "update_skills() wraps embed_documents in try/except — provider failure degrades to trigger-only, never raises"
  - "embed_query called once per message regardless of skill count — O(1) API cost (T-01-09 mitigation)"
  - "First-match-wins for trigger phrases in skill list order — prevents cross-skill trigger hijacking (T-01-08)"

# Metrics
duration: 20min
completed: 2026-04-07
---

# Phase 01 Plan 03: SkillRouter — Embedding-Based Intent Matching Summary

**SkillRouter with two-stage matching (trigger bypass + cosine similarity), pure Python cosine impl, graceful no-provider fallback — 10 tests passing**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-04-07
- **Completed:** 2026-04-07
- **Tasks:** 1 (TDD RED + GREEN in same plan execution)
- **Files created:** 2

## Accomplishments

- `SkillRouter` class with `DEFAULT_THRESHOLD = 0.45`, configurable at construction time
- `update_skills(manifests)` — embeds all descriptions via `EmbeddingProvider.embed_documents()` at load time; falls back to trigger-only routing if provider unavailable or fails
- `match(user_message)` — two-stage: trigger substring check first (always wins), then cosine similarity vs threshold
- `_try_trigger_match()` — case-insensitive, iterates skills in list order, first-match-wins
- `_try_embedding_match()` — single `embed_query` call per message, O(1) API cost regardless of skill count
- `_cosine_similarity()` — pure Python, no numpy, handles zero-vector edge case
- `get_provider()` wrapper function using lazy import — enables mock patching in tests
- 10 unit tests: embedding match, below-threshold None, trigger case-insensitive, trigger priority over embeddings, update_skills re-embed, no-provider fallback, configurable threshold, empty list, default threshold value, multi-trigger

## Task Commits

1. **TDD RED — failing tests for SkillRouter** - `75e29cc` (test)
2. **TDD GREEN — implement SkillRouter** - `f733871` (feat)

## Files Created/Modified

- `workspace/sci_fi_dashboard/skills/router.py` — SkillRouter class, _cosine_similarity helper, get_provider lazy wrapper
- `workspace/tests/test_skill_router.py` — 10 unit tests covering all plan behaviors

## Decisions Made

- `get_provider()` is a wrapper function (not direct import) so tests can `patch('sci_fi_dashboard.skills.router.get_provider')` — simpler than patching the factory module
- Pure Python cosine similarity avoids numpy dependency — the skill system should be importable without ML libraries installed
- `update_skills()` silently falls back to trigger-only on provider failure — consistent with retriever.py's error handling pattern; partial operation is better than raising at startup
- `match()` does NOT update `__init__.py` — per plan note, export wiring is consolidated in Plan 04 Task 2 to avoid parallel write conflicts

## Deviations from Plan

None — plan executed exactly as written. The lazy import pattern for `get_provider` was required by the test mock patching approach specified in the plan's action section; this was an implementation detail within the specified design.

## Known Stubs

None — `SkillRouter` is fully functional. No placeholder values.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced. Operations are pure in-memory computation (cosine similarity) plus embedding API calls via existing infrastructure.

---
*Phase: 01-skill-architecture*
*Completed: 2026-04-07*

## Self-Check: PASSED

- FOUND: workspace/sci_fi_dashboard/skills/router.py
- FOUND: workspace/tests/test_skill_router.py
- FOUND: commit 75e29cc (TDD RED — failing tests)
- FOUND: commit f733871 (TDD GREEN — implementation)
- Tests: 10 passed in 0.06s
- Acceptance criteria:
  - class SkillRouter: 1 match
  - def match: 1 match
  - def update_skills: 1 match
  - _cosine_similarity: present (no numpy)
  - get_provider: present
  - def test_ count: 10 (>= 7)
  - All tests pass: YES
