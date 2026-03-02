---
phase: 04-whatsapp-baileys-bridge
plan: 02
subsystem: infra
tags: [baileys, whatsapp, nodejs, express, websocket, bridge, microservice]

# Dependency graph
requires:
  - phase: 03-channel-abstraction-layer
    provides: "ChannelRegistry + BaseChannel contract — WhatsApp slot reserved as StubChannel; Phase 4 replaces it"
provides:
  - "baileys-bridge/index.js: ~293-line CommonJS Express + Baileys WhatsApp WebSocket microservice"
  - "baileys-bridge/package.json: @whiskeysockets/baileys@6.7.21 pinned + write-file-atomic, node-cache, pino, qrcode-terminal, express"
  - "baileys-bridge/.gitignore: auth credentials and node_modules excluded; package-lock.json committed"
affects:
  - 04-whatsapp-baileys-bridge
  - 05-telegram-channel
  - onboarding

# Tech tracking
tech-stack:
  added:
    - "@whiskeysockets/baileys@6.7.21 (exact pin, CommonJS stable)"
    - "express@^4.18.3 — HTTP server for bridge REST endpoints"
    - "node-cache@^5.1.2 — in-memory group metadata cache (anti-spam)"
    - "write-file-atomic@^5.0.1 — atomic auth state file writes (crash safety)"
    - "qrcode-terminal@^0.12.0 — QR code terminal output for onboarding"
    - "pino@^8.21.0 — structured logger; silences noisy Baileys debug output"
  patterns:
    - "CJS bridge: no 'type: module' — baileys@6.7.21 is CommonJS; ESM not used"
    - "Built-in Node 18+ fetch() — no node-fetch npm dependency needed"
    - "Module-state socket: sock/qrData/connectionState are module-level vars; Express server never restarts, only socket"
    - "Anti-spam jitter: 1000 + Math.random()*2000 ms delay before each POST /send"
    - "DisconnectReason guard: loggedOut (401) + forbidden (403) set logged_out state, no auto-reconnect"
    - "Atomic auth backup: writeFileAtomic for creds.json + fs.cpSync auth_state/ to auth_state.bak/ on each creds.update"

key-files:
  created:
    - "baileys-bridge/index.js"
    - "baileys-bridge/package.json"
    - "baileys-bridge/.gitignore"
  modified:
    - ".gitignore (root) — added !baileys-bridge/package.json and !baileys-bridge/package-lock.json exceptions"

key-decisions:
  - "baileys@6.7.21 pinned exactly (not ^) — Baileys API surface changes between patch releases; pin + package-lock.json ensures reproducible installs"
  - "No 'type: module' in package.json — baileys@6.7.21 is CommonJS; adding it would break all require() calls"
  - "Built-in global fetch() used instead of node-fetch npm — Node 18+ has stable built-in fetch; WA-08 validates >=18 so no fallback needed"
  - "printQRInTerminal: false in makeWASocket — QR served via GET /qr for programmatic access; qrcode-terminal still prints for terminal convenience"
  - "DisconnectReason.forbidden (403) treated same as loggedOut (401) — both indicate forced session invalidation; auto-reconnect on either risks account suspension"
  - "auth_state.bak/ rolling backup on every creds.update — guard against SIGKILL mid-write leaving auth_state/ in corrupt partial state"

patterns-established:
  - "Bridge REST schema: GET /qr, POST /send (jid+text), POST /typing (jid), POST /seen (jid+messageId+fromMe+participant), GET /health"
  - "Payload schema: {channel_id:'whatsapp', user_id, chat_id, text, message_id, is_group, timestamp, raw}"
  - "PYTHON_WEBHOOK_URL env var (default: http://127.0.0.1:8000/channels/whatsapp/webhook) — inbound webhook target"
  - "BRIDGE_PORT env var (default: 5010) — bridge HTTP listen port"

requirements-completed: [WA-01, WA-03, WA-04, WA-05, WA-07]

# Metrics
duration: 3min
completed: 2026-03-02
---

# Phase 4 Plan 2: Baileys Bridge Summary

