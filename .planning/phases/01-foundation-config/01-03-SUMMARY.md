---
phase: "01"
plan: "03"
subsystem: "foundation-config"
tags: ["openclaw-removal", "gateway", "onboarding", "sender", "CONF-01"]
dependency_graph:
  requires: ["01-01 (SynapseConfig)", "01-02 (DB modules wired)"]
  provides: ["openclaw-free gateway boot", "openclaw-free onboarding"]
  affects: ["api_gateway.py", "sender.py", "synapse_onboard.sh", "synapse_onboard.bat"]
tech_stack:
  removed: ["openclaw CLI dependency", "OPENCLAW_GATEWAY_TOKEN global", "OPENCLAW_GATEWAY_URL global", "shutil import", "subprocess import"]
  patterns: ["SynapseConfig.load() for path resolution", "Phase-annotated TODO comments for deferred features"]
key_files:
  modified:
    - "workspace/sci_fi_dashboard/api_gateway.py"
    - "workspace/sci_fi_dashboard/gateway/sender.py"
    - "synapse_onboard.sh"
    - "synapse_onboard.bat"
decisions:
  - "whatsapp_loop_test endpoint now returns HTTP 501 with Baileys Phase 4 note rather than attempting CLI call"
  - "continue_conversation() logs Phase 4 note instead of calling send_via_cli()"
  - "validate_api_key() uses GEMINI_API_KEY for auth (was OPENCLAW_GATEWAY_TOKEN)"
metrics:
  duration: "~25 minutes"
  completed: "2026-03-02"
  tasks_completed: 3
  files_modified: 4
---

# Phase 01 Plan 03: Remove openclaw Dependency Summary

**One-liner:** Surgically removed all openclaw binary dependencies from api_gateway.py, sender.py, and both onboarding scripts, making the gateway bootable without openclaw installed (CONF-01).

---

## Changes by File

### workspace/sci_fi_dashboard/api_gateway.py

**Lines changed:** Major rewrite of ~120 lines removed, ~30 lines added.

**1a. validate_env() rewritten (lines 56-103 original)**
- Removed: `OPENCLAW_GATEWAY_TOKEN` check, `sys.exit(1)` on missing token, proxy liveness check, OpenClaw Proxy feature row
- Added: `SynapseConfig.load()` call (prints `[INFO] Synapse data root: ...`)
- Added: GEMINI_API_KEY warn-only (not fatal) so gateway boots without any key

**1b. _resolve_openclaw_cli_bin() removed (lines 105-107 original)**
- Was: `configured or shutil.which("openclaw") or "openclaw"`
- Replaced with: nothing (function deleted entirely)

**1c. send_via_cli() removed (lines 125-163 original)**
- Entire 39-line function deleted
- Replaced with: `# send_via_cli() removed — Phase 4 replaces with Baileys HTTP bridge`
- `continue_conversation()` updated to log a Phase 4 note instead of calling the removed function

**1d. WhatsAppSender instantiation fixed (line 243 original)**
- Before: `sender = WhatsAppSender(cli_command="openclaw")`
- After: `sender = WhatsAppSender()`

**1e. OPENCLAW_GATEWAY_URL / OPENCLAW_GATEWAY_TOKEN globals removed (lines 322-323 original)**
- Before: Two global variable assignments + comment about OpenClaw proxy
- After: Single `GEMINI_API_KEY` line with Phase 2 comment

**1f. call_gateway_model() simplified (lines 386-437 original)**
- Before: 52-line function with openclaw proxy branch + Gemini fallback
- After: 6-line function that always calls `call_gemini_direct()`
- Docstring updated: "Phase 2 will replace this with litellm.acompletion() routing"

**1g. Remaining OPENCLAW_GATEWAY_TOKEN references fixed**
- `validate_api_key()`: `OPENCLAW_GATEWAY_TOKEN` → `GEMINI_API_KEY`
- `_llm_arch` block: removed openclaw ternary, always uses Direct Gemini path string
- `whatsapp_loop_test` endpoint: replaced CLI subprocess block with `raise HTTPException(status_code=501, ...)`

