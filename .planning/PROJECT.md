# Synapse-OSS

## What This Is

Synapse-OSS is an open-source AI assistant that runs as a personal WhatsApp bot, featuring hybrid RAG memory, a persona engine (Soul-Brain Sync), local LLM routing, and a FastAPI gateway. It is designed to be installed by anyone — including non-technical users — on Windows, macOS, or Linux.

## Core Value

Anyone can install and run Synapse-OSS on their machine without hitting cryptic errors, regardless of OS or which optional services they have installed.

## Requirements

### Validated

- ✓ WhatsApp message pipeline (flood gate → dedup → async queue → workers) — existing
- ✓ Hybrid RAG memory (sqlite-vec + FTS + Qdrant) with hemisphere tagging — existing
- ✓ LLM routing (Gemini Flash, Claude, OpenRouter fallback, local Ollama) — existing
- ✓ Soul-Brain Sync persona engine (8-layer profile, real-time + batch) — existing
- ✓ Knowledge graph (SQLite subject-predicate-object triples) — existing
- ✓ Dual cognition (inner monologue + tension scoring before LLM call) — existing
- ✓ Toxic-BERT lazy-loaded scoring — existing
- ✓ Web scraping via Crawl4AI (`/browse` endpoint) — existing
- ✓ Voice transcription via Groq Whisper — existing
- ✓ FastAPI gateway with tool endpoints — existing
- ✓ Onboarding scripts (synapse_onboard.bat + synapse_onboard.sh) — existing

### Active

- [ ] Ollama is optional — installer skips it gracefully, runtime surfaces which features are unavailable
- [ ] OS-aware browser backend — Crawl4AI on Mac/Linux, Playwright on Windows, unified `/browse` abstraction
- [ ] Fix Windows Unicode crash — emojis in `smart_entity.py` and other files crash on `cp1252` encoding
- [ ] `.env` validation at startup — detect empty/placeholder API keys, tell user which features are affected

### Out of Scope

- Full CI/CD or Docker containerization — too much overhead for this milestone
- Replacing Qdrant with another vector DB — not an onboarding problem
- Changing the LLM routing logic — out of scope for this improvement cycle

## Context

This project was installed on a friend's Windows PC (user: Shreya) and hit 4 distinct failures:
1. Crawl4AI installation errors on Windows
2. `UnicodeEncodeError` on Windows `cp1252` when smart_entity.py emojis are printed at boot
3. Ollama treated as required — app behavior unclear when it isn't installed
4. Missing `.env` keys caused silent feature failures with no helpful guidance

The codebase has already been mapped at `.planning/codebase/` (2026-02-27).

## Constraints

- **Tech stack**: Python 3.11, FastAPI, asyncio — no changes to core architecture
- **Compatibility**: Must work on Windows 11, macOS (Apple Silicon), Ubuntu
- **No breaking changes**: Existing users with all dependencies should see zero behavior change
- **Ollama fallback**: sentence-transformers is already in requirements.txt as the embedding fallback — use it

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Playwright for Windows, Crawl4AI for Mac/Linux | Crawl4AI has Windows install issues; Playwright is the underlying engine both share | — Pending |
| Fix emojis at source in smart_entity.py | Setting PYTHONUTF8=1 is a workaround, not a fix; ASCII replacements are more robust | — Pending |
| Feature flag via env check at startup | Avoids import-time crashes; surfaces missing deps as warnings, not exceptions | — Pending |

---
*Last updated: 2026-02-27 after initialization*
