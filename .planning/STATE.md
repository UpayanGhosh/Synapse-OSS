---
gsd_state_version: 1.0
milestone: v3.1
milestone_name: Reliability + OpenClaw Supervisor Patterns
status: executing
stopped_at: Completed 15-02-PLAN.md
last_updated: "2026-04-23T17:46:27.301Z"
last_activity: 2026-04-23 -- Phase 16 planning complete
progress:
  total_phases: 6
  completed_phases: 5
  total_plans: 19
  completed_plans: 18
  percent: 95
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-21)

**Core value:** An AI that knows you deeply, grows with you continuously, and reaches out to you first — on your machine, under your full control.
**Current focus:** v3.1 milestone — ROADMAP.md drafted (Phases 12-18), ready to plan Phase 12

## Current Position

Phase: 12 of 18 (P0 Bug Fixes — Ship-Blocking) — v3.1 starts at 12
Plan: — (not yet planned)
Status: Ready to execute
Last activity: 2026-04-23 -- Phase 16 planning complete

Progress (v3.1): [░░░░░░░░░░] 0% (0/7 phases complete)

## Milestone Map

| Milestone | Target | Status | Description |
|-----------|--------|--------|-------------|
| v1.0 | 2026-03-03 | COMPLETE | OSS independence — all OpenClaw deps removed |
| v2.0 | 2026-04-08 | COMPLETE | The Adaptive Core — skills, self-mod, subagents, browser |
| v3.0 | 2026 | 96% (Phase 11 open) | OpenClaw Feature Harvest — providers, skills library, TTS, image gen, cron v2, dashboard; Realtime Voice carrying over |
| v3.1 | 2026 | CURRENT | Reliability + OpenClaw Supervisor Patterns — WhatsApp bug fixes + watchdog, echo tracker, heartbeat, structured logging, multi-account, Baileys 7.x. Phases 12-18 |
| v4.0 | Future | Planned | The Jarvis Threshold |

## v3.1 Phase Map (at a glance)

| Phase | Name | REQs | Scope |
|-------|------|------|-------|
| 12 | P0 Bug Fixes (Ship-Blocking) | 9 | WA-FIX-01..05 + PROA-01..04 |
| 13 | Structured Observability | 4 | OBS-01..04 |
| 14 | Supervisor + Watchdog + Echo Tracker | 6 | SUPV-01..04 + ACL-01..02 |
| 15 | Auth Persistence + Baileys 7.x | 7 | AUTH-V31-01..03 + BAIL-01..04 |
| 16 | Heartbeat + Bridge Hardening | 9 | HEART-01..05 + BRIDGE-01..04 |
| 17 | Pipeline Decomposition + Inbound Gate | 5 | PIPE-01..04 + ACL-03 |
| 18 | Multi-Account WhatsApp | 4 | MULT-01..04 |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Recent decisions affecting current work:

