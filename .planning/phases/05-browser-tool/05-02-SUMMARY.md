---
phase: 05-browser-tool
plan: 02
subsystem: browser-skill
tags: [duckduckgo, web-search, rate-limiting, asyncio, browser-skill]

# Dependency graph
requires:
  - phase: 05-browser-tool-plan-01
    provides: "~/.synapse/skills/browser/scripts/ directory and fetch_and_summarize.py with FetchResult interface"
provides:
  - "~/.synapse/skills/browser/scripts/web_search.py: DuckDuckGo web search with rate limiting, SearchResult/SearchResponse dataclasses, source URL provenance"
  - "duckduckgo-search>=7.0.0 in requirements-optional.txt"
affects:
  - "05-03-PLAN.md — browser orchestrator uses search() to discover URLs before fetch_and_summarize()"

# Tech tracking
tech-stack:
  added:
    - "duckduckgo-search>=7.0.0 (zero-cost search, no API key)"
  patterns:
    - "asyncio.to_thread() for sync library wrappers (DDGS is sync-only)"
    - "Module-level _last_request_time singleton for per-process rate limiting"
    - "Lazy import pattern: DDGS imported inside sync function to fail gracefully if not installed"
    - "Exponential backoff: BACKOFF_BASE * 2^attempt, capped at BACKOFF_MAX"

key-files:
  created:
    - "~/.synapse/skills/browser/scripts/web_search.py"
  modified:
    - "requirements-optional.txt"

key-decisions:
  - "DDGS is imported inside _search_ddgs_sync() not at module top level — allows graceful ImportError in search() if library not installed"
  - "Module-level _last_request_time provides simple per-process rate limiting without external state"
  - "SearchResponse.source_urls collects all result URLs for BROWSE-05 provenance requirement"
  - "format_search_results() produces plain text with numbered results suitable for LLM context injection"
  - "duckduckgo-search dependency was already committed in Plan 05-01 commit (8df5a70) — no duplicate commit needed"

patterns-established:
  - "Rate limiting pattern: _rate_limit_wait() as sync function called from thread, global monotonic timer"
  - "Search provider pattern: sync DDGS wrapped in asyncio.to_thread(), retry loop with RatelimitException backoff"

requirements-completed: [BROWSE-01, BROWSE-05]

# Metrics
duration: 10min
completed: 2026-04-07
---

# Phase 05 Plan 02: Browser Tool Web Search Summary

**DuckDuckGo search skill (web_search.py) with 1 req/s rate limiting, exponential backoff on RatelimitException, and SearchResult/SearchResponse dataclasses with source URL provenance**

## Performance

- **Duration:** 10 min
- **Started:** 2026-04-07T13:30:00Z
- **Completed:** 2026-04-07T13:40:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `~/.synapse/skills/browser/scripts/web_search.py` (174 lines) with full DuckDuckGo integration
- SearchResult and SearchResponse dataclasses with source_urls for BROWSE-05 provenance tracking
- Rate limiting implemented: 1 req/s minimum interval via module-level monotonic timer + exponential backoff (2s, 4s, 8s, max 32s) on RatelimitException with 3 max retries
- All DDGS calls non-blocking via asyncio.to_thread() wrapping
- Graceful ImportError fallback when duckduckgo-search not installed
- `duckduckgo-search>=7.0.0` present in requirements-optional.txt (added by Plan 05-01 executor in same batch commit)

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement web_search.py with DDGS and rate limiting** - Runtime file at `~/.synapse/skills/browser/scripts/web_search.py` (outside git repo, not committed to VCS)
2. **Task 2: Add duckduckgo-search to requirements-optional.txt** - Already committed in `8df5a70` (feat(05-01)) — Plan 05-01 executor added both trafilatura and duckduckgo-search in one batch

**Plan metadata:** Committed in SUMMARY.md docs commit

_Note: web_search.py lives at `~/.synapse/` (runtime user data dir, outside git repo). The in-repo artifact is requirements-optional.txt._

## Files Created/Modified

- `~/.synapse/skills/browser/scripts/web_search.py` — DuckDuckGo search wrapper with SearchResult/SearchResponse dataclasses, rate limiting, exponential backoff, asyncio.to_thread wrapping
- `requirements-optional.txt` — `duckduckgo-search>=7.0.0` already present from Plan 05-01 commit `8df5a70`

## Decisions Made

- DDGS imported lazily inside `_search_ddgs_sync()` to allow graceful ImportError fallback in the async `search()` function
- Module-level `_last_request_time` float provides simple per-process rate limiting without Redis or external state
- `SearchResponse.source_urls` aggregates all result URLs to satisfy BROWSE-05 (source attribution) without requiring callers to iterate results manually
- `format_search_results()` returns plain text with numbered results — suitable for direct LLM context injection without HTML

## Deviations from Plan

None — plan executed exactly as written. The `duckduckgo-search>=7.0.0` requirement was already committed by the Plan 05-01 executor (8df5a70), so no duplicate requirements commit was needed.

## Issues Encountered

None — `requirements-optional.txt` change for duckduckgo-search was already present in HEAD (committed alongside trafilatura in Plan 05-01 execution). This is not a conflict; Plan 05-02's Task 2 is satisfied by the existing commit.

## User Setup Required

None — no external service configuration required. Install with:
```
pip install duckduckgo-search>=7.0.0
```

## Next Phase Readiness

- `web_search.py` is ready for use by the browser orchestrator (Plan 05-03)
- The `search()` function returns `SearchResponse.source_urls` which feed directly into `fetch_and_summarize()` calls
- Plan 05-03 wires the search -> fetch -> summarize chain and hemisphere privacy guard

---
*Phase: 05-browser-tool*
*Completed: 2026-04-07*

## Self-Check: PASSED

- FOUND: `~/.synapse/skills/browser/scripts/web_search.py`
- FOUND: `05-02-SUMMARY.md`
- FOUND: `duckduckgo-search>=7.0.0` in `requirements-optional.txt`
- FOUND: `source_urls` field in SearchResult and SearchResponse
- FOUND: `asyncio.to_thread()` wrapping DDGS calls
- FOUND: `_rate_limit_wait()` rate limiting function
- FOUND: `RatelimitException` backoff handling
