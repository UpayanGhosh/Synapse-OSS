# Roadmap: Synapse-OSS Onboarding Improvement

## Overview

This milestone makes Synapse-OSS installable and runnable by anyone on Windows, macOS, or Linux without hitting cryptic errors. The four phases apply a surgical fix sequence ordered by dependency: fix encoding first (unblocks all Windows testing), then make Ollama optional (gets the app to a clean start state), then swap the Windows browser backend (resolves the pip install failure), and finally add startup validation (converts silent failures into actionable messages). Each phase delivers one complete, verifiable improvement with zero changes to the core request pipeline, memory system, or LLM routing.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Unicode Source Fix** - Replace all emoji in workspace Python files with ASCII tags so the app imports without crashing on Windows cp1252 (completed 2026-02-27)
- [x] **Phase 2: Optional Ollama** - Guard the Ollama import at module level and activate the sentence-transformers fallback so the app starts cleanly without Ollama installed (completed 2026-02-27)
- [ ] **Phase 3: Platform-Aware Browser Backend** - Add PEP 508 platform markers and a Playwright adapter so pip install and the browser tool both work on Windows
- [ ] **Phase 4: Startup Validation** - Add .env key validation and a feature availability summary at startup so users know exactly what is working and what is not

## Phase Details

### Phase 1: Unicode Source Fix
**Goal**: The app imports and boots on Windows without any UnicodeEncodeError
**Depends on**: Nothing (first phase)
**Requirements**: ENC-01, ENC-02
**Success Criteria** (what must be TRUE):
  1. Running `python -c "import workspace.sci_fi_dashboard.api_gateway"` on a Windows cp1252 machine produces no UnicodeEncodeError
  2. A workspace-wide grep for non-ASCII characters in print and log statements returns zero results
  3. The fix covers all affected files in a single pass — not just smart_entity.py but every workspace/*.py file that contained emoji
**Plans**: 1 plan

Plans:
- [ ] 01-01-PLAN.md -- Replace emoji/non-ASCII in all 54 workspace Python files and add PYTHONUTF8=1 defense-in-depth

### Phase 2: Optional Ollama
**Goal**: The app starts successfully and provides useful embedding functionality even when Ollama is not installed
**Depends on**: Phase 1
**Requirements**: OLL-01, OLL-02, OLL-03, OLL-04
**Success Criteria** (what must be TRUE):
  1. Starting the app on a machine with no Ollama installed reaches the "ready" state without raising ModuleNotFoundError or any import-time exception
  2. Embedding queries return results using the sentence-transformers all-MiniLM-L6-v2 fallback model when Ollama is unavailable
  3. The startup log prints a clear message naming which features are unavailable (e.g., "Ollama not found -- local embedding and The Vault disabled")
  4. Running synapse_onboard.bat and synapse_onboard.sh on a machine without Ollama completes without error and continues to the next onboarding step
**Plans**: 2 plans

Plans:
- [x] 02-01-PLAN.md -- Guard memory_engine.py import + sentence-transformers fallback + startup log (OLL-01, OLL-02, OLL-03)
- [x] 02-02-PLAN.md -- Demote Ollama to optional in synapse_onboard.bat and synapse_onboard.sh (OLL-04)

### Phase 3: Platform-Aware Browser Backend
**Goal**: pip install succeeds on Windows and the /browse tool works using Playwright on Windows and Crawl4AI on Mac/Linux
**Depends on**: Phase 2
**Requirements**: BRW-01, BRW-02, BRW-03, BRW-04
**Success Criteria** (what must be TRUE):
  1. Running `pip install -r requirements.txt` on Windows 11 completes without errors (crawl4ai is not installed on Windows)
  2. Calling the /browse endpoint on Windows returns a valid HTML response via the Playwright backend
  3. Calling the /browse endpoint on Mac or Linux returns a valid HTML response via the Crawl4AI backend unchanged
  4. synapse_onboard.bat runs `python -m playwright install chromium` so Playwright browser binaries are present on Windows
**Plans**: 2 plans

Plans:
- [ ] 03-01-PLAN.md -- Add PEP 508 markers to requirements.txt + playwright binary install in synapse_onboard.bat (BRW-01, BRW-02, BRW-03)
- [ ] 03-02-PLAN.md -- Rewrite tools.py with platform-aware dispatch + guard scrape_threads.py (BRW-04)

### Phase 4: Startup Validation
**Goal**: Users see a clear feature availability summary at startup and receive actionable messages for any missing configuration
**Depends on**: Phase 3
**Requirements**: ENV-01, ENV-02, ENV-03
**Success Criteria** (what must be TRUE):
  1. Starting the app without GEMINI_API_KEY causes a hard exit with a message that names the missing key and explains it is required
  2. Starting the app without optional keys (GROQ_API_KEY, OPENROUTER_API_KEY, etc.) prints a per-key warning naming the affected feature but does not prevent startup
  3. The startup output includes a feature availability block listing each service (Ollama, Qdrant, Groq, OpenRouter, WhatsApp bridge) as ON or OFF
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Unicode Source Fix | 1/1 | Complete    | 2026-02-27 |
| 2. Optional Ollama | 2/2 | Complete   | 2026-02-27 |
| 3. Platform-Aware Browser Backend | 0/2 | Not started | - |
| 4. Startup Validation | 0/TBD | Not started | - |