- v3.0 phases numbered 6-11 (continuous from v2.0 which ended at Phase 5)
- v3.1 phases numbered 12-18 (continuous from v3.0 which ended at Phase 11 — no renumber, no reset)
- Phase 11 (Realtime Voice Streaming) remains a v3.0 phase even though it is in flight during v3.1 period — NOT counted toward v3.1 progress
- Phase 10 combines CRON + DASH (9 requirements) — tightly coupled; dashboard panels require TTS/image gen SSE events from Phases 8-9
- gpt-image-1 target for Phase 9 (DALL-E 3 deprecated May 12, 2026 — time-sensitive)
- litellm budget-fallback bug (GitHub #10052) patched in Phase 6 — critical correctness dependency for all LLM-reliant phases
- BackgroundTask pattern used for all media outputs (TTS, image gen) — never inline await in persona_chat()
- Vault hemisphere isolation enforced at every cloud-API dispatch point across Phases 8-9
- [v3.1 roadmap]: Phase 12 bundles all P0 bug fixes (9 REQs) so ship-blocking work is decoupled from downstream architectural changes — user gets a responsive WhatsApp bot ASAP
- [v3.1 roadmap]: OBS (Phase 13) precedes SUPV (Phase 14) — watchdog state transitions are invisible without runId-correlated structured logs
- [v3.1 roadmap]: AUTH + BAIL bundled in Phase 15 — both live in bridge + auth surface; Baileys 7.x breaking changes in `useMultiFileAuthState` must be validated together with per-authDir atomic creds queue
- [v3.1 roadmap]: HEART + BRIDGE bundled in Phase 16 — share emitter infra from OBS (Phase 13) and supervisor hooks from Phase 14
- [v3.1 roadmap]: PIPE (Phase 17) ships AFTER WA-FIX-05 cleanup — decomposition starts from known-good baseline; ACL-03 (gate before FloodGate) rides along because it changes inbound ordering
- [v3.1 roadmap]: MULT (Phase 18) is last — depends on per-authDir creds-queue isolation (Phase 15), per-account healthState (Phase 14), per-account log-correlation (Phase 13), bridge contract (Phase 16), and pipeline context threading (Phase 17)
- [Phase 15]: Used node --test test/*.test.js glob instead of directory path — Windows requires explicit glob on Node 22 win32
- [Phase 15]: Synthetic OGG Opus fixture written via hand-crafted Node.js page builder (ffmpeg absent) — 129 bytes, valid OggS header, zero PII
- [Phase 15]: _readRaw() duplicated in creds_queue.js to avoid forward dep on Plan 02 readCredsJsonRaw — Plan 02 can optionally refactor to import from restore.js
- [Phase 15]: Gate 1 corrupt-creds detection requires inner try/catch in CommonJS synchronous port — outer catch must not swallow corrupt-creds case or restoration never runs

### Pending Todos

- Phase 2 (v2.0): 02-06-PLAN.md integration tests still pending
- Phase 7 (v3.0): 07-02, 07-03 plans pending — Bundled Skills Library 1/3 complete
- Phase 11 (v3.0): 11-02, 11-03 plans pending — Realtime Voice Streaming 1/3 complete (carryover)
- Merge develop -> main for v2.0 release

### Blockers/Concerns

None active. v3.1 scope is fully defined; ready to plan Phase 12.

## Session Continuity

Last session: 2026-04-22T18:09:15.639Z
Stopped at: Completed 15-02-PLAN.md
Resume file: None
Next step: `/gsd-plan-phase 12` to decompose Phase 12 (P0 Bug Fixes) into plans

## v3.1 Seed Findings (from comparative analysis, 2026-04-21)

**Smoking-gun Synapse bugs identified by OpenClaw comparison:**

1. `routes/whatsapp.py:147` — `wa_channel.update_connection_state(payload)` not awaited -> retry-queue never flushes, code 515 restart never fires, isLoggedOut flag never set
2. `GentleWorker` class never instantiated in production (only tests + `__main__` guard) -> `maybe_reach_out()` is dead code
3. `chat_pipeline.py` lines 472-509 and 546-586 — duplicate skill-routing block -> state mutations fire twice on skill match
4. `pipeline_helpers.py:407` vs `:519` — two different session-key builders -> SessionActorQueue can't serialize per-conversation

**OpenClaw reliability patterns to port (by source file):**

- `extensions/whatsapp/src/auto-reply/monitor.ts:283-338` — watchdog timer (30-min silence -> force reconnect) [Phase 14]
- `extensions/whatsapp/src/reconnect.ts` — `DEFAULT_RECONNECT_POLICY` with jitter + configurable maxAttempts [Phase 14]
- `extensions/whatsapp/src/session.ts:37-95` — per-authDir `enqueueSaveCreds` atomic queue + `maybeRestoreCredsFromBackup` [Phase 15]
- `extensions/whatsapp/src/inbound/monitor.ts` — `createInboundDebouncer`, `rememberRecentOutboundMessage`, `checkInboundAccessControl` [Phase 14 echo + Phase 17 gate]
- `extensions/whatsapp/src/auto-reply/heartbeat-runner.ts` — `runWebHeartbeatOnce` + `resolveWhatsAppHeartbeatRecipients` + `HEARTBEAT_TOKEN` opt-out [Phase 16]
- `extensions/whatsapp/src/accounts.ts` + `account-config.ts` — multi-account resolution pattern [Phase 18]
- Structured logging: `getChildLogger({module, runId})` + `redactIdentifier()` everywhere [Phase 13 ✅ merged]

**Version gap:** Baileys `^6.7.21` (Synapse bridge) vs `7.0.0-rc.9` (OpenClaw) — upgrade validates pairing + media + groups [Phase 15].
