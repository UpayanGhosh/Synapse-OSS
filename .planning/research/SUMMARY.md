# Project Research Summary

**Project:** Synapse-OSS Windows Compatibility & Graceful Degradation
**Domain:** Python open-source application — cross-platform packaging and optional dependency management
**Researched:** 2026-02-27
**Confidence:** HIGH

## Executive Summary

Synapse-OSS is a self-hosted AI assistant with a complex dependency tree (crawl4ai, ollama, sentence-transformers, FastAPI) that currently hard-fails on Windows at import time. The root problems are well-understood and documented: emoji characters in print statements crash on Windows cp1252 encoding, a top-level `import ollama` raises `ModuleNotFoundError` before any error-handling code runs, and crawl4ai carries platform-specific native binaries that fail on Windows. All three issues are installation-time or module-import-time failures that prevent the app from starting at all — they are not logic bugs.

The recommended approach is a surgical, four-phase fix that works from the outermost layer inward: fix encoding first (unblocks all subsequent testing on Windows), then guard optional imports at module level (unblocks startup without Ollama), then introduce a platform-aware browser backend using Playwright on Windows (unblocks the browser tool), and finally add startup .env validation with a feature availability summary (polish that helps non-technical users). The entire fix touches 4-5 files and introduces 2 new small modules. No restructuring of the core request pipeline, memory system, or LLM routing is needed.

The key risk is partial fixes — fixing only one file for Unicode when 10 files have the problem, or placing a `try/except` inside a function body when the crash happens at module-level import. Research identified 7 specific pitfall patterns with concrete prevention strategies. The fix is low-risk because it is purely additive (guarded imports, new adapter files) and the high-risk zones (api_gateway routing, sbs/, memory.db schema) are explicitly out of scope.

---

## Key Findings

### Recommended Stack

The existing stack requires no new dependencies beyond what is already in requirements.txt. `sentence-transformers` (the Ollama fallback) is already listed. The only new dependency is `playwright>=1.49.0` for Windows users, added via a PEP 508 platform marker so it installs automatically and exclusively on Windows. Docker, pyproject.toml extras, and separate requirements files are explicitly ruled out — they add friction for the non-technical target audience.

**Core technologies:**
- `playwright>=1.49.0; sys_platform == "win32"`: Windows browser automation — direct Playwright replaces Crawl4AI on Windows because Crawl4AI's ML extras and native binaries fail to install cleanly
- `crawl4ai>=0.2.0; sys_platform != "win32"`: Mac/Linux browser automation — kept as-is, no change needed on those platforms
- `sentence-transformers>=2.2.0`: Ollama embedding fallback — already in requirements.txt, activated when `ollama` Python package is not installed
- PEP 508 environment markers: platform-conditional deps — single requirements.txt, no separate files, works with plain `pip install -r requirements.txt` since pip 9

### Expected Features

The goal is not new features — it is making existing features reliably available. The "features" here are reliability properties: install without errors, start without crashing, tell the user what is broken.

**Must have (table stakes):**
- No cryptic errors during `pip install -r requirements.txt` on Windows — users abandon at this step
- App starts without crashing when Ollama is not installed — Ollama is a separate install that many users skip initially
- No UnicodeEncodeError on Windows at startup — crashes on first import of any file with emoji print statements
- `.env` validation at startup — silent failures on missing API keys produce confusing behavior deeper in the call stack

**Should have (competitive differentiators vs. other self-hosted Python projects):**
- Feature availability summary at startup — one clean block showing what is ON vs OFF based on installed services and configured keys
- Actionable fix messages — "Ollama not found. Install from ollama.com, then restart." rather than a raw stack trace
- OS-aware onboarding script — detects Python/pip/git presence before attempting install

**Defer to v2+:**
- Interactive setup wizard (TUI) — breaks in non-TTY environments, high complexity
- Auto-install of missing packages at runtime — modifies user environment without consent, considered hostile UX
- Docker/docker-compose setup — heavy; incompatible with target audience (non-technical personal users)

### Architecture Approach

The fix is purely additive: guard existing imports, extract one module, add one new module, and add one new utility file. Four components are in scope. Everything else — the `api_gateway.py` routing logic, the `gateway/` pipeline, `sbs/` persona engine, and `memory.db` schema — is an explicit no-change zone. The build order within each phase is prescribed: extract before rewrite (browser abstraction), source fix before env var workaround (Unicode), module-level guard before function-level handling (Ollama import).