**1h. Unused imports removed**
- `import shutil` removed (was only used by `_resolve_openclaw_cli_bin()`)
- `import subprocess` removed (was only used by `send_via_cli()` and `whatsapp_loop_test`)

**Verification result:** `grep -in "openclaw" api_gateway.py` → zero matches.

---

### workspace/sci_fi_dashboard/gateway/sender.py

**Lines changed:** 19 lines modified.

**Change 1 — __init__ default parameter**
- Before: `cli_command: str = "openclaw"`
- After: `cli_command: str = ""`

**Change 2 — Class docstring updated**
- Before: "Sends messages via OpenClaw CLI."
- After: "Sends messages via CLI subprocess. Phase 4 will replace this with a Baileys HTTP bridge client."

**Change 3 — __init__ arg docstring updated**
- Before: "Base CLI command. Could be 'openclaw' or full path like '/usr/local/bin/openclaw'"
- After: "Base CLI command for WhatsApp send. Deprecated — will be replaced by Baileys HTTP bridge in Phase 4. Pass empty string to disable CLI send path."

**Change 4 — Method docstrings updated**
- `send_text()`: "Send a text message via OpenClaw CLI." → "Send a text message via CLI subprocess."
- `send_typing()`: "if OpenClaw CLI supports it" → "if CLI supports it"
- `send_seen()`: "if CLI supports it" (minor cleanup)

**Change 5 — FileNotFoundError message updated**
- Before: "Is OpenClaw installed and in PATH?"
- After: "Phase 4 will replace CLI send with Baileys HTTP bridge."

**No ~/.openclaw/ path references found in sender.py** — step 3 skipped.

**Verification result:** `grep -in "openclaw|OPENCLAW" sender.py` → zero matches.

---

### synapse_onboard.sh

**Strategy:** Commented out all openclaw lines with `#`, preceded by `# TODO Phase X:` annotations. Replaced active log paths with `~/.synapse/logs`.

**Changes made:**

| Line range (original) | Change |
|---|---|
| 88 | `check_tool openclaw` → commented + TODO Phase 7 annotation |
| 180 (comment) | "BEFORE running openclaw" → "BEFORE running bridge setup" |
| 227-232 | `openclaw channels login` block → commented + TODO Phase 4, replaced with informational echo |
| 239-271 | Saving config to OpenClaw block → `openclaw config set allowFrom` commented (TODO Phase 4), `openclaw config set workspace` commented (TODO Phase 1), `CONFIGURED_DIR` now reads `${SYNAPSE_HOME:-$HOME/.synapse}/workspace` |
| 277-306 | Gateway token block → entire block commented (TODO Phase 2), replaced with simpler GEMINI_API_KEY check |
| 318 | `mkdir -p ~/.openclaw/logs` → `mkdir -p ~/.synapse/logs` |
| 343 | `~/.openclaw/logs/ollama.log` → `~/.synapse/logs/ollama.log` |
| 360 | `~/.openclaw/logs/gateway.log` → `~/.synapse/logs/gateway.log` |
| 369-375 | `openclaw gateway` start block → commented + TODO Phase 7/4, replaced with informational echo |
| 397-398 | `~/.openclaw/logs/gateway.log` reference in health check warning → `~/.synapse/logs/gateway.log` |
| 401-419 | openclaw gateway health check block → commented with TODO Phase 7 |
| 422-427 | `openclaw status` / `~/.openclaw/logs/` in status messages → removed / updated |

**Verification result:** `grep -v "^#|^[[:space:]]*#" synapse_onboard.sh | grep -i "openclaw"` → zero matches.

---

### synapse_onboard.bat

**Strategy:** Commented out all openclaw lines with `REM`, preceded by `REM TODO Phase X:` annotations.

