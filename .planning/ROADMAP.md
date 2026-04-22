# Roadmap: Synapse-OSS

## Milestones

- [x] **v1.0 OSS Independence** - Phases 0-9 (shipped 2026-03-03)
- [x] **v2.0 The Adaptive Core** - Phases 0-5 (shipped 2026-04-08)
- [ ] **v3.0 OpenClaw Feature Harvest** - Phases 6-11 (96% — Phase 11 Realtime Voice Streaming carrying over)
- [ ] **v3.1 Reliability + OpenClaw Supervisor Patterns** - Phases 12-18 (current)

---

<details>
<summary>v1.0 OSS Independence (Phases 0-9) — SHIPPED 2026-03-03</summary>

All channels live, hybrid RAG memory, SBS 8-layer profiling, Dual Cognition Engine, proactive outreach.
38 plans, 10 phases, 100% complete. See `.planning/phases/` for archive.

</details>

<details>
<summary>v2.0 The Adaptive Core (Phases 0-5) — SHIPPED 2026-04-08</summary>

Skills-as-directories, safe self-modification + rollback, subagent system, onboarding wizard v2, browser tool, embedding refactor (Qdrant -> LanceDB), Ollama made optional, Docker removed.

### Phase 0: Session & Context Persistence
**Goal**: Every WhatsApp conversation maintains history across messages.
**Plans**: 5/5

### Phase 1: Skill Architecture
**Goal**: Any capability lives in a skill directory, not the core codebase.
**Plans**: 5/5

### Phase 2: Safe Self-Modification + Rollback
**Goal**: Synapse can modify its own Zone 2 architecture — every change is consented, snapshotted, reversible.
**Plans**: 5/6 (02-06 integration tests pending)

### Phase 3: Subagent System
**Goal**: Main conversation can delegate to isolated async sub-agents without blocking the parent.
**Plans**: 4/4

### Phase 4: Onboarding Wizard v2
**Goal**: Fresh install reaches personalized baseline in under 5 minutes.
**Plans**: 4/4

### Phase 5: Browser Tool
**Goal**: Synapse can access live web content, summarize it, and inject it into context as a skill.
**Plans**: 4/4

</details>

<details>
<summary>v3.0 OpenClaw Feature Harvest (Phases 6-11) — 96% complete, Phase 11 carryover</summary>

Port high-value design patterns from the OpenClaw TypeScript codebase into Synapse-OSS Python. 10+ bundled skills, expanded provider routing, TTS voice output, image generation, cron with isolated agents, real-time web control panel, realtime voice streaming.

### Phase 6: LLM Provider Expansion (Complete 2026-04-09)
### Phase 7: Bundled Skills Library (In Progress — 1/3)
### Phase 8: TTS Voice Output (Complete 2026-04-09)
### Phase 9: Image Generation (Complete 2026-04-09)
### Phase 10: Cron Wiring + Web Control Panel (Complete 2026-04-09)
### Phase 11: Realtime Voice Streaming (In Progress — 1/3, carryover to v3.1 period but tracked as v3.0)

See `.planning/phases/` for full detail. Phase 11 remains a v3.0 phase and does NOT count toward v3.1 progress.

</details>

---

## v3.1 Reliability + OpenClaw Supervisor Patterns (Current)

**Milestone Goal:** Fix Synapse's WhatsApp unresponsiveness and dead proactive-outreach code, then port OpenClaw's battle-tested supervisor/reliability patterns (watchdog, echo tracker, heartbeat, structured logging, multi-account, configurable reconnect) into the Python stack. Derived from a direct comparative analysis of OpenClaw (TypeScript, in-process Baileys) vs Synapse-OSS (Python + Node bridge).

**Scope discipline:** Seven phases (12-18), 44 REQ-IDs across 11 categories. Small surgical fixes ship first; architectural refactors last. Every OpenClaw pattern port cites its TypeScript source file in the phase goal so planners can find the reference implementation.

**Carryover note:** Phase 11 (Realtime Voice Streaming) is 96% done but remains a v3.0 phase. It is NOT part of v3.1 progress accounting.

