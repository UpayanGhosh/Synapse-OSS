# Stack Research: Python Optional Dependencies & Platform-Aware Installation

**Research Date:** 2026-02-27
**Dimension:** Stack
**Confidence:** High — patterns verified against Python packaging docs and known library behaviour

---

## Current State

| Component | Current | Problem |
|-----------|---------|---------|
| Browser automation | `crawl4ai>=0.2.0` (top-level import) | Fails to install on Windows |
| Local LLM / embeddings | `ollama>=0.1.0` (top-level import, line 64 memory_engine.py) | Assumed present; crashes at import if not installed |
| Encoding | Emojis in print statements across workspace/ | `cp1252` on Windows raises `UnicodeEncodeError` at boot |
| .env validation | None | Silent failures when keys are missing |

---

## Recommended Patterns

### 1. Optional Imports — Standard Python Pattern

Use a guarded top-level import with a module-level flag:

```python
# At module level
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None
    OLLAMA_AVAILABLE = False
```

Then at usage site:
```python
if not OLLAMA_AVAILABLE:
    warnings.warn("Ollama not installed. Falling back to sentence-transformers.")
    return self._sentence_transformer_embed(text)
response = ollama.embeddings(model=EMBEDDING_MODEL, prompt=text)
```

**Why not lazy import?** Lazy imports (importlib at call time) are harder to reason about and don't give a clear module-level flag. The try/except pattern is idiomatic Python and understood by all contributors.

**Confidence:** High

### 2. Platform-Aware Browser Backend

**Decision: Playwright on Windows, Crawl4AI on Mac/Linux**

Crawl4AI wraps Playwright under the hood, but adds:
- Additional ML dependencies (torch, transformers) for content extraction
- Complex binary installation that fails on Windows without Visual C++ redistributables
- Post-install steps (`crawl4ai-setup`) that don't run reliably on Windows

Playwright directly is cleaner on Windows:
```
pip install playwright
python -m playwright install chromium
```

**Abstraction pattern — thin adapter in tools.py:**

```python
import platform

if platform.system() == "Windows":
    from .browser_playwright import search_web
else:
    from .browser_crawl4ai import search_web
```

Both modules expose the same `async def search_web(url: str) -> str` interface.

**Playwright API for search_web equivalent:**
```python
from playwright.async_api import async_playwright

async def search_web(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, timeout=15000)
        text = await page.inner_text("body")
        await browser.close()
        return text[:3000]
```

**Confidence:** High — Playwright 1.49+ works reliably on Windows 11

### 3. Requirements Split

**`requirements.txt`** — core, works everywhere:
```
# Remove: crawl4ai>=0.2.0
# Add:
playwright>=1.49.0; sys_platform == "win32"
crawl4ai>=0.2.0; sys_platform != "win32"
```

PEP 508 environment markers work in plain `pip install -r requirements.txt`. No separate files needed.

For Ollama — move to optional section with a comment:
```
# --- Optional: Local LLM (Ollama must be installed separately from ollama.com) ---
# ollama>=0.1.0
```

**Confidence:** High — PEP 508 markers are standard pip behavior since pip 9

### 4. Encoding Fix

**Root cause:** Python on Windows defaults to `cp1252` unless `PYTHONUTF8=1` or `-X utf8` is set.

**Fix at source — replace emojis with ASCII tags:**
```python
# Before
print(f"✅ Loaded {len(entities_dict)} entity groups")
print(f"⚠️ Warning: Entities file not found")

# After
print(f"[OK] Loaded {len(entities_dict)} entity groups")
print(f"[WARN] Entities file not found")
```

**Files to fix:** smart_entity.py, memory_engine.py, change_tracker.py, and any other workspace/*.py with non-ASCII print statements.

**Alternative:** Add `# -*- coding: utf-8 -*-` + set stdout encoding at startup. But source fix is more robust.

**Confidence:** High

### 5. Startup .env Validation

```python
import os
from typing import Optional

REQUIRED_KEYS = ["GEMINI_API_KEY"]
OPTIONAL_KEYS = {
    "GROQ_API_KEY": "Voice message transcription (Whisper) will be disabled",
    "OPENROUTER_API_KEY": "LLM fallback routing will be disabled",
    "WHATSAPP_BRIDGE_TOKEN": "WhatsApp integration will not work",
}

def validate_env() -> list[str]:
    warnings = []
    for key, feature_msg in OPTIONAL_KEYS.items():
        val = os.getenv(key, "")
        if not val or val.startswith("your_") or val == "placeholder":
            warnings.append(f"[WARN] {key} not set — {feature_msg}")
    return warnings
```

Called once at `api_gateway.py` startup, prints warnings to console.

**Confidence:** High

---

## What NOT to Use

| Approach | Why Not |
|----------|---------|
| `importlib.import_module` for lazy loading | Harder to read, no module-level availability flag |
| Separate `requirements-windows.txt` | Forces users to know which file to use — error prone |
| `pyproject.toml` extras (`pip install synapse[windows]`) | Too much friction for non-technical users |
| Docker for isolation | Heavy; target users are non-technical friends, not DevOps |

---

## Key Versions (2026)

| Package | Recommended Version | Notes |
|---------|--------------------|----|
| `playwright` | `>=1.49.0` | Windows 11 compatible, Chromium bundled |
| `crawl4ai` | `>=0.2.0` | Mac/Linux only in this project |
| `sentence-transformers` | `>=2.2.0` | Already in requirements.txt — Ollama fallback |