**Major components modified or added:**
1. `workspace/db/tools.py` — updated to dispatch to platform-specific browser backend via `platform.system()` check
2. `workspace/db/browser_playwright.py` — new file, Windows browser adapter exposing `async def search_web(url) -> str`
3. `workspace/db/browser_crawl4ai.py` — extracted from current tools.py, same interface as above
4. `workspace/sci_fi_dashboard/memory_engine.py` — module-level `try/except` import guard for ollama + sentence-transformers fallback path
5. `workspace/sci_fi_dashboard/startup_checks.py` — new file, `.env` validation + feature status printer
6. All `workspace/**/*.py` files with emoji in print statements — pure text replacement, no logic changes

### Critical Pitfalls

1. **Fixing Unicode at the wrong layer** — setting `PYTHONUTF8=1` in a shell script fixes the developer's machine but not the source. Anyone running the app without that env var (IDE, direct invocation, import from another tool) hits the crash again. Fix must be in the source files: replace emoji with `[OK]`, `[WARN]`, `[ERROR]` ASCII tags.

2. **Placing the import guard inside a function body** — the current `memory_engine.py` has `import ollama` at module level (line 64) with a `try/except` inside `get_embedding()`. The module-level import crashes before any function is called, so the inner `except` never executes. The guard must be at module level: `try: import ollama; OLLAMA_AVAILABLE = True`.

3. **Fixing Unicode in only one file** — `smart_entity.py` is the file that appears in the observed error trace, but `memory_engine.py`, `change_tracker.py`, `finish_facts.py`, and others also contain emoji. A partial fix means the crash reappears on the next import. The fix must be done with a whole-workspace grep in one pass.

4. **Embedding dimension mismatch when switching models** — Ollama's `nomic-embed-text` produces 768-dim vectors; `all-MiniLM-L6-v2` (the sentence-transformers fallback) produces 384-dim. If a database was initialized with 768-dim vectors and the app falls back to 384-dim, sqlite-vec rejects queries silently or throws. A startup check must compare the active model's output dimension against the stored schema dimension and warn explicitly if they differ.

5. **Playwright installed without browser binaries** — `pip install playwright` succeeds but `playwright install chromium` must be run separately. If the onboarding script omits this step, the browser tool fails at runtime with "Executable doesn't exist." The onboarding script for Windows must include `python -m playwright install chromium` explicitly.

6. **Pinning old crawl4ai version for Windows** — this produces divergent behavior between Windows (old API) and Mac/Linux (new API). The correct fix is the PEP 508 platform marker, not version pinning.

7. **Overly aggressive .env validation blocking startup** — using `sys.exit()` for optional keys (GROQ, OPENROUTER) means users who haven't configured voice transcription cannot start the app at all. Only `GEMINI_API_KEY` warrants a hard exit; all other keys should warn and disable the specific feature.

---

## Implications for Roadmap

Based on research, the phase structure is prescribed by the dependency chain between fixes. Each phase unblocks the next. The architecture research document explicitly maps this order.

### Phase 1: Unicode Source Fix
**Rationale:** This is the most impactful fix per line of code changed. It unblocks all subsequent testing on Windows because the app can now be imported. Zero logic risk — pure text replacement. Must happen first because every other fix requires running the app on Windows to verify.
**Delivers:** App imports without UnicodeEncodeError on Windows cp1252; all workspace Python files are ASCII-safe
**Addresses:** "No encoding crash on Windows" (table stakes), "Works on all 3 target OSes" (table stakes)
**Avoids:** Pitfall 1 (wrong layer fix), Pitfall 3 (partial file fix) — grep the entire workspace, fix all occurrences in one pass
**Research flag:** No deeper research needed — standard text replacement with well-known mapping

### Phase 2: Optional Ollama Import Guard
**Rationale:** Ollama is a separate external install that users frequently skip or defer. The app should start and partially function without it. This phase makes Ollama optional by moving its import guard to module level and activating the sentence-transformers fallback that is already in requirements.txt.
**Delivers:** App starts cleanly without Ollama installed; embedding falls back to sentence-transformers with a clear startup message; startup log shows which embedding model is active
**Addresses:** "App starts without crashing when optional services not present" (table stakes), "Tells user what's broken" (table stakes)
**Avoids:** Pitfall 2 (guard at wrong level — must be module-level, not inside get_embedding), Pitfall 4 (embedding dimension mismatch — add startup dimension check)
**Research flag:** The embedding dimension check needs one implementation decision: warn-only vs. hard-fail when mismatch detected. Recommend warn-only with clear message (consistent with Pitfall 7 philosophy for optional features).