### Dependency Graph

```
Phase 12 (P0 Bug Fixes)
   -> Phase 13 (Structured Observability)
         -> Phase 14 (Supervisor + Watchdog + Echo Tracker)
               -> Phase 15 (Auth Persistence + Baileys 7.x)
                     -> Phase 16 (Heartbeat + Bridge Hardening)
                           -> Phase 17 (Pipeline Decomposition + Inbound Gate)
                                 -> Phase 18 (Multi-Account WhatsApp)
```

**Ordering rationale:**
1. **P0 bugs first** — WA-FIX + PROA are one-line / small surgical fixes with huge user-visible impact. Decoupled from every downstream phase so the user gets a responsive WhatsApp bot ASAP.
2. **OBS before SUPV** — watchdog state transitions are invisible without structured logs + runId correlation. Ship logging first so every downstream reliability feature is observable by default.
3. **AUTH bundled with BAIL** — both live in the bridge surface and share regression risk; Baileys 7.x has breaking changes in `useMultiFileAuthState` so atomic creds-queue lands in the same phase that validates the new API.
4. **BRIDGE + HEART share emitter infra** — bridge `/health` polling and heartbeat ping-emission are both event-emitting subsystems; they share SUPV hooks and OBS structured-log plumbing.
5. **PIPE after WA-FIX-05** — WA-FIX-05 (duplicate skill-routing block removal) establishes a known-good baseline for chat_pipeline.py before the module split begins. ACL-03 rides along because it changes inbound ordering.
6. **MULT last** — multi-account needs per-authDir creds-queue isolation from AUTH (Phase 15), per-account healthState from SUPV (Phase 14), and per-account log-correlation from OBS (Phase 13). Ships only after everything it depends on is stable.

## Phases

- [ ] **Phase 12: P0 Bug Fixes (Ship-Blocking)** - Restore WhatsApp reply reliability and wake dead proactive outreach (9 REQs, smallest diff possible)
- [ ] **Phase 13: Structured Observability** - runId correlation, PII-redacted JSON logs, per-module log levels (4 REQs, foundation for everything downstream)
- [ ] **Phase 14: Supervisor + Watchdog + Echo Tracker** - 30-min-silence watchdog, configurable reconnect policy, healthState enum, self-echo suppression (6 REQs)
- [ ] **Phase 15: Auth Persistence + Baileys 7.x** - Per-authDir atomic creds queue, backup restore, upgrade to Baileys 7.x with pairing/media/group validation (7 REQs)
- [ ] **Phase 16: Heartbeat + Bridge Hardening** - Configurable heartbeat recipients, `/health` endpoint, 3-strike subprocess restart, webhook idempotency (9 REQs)
- [ ] **Phase 17: Pipeline Decomposition + Inbound Gate** - Split chat_pipeline.py into normalize/debounce/access/enrich/route/reply modules; ACL gate pre-FloodGate (5 REQs)
- [ ] **Phase 18: Multi-Account WhatsApp** - Multiple WA accounts per instance with independent authDirs, allowlists, and media limits (4 REQs)

## Phase Details

### Phase 12: P0 Bug Fixes (Ship-Blocking)
**Goal**: Restore Synapse's WhatsApp responsiveness by fixing four smoking-gun bugs in `routes/whatsapp.py`, `chat_pipeline.py`, and `pipeline_helpers.py`; and wire `ProactiveAwarenessEngine.maybe_reach_out()` into the live gateway so 8h+ silence triggers a real outbound send. Smallest possible diff — no architectural work, no module splits.
**Depends on**: Nothing (first v3.1 phase; all fixes are local surgical edits)
**Requirements**: WA-FIX-01, WA-FIX-02, WA-FIX-03, WA-FIX-04, WA-FIX-05, PROA-01, PROA-02, PROA-03, PROA-04
**Success Criteria** (what must be TRUE):
  1. User sends a WhatsApp message after a bridge reconnect and receives a reply — the retry queue has flushed because `update_connection_state()` was awaited at `routes/whatsapp.py:147`, confirmed by a gateway log line showing the awaited coroutine completing
  2. Force-killing the Baileys bridge and restarting it resolves with code 515 (restart-after-pairing) triggering a bridge re-open — the bot continues replying without manual restart
  3. `GET /channels/whatsapp/status` surfaces `isLoggedOut: true` within 10 seconds of the bridge reporting a logged-out event — the flag is no longer silently dropped
  4. A single inbound WhatsApp message produces exactly one skill-routing log entry (not two) — the duplicate skill-routing block at `chat_pipeline.py:546-586` is gone and state mutations fire once per message
  5. A conversation that goes silent for 8+ hours outside the configured sleep window receives a proactive check-in message via `channel_registry.get("whatsapp").send()` — confirmed by a pipeline SSE event `proactive.sent` visible in the dashboard, with thermal guard (CPU < 20% AND plugged in) honored
