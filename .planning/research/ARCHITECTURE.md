# Architecture Research: Graceful Degradation & Platform-Aware Backends

**Research Date:** 2026-02-27
**Dimension:** Architecture
**Focus:** Retrofitting optional dependencies into Synapse-OSS without restructuring

---

## Components to Modify

### Component 1: Browser Abstraction (`workspace/db/tools.py`)

**Current:**
```
tools.py
  └── from crawl4ai import AsyncWebCrawler  ← top-level, Windows fails here
  └── ToolRegistry.search_web() → AsyncWebCrawler.arun(url)
```

**Target:**
```
tools.py
  └── platform.system() == "Windows"?
        ├── YES → from .browser_playwright import search_web
        └── NO  → from .browser_crawl4ai import search_web
  └── ToolRegistry.search_web() → search_web(url)  ← same interface

browser_crawl4ai.py   ← extracted from current tools.py
  └── async def search_web(url) → str

browser_playwright.py ← new file
  └── async def search_web(url) → str
```

**Build order:** Create `browser_crawl4ai.py` first (extract existing), then `browser_playwright.py` (new), then update `tools.py` to dispatch.

**Data flow:** `api_gateway.py → ToolRegistry.search_web(url) → [platform adapter] → str`

---

### Component 2: Ollama Optional (`workspace/sci_fi_dashboard/memory_engine.py`)

**Current:**
```
memory_engine.py
  └── import ollama  ← line 64, top-level, CRASHES if ollama not installed
  └── get_embedding(text) → ollama.embeddings(...)
        └── except Exception → returns zero vector [0.0 * 768]
```

**Problem:** The `import ollama` at module level raises `ModuleNotFoundError` before `get_embedding` is ever called. The existing `except` on line 106 never executes.

**Target:**
```
memory_engine.py
  └── try: import ollama; OLLAMA_AVAILABLE = True
      except ImportError: OLLAMA_AVAILABLE = False

  └── get_embedding(text):
        if OLLAMA_AVAILABLE:
            → ollama.embeddings(...)
        else:
            → sentence_transformer_embed(text)  ← new private method

  └── _sentence_transformer_embed(text):
        lazy-load SentenceTransformer("all-MiniLM-L6-v2")
        return tuple(model.encode(text).tolist())
```

**sentence-transformers is already in requirements.txt** — this is not a new dependency.

**Embedding dimension note:** nomic-embed-text outputs 768-dim. all-MiniLM-L6-v2 outputs 384-dim. The zero-vector fallback currently returns 768-dim. The DB was initialized with whichever dim was used first. The fallback must match the DB's stored dimension. Best practice: check `sqlite-vec` table schema at startup and warn if mismatch.

**Data flow:** `MemoryEngine.get_embedding(text) → [ollama OR sentence-transformers] → tuple`

---

### Component 3: Unicode Fix (multiple files)

**Current problem files (from grep):**
- `workspace/sci_fi_dashboard/smart_entity.py` — lines 21, 23 (✅ ⚠️)
- `workspace/sci_fi_dashboard/memory_engine.py` — lines 95, 107 (✅ ⚠️)
- `workspace/change_tracker.py` — many lines (⏸️ ⚠️ ✅ 🚀 etc.)
- `workspace/finish_facts.py` — ⚠️

**Target:** Replace all emoji print statements with ASCII tags:
- `✅` → `[OK]`
- `⚠️` → `[WARN]`
- `❌` → `[ERROR]`
- `🚀` → `[INFO]`

**Scope:** All `workspace/**/*.py` files. The grep output showed ~30+ instances across ~10 files.

**Important:** This is a pure text replacement — no logic changes. Low risk.

---

### Component 4: .env Validation (`workspace/sci_fi_dashboard/api_gateway.py`)

**Insertion point:** Early in `api_gateway.py` startup, before singletons are initialized.

**Target:**
```python
# api_gateway.py — after imports, before singleton init
from .startup_checks import validate_env, print_feature_status

warnings = validate_env()
print_feature_status(warnings)
```

New file: `workspace/sci_fi_dashboard/startup_checks.py`
- `validate_env()` → checks REQUIRED and OPTIONAL keys, returns list of warning strings
- `print_feature_status(warnings)` → prints a clean summary block

**Data flow:** `api_gateway startup → startup_checks.validate_env() → console output`

---

## Suggested Build Order

```
Phase 1: Unicode Fix (zero risk, unblocks everything)
  → Replace emojis in all workspace/*.py files
  → Test: python -c "import workspace.sci_fi_dashboard.smart_entity" on Windows

Phase 2: Optional Ollama (unblocks startup on machines without Ollama)
  → Add try/except import guard in memory_engine.py
  → Add sentence-transformers fallback in get_embedding()
  → Test: uninstall ollama, start app, confirm fallback message shown

Phase 3: Platform Browser Backend (unblocks Crawl4AI Windows failure)
  → Extract browser_crawl4ai.py from tools.py
  → Create browser_playwright.py
  → Update tools.py to dispatch by platform
  → Test: Windows install with only playwright, Mac/Linux with crawl4ai

Phase 4: .env Validation + Feature Status (polish)
  → Create startup_checks.py
  → Hook into api_gateway.py startup
  → Test: empty GEMINI_API_KEY, confirm clear error message
```

---

## No-Change Zones

These components should NOT be modified in this milestone:
- `api_gateway.py` core routing logic
- `gateway/` pipeline (flood, dedup, queue, worker)
- `sbs/` persona engine
- `memory.db` schema
- Any LLM routing logic

The goal is surgical: fix install + startup only.
