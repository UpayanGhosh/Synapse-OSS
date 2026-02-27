---
phase: 03-platform-aware-browser-backend
plan: 01
subsystem: infra
tags: [pip, requirements, playwright, crawl4ai, pep508, windows, platform-markers, bat]

# Dependency graph
requires:
  - phase: 02-optional-ollama
    provides: warn-only optional dependency pattern ([--] / [OK] convention)
provides:
  - PEP 508 platform-gated browser dependencies in requirements.txt
  - playwright Chromium binary install in synapse_onboard.bat
  - Windows-safe pip install (crawl4ai skipped on win32)
affects: [synapse_onboard.bat, requirements.txt, pip install, browse tool]

# Tech tracking
tech-stack:
  added: [playwright>=1.20.0 (Windows only)]
  patterns:
    - PEP 508 sys_platform markers for OS-conditional pip dependencies
    - warn-only ([--]) browser binary install consistent with Ollama optional pattern

key-files:
  created: []
  modified:
    - requirements.txt
    - synapse_onboard.bat

key-decisions:
  - "crawl4ai gated to sys_platform != 'win32' -- crawl4ai has confirmed build failures on Windows (multiple upstream GitHub issues)"
  - "playwright added as Windows replacement with sys_platform == 'win32' -- shares same Chromium engine as crawl4ai internally"
  - "playwright binary install placed unconditionally outside venv if/else block -- ensures re-runs and existing venv users both get Chromium"
  - "playwright install failure is warn-only ([--] not exit /b 1) -- consistent with Ollama pattern; browse tool non-critical, app still runs"

patterns-established:
  - "PEP 508 sys_platform markers for cross-platform conditional pip deps (win32 / darwin / linux)"
  - "Unconditional post-venv step pattern in bat: place idempotent installs after the if/else venv block"

requirements-completed: [BRW-01, BRW-02, BRW-03]

# Metrics
duration: 4min
completed: 2026-02-27
---

# Phase 03 Plan 01: Platform-Aware Browser Backend Summary

**PEP 508 platform markers split crawl4ai (Mac/Linux) and playwright (Windows) in requirements.txt, plus unconditional playwright Chromium binary install added to synapse_onboard.bat**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-27T17:34:56Z
- **Completed:** 2026-02-27T17:38:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- requirements.txt now installs crawl4ai on Mac/Linux and playwright on Windows — pip install succeeds on Windows 11 without build errors
- playwright Chromium binary install added to synapse_onboard.bat unconditionally (outside venv if/else), so it runs on both fresh installs and re-runs
- playwright install failure prints `[--]` warning with manual fallback instruction, never aborts onboarding — consistent with Ollama optional pattern from Phase 2

## Task Commits

Each task was committed atomically:

1. **Task 1: Add PEP 508 platform markers to requirements.txt** - `395a0ad` (feat)
2. **Task 2: Add playwright binary install to synapse_onboard.bat** - `1427380` (feat)

**Plan metadata:** (docs commit to follow)

## Files Created/Modified

- `requirements.txt` - crawl4ai now has `; sys_platform != 'win32'` marker; playwright line added with `; sys_platform == 'win32'` marker; section comment updated
- `synapse_onboard.bat` - 10-line playwright Chromium install block inserted at line 144-152, after venv if/else close, before Step 3 Docker section

## Decisions Made

- crawl4ai gated to `sys_platform != 'win32'`: confirmed build failures on Windows across multiple upstream GitHub issues; the fix had to be at the pip layer (not a runtime workaround)
- playwright added as Windows replacement: same underlying Chromium engine as crawl4ai, idiomatic Windows automation library
- playwright binary install placed unconditionally after the venv if/else block: ensures users who already ran onboard (and thus hit the `else` branch) still get the Chromium binaries; `python -m playwright install chromium` is idempotent
- warn-only failure handling (`[--]` not `exit /b 1`): browse tool is non-critical; matches the Ollama optional pattern established in Phase 2

## Deviations from Plan

None - plan executed exactly as written.

## Before / After: requirements.txt Web Browsing Section

**Before (line 37):**
```
# --- Web Browsing & Scraping ---
crawl4ai>=0.2.0                  # Headless browser automation (ToolRegistry /browse)
```

**After (lines 36-39):**
```
# --- Web Browsing & Scraping ---
# crawl4ai on Mac/Linux; playwright on Windows (crawl4ai has build failures on Windows)
crawl4ai>=0.2.0 ; sys_platform != 'win32'   # Headless browser automation -- Mac/Linux only (Windows: fails to install)
playwright>=1.20.0 ; sys_platform == 'win32' # Windows browser automation -- replaces crawl4ai on Windows
```

## Verification Outputs

```
$ grep "crawl4ai" requirements.txt
# crawl4ai on Mac/Linux; playwright on Windows (crawl4ai has build failures on Windows)
crawl4ai>=0.2.0 ; sys_platform != 'win32'   # Headless browser automation -- Mac/Linux only (Windows: fails to install)
playwright>=1.20.0 ; sys_platform == 'win32' # Windows browser automation -- replaces crawl4ai on Windows

$ grep "playwright" requirements.txt
# crawl4ai on Mac/Linux; playwright on Windows (crawl4ai has build failures on Windows)
playwright>=1.20.0 ; sys_platform == 'win32' # Windows browser automation -- replaces crawl4ai on Windows

# No bare crawl4ai line (grep returns empty = PASS):
$ grep -v "sys_platform" requirements.txt | grep "crawl4ai" | grep -v "^#"
(empty)

$ grep -n "playwright install chromium" synapse_onboard.bat
146:call "%PROJECT_ROOT%\.venv\Scripts\python.exe" -m playwright install chromium
149:    echo      Try manually: python -m playwright install chromium
```

Line 146 > 142 (end of venv if/else block) and < 154 (REM Step 3: Set up Docker). Placement confirmed correct.

## Issues Encountered

None.

## Next Phase Readiness

- Platform-conditional dependencies are in place; any future phase adding Windows-specific packages can follow the same `; sys_platform == 'win32'` pattern
- The browse tool (`/browse`) now has its binary dependency installed on Windows — Phase 4 backend work can assume Chromium is available on all platforms

---
*Phase: 03-platform-aware-browser-backend*
*Completed: 2026-02-27*