**Plans**: TBD

### Phase 13: Structured Observability
**Goal**: Port OpenClaw's `getChildLogger({module, runId})` + `redactIdentifier()` pattern into Synapse so every log line for a given message carries the same correlation ID from receipt through outbound send, phone numbers and JIDs are redacted via a single helper, logs are structured JSON/key=value, and log levels are configurable per module via `synapse.json`. Foundation for every downstream reliability feature — watchdog state transitions, heartbeat emissions, and bridge health polls are all invisible without this.
**Depends on**: Phase 12 (works on a stable baseline where the P0 bugs are fixed — otherwise logs instrument broken code paths)
**Requirements**: OBS-01, OBS-02, OBS-03, OBS-04
**Success Criteria** (what must be TRUE):
  1. A single inbound WhatsApp message produces a sequence of log lines (flood -> dedup -> queue -> pipeline -> traffic-cop -> LLM -> channel.send) all sharing the same `runId` — confirmed by `jq 'select(.runId == "<id>")'` filtering the JSON log to exactly one conversation
  2. No raw phone number or full JID appears in any log file — `redact_identifier("1234567890@s.whatsapp.net")` returns a stable-hash form like `wa:1234****@s` used everywhere, confirmed by `grep -E '[0-9]{10}@'` returning zero matches in fresh logs
  3. Every log line is structured (parseable via `json.loads()` or a single regex) with at minimum `module / runId / level / chat_id_redacted` fields — confirmed by a parser-based smoke test
  4. Setting `logging.modules.llm: "DEBUG"` and `logging.modules.channel: "WARNING"` in synapse.json makes LLM logs verbose while channel logs go quiet — confirmed by message-count assertions on a sample trace
**Plans**: 7 plans
Plans:
- [ ] 13-00-PLAN.md — Wave 0: create failing test scaffolds for every OBS-* requirement + conftest run_id reset fixture + flip 13-VALIDATION.md nyquist flag
- [ ] 13-01-PLAN.md — Wave 1: implement `redact_identifier()` HMAC-SHA256 helper + `observability/` package bootstrap (OBS-02)
- [ ] 13-02-PLAN.md — Wave 1: ContextVar + `mint/set/get_run_id()` + `get_child_logger()` LoggerAdapter + `JsonFormatter` (ensure_ascii) + RunIdFilter + sensitive-field auto-redaction (OBS-01, OBS-03)
- [ ] 13-03-PLAN.md — Wave 2: thread runId through WhatsApp route -> FloodGate -> Dedup -> Queue -> Worker -> channel.send; add `run_id` field to MessageTask; fix PII leaks at channels/whatsapp.py:571 and worker:~128 (OBS-01, OBS-02)
- [x] 13-04-PLAN.md — Wave 2: fix `pipeline_emitter.start_run()` singleton race via ContextVar backfeed; migrate `persona_chat` + `llm_router` to `get_child_logger()`; fix `[MAIL] Inbound` PII leak (OBS-01, OBS-02, OBS-03)
- [ ] 13-05-PLAN.md — Wave 2: add `logging` field to SynapseConfig; implement `apply_logging_config()` with per-module levels, third-party taming, and idempotent `_OWNED_MARKER` re-apply; wire into `lifespan()`; extend `synapse.json.example` (OBS-04)
- [ ] 13-06-PLAN.md — Wave 3: E2E smoke test (fake WhatsApp -> one runId, zero raw digits, structured JSON only, per-module toggle works) + conftest fixtures + standalone 13-MANUAL-VALIDATION.md for the 3 checks pytest cannot reproduce

