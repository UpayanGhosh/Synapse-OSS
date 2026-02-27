# Requirements: Synapse-OSS Onboarding Improvement

**Defined:** 2026-02-27
**Core Value:** Anyone can install and run Synapse-OSS on their machine without hitting cryptic errors, regardless of OS or which optional services they have installed.

## v1 Requirements

Requirements for this milestone. Each maps to a roadmap phase.

### Encoding

- [ ] **ENC-01**: App boots on Windows without UnicodeEncodeError (all emoji in workspace/*.py replaced with ASCII tags)
- [ ] **ENC-02**: Fix covers all affected files in one pass (not just smart_entity.py — grep confirms zero non-ASCII in print/log statements)

### Optional Ollama

- [ ] **OLL-01**: App starts successfully when Ollama is not installed (module-level import guard in memory_engine.py)
- [ ] **OLL-02**: Embedding falls back to sentence-transformers (all-MiniLM-L6-v2) when Ollama is unavailable
- [ ] **OLL-03**: Startup prints a clear message listing which features are unavailable when Ollama is not detected
- [ ] **OLL-04**: Onboarding scripts (synapse_onboard.bat and .sh) treat Ollama as optional, not required

### Browser Backend

- [ ] **BRW-01**: `pip install -r requirements.txt` completes without errors on Windows 11
- [ ] **BRW-02**: requirements.txt uses PEP 508 platform markers (crawl4ai on Mac/Linux, playwright on Windows)
- [ ] **BRW-03**: `synapse_onboard.bat` runs `python -m playwright install chromium` on Windows
- [ ] **BRW-04**: `tools.py` browser abstraction dispatches to Crawl4AI or Playwright based on OS, with identical `search_web(url)` interface

### Startup Validation

- [ ] **ENV-01**: Startup validates all env keys — hard-fails only on GEMINI_API_KEY, warns-only on optional keys
- [ ] **ENV-02**: Each warning names the affected feature (e.g. "GROQ_API_KEY not set — voice transcription disabled")
- [ ] **ENV-03**: Startup prints a feature availability summary showing which services are ON vs OFF (Ollama, Qdrant, Groq, OpenRouter, WhatsApp bridge)

## v2 Requirements

Deferred to future milestone.

### Onboarding Polish

- **ONB-01**: First-run smoke test — send a test message through the pipeline and confirm it completes
- **ONB-02**: Guided `.env` setup — interactive prompts for each key with description and URL
- **ONB-03**: Capability summary as a formatted table (tabulate-style) with health-check pings per service

### Embedding Robustness

- **EMB-01**: Startup detects embedding dimension mismatch between stored vectors and active model, warns user
- **EMB-02**: `python main.py verify` checks and reports embedding model consistency

## Out of Scope

| Feature | Reason |
|---------|--------|
| Docker / docker-compose setup | Heavy; target audience is non-technical friends, not DevOps |
| Auto-updater | Disproportionate complexity for personal use; `git pull` is sufficient |
| Web-based config UI | Separate product; guided .env (v2) solves the actual problem |
| Platform-specific installers (.msi, .dmg) | Massive packaging effort; onboarding scripts are the installer |
| Strict dependency pinning / lock files | Not solving a current user problem; would add maintenance burden |

## Traceability

Which phases cover which requirements. Confirmed during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENC-01 | Phase 1 | Pending |
| ENC-02 | Phase 1 | Pending |
| OLL-01 | Phase 2 | Pending |
| OLL-02 | Phase 2 | Pending |
| OLL-03 | Phase 2 | Pending |
| OLL-04 | Phase 2 | Pending |
| BRW-01 | Phase 3 | Pending |
| BRW-02 | Phase 3 | Pending |
| BRW-03 | Phase 3 | Pending |
| BRW-04 | Phase 3 | Pending |
| ENV-01 | Phase 4 | Pending |
| ENV-02 | Phase 4 | Pending |
| ENV-03 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-27*
*Last updated: 2026-02-27 — traceability confirmed during roadmap creation*
