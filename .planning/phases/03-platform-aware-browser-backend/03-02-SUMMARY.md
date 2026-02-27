---
phase: 03-platform-aware-browser-backend
plan: "02"
subsystem: browser-backend
tags: [windows, platform-dispatch, crawl4ai, playwright, lazy-import]
dependency_graph:
  requires: []
  provides: [platform-aware-browser-dispatch, windows-safe-tool-registry]
  affects: [workspace/db/tools.py, workspace/scrape_threads.py]
tech_stack:
  added: [playwright.async_api]
  patterns: [lazy-import, sys.platform-dispatch, early-exit-guard]
key_files:
  created: []
  modified:
    - workspace/db/tools.py
    - workspace/scrape_threads.py
decisions:
  - "Lazy imports inside function bodies used for both backends: avoids module-level ImportError on any platform"
  - "sys.platform == 'win32' is the correct check for all Windows versions (historical Python artifact — not 'win64')"
  - "scrape_threads.py uses early sys.exit(1) guard pattern (not lazy import) because it is a script, not a library"
  - "workspace/db/ is gitignored by overly broad pattern -- tools.py force-added with git add -f as it is source code, not a DB file"
metrics:
  duration: "~2 min"
  completed_date: "2026-02-27"
  tasks_completed: 2
  files_modified: 2
---

# Phase 3 Plan 2: Platform-Aware Browser Dispatch Summary

**One-liner:** Platform-aware browser dispatch in tools.py using sys.platform check and lazy imports, with Windows-safe early-exit guard in scrape_threads.py.

## What Was Built

### Task 1: Rewrite tools.py with platform-aware browser dispatch

`workspace/db/tools.py` was rewritten to remove the bare module-level `from crawl4ai import AsyncWebCrawler` that caused `ModuleNotFoundError` on Windows whenever any module imported `ToolRegistry`.

Key changes:
- Removed: `from crawl4ai import AsyncWebCrawler` at module level (line 3)
- Added: `import sys` at module level
- `search_web(url)` now dispatches based on `sys.platform == "win32"`:
  - Windows: calls `_search_web_playwright(url)` (new method)
  - Mac/Linux: calls `_search_web_crawl4ai(url)` (extracted from original implementation)
- Both private methods use **lazy imports** inside the function body
- Both backends truncate to 3000 chars (unchanged limit)
- `[Playwright]` / `[Crawl4AI]` prefixes identify which backend ran
- `get_tool_schemas()` and `search_web(url: str) -> str` public interface **unchanged**

New tools.py content:
```python
import asyncio
import json
import sys


class ToolRegistry:
    @staticmethod
    def get_tool_schemas():
        """Returns the OpenAI-compatible JSON schema for the tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_web",
                    "description": "Searches the live internet by visiting a URL and extracting the main content as clean markdown. Use this whenever you need up-to-date information, weather, or factual data not in your memory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The exact URL to visit (e.g., 'https://lite.cnn.com' or a google search URL like 'https://www.google.com/search?q=weather+kolkata')",
                            }
                        },
                        "required": ["url"],
                    },
                },
            }
        ]

    @staticmethod
    async def search_web(url: str) -> str:
        if sys.platform == "win32":
            return await ToolRegistry._search_web_playwright(url)
        else:
            return await ToolRegistry._search_web_crawl4ai(url)

    @staticmethod
    async def _search_web_crawl4ai(url: str) -> str:
        from crawl4ai import AsyncWebCrawler  # lazy import -- only on Mac/Linux
        ...

    @staticmethod
    async def _search_web_playwright(url: str) -> str:
        from playwright.async_api import async_playwright  # lazy import -- only on Windows
        ...
```

### Task 2: Guard scrape_threads.py against Windows crawl4ai import crash

`workspace/scrape_threads.py` was updated with an early-exit guard before the `from crawl4ai import AsyncWebCrawler` line. Since the file is a script (not a library), the cleanest approach is `sys.exit(1)` with an actionable message.

New scrape_threads.py content:
```python
import asyncio
import sys

if sys.platform == "win32":
    print("[scrape_threads] This script uses crawl4ai which is not available on Windows.")
    print("                 On Windows, use the /browse endpoint via Playwright instead.")
    sys.exit(1)

from crawl4ai import AsyncWebCrawler  # only reached on Mac/Linux
...
```

## Verification Output

```
=== Verification 1: Import ToolRegistry ===
OK
=== Verification 2: No bare crawl4ai in tools.py ===
PASS
=== Verification 3: Windows guard in scrape_threads.py ===
[scrape_threads] This script uses crawl4ai which is not available on Windows.
                 On Windows, use the /browse endpoint via Playwright instead.
Exit code: 1
=== Verification 4: sys.platform dispatch in tools.py ===
        Dispatches to Playwright on Windows (sys.platform == 'win32') and
        if sys.platform == "win32":
=== Verification 5: Both methods present ===
    async def _search_web_crawl4ai(url: str) -> str:
    async def _search_web_playwright(url: str) -> str:
```

Note confirming schema unchanged: `ToolRegistry.get_tool_schemas()` returns a single `search_web` function schema with `url` string parameter — identical to the pre-rewrite schema.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] workspace/db/ is gitignored by overly broad pattern**
- **Found during:** Task 1 commit
- **Issue:** `.gitignore` contains `workspace/db/` which ignores all Python source files in that directory, not just database files. `git add workspace/db/tools.py` failed with "ignored by .gitignore".
- **Fix:** Used `git add -f workspace/db/tools.py` to force-add the source file. The gitignore was written to exclude database binary files (`*.db`) but the pattern `workspace/db/` is overly broad and catches Python source files too.
- **Files modified:** None (gitignore not changed — fixing the gitignore would be a separate scoped task)
- **Commit:** d092813

## Commits

| Task | Commit | Message |
|------|--------|---------|
| Task 1: tools.py platform dispatch | d092813 | feat(03-02): platform-aware browser dispatch in tools.py |
| Task 2: scrape_threads.py Windows guard | 9b13f06 | fix(03-02): guard scrape_threads.py against Windows crawl4ai import crash |

## Self-Check: PASSED

- FOUND: workspace/db/tools.py
- FOUND: workspace/scrape_threads.py
- FOUND: .planning/phases/03-platform-aware-browser-backend/03-02-SUMMARY.md
- FOUND commit d092813: feat(03-02): platform-aware browser dispatch in tools.py
- FOUND commit 9b13f06: fix(03-02): guard scrape_threads.py against Windows crawl4ai import crash
