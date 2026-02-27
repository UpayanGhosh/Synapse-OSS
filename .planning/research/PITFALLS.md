# Pitfalls Research: Windows Install & Optional Dependency Handling

**Research Date:** 2026-02-27
**Dimension:** Pitfalls
**Source:** problems_faced.md (real failures) + Python packaging knowledge

---

## Pitfall 1: Fixing the Wrong Layer for Unicode

**What goes wrong:** Developers set `PYTHONUTF8=1` as an env var in the start script and call it done. This fixes their machine but not the source files. Anyone who runs the app without the env var (e.g. via IDE, direct python invocation, or importing from another tool) hits the crash again.

**Warning signs:**
- Fix is in a shell script, not in the Python source
- Source files still contain non-ASCII characters in print/log statements

**Prevention:**
- Fix at source: replace emojis with ASCII tags `[OK]`, `[WARN]`, `[ERROR]`
- Add `PYTHONUTF8=1` to the start script anyway as defense-in-depth, not as the sole fix
- Run `grep -rn '[^\x00-\x7F]' workspace/*.py` to find all non-ASCII in source

**Phase to address:** Phase 1 (first, unblocks everything else)

---

## Pitfall 2: Guarding the Wrong Import Level

**What goes wrong:** Developer adds `try/except ImportError` inside a function body rather than at module level. The module still fails to import because the top-level `import ollama` runs before any function is called.

**Concrete example (current memory_engine.py):**
```python
import ollama  # ← line 64: crashes HERE on ModuleNotFoundError

def get_embedding(self, text):
    try:
        response = ollama.embeddings(...)  # ← try/except here is never reached
    except Exception as e:
        return tuple([0.0] * 768)  # ← this fallback never executes
```

**Prevention:**
- Guard must be at module level: `try: import ollama; OLLAMA_AVAILABLE = True`
- Test by actually uninstalling the package: `pip uninstall ollama -y && python -c "from workspace.sci_fi_dashboard import memory_engine"`

**Phase to address:** Phase 2

---

## Pitfall 3: Embedding Dimension Mismatch After Switching Models

**What goes wrong:** App ran fine with Ollama (nomic-embed-text = 768-dim vectors stored in memory.db). Ollama is then not available, sentence-transformers fallback kicks in (all-MiniLM-L6-v2 = 384-dim). sqlite-vec or Qdrant rejects the query because dimension doesn't match stored vectors.

**Warning signs:**
- App appears to start OK but semantic search returns no results or throws an error
- Error messages like "vector dimension mismatch" or "expected 768, got 384"

**Prevention:**
- Log which embedding model is being used at startup
- Add a startup check: query the sqlite-vec table for its stored dimension, compare with active model's dimension
- If mismatch: log a clear warning ("Stored vectors are 768-dim but current model produces 384-dim. Semantic search may fail. Re-ingest memories after switching models.")
- Do NOT silently truncate or zero-pad — this produces garbage results

**Phase to address:** Phase 2 (when implementing Ollama fallback)

---

## Pitfall 4: Crawl4AI "Fixed" by Pinning an Old Version

**What goes wrong:** Developer finds that `crawl4ai==0.2.3` installed on Windows but `>=0.2.0` doesn't resolve to it. They pin the old version. It installs but has different API behavior — `result.markdown` may not exist or behave differently.

**Warning signs:**
- requirements.txt has a specific pinned crawl4ai version for "stability"
- Windows users get the pinned version, Mac users get newer — divergent behavior

**Prevention:**
- Don't try to fix Crawl4AI on Windows — use Playwright instead (it's what Crawl4AI wraps)
- PEP 508 platform marker is the right solution: `crawl4ai>=0.2.0; sys_platform != "win32"`
- After adding marker, test: `pip install -r requirements.txt` on Windows — crawl4ai should not appear in `pip list`

**Phase to address:** Phase 3

---

## Pitfall 5: Playwright Install Without Browser Binaries

**What goes wrong:** `pip install playwright` succeeds but the actual Chromium binary is never downloaded. `playwright install chromium` must be run separately. Onboarding script doesn't include this step. User runs the app, browser tool fails with "Executable doesn't exist."

**Warning signs:**
- Playwright package installs cleanly
- First `search_web()` call raises `playwright._impl._errors.Error: Executable doesn't exist`

**Prevention:**
- Add to `synapse_onboard.bat` (Windows only):
  ```batch
  python -m playwright install chromium
  ```
- Add a startup check in `browser_playwright.py`: try to locate the chromium binary, warn if missing

**Phase to address:** Phase 3

---

## Pitfall 6: .env Validation Too Aggressive (Blocking Startup)

**What goes wrong:** Developer adds env validation that raises a `SystemExit` if any key is missing. User who hasn't set up voice transcription yet can't start the app at all, even though Gemini (the required key) is set.

**Warning signs:**
- Startup validation uses `raise SystemExit` or `sys.exit()` for optional keys
- Users complain they can't start the app after partial setup

**Prevention:**
- Only hard-fail (`sys.exit`) on truly required keys (e.g. `GEMINI_API_KEY`)
- For optional keys: print a warning, continue startup, disable the specific feature
- Make the distinction explicit in code comments: `REQUIRED_KEYS` vs `OPTIONAL_KEYS`

**Phase to address:** Phase 4

---

## Pitfall 7: Fixing Only smart_entity.py for Unicode

**What goes wrong:** Developer fixes the emoji in smart_entity.py (the file named in the error). But memory_engine.py, change_tracker.py, and other files also have emojis. On a fresh Windows boot, whichever of those files gets imported first triggers the same crash.

**Warning signs:**
- `smart_entity.py` is fixed but other files still have `✅`, `⚠️`, `🚀` in print statements

**Prevention:**
- Do a whole-workspace grep before declaring the fix done:
  ```bash
  grep -rn "[^\x00-\x7F]" workspace/ --include="*.py"
  ```
- Fix ALL occurrences in one pass, not file by file

**Phase to address:** Phase 1
