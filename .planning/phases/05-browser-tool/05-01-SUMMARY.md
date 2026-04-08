---
phase: 05-browser-tool
plan: 01
subsystem: browser
tags: [browser, trafilatura, ssrf, web-fetch, skills]

# Dependency graph
requires:
  - phase: 01-skill-architecture
    provides: "SkillManifest schema and skill directory convention (SKILL.md + scripts/)"
provides:
  - "Browser skill directory at ~/.synapse/skills/browser/ with SKILL.md and fetch_and_summarize.py"
  - "SSRF-guarded URL fetch using safe_httpx_client from media/ssrf.py"
  - "Trafilatura-based HTML extraction wrapped in asyncio.to_thread (non-blocking)"
  - "FetchResult dataclass with source_urls for content provenance tracking"
  - "format_for_context() produces plain text for LLM injection — never raw HTML"
affects:
  - "05-browser-tool/05-02 (URL extraction)"
  - "05-browser-tool/05-03 (skill wiring into pipeline)"

# Tech tracking
tech-stack:
  added:
    - "trafilatura>=2.0.0 (HTML content extraction)"
  patterns:
    - "Skill directory: SKILL.md (YAML frontmatter + instructions body) + scripts/ subdirectory"
    - "SSRF guard reuse: import from sci_fi_dashboard.media.ssrf, never re-implement"
    - "Sync CPU-bound work wrapped in asyncio.to_thread() to avoid blocking the event loop"
    - "Fail-safe extraction: trafilatura primary, regex strip fallback if unavailable"

key-files:
  created:
    - "~/.synapse/skills/browser/SKILL.md"
    - "~/.synapse/skills/browser/scripts/__init__.py"
    - "~/.synapse/skills/browser/scripts/fetch_and_summarize.py"
  modified:
    - "requirements-optional.txt"

key-decisions:
  - "SSRF guard imported lazily at call time from sci_fi_dashboard.media.ssrf — no re-implementation"
  - "trafilatura.fetch_url() never called — all HTTP goes through safe_httpx_client()"
  - "MAX_CONTENT_CHARS=8000 caps extracted text to prevent context window overflow"
  - "Regex fallback provided for trafilatura ImportError — graceful degradation"
  - "FetchResult.success=False used for partial results (JS-heavy pages) to allow caller to handle"
  - "trafilatura added to requirements-optional.txt (not requirements.txt) — optional dependency"

patterns-established:
  - "Browser skill follows SKILL.md format: YAML frontmatter (name/description/version/triggers/model_hint) + instructions body"
  - "All skill HTTP calls must go through safe_httpx_client from media/ssrf.py"
  - "format_for_context() is the canonical adapter between FetchResult and LLM prompt injection"

requirements-completed:
  - BROWSE-01
  - BROWSE-02
  - BROWSE-04

# Metrics
duration: 15min
completed: 2026-04-07
---

# Phase 05 Plan 01: Browser Skill Foundation Summary

**SSRF-guarded browser skill with trafilatura HTML extraction wrapped in asyncio.to_thread, reusing the project's existing media/ssrf.py guard — never raw HTML to the LLM**

## Performance

- **Duration:** 15 min
- **Started:** 2026-04-07T13:34:47Z
- **Completed:** 2026-04-07T13:50:00Z
- **Tasks:** 2
- **Files modified:** 4 (3 created at ~/.synapse/, 1 modified in repo)

## Accomplishments

- Browser skill directory created at `~/.synapse/skills/browser/` with valid SKILL.md (name, description, version, triggers, model_hint, permissions) parseable by SkillLoader
- `fetch_and_summarize.py` implemented: URL validation → SSRF check → safe_httpx_client fetch → asyncio.to_thread extraction → FetchResult — never raw HTML
- `format_for_context()` produces plain text with source citation for LLM prompt injection
- `trafilatura>=2.0.0` added to the Web Browsing section of `requirements-optional.txt`

## Task Commits

Each task was committed atomically:

1. **Task 1: Create browser skill SKILL.md and fetch_and_summarize.py** - `8df5a70` (feat)
2. **Task 2: Add trafilatura to requirements-optional.txt** - `8df5a70` (feat — combined with Task 1)

**Plan metadata:** see final docs commit

## Files Created/Modified

- `~/.synapse/skills/browser/SKILL.md` - Skill metadata with YAML frontmatter (name, description, version, triggers, model_hint, permissions) and LLM instruction body
- `~/.synapse/skills/browser/scripts/__init__.py` - Package marker for browser skill scripts
- `~/.synapse/skills/browser/scripts/fetch_and_summarize.py` - Core fetch+extraction logic: FetchResult dataclass, _extract_with_trafilatura (sync, to_thread wrapped), fetch_and_summarize (async, SSRF-guarded), format_for_context (plain text adapter)
- `requirements-optional.txt` - Added trafilatura>=2.0.0 to Web Browsing section

## Decisions Made

- **SSRF guard reused directly:** Imported lazily from `sci_fi_dashboard.media.ssrf` — zero re-implementation. Returns error FetchResult if import fails (edge case for isolated testing).
- **trafilatura.fetch_url() explicitly excluded:** All HTTP routing goes through `safe_httpx_client()` to maintain SSRF protection on redirects.
- **MAX_CONTENT_CHARS=8000:** Caps extracted text to prevent a single page from consuming the LLM context window. Tunable constant at module level.
- **Regex fallback:** If trafilatura is not installed, script strips HTML tags with regex rather than returning raw HTML. Keeps the "never raw HTML" invariant even without the optional dep.
- **FetchResult.success=False for partial results:** JS-heavy pages return success=False with a descriptive message rather than empty text — allows callers to handle and communicate the limitation to users.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `~/.synapse/skills/` directory did not exist yet (first browser plan to run). Created the full path `~/.synapse/skills/browser/scripts/` with `mkdir -p`. Not a deviation — directory creation is implied by the task.
- `workspace/sci_fi_dashboard/skills/schema.py` and `skills/loader.py` did not exist (Phase 01 skill architecture builds these). The SKILL.md format was cross-referenced from the plan's `<interfaces>` block instead, which provided the SkillManifest schema directly.

## User Setup Required

None - no external service configuration required. `trafilatura` is optional; the script degrades gracefully if it's not installed.

## Next Phase Readiness

- Browser skill foundation is complete. Plan 05-02 (URL extraction from user messages) can proceed immediately.
- Plan 05-03 (wiring fetch_and_summarize into the skill pipeline) requires Phase 01 SkillRunner to be available.
- The `format_for_context()` function is the injection point for Plan 05-03 — it produces the text block to prepend to the LLM system/user prompt.

## Self-Check: PASSED

- FOUND: ~/.synapse/skills/browser/SKILL.md
- FOUND: ~/.synapse/skills/browser/scripts/__init__.py
- FOUND: ~/.synapse/skills/browser/scripts/fetch_and_summarize.py
- FOUND: requirements-optional.txt (trafilatura line confirmed)
- FOUND: .planning/phases/05-browser-tool/05-01-SUMMARY.md
- FOUND: commit 8df5a70 (feat: browser skill + trafilatura dependency)
- FOUND: commit d0957ac (docs: plan metadata)

---
*Phase: 05-browser-tool*
*Completed: 2026-04-07*
