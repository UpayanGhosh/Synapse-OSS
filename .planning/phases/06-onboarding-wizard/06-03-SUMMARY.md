---
phase: 06-onboarding-wizard
plan: "03"
subsystem: cli
tags: [telegram, discord, slack, whatsapp, qrcode, httpx, questionary, rich, subprocess]

# Dependency graph
requires:
  - phase: 05-core-channels-telegram-discord-slack
    provides: Channel adapters (TelegramChannel, DiscordChannel, SlackChannel) whose token validation patterns are mirrored here
  - phase: 04-whatsapp-baileys-bridge
    provides: WhatsAppChannel bridge subprocess pattern and BRIDGE_PORT=5010 + /qr + /health endpoints

provides:
  - workspace/cli/channel_steps.py with 9 exported symbols (CHANNEL_LIST + 4 validate_*() + 4 setup_*())
  - validate_telegram_token() — httpx GET /bot{token}/getMe → dict or ValueError
  - validate_discord_token() — httpx GET /users/@me with Authorization-Bot prefix → dict or ValueError
  - validate_slack_tokens() — fail-fast prefix check + auth.test POST → dict or ValueError
  - run_whatsapp_qr_flow() — subprocess.Popen + QR poll + ASCII render + scan poll + finally terminate
  - setup_telegram/discord/slack/whatsapp() — interactive + non-interactive orchestration wrappers

affects:
  - 06-04 (wizard_runner.py calls all setup_*() functions)
  - future onboarding test plan (can unit-test validation functions without network calls)

# Tech tracking
tech-stack:
  added:
    - qrcode>=8.0 (was in requirements.txt; installed in this environment during execution)
    - pillow>=12.0 (pulled in as qrcode[pil] dependency)
  patterns:
    - fail-fast prefix validation before network calls (Slack xoxb-/xapp-)
    - non_interactive flag for CI/environment-variable-driven setup
    - try/finally bridge termination in run_whatsapp_qr_flow
    - lazy questionary import inside functions (testability without interactive TTY)
    - Console/Panel fallback to plain print when rich not available

key-files:
  created:
    - workspace/cli/channel_steps.py
  modified: []

key-decisions:
  - "qrcode import at module level (not lazy) — plan spec requires it as a module-level import; qrcode is in requirements.txt"
  - "run_whatsapp_qr_flow uses synchronous subprocess.Popen + httpx.get (no asyncio) — onboarding wizard is a CLI tool not an async FastAPI handler"
  - "setup_whatsapp() in non-interactive mode always returns config dict — QR cannot be automated; user pairs at runtime via dashboard"
  - "validate_discord_token Authorization header uses 'Bot ' prefix (capital B, space after) — mandatory Discord API requirement"
  - "MESSAGE_CONTENT intent instruction shown even in non-interactive mode (print, no pause) — always-required setup step"

patterns-established:
  - "Non-interactive setup_*(): env-var driven, returns None on missing, no prompts"
  - "Lazy questionary import inside setup_*() functions — allows unit tests without interactive TTY or questionary installed"
  - "fail-fast validate_slack_tokens: prefix check first (no network), then auth.test — network call only when prefix is valid"
  - "try/finally bridge termination in run_whatsapp_qr_flow — bridge always terminated even on timeout or exception"

requirements-completed: [ONB-04, ONB-05, ONB-06]

# Metrics
duration: 3min
completed: 2026-03-02
---

# Phase 06 Plan 03: Channel Steps Summary

**Per-channel credential validation and QR pairing module for the onboarding wizard — Telegram getMe, Discord users/@me with Bot-prefix auth, Slack xoxb-/xapp- prefix + auth.test, WhatsApp Baileys subprocess QR flow with ASCII rendering**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-02T19:53:03Z
- **Completed:** 2026-03-02T19:56:26Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- `workspace/cli/channel_steps.py` created with all 9 exported symbols matching plan spec
- Slack prefix validation is purely local (no network call) — rejects xoxb-/xapp- mismatch immediately
- WhatsApp QR flow uses the same subprocess.Popen pattern as WhatsAppChannel with Windows UTF-8 stdout fix and try/finally termination
- All setup_*() functions return None on skip or missing env vars in non-interactive mode
- Discord MESSAGE_CONTENT intent instruction displayed after successful token validation in both interactive and NI modes

## Task Commits

Each task was committed atomically:

1. **Task 1: CHANNEL_LIST and Telegram + Discord + Slack validation functions** - `7e4f6b8` (feat)
2. **Task 2: WhatsApp QR flow and setup_*() orchestration functions** - `7e4f6b8` (feat — same file, committed together)

**Plan metadata:** (docs commit — see below)

_Note: Both tasks modify the same file (workspace/cli/channel_steps.py). The complete file was written and committed atomically in a single commit covering both tasks._

## Files Created/Modified

- `workspace/cli/channel_steps.py` — Per-channel credential collection, validation functions (validate_telegram_token, validate_discord_token, validate_slack_tokens, run_whatsapp_qr_flow) and setup orchestration wrappers (setup_telegram, setup_discord, setup_slack, setup_whatsapp)

## Decisions Made

- `qrcode` imported at module level per plan spec (it's in requirements.txt; installed qrcode==8.2 + pillow==12.1.1 in this dev environment where it was missing — Rule 3 auto-fix)
- `run_whatsapp_qr_flow` is synchronous (subprocess.Popen + httpx.get) — onboarding wizard is a blocking CLI tool, no asyncio needed
- `setup_whatsapp` in non-interactive mode always returns the config dict — QR cannot be automated; user pairs at first launch
- Discord `Authorization: Bot {token}` header uses "Bot " with capital B and trailing space — mandatory Discord API requirement documented in code
- `questionary` is lazily imported inside each `setup_*()` function — keeps module importable without questionary installed (testability)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] qrcode not installed in dev environment**
- **Found during:** Task 1 (import verification)
- **Issue:** `import qrcode` raised ModuleNotFoundError — qrcode/pillow not installed in current venv
- **Fix:** Ran `pip install "qrcode[pil]"` — installs qrcode==8.2 and pillow==12.1.1. Already listed in requirements.txt so no file changes needed.
- **Files modified:** None (requirements.txt already correct)
- **Verification:** Import succeeded; CHANNEL_LIST and prefix validation assertions passed
- **Committed in:** Not a code change; environment fix only

---

**Total deviations:** 1 auto-fixed (1 blocking — missing dev dependency)
**Impact on plan:** Minimal — qrcode was already in requirements.txt; dev environment simply lacked it. No scope creep.

## Issues Encountered

None — plan executed as specified after fixing the missing qrcode dev dependency.

## User Setup Required

None - no external service configuration required for this module. Credentials are collected by the wizard at runtime.

## Next Phase Readiness

- `channel_steps.py` is ready to be imported by `wizard_runner.py` (Phase 06-04)
- All `setup_*()` functions follow identical skip-gate + validate + return-dict pattern — wizard runner can call them in a loop
- Non-interactive mode supports CI/headless environments for all channels except WhatsApp (QR by definition requires a human)

---
*Phase: 06-onboarding-wizard*
*Completed: 2026-03-02*