### Phase 14: Supervisor + Watchdog + Echo Tracker
**Goal**: Port OpenClaw's watchdog pattern (`extensions/whatsapp/src/auto-reply/monitor.ts:283-338`), reconnect policy (`extensions/whatsapp/src/reconnect.ts` `DEFAULT_RECONNECT_POLICY`), and outbound echo tracker (`extensions/whatsapp/src/inbound/monitor.ts` `rememberRecentOutboundMessage`) into Synapse so dead-but-connected sockets are force-reconnected, reconnect backoff is configurable, non-retryable close codes stop the loop cleanly, and bot replies can no longer trigger their own pipeline via self-echo.
**Depends on**: Phase 13 (watchdog state transitions, reconnect decisions, and echo-drop events must emit structured logs with runId — otherwise operator has no way to diagnose what the supervisor did)
**Requirements**: SUPV-01, SUPV-02, SUPV-03, SUPV-04, ACL-01, ACL-02
**Success Criteria** (what must be TRUE):
  1. Simulating 30+ minutes of zero inbound traffic on a connected WhatsApp bridge triggers a force-reconnect — confirmed by a `supv.watchdog.fired` log entry and the bridge socket being re-opened without manual intervention
  2. Editing `synapse.json -> reconnect.initialMs`, `maxMs`, `factor`, `jitter`, `maxAttempts` changes the observed backoff curve on a simulated disconnect — confirmed by timing successive reconnect attempts and asserting they match the configured policy within jitter tolerance
  3. `GET /channels/whatsapp/status` returns one of `connected / logged-out / conflict / reconnecting / stopped` for `healthState` at all times — including during a live reconnect loop where the field transitions `connected -> reconnecting -> connected`
  4. A WhatsApp 440 (conflict) or logged-out close code stops the reconnect loop and surfaces an operator-facing message — `healthState` transitions to `conflict` or `logged-out` and reconnect attempts cease until operator intervention
  5. The bot sends a reply that echoes back via WhatsApp's own inbound feed — the echo is dropped with a `reason: self-echo` log entry and the pipeline is never invoked, confirmed by asserting the outbound tracker matched the inbound text within its N-message window
**Plans**: 3 plans
Plans:
- [ ] 14-01-PLAN.md — Wave 0: failing test stubs for SUPV-01..04 (test_supervisor_watchdog.py) + ACL-01..02 (test_echo_tracker.py) + conftest reset_run_id fixture + flip 14-VALIDATION.md nyquist_compliant: true
- [ ] 14-02-PLAN.md — Wave 1: supervisor.py module (WhatsAppSupervisor + ReconnectPolicy + state machine) + ReconnectPolicy wiring in synapse_config.py + synapse.json.example + wire into WhatsAppChannel (replace MAX_RESTARTS loop, add healthState, drive update_connection_state through supervisor) (SUPV-01, SUPV-02, SUPV-03, SUPV-04)
- [ ] 14-03-PLAN.md — Wave 2: gateway/echo_tracker.py (OutboundTracker ring buffer, sha256[:16] fingerprint, 20-msg window, 60s TTL) + wire record() into WhatsAppChannel.send() on 200 OK + wire is_echo() check into unified_webhook before dedup (ACL-01, ACL-02)