**~293-line CommonJS Express microservice wrapping @whiskeysockets/baileys@6.7.21 with atomic auth writes, group metadata caching, and REST endpoints for Python channel integration**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-02T16:29:28Z
- **Completed:** 2026-03-02T16:32:42Z
- **Tasks:** 3
- **Files modified:** 4 (3 new files + root .gitignore exception)

## Accomplishments
- baileys-bridge/index.js: full CommonJS Express + Baileys bridge with all 5 REST endpoints (WA-03/07), atomic auth writes (WA-04), cachedGroupMetadata anti-spam (WA-05), and DisconnectReason.loggedOut guard
- baileys-bridge/package.json: @whiskeysockets/baileys@6.7.21 exactly pinned with all required dependencies; no "type": "module" field
- baileys-bridge/.gitignore: auth_state/ and node_modules/ excluded; package-lock.json intentionally not excluded (reproducible installs)
- Root .gitignore updated with exceptions for baileys-bridge JSON files (blocking issue resolved)

## Task Commits

Each task was committed atomically:

1. **Task 1: package.json with pinned dependencies** - `37e50ba` (chore)
2. **Task 2: index.js Express + Baileys microservice** - `7163b36` (feat)
3. **Task 3: .gitignore for baileys-bridge** - `7b4d465` (chore)

## Files Created/Modified
- `baileys-bridge/index.js` — 293-line CommonJS Express server + Baileys socket: GET /qr, POST /send (anti-spam jitter), POST /typing, POST /seen, GET /health; forwardToFastAPI via built-in fetch; atomicSaveCreds; cachedGroupMetadata with node-cache; DisconnectReason guard
- `baileys-bridge/package.json` — Node.js project manifest, @whiskeysockets/baileys@6.7.21 exactly pinned, no "type": "module"
- `baileys-bridge/.gitignore` — node_modules/ and auth_state/ excluded; package-lock.json NOT excluded (must be committed)
- `.gitignore` (root) — added !baileys-bridge/package.json and !baileys-bridge/package-lock.json exceptions

## Decisions Made
- Pinned `@whiskeysockets/baileys` to exactly `6.7.21` (not semver range) — Baileys API changes between patch releases; exact pin + committed package-lock.json ensures reproducible installs for self-hosters
- No `"type": "module"` — baileys@6.7.21 is CommonJS; adding this field would break all `require()` calls; ESM migration deferred to v7 stable
- Used Node 18+ built-in `global fetch()` — no `node-fetch` npm dependency; WA-08 validates Node >= 18 so built-in is always available
- `printQRInTerminal: false` — QR is served programmatically via GET /qr; `qrcode-terminal` still prints to terminal as a convenience for direct terminal users

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added baileys-bridge/*.json exceptions to root .gitignore**
- **Found during:** Task 1 (package.json commit)
- **Issue:** Root `.gitignore` has a broad `*.json` rule that blocked `git add baileys-bridge/package.json` with "The following paths are ignored by one of your .gitignore files"
- **Fix:** Added `!baileys-bridge/package.json` and `!baileys-bridge/package-lock.json` exception lines to root `.gitignore` after the existing `*.json` rule
- **Files modified:** `.gitignore`
- **Verification:** `git check-ignore -v` no longer flags baileys-bridge/package.json; `git add` succeeded
- **Committed in:** `37e50ba` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** The root .gitignore exception is essential — without it the plan's output files cannot be committed. No scope creep.

## Issues Encountered
- Root `*.json` gitignore rule is very broad; it also blocks other potential JSON files in new subdirectories. Deferred a full gitignore cleanup to avoid scope creep — only the baileys-bridge exceptions were added.

## User Setup Required
None — no external service configuration required for the bridge files themselves. Users run `npm install` in `baileys-bridge/` during onboarding (covered by the onboarding scripts in Phase 4).

## Next Phase Readiness
- baileys-bridge/index.js ready for `npm install && node index.js`
- Plan 04-03: WhatsAppChannel Python class (BaseChannel subclass) — subprocess supervisor, httpx send client, health_check integration
- WA-01, WA-03, WA-04, WA-05, WA-07 requirements satisfied by this plan; WA-02, WA-06, WA-08 will be satisfied by Plan 04-03

---
*Phase: 04-whatsapp-baileys-bridge*
*Completed: 2026-03-02*