**Changes made:**

| Section | Change |
|---|---|
| Step 1 Prerequisites (line 42-48) | `where openclaw` check block → commented with `REM TODO Phase 7` |
| Step 3 Link WhatsApp (line 112-118) | `openclaw channels login` block → commented with `REM TODO Phase 4`, informational echo added |
| Step 5 Configure (line 148-155) | `openclaw config set allowFrom` → commented `REM TODO Phase 4`; `openclaw config set workspace` → commented `REM TODO Phase 1` |
| Step 6 LLM access (line 162-199) | Entire `openclaw config get gateway.auth.token` block + OPENCLAW_GATEWAY_TOKEN echo lines → commented with `REM TODO Phase 2`; replaced with direct GEMINI_API_KEY check only |

**Verification result:** `grep -i "openclaw" synapse_onboard.bat | grep -v "^REM"` → zero matches.

---

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] continue_conversation() called removed send_via_cli()**
- **Found during:** Task 1
- **Issue:** After deleting `send_via_cli()`, `continue_conversation()` still called it at line 135
- **Fix:** Replaced the `send_via_cli(target, continuation)` call with a log statement noting Phase 4 will implement the send
- **Files modified:** `workspace/sci_fi_dashboard/api_gateway.py`
- **Commit:** 6ece8ec

**2. [Rule 1 - Bug] whatsapp_loop_test still called _resolve_openclaw_cli_bin()**
- **Found during:** Task 1
- **Issue:** The `/whatsapp/loop-test` endpoint still referenced the deleted `_resolve_openclaw_cli_bin()` function and used `subprocess.run()` to invoke openclaw
- **Fix:** Replaced the entire endpoint body (after target validation) with a 501 HTTPException noting Phase 4 Baileys bridge
- **Files modified:** `workspace/sci_fi_dashboard/api_gateway.py`
- **Commit:** 6ece8ec

**3. [Rule 1 - Cleanup] Residual "OpenClaw" mentions in docstrings/comments**
- **Found during:** Task 1 final grep check
- **Issue:** Two remaining matches: a docstring for `call_gemini_direct()` saying "(no OpenClaw proxy needed)" and a route docstring mentioning "local OpenClaw Node Gateway"
- **Fix:** Updated both to remove openclaw wording
- **Files modified:** `workspace/sci_fi_dashboard/api_gateway.py`
- **Commit:** 6ece8ec

**4. [Rule 1 - Cleanup] subprocess import unused after removals**
- **Found during:** Task 1 import cleanup
- **Issue:** `import subprocess` was only used by `send_via_cli()` and `whatsapp_loop_test()`, both of which were replaced
- **Fix:** Removed `import subprocess` along with `import shutil`
- **Files modified:** `workspace/sci_fi_dashboard/api_gateway.py`
- **Commit:** 6ece8ec

---

## Verification Results

| Check | Result |
|---|---|
| `grep -in "openclaw" api_gateway.py` | PASS: zero matches |
| `grep -in "openclaw" sender.py` | PASS: zero matches |
| `grep -v "^#..." synapse_onboard.sh \| grep -i openclaw` | PASS: zero active matches |
| `grep -i openclaw synapse_onboard.bat \| grep -v "^REM"` | PASS: zero active matches |
| `SynapseConfig.load()` in validate_env context | PASS: prints `[INFO] Synapse data root: C:\Users\upayan.ghosh\.synapse` |

---

## Commits

| Hash | Description |
|---|---|
| 6ece8ec | feat(01-foundation-config-03): remove openclaw from api_gateway.py |
| 841b1ca | feat(01-foundation-config-03): clear WhatsAppSender default cli_command in sender.py |
| 67384da | feat(01-foundation-config-03): comment out openclaw calls in onboard scripts |

## Self-Check: PASSED

All modified files verified present and committed. Zero openclaw references in all active code paths.