### Phase 15: Auth Persistence + Baileys 7.x
**Goal**: Port OpenClaw's per-authDir `enqueueSaveCreds` atomic queue and `maybeRestoreCredsFromBackup` logic (`extensions/whatsapp/src/session.ts:37-95`) into the Node bridge, then upgrade Baileys from `^6.7.21` to the latest stable 7.x. Bundled together because both changes live in the bridge + auth surface, share regression risk, and Baileys 7.x has breaking changes in `useMultiFileAuthState` and `sendMessage` media shapes that the atomic creds queue must be validated against.
**Depends on**: Phase 13 (creds-save failures and backup-restore events must emit structured logs so a corrupt-creds recovery is observable), Phase 14 (reconnect policy and healthState enum must handle the new 7.x close-code surface)
**Requirements**: AUTH-V31-01, AUTH-V31-02, AUTH-V31-03, BAIL-01, BAIL-02, BAIL-03, BAIL-04
**Success Criteria** (what must be TRUE):
  1. Issuing 10 concurrent `saveCreds()` calls on the same authDir writes them in serial order via the per-authDir queue — `creds.json` parses as valid JSON at every intermediate state, confirmed by a concurrent-write stress test + JSON-parse assertion loop
  2. Corrupting `creds.json` on disk and restarting the bridge triggers a fallback to the most recent valid backup — the bridge re-connects without a re-pair flow, confirmed by asserting no new QR code is emitted during the simulated corruption recovery
  3. `package.json` shows Baileys at the latest stable 7.x tag — QR pairing + multi-device login succeed end-to-end against a fresh phone, confirmed by a manual pairing smoke test
  4. Sending an image, audio (voice note OGG Opus), document (PDF), and voice recording through WhatsApp all succeed on 7.x — the new `sendMessage` media shape is correctly used, confirmed by five media-send smoke tests each asserting a delivered receipt
  5. Group metadata fetch returns `{id, subject, participants, ...}` and an inbound message in a group is correctly routed by `self-JID + chat-JID` on 7.x — confirmed by a group smoke test asserting both metadata structure and a round-trip reply
**Plans**: 7 plans
Plans:
- [ ] 15-00-PLAN.md — Wave 0: Node `node:test` harness + lib/ module skeletons + tmp-authDir + corrupt-creds fixtures + OGG Opus test fixture + RED test stubs for every REQ + 15-MANUAL-VALIDATION.md scaffold (all REQs)
- [ ] 15-01-PLAN.md — Wave 1: Port OpenClaw `enqueueSaveCreds` per-authDir Promise-chain queue + `safeSaveCreds` with JSON-parse-before-backup guard + chmod 600 to `baileys-bridge/lib/creds_queue.js` (AUTH-V31-01, AUTH-V31-03)
- [ ] 15-02-PLAN.md — Wave 1: Port OpenClaw `maybeRestoreCredsFromBackup` + `readCredsJsonRaw` size guard to `baileys-bridge/lib/restore.js` (AUTH-V31-02)
- [ ] 15-03-PLAN.md — Wave 2: Replace `atomicSaveCredsWrapper` in `index.js` with `enqueueSaveCreds` wiring; call `maybeRestoreCredsFromBackup` before `useMultiFileAuthState`; remove legacy `auth_state.bak/` dir-copy; rename legacy bak dir to `.legacy/` (AUTH-V31-01..03)
- [ ] 15-04-PLAN.md — Wave 3: Pin `@whiskeysockets/baileys@7.0.0-rc.9` (exact); bump `engines.node` to `>=20.0.0`; ESM decision (empirical test); Node-version runtime guard in `index.js` + `synapse_start.sh/.bat`; update `HOW_TO_RUN.md` + `DEPENDENCIES.md`; manual QR pairing checkpoint (BAIL-01, BAIL-02)
- [ ] 15-05-PLAN.md — Wave 4: Update `extractPayload` to emit `user_id_alt` from `participantAlt`/`remoteJidAlt`; enrich `GET /groups/:jid` with `ownerPn`; fill `test_group_metadata_shape` integration test; LID-mapping compat (BAIL-04)
- [ ] 15-06-PLAN.md — Wave 5: Extract `buildSendPayload()` pure helper to `lib/send_payload.js` (7.x AnyMediaMessageContent parity); refactor `/send` + `/send-voice` to call helper; operator sign-off on BAIL-02 + BAIL-03 5-row media matrix + BAIL-04 group round-trip (BAIL-02, BAIL-03, BAIL-04)

