# Phase 1: Unicode Source Fix - Research

**Researched:** 2026-02-27
**Domain:** Python Unicode encoding on Windows (cp1252 vs UTF-8)
**Confidence:** HIGH

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| ENC-01 | App boots on Windows without UnicodeEncodeError (all emoji in workspace/*.py replaced with ASCII tags) | Root cause confirmed: module-level print statements in smart_entity.py, memory_engine.py, and 49 other files execute at import time and crash cp1252. ASCII replacement pattern documented. |
| ENC-02 | Fix covers all affected files in one pass (not just smart_entity.py — grep confirms zero non-ASCII in print/log statements) | Full scan completed: 252 runtime print/log hits across 51 files. Grep verification command documented. Replacement map established. |

</phase_requirements>

---

## Summary

Python on Windows defaults to the `cp1252` encoding for stdout unless `PYTHONUTF8=1` or `-X utf8` is set. When any `print()` or `logging.*()` statement emits a character outside the cp1252 range — such as emoji (✅, ⚠️, ❌, 🚀) or box-drawing characters (═, ─) — Python raises `UnicodeEncodeError` immediately. This crash occurs at the Python level before the message ever reaches the terminal.

A full workspace scan of all `workspace/*.py` files found **586 non-ASCII occurrences across 51 files**. Of these, **252 are inside runtime print/log statements** (the crash-causing category). The remaining 334 are in comments, docstrings, and string literals that are not directly written to stdout — but any of these that are eventually passed to a logging handler or print call will also crash. The known crash site (`smart_entity.py:21`) is only one of 252 such call sites.

The fix is straightforward: replace all non-ASCII characters in print/log statements with ASCII-only equivalents, then add `PYTHONUTF8=1` to start scripts as defense-in-depth. The approach must be applied workspace-wide in one pass, not file by file, to satisfy ENC-02. A post-fix grep verifies completeness.

**Primary recommendation:** Replace emoji and non-ASCII in all print/log statements across all 51 affected files using the documented replacement map, then verify with `grep -rn "[^\x00-\x7F]" workspace/ --include="*.py"`.

---

## Standard Stack

### Core

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| Python built-ins | stdlib | `re`, `os.walk` for scanning | No dependencies needed; the scan and fix require only stdlib |
| `ruff` | project-pinned | Lint after fix to verify no regressions | Already in project toolchain per CLAUDE.md |
| `black` | project-pinned | Format after fix | Already in project toolchain per CLAUDE.md |

### Supporting

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| `pytest` | project-pinned | Verify imports pass after fix | Run smoke tests post-fix to confirm no regressions |
| `grep` / Python scan script | stdlib | Verify zero non-ASCII remain | Post-fix verification command |

### No External Libraries Needed

This phase requires no new dependencies. It is a pure source-code text replacement task.

**Verification command (post-fix):**
```bash
# Must return zero results for ENC-02 to pass
grep -rn "[^\x00-\x7F]" workspace/ --include="*.py"
```

**On Windows (cp1252 environment), verify boot:**
```bash
python -c "import workspace.sci_fi_dashboard.api_gateway"
```

---

## Architecture Patterns

### Scope of Change

The fix touches **51 Python files** in the workspace. The full list from the workspace scan:

```
workspace/change_tracker.py
workspace/change_viewer.py
workspace/finish_facts.py
workspace/main.py
workspace/monitor.py
workspace/purge_trash.py
workspace/sci_fi_dashboard/api_gateway.py
workspace/sci_fi_dashboard/build_persona.py
workspace/sci_fi_dashboard/chat_parser.py
workspace/sci_fi_dashboard/conflict_resolver.py
workspace/sci_fi_dashboard/db.py
workspace/sci_fi_dashboard/dual_cognition.py
workspace/sci_fi_dashboard/emotional_trajectory.py
workspace/sci_fi_dashboard/gateway/worker.py
workspace/sci_fi_dashboard/gentle_worker.py
workspace/sci_fi_dashboard/ingest.py
workspace/sci_fi_dashboard/memory_engine.py
workspace/sci_fi_dashboard/migrate_graph.py
workspace/sci_fi_dashboard/narrative.py
workspace/sci_fi_dashboard/persona.py
workspace/sci_fi_dashboard/retriever.py
workspace/sci_fi_dashboard/sbs/injection/compiler.py
workspace/sci_fi_dashboard/sbs/processing/batch.py
workspace/sci_fi_dashboard/sbs/processing/realtime.py
workspace/sci_fi_dashboard/sbs/processing/selectors/exemplar.py
workspace/sci_fi_dashboard/sbs/profile/manager.py
workspace/sci_fi_dashboard/sbs/sentinel/gateway.py
workspace/sci_fi_dashboard/sbs/sentinel/manifest.py
workspace/sci_fi_dashboard/sbs/vacuum.py
workspace/sci_fi_dashboard/sbs_bootstrap.py
workspace/sci_fi_dashboard/smart_entity.py
workspace/sci_fi_dashboard/sqlite_graph.py
workspace/sci_fi_dashboard/toxic_scorer_lazy.py
workspace/sci_fi_dashboard/ui_components.py
workspace/sci_fi_dashboard/verify_dual_cognition.py
workspace/sci_fi_dashboard/verify_soul.py
workspace/scripts/db_cleanup.py
workspace/scripts/db_organize.py
workspace/scripts/dsa_logger.py
workspace/scripts/fact_extractor.py
workspace/scripts/genesis.py
workspace/scripts/latency_watcher.py
workspace/scripts/memory_test.py
workspace/scripts/migrate_temporal.py
workspace/scripts/nightly_ingest.py
workspace/scripts/prune_sessions.py
workspace/scripts/ram_watchdog.py
workspace/scripts/sanitizer.py
workspace/scripts/update_memory_schema.py
workspace/scripts/v2_migration/migrate_vectors.py
workspace/skills/google_native.py
workspace/skills/memory/ingest_memories.py
workspace/tests/test_e2e.py
workspace/utils/env_loader.py
```

### Pattern 1: ASCII Replacement Map

**What:** Replace each category of non-ASCII character with a semantically equivalent ASCII tag.

**When to use:** Every print/log call site. Also apply to string literals that are displayed (e.g., monitor.py tool label dictionary values).

**Replacement map (verified against actual occurrences in codebase scan):**

```python
# Source: direct scan of workspace files, 2026-02-27

# Status emoji
"✅"  ->  "[OK]"
"❌"  ->  "[ERROR]"
"⚠️"  ->  "[WARN]"   # note: ⚠️ is two chars: U+26A0 + U+FE0F
"🚀"  ->  "[INFO]"

# Action/state emoji
"📝"  ->  "[LOG]"
"📂"  ->  "[DIR]"
"🔍"  ->  "[SEARCH]"
"⏳"  ->  "[WAIT]"
"⏸️"  ->  "[PAUSED]"
"▶️"  ->  "[RESUME]"
"ℹ️"  ->  "[INFO]"
"⏱️"  ->  "[TIME]"
"🛑"  ->  "[STOP]"
"👋"  ->  "[BYE]"
"👁️"  ->  "[WATCH]"
"🛡️"  ->  "[GUARD]"
"🌿"  ->  "[BRANCH]"
"🚨"  ->  "[ALERT]"
"📊"  ->  "[STATS]"
"📜"  ->  "[HISTORY]"
"🧬"  ->  "[PROC]"
"🕵️"  ->  "[CHECK]"
"🧹"  ->  "[CLEAN]"
"🔗"  ->  "[LINK]"

# Box-drawing characters (used in section headers)
"═" (U+2550)  ->  "="
"─" (U+2500)  ->  "-"
"—" (U+2014, em-dash)  ->  "--"

# Number keycap sequences (1️⃣, 2️⃣, 3️⃣)
"1️⃣"  ->  "1."
"2️⃣"  ->  "2."
"3️⃣"  ->  "3."

# Other common ones found in scan
"🌐"  ->  "[WEB]"
"📡"  ->  "[FETCH]"
"💬"  ->  "[REPLY]"
"🧠"  ->  "[MEM]"
"📥"  ->  "[ADD]"
"📖"  ->  "[READ]"
"✉️"  ->  "[MSG]"
"📅"  ->  "[CAL]"
"👥"  ->  "[CONTACTS]"
"💻"  ->  "[CMD]"
"⚙️"  ->  "[EVAL]"
"📧"  ->  "[EMAIL]"
"🖼️"  ->  "[IMG]"
"🤖"  ->  "[BOT]"
"👤"  ->  "[USER]"
"🌍"  ->  "[WEB]"
"📈"  ->  "[CHART]"
"🔒"  ->  "[LOCK]"
"🔓"  ->  "[UNLOCK]"
"🌱"  ->  "[NEW]"
```

**The known crash site example:**
```python
# workspace/sci_fi_dashboard/smart_entity.py:21

# Before (crashes on cp1252):
print(f"✅ Loaded {len(entities_dict)} entity groups from {self.entities_file}")
print(f"⚠️ Warning: Entities file {self.entities_file} not found. Starting empty.")

# After (safe on all platforms):
print(f"[OK] Loaded {len(entities_dict)} entity groups from {self.entities_file}")
print(f"[WARN] Entities file {self.entities_file} not found. Starting empty.")
```

### Pattern 2: Systematic Multi-File Edit Approach

**What:** Process all 51 files in a single pass using a Python script that reads each file, applies replacements, and writes back.

**When to use:** Required for ENC-02 (all files in one pass).

**Approach:**
```python
# Pseudocode for systematic replacement
import re

REPLACEMENTS = {
    "✅": "[OK]",
    "❌": "[ERROR]",
    "⚠️": "[WARN]",
    # ... (full map above)
    "\u2550": "=",   # ═ box-drawing double horizontal
    "\u2500": "-",   # ─ box-drawing single horizontal
    "\u2014": "--",  # — em-dash
}

def fix_file(path):
    content = open(path, encoding="utf-8").read()
    for emoji, replacement in REPLACEMENTS.items():
        content = content.replace(emoji, replacement)
    open(path, "w", encoding="utf-8").write(content)
```

**Note:** Apply replacements to ALL contexts (comments, docstrings, string literals, print/log calls) to achieve a complete zero-non-ASCII result for ENC-02. The ENC-02 success criterion is a grep returning zero results — no exceptions for comments.

### Pattern 3: Defense-in-Depth in Start Scripts

**What:** Add `PYTHONUTF8=1` to start scripts so that even if a non-ASCII character is missed, it degrades gracefully rather than crashing.

**When to use:** After the source fix is complete — this is supplemental, not the primary fix.

```batch
REM synapse_start.bat — add before uvicorn invocation
set PYTHONUTF8=1
```

```bash
# synapse_start.sh — add at top
export PYTHONUTF8=1
```

### Anti-Patterns to Avoid

- **Fixing only smart_entity.py:** The CONCERNS.md and PITFALLS.md both document this trap. There are 51 files with non-ASCII. The first module that runs on Windows boots determines which error appears.
- **Using `PYTHONUTF8=1` as the sole fix:** Any user who runs `python main.py` directly (not via start script) still crashes. Source fix is required.
- **Using `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')` at startup:** Fragile — only protects code that runs after the wrapper is installed. Module-level prints during import run before any gateway code.
- **Adding `# -*- coding: utf-8 -*-` at file top:** This declares the SOURCE FILE encoding for the parser, not the OUTPUT encoding for stdout. It does not prevent the crash.
- **Replacing in print/log only, leaving comments:** ENC-02 criterion is a grep across all contexts. Comments with non-ASCII will cause the grep verification to fail.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Finding all non-ASCII characters | Custom recursive scanner with regex | `grep -rn "[^\x00-\x7F]" workspace/ --include="*.py"` | Grep is the standard tool, works the same on all platforms |
| Encoding-safe output wrapper | Custom StreamWriter class | ASCII replacement at source | Wrappers have edge cases (logging handlers bypass them) |
| Platform detection for encoding | `platform.system()` check before every print | Source fix makes it unconditional | Conditional encoding is fragile and hard to maintain |

**Key insight:** This is a text replacement problem, not an architecture problem. The correct solution is the simplest one: replace the characters in the source files.

---

## Common Pitfalls

### Pitfall 1: Partial Fix (Only smart_entity.py)

**What goes wrong:** Developer fixes only the file named in the reported error. Other files with emoji print statements crash on subsequent boots depending on import order.

**Why it happens:** Error message names the specific file at crash time, which varies by import order.

**How to avoid:** Always scan the entire workspace before declaring done. Run the grep verification after the fix.

**Warning signs:** Fixed smart_entity.py but haven't run grep on the full workspace.

### Pitfall 2: PYTHONUTF8=1 as the Primary Fix

**What goes wrong:** Added to `synapse_start.bat`, works when running via start script, crashes when user runs `python main.py` directly or imports from IDE.

**Why it happens:** Environment variable only applies to processes launched through the script.

**How to avoid:** Fix at source. The env var is additive, not the solution.

**Warning signs:** The fix is in a shell script file, not in any Python source file.

### Pitfall 3: Fixing print() but Missing logging.* Calls

**What goes wrong:** All `print(f"✅ ...")` calls are fixed but `log.info("✅ ...")` and `logging.warning("⚠️ ...")` calls are left. These also crash.

**Why it happens:** Developer scans for `print(` but not `log.`, `logger.`, `logging.`.

**How to avoid:** The replacement approach should operate on all non-ASCII characters in the file, not just in `print()` calls. Replacing the emoji character itself in the source is simpler than trying to identify call contexts.

**Warning signs:** Grep still returns hits after fix in lines containing `log.` or `logger.`.

### Pitfall 4: Missing Compound Emoji (⚠️ = U+26A0 + U+FE0F)

**What goes wrong:** Developer replaces the codepoint U+26A0 (warning sign ⚠) but not the variation selector U+FE0F that follows it. The scan still returns a hit.

**Why it happens:** Emoji with variation selectors are two characters, but appear as one glyph. String replacement of just `"\u26a0"` leaves the variation selector behind.

**How to avoid:** Replace `"⚠️"` (the full emoji + variation selector) as a string literal in Python source. Python's string handling treats it as a sequence and the `replace()` call handles both characters.

**Warning signs:** Post-fix grep still hits the same line.

### Pitfall 5: Not Testing Boot (import) Specifically

**What goes wrong:** Developer runs pytest tests (which avoid importing api_gateway directly) and sees all tests pass. But `python -c "import workspace.sci_fi_dashboard.api_gateway"` still crashes because api_gateway has module-level print statements.

**Why it happens:** Test suite imports only specific submodules, not the full gateway.

**How to avoid:** Run the exact import command from the success criterion: `python -c "import workspace.sci_fi_dashboard.api_gateway"` on a cp1252 system.

**Warning signs:** Tests pass but manual boot test has not been performed.

---

## Code Examples

Verified patterns from actual codebase scan:

### The Canonical Before/After (smart_entity.py)
```python
# Source: workspace/sci_fi_dashboard/smart_entity.py lines 21-23

# BEFORE — crashes on Windows cp1252:
print(f"✅ Loaded {len(entities_dict)} entity groups from {self.entities_file}")
print(f"⚠️ Warning: Entities file {self.entities_file} not found. Starting empty.")

# AFTER — safe everywhere:
print(f"[OK] Loaded {len(entities_dict)} entity groups from {self.entities_file}")
print(f"[WARN] Entities file {self.entities_file} not found. Starting empty.")
```

### Box-Drawing in Logging (change_tracker.py)
```python
# Source: workspace/change_tracker.py lines 485-495

# BEFORE:
log.info("═" * 56)
log.info("🔍 CHANGE TRACKER v2.0 — Hardened Git Auto-Commit")
log.info("═" * 56)
log.info(f"📂 Watching: {WORKSPACE}")
log.info(f"🌿 Branch:   {BRANCH}")

# AFTER:
log.info("=" * 56)
log.info("[SEARCH] CHANGE TRACKER v2.0 -- Hardened Git Auto-Commit")
log.info("=" * 56)
log.info(f"[DIR] Watching: {WORKSPACE}")
log.info(f"[BRANCH] Branch:   {BRANCH}")
```

### String Dict Values (monitor.py tool label map)
```python
# Source: workspace/monitor.py lines 35-56

# BEFORE:
TOOL_LABELS = {
    "message": "✉️  SENDING MESSAGE",
    "query": "🔍 SEARCHING MEMORIES",
    "add": "📥 STORING NEW MEMORY",
}

# AFTER:
TOOL_LABELS = {
    "message": "[MSG] SENDING MESSAGE",
    "query": "[SEARCH] SEARCHING MEMORIES",
    "add": "[ADD] STORING NEW MEMORY",
}
```

### Verification Command
```bash
# Run after fix — must return zero output for ENC-02 to pass
grep -rn "[^\x00-\x7F]" workspace/ --include="*.py"

# Windows boot test — must return no UnicodeEncodeError for ENC-01 to pass
python -c "import workspace.sci_fi_dashboard.api_gateway"
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| `sys.setdefaultencoding('utf-8')` (Python 2) | `PYTHONUTF8=1` env var (Python 3) | Python 2 approach removed in Python 3; env var is the correct modern equivalent |
| Encode-at-output wrappers | Fix at source | Source fix is unconditional; wrappers depend on execution context |
| `# -*- coding: utf-8 -*-` header | Not applicable to this problem | Source encoding header affects parser, not stdout encoding |

**Important:** `PYTHONUTF8=1` is documented in Python 3.7+ as the official mechanism for forcing UTF-8 mode. It is correct and sufficient as defense-in-depth. But it does NOT substitute for fixing the source: anyone invoking Python without this environment variable still crashes.

---

## Open Questions

1. **Comments and docstrings: fix or leave?**
   - What we know: Comments in Python source do not cause UnicodeEncodeError at import time. ENC-01 only requires no crash on boot.
   - What's unclear: ENC-02 says "a workspace-wide grep for non-ASCII characters in print and log statements returns zero results" — this could be interpreted as only print/log lines, or all lines.
   - Recommendation: Fix ALL non-ASCII in ALL contexts (comments, docstrings, strings, print/log). Reasons: (1) the grep command `grep -rn "[^\x00-\x7F]" workspace/ --include="*.py"` returns hits in comments too; (2) some comment text is later used in f-strings or logging calls; (3) a clean zero-hit grep is the only unambiguous success signal. Total effort is not meaningfully greater.

2. **test_e2e.py has non-ASCII in a docstring comment (line 41: "→")**
   - What we know: The arrow → (U+2192) is in a docstring, not a print statement. It does not cause a boot crash.
   - What's unclear: Whether to fix test files or only workspace source files.
   - Recommendation: Fix it. The ENC-02 grep targets `workspace/` which includes `workspace/tests/`. Clean sweep is consistent.

3. **change_viewer.py uses Rich library for terminal output**
   - What we know: Rich handles its own encoding. `console.print()` is NOT the same as Python's built-in `print()`. Rich renders to terminal using its own codec handling.
   - What's unclear: Whether Rich's `console.print()` also crashes on cp1252 or whether it handles encoding internally.
   - Recommendation: Treat change_viewer.py's Rich calls the same as print() calls and apply replacements. If Rich handles encoding correctly, the ASCII replacements are harmless. If it doesn't, the fix is necessary.

---

## Sources

### Primary (HIGH confidence)

- Direct scan of `C:/Users/upayan.ghosh/personal/Jarvis-OSS/workspace/` — 586 hits, 51 files confirmed on 2026-02-27
- `workspace/sci_fi_dashboard/smart_entity.py` — confirmed crash site at line 21
- `.planning/research/PITFALLS.md` — Pitfall 1 (wrong layer) and Pitfall 7 (partial fix) documented
- `.planning/research/STACK.md` — Section 4 (Encoding Fix) with replacement pattern
- `.planning/codebase/CONCERNS.md` — Known Bug 1: Unicode Encoding Error on Windows Startup

### Secondary (MEDIUM confidence)

- Python 3 documentation on `PYTHONUTF8` environment variable — UTF-8 mode documented as Python 3.7+ feature
- Windows cmd/PowerShell default encoding is cp1252 on Windows 11 (English locale) — well-established behavior

### Tertiary (LOW confidence — not needed, risk is already fully characterised)

None — the problem and fix are completely understood from direct codebase inspection.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no libraries needed; grep and Python stdlib are the tools
- Architecture: HIGH — 51 files confirmed, replacement map derived from actual scan hits
- Pitfalls: HIGH — all pitfalls documented from real codebase analysis and PITFALLS.md
- Scope: HIGH — 586 total hits, 252 in runtime statements; exact file list captured

**Research date:** 2026-02-27
**Valid until:** Stable — encoding behavior in Python is not changing. Valid indefinitely.