### Phase 3: Platform-Aware Browser Backend
**Rationale:** Crawl4AI's Windows install failure is the other hard blocker. The fix is a thin abstraction: extract the existing crawl4ai usage into `browser_crawl4ai.py`, create a parallel `browser_playwright.py`, and dispatch by `platform.system()`. Both modules expose the same interface so `tools.py` callers are unaffected.
**Delivers:** `pip install -r requirements.txt` completes on Windows (crawl4ai excluded via PEP 508 marker); browser tool functions on Windows using Playwright; no behavior change on Mac/Linux
**Addresses:** "No cryptic errors during pip install" (table stakes), "Single install command" (table stakes)
**Avoids:** Pitfall 5 (Playwright without browser binaries — add `python -m playwright install chromium` to `synapse_onboard.bat`), Pitfall 6 (crawl4ai version pinning — use platform marker instead)
**Research flag:** No deeper research needed — Playwright 1.49+ Windows compatibility is confirmed HIGH confidence

### Phase 4: .env Validation and Feature Status
**Rationale:** This is polish that converts silent failures (missing API keys causing cryptic errors deep in the call stack) into explicit startup messages. It also produces the "feature availability summary" differentiator. Comes last because the app must actually start (Phases 1-2) for this output to be visible.
**Delivers:** Clean startup block showing which features are ON/OFF; hard exit only on missing GEMINI_API_KEY; actionable fix messages for all optional keys; new `startup_checks.py` module callable independently
**Addresses:** ".env validation at startup" (table stakes), "Feature availability summary" (differentiator), "Actionable fix messages" (differentiator)
**Avoids:** Pitfall 7 (overly aggressive validation blocking startup — only GEMINI_API_KEY is REQUIRED, all others are OPTIONAL with warn-and-continue behavior)
**Research flag:** No deeper research needed — straightforward dictionary-based validation pattern

### Phase Ordering Rationale

- Phase 1 before everything: Unicode fix unblocks the ability to run the app on Windows at all, which is required to verify all subsequent phases
- Phase 2 before Phase 3: Ollama guard is simpler (one file, one pattern) and gets the app to "starts cleanly" state; browser abstraction is more structural (two new files, adapter pattern) and benefits from a working baseline
- Phase 3 before Phase 4: The browser backend must work before the feature status message that reports on it can be validated end-to-end
- Phases are independent enough that they could be done in parallel by two developers, but sequentially they form a clean validation chain: import works → app starts → browser works → startup is informative

### Research Flags

Phases needing no additional research (standard, well-documented patterns):
- **Phase 1:** Pure text replacement — no research needed
- **Phase 3:** PEP 508 platform markers and Playwright on Windows are HIGH confidence confirmed patterns
- **Phase 4:** .env validation is a trivial dict check pattern

Phases with one open implementation decision:
- **Phase 2:** Embedding dimension mismatch handling — warn-only vs. hard-fail. Recommend warn-only (consistent with the project's philosophy of not blocking startup for optional features), but this should be confirmed during planning.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | PEP 508 markers are standard pip behavior since pip 9; Playwright 1.49+ Windows compatibility is well-documented; sentence-transformers fallback is already in requirements.txt |
| Features | HIGH | Derived directly from observed install failures documented in problems_faced.md — these are real failures, not hypothetical |
| Architecture | HIGH | Changes are additive and minimal; no restructuring; build order is prescribed by dependency analysis of current code |
| Pitfalls | HIGH | Pitfalls 1-3 are confirmed patterns from the actual codebase (line numbers cited); Pitfalls 4-7 are well-known Python packaging failure modes |

**Overall confidence:** HIGH

### Gaps to Address

- **Embedding dimension check behavior:** Research recommends warn-only for the dimension mismatch case, but this decision should be confirmed against how the memory system currently behaves when semantic search returns garbage results. If garbage results cause downstream failures (e.g., LLM gets bad context silently), a hard-fail may be safer.
- **Playwright binary path detection:** The startup check in `browser_playwright.py` that warns when Chromium binary is missing needs to use Playwright's internal `executable_path()` API — the exact call should be verified against Playwright 1.49 docs during Phase 3 implementation.
- **`change_tracker.py` scope:** This file contains many emoji instances but is not part of the core startup path. Confirm whether it is imported at startup (which would cause a crash) or only on explicit user invocation (which would be lower priority).

---

## Sources

### Primary (HIGH confidence)
- `problems_faced.md` — documented real install failures on Windows; source of all confirmed bug locations
- Python PEP 508 — environment markers for platform-conditional dependencies
- `workspace/sci_fi_dashboard/memory_engine.py` line 64 — confirmed top-level import location
- `workspace/db/tools.py` — confirmed crawl4ai top-level import

### Secondary (MEDIUM confidence)
- Playwright documentation (1.49+) — Windows 11 compatibility and `playwright install chromium` requirement
- Python packaging docs — `try/except ImportError` module-level guard pattern

### Tertiary (LOW confidence)
- sqlite-vec dimension enforcement behavior — inferred from general vector DB behavior; not directly tested in this codebase

---
*Research completed: 2026-02-27*
*Ready for roadmap: yes*