### Phase 16: Heartbeat + Bridge Hardening
**Goal**: Port OpenClaw's heartbeat-runner (`extensions/whatsapp/src/auto-reply/heartbeat-runner.ts`: `runWebHeartbeatOnce`, `resolveWhatsAppHeartbeatRecipients`, `HEARTBEAT_TOKEN` opt-out) and add a Python gateway <-> Node bridge health-polling contract: bridge exposes `/health`, gateway polls every 30s, N consecutive failures (default 3) restart the subprocess, webhooks are idempotent via `messageId` deduplication. Both features share the same emitter infrastructure from Phase 13 and both act on failure using supervisor hooks from Phase 14.
**Depends on**: Phase 13 (heartbeat emission events and health-poll results must carry `runId`), Phase 14 (bridge restart uses the same supervisor + reconnect policy; `healthState` reflects bridge-poll failures), Phase 15 (Baileys 7.x is stable and the atomic creds queue survives restarts)
**Requirements**: HEART-01, HEART-02, HEART-03, HEART-04, HEART-05, BRIDGE-01, BRIDGE-02, BRIDGE-03, BRIDGE-04
**Success Criteria** (what must be TRUE):
  1. User configures `heartbeat.recipients: ["919000000000@s.whatsapp.net"]` and `heartbeat.prompt: "Health check"` in synapse.json — scheduled heartbeats send the prompt to each recipient and the recipient's reply is visible in logs (with PII redaction), confirmed by asserting exactly N send-events and N response-events per heartbeat cycle
  2. A recipient reply containing the `HEARTBEAT_TOKEN` substring is stripped/suppressed and never surfaces as a visible response — `showOk: false, showAlerts: false, useIndicator: true` flags behave independently per heartbeat definition, confirmed by three variant smoke tests
  3. The Node bridge responds to `GET /health` with `{status, last_inbound_at, last_outbound_at, uptime_ms, bridge_version}` — the Python gateway polls this every 30s and the result is visible at `GET /channels/whatsapp/status.bridge_health`
  4. Three consecutive bridge `/health` failures (configurable via `bridge.healthFailuresBeforeRestart`) trigger a `WhatsAppChannel` subprocess restart — confirmed by a simulated-bridge-hang test where the gateway kills and respawns the subprocess after 3 x 30s = 90s and `healthState` reflects the transition
  5. The bridge webhook receives the same `messageId` twice within 300s — the second POST returns `{accepted: true, reason: "duplicate"}` and the message is not re-processed, confirmed by a duplicate-webhook replay test
  6. A heartbeat failure (e.g., recipient unreachable, timeout) emits a warning event and the next heartbeat fires on schedule — the gateway never crashes on a heartbeat error, confirmed by a fault-injection test asserting gateway uptime through 10 consecutive simulated heartbeat failures
**Plans**: TBD

### Phase 17: Pipeline Decomposition + Inbound Gate
**Goal**: Split the monolithic `chat_pipeline.py` (post-WA-FIX-05 cleanup) into six phase modules — `normalize.py`, `debounce.py`, `access.py`, `enrich.py`, `route.py`, `reply.py` — each with a single-purpose function and explicit typed inputs/outputs; `persona_chat()` becomes an orchestrator threading a shared context object through phases. In the same phase, move the DmPolicy access-control gate to run before FloodGate (inbound gating, not only pipeline-side) so bad senders never consume batching or dedup budget. Largest refactor in the milestone — ships last before multi-account because PIPE-04 requires existing tests pass unchanged.
**Depends on**: Phase 12 (WA-FIX-05 duplicate-skill-routing fix must have landed so the decomposition starts from a known-good baseline), Phase 13 (each phase module emits structured logs with runId for cross-module correlation), Phase 16 (stable bridge + supervisor contract so pipeline tests don't flake on bridge restarts)
**Requirements**: PIPE-01, PIPE-02, PIPE-03, PIPE-04, ACL-03
**Success Criteria** (what must be TRUE):
  1. `workspace/sci_fi_dashboard/pipeline/` contains six modules (`normalize.py`, `debounce.py`, `access.py`, `enrich.py`, `route.py`, `reply.py`) — each module exports exactly one public function with typed Pydantic or dataclass input + output, confirmed by inspecting module boundaries and a type-coverage smoke check
  2. `persona_chat()` in `api_gateway.py` is an orchestrator ~50-80 lines that constructs a `PipelineContext` dataclass and threads it through the six phase functions in order — no phase reaches "backward" into orchestrator state
  3. Running the full existing test suite (`cd workspace && pytest tests/ -v`) passes with zero test modifications after the split — confirmed by a clean `pytest` exit code 0 and equal test count pre/post refactor
  4. A message from a sender blocked by `DmPolicy = allowlist` is rejected at the inbound gate before FloodGate queues it — confirmed by asserting zero FloodGate `enqueue` events and zero dedup-cache entries for the blocked sender across a 100-message stress test
  5. Access-control rejection emits a structured log line `module: access, reason: dm-policy, sender: <redacted>, runId: <id>` and never invokes any downstream phase — confirmed by log filtering + downstream-phase-entry assertion
**Plans**: TBD

### Phase 18: Multi-Account WhatsApp
**Goal**: Port OpenClaw's multi-account pattern (`extensions/whatsapp/src/accounts.ts` + `account-config.ts`) so one Synapse instance can run multiple WhatsApp accounts in parallel: each with its own authDir under `~/.synapse/wa_auth/{accountId}/`, independent `allowFrom` / `groupPolicy` / `mediaMaxMb` policies, and inbound routing keyed on self-JID -> accountId. Ships last because it depends on every prior piece of infrastructure: per-authDir atomic creds queue (Phase 15), per-account healthState (Phase 14), per-account structured logs (Phase 13), stable bridge contract (Phase 16), and the clean phase modules that receive account context (Phase 17).
**Depends on**: Phase 15 (per-authDir atomic creds queue is a prerequisite for parallel accounts), Phase 14 (each account surfaces its own `healthState`), Phase 13 (logs carry `accountId` alongside `runId`), Phase 16 (bridge `/health` reports per-account status), Phase 17 (pipeline context threads `accountId` through phases)
**Requirements**: MULT-01, MULT-02, MULT-03, MULT-04
**Success Criteria** (what must be TRUE):
  1. `synapse.json -> channels.whatsapp.accounts` lists two accounts (e.g., `personal` and `work`) — both boot successfully at startup, each with its own authDir and each visible in `GET /channels/whatsapp/status` as a separate entry with its own `healthState`
  2. `~/.synapse/wa_auth/personal/creds.json` and `~/.synapse/wa_auth/work/creds.json` exist as fully isolated auth stores — corrupting one does not affect the other, confirmed by a per-authDir corruption + recovery smoke test
  3. Account `personal` has `allowFrom: ["9190000...@s.whatsapp.net"]` and `mediaMaxMb: 6`; account `work` has `allowFrom: ["*"]` and `mediaMaxMb: 50` — a 10 MB image sent to `personal` is rejected with `reason: media-too-large`, while the same image sent to `work` is accepted, confirmed by two variant smoke tests
  4. Inbound routing correctly selects the target account by self-JID — a message received on the `work` self-JID is processed under the `work` account context (its SBS profile, its allowlist, its media limits) and outbound replies resolve through the `work` send path, confirmed by cross-account isolation assertions on a two-account conversation trace
**Plans**: TBD

---

## Coverage Table

Every v3.1 requirement is mapped to exactly one phase. Total: 44/44 (100%).

| REQ-ID | Category | Phase |
|--------|----------|-------|
| WA-FIX-01 | WhatsApp Reliability | 12 |
| WA-FIX-02 | WhatsApp Reliability | 12 |
| WA-FIX-03 | WhatsApp Reliability | 12 |
| WA-FIX-04 | WhatsApp Reliability | 12 |
| WA-FIX-05 | WhatsApp Reliability | 12 |
| PROA-01 | Proactive Outreach | 12 |
| PROA-02 | Proactive Outreach | 12 |
| PROA-03 | Proactive Outreach | 12 |
| PROA-04 | Proactive Outreach | 12 |
| OBS-01 | Observability | 13 |
| OBS-02 | Observability | 13 |
| OBS-03 | Observability | 13 |
| OBS-04 | Observability | 13 |
| SUPV-01 | Supervisor + Watchdog | 14 |
| SUPV-02 | Supervisor + Watchdog | 14 |
| SUPV-03 | Supervisor + Watchdog | 14 |
| SUPV-04 | Supervisor + Watchdog | 14 |
| ACL-01 | Echo + Access Control | 14 |
| ACL-02 | Echo + Access Control | 14 |
| AUTH-V31-01 | Auth Persistence | 15 |
| AUTH-V31-02 | Auth Persistence | 15 |
| AUTH-V31-03 | Auth Persistence | 15 |
| BAIL-01 | Baileys Upgrade | 15 |
| BAIL-02 | Baileys Upgrade | 15 |
| BAIL-03 | Baileys Upgrade | 15 |
| BAIL-04 | Baileys Upgrade | 15 |
| HEART-01 | Heartbeat Health Pings | 16 |
| HEART-02 | Heartbeat Health Pings | 16 |
| HEART-03 | Heartbeat Health Pings | 16 |
| HEART-04 | Heartbeat Health Pings | 16 |
| HEART-05 | Heartbeat Health Pings | 16 |
| BRIDGE-01 | Bridge Hardening | 16 |
| BRIDGE-02 | Bridge Hardening | 16 |
| BRIDGE-03 | Bridge Hardening | 16 |
| BRIDGE-04 | Bridge Hardening | 16 |
| PIPE-01 | Pipeline Decomposition | 17 |
| PIPE-02 | Pipeline Decomposition | 17 |
| PIPE-03 | Pipeline Decomposition | 17 |
| PIPE-04 | Pipeline Decomposition | 17 |
| ACL-03 | Echo + Access Control | 17 |
| MULT-01 | Multi-Account WhatsApp | 18 |
| MULT-02 | Multi-Account WhatsApp | 18 |
| MULT-03 | Multi-Account WhatsApp | 18 |
| MULT-04 | Multi-Account WhatsApp | 18 |

---

## Progress

**Execution Order (v3.1):**
Phases execute in dependency order: 12 -> 13 -> 14 -> 15 -> 16 -> 17 -> 18

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 0. Session & Context Persistence | v2.0 | 5/5 | Complete | 2026-04-07 |
| 1. Skill Architecture | v2.0 | 5/5 | Complete | 2026-04-07 |
| 2. Safe Self-Modification + Rollback | v2.0 | 5/6 | In Progress | — |
| 3. Subagent System | v2.0 | 4/4 | Complete | 2026-04-07 |
| 4. Onboarding Wizard v2 | v2.0 | 4/4 | Complete | 2026-04-07 |
| 5. Browser Tool | v2.0 | 4/4 | Complete | 2026-04-07 |
| 6. LLM Provider Expansion | v3.0 | 3/3 | Complete | 2026-04-09 |
| 7. Bundled Skills Library | v3.0 | 1/3 | In Progress | — |
| 8. TTS Voice Output | v3.0 | 3/3 | Complete | 2026-04-09 |
| 9. Image Generation | v3.0 | 3/3 | Complete | 2026-04-09 |
| 10. Cron Wiring + Web Control Panel | v3.0 | 4/4 | Complete | 2026-04-09 |
| 11. Realtime Voice Streaming | v3.0 | 1/3 | In Progress | — |
| 12. P0 Bug Fixes (Ship-Blocking) | v3.1 | 0/TBD | Not started | - |
| 13. Structured Observability | v3.1 | 0/7 | Not started | - |
| 14. Supervisor + Watchdog + Echo Tracker | v3.1 | 0/3 | Not started | - |
| 15. Auth Persistence + Baileys 7.x | v3.1 | 0/7 | Not started | - |
| 16. Heartbeat + Bridge Hardening | v3.1 | 0/TBD | Not started | - |
| 17. Pipeline Decomposition + Inbound Gate | v3.1 | 0/TBD | Not started | - |
| 18. Multi-Account WhatsApp | v3.1 | 0/TBD | Not started | - |
