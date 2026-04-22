# Requirements: Synapse-OSS

**Core Value:** An AI that knows you deeply, grows with you continuously, and reaches out to you first — on your machine, under your full control.

## v3.1 Requirements — Reliability + OpenClaw Supervisor Patterns

**Defined:** 2026-04-21
Scope derived from a direct comparative analysis of Synapse-OSS against OpenClaw's TypeScript WhatsApp stack. Focus: fix the bugs that cause Synapse WhatsApp to silently stop responding, wire up dead proactive-outreach code, and port OpenClaw's supervisor/observability patterns.

### WhatsApp Reliability (P0 bug fixes)

- [ ] **WA-FIX-01**: `update_connection_state()` in `routes/whatsapp.py` is awaited so the bridge-triggered retry-queue flush runs on every reconnect
- [ ] **WA-FIX-02**: WhatsApp disconnect code 515 (restart-after-pairing) triggers a bridge restart that re-opens the socket
- [ ] **WA-FIX-03**: `isLoggedOut` state from the bridge is honored and surfaces in `/channels/whatsapp/status`
- [ ] **WA-FIX-04**: Every inbound WhatsApp message uses one canonical `build_session_key()` — `on_batch_ready()` and `process_message_pipeline()` agree
- [ ] **WA-FIX-05**: The duplicate skill-routing block in `chat_pipeline.py` is removed; skills fire exactly once per message

### Proactive Outreach (wiring dead code)

- [ ] **PROA-01**: `heavy_task_proactive_checkin` (or equivalent) runs in the live gateway — not only inside `if __name__ == "__main__"`
- [ ] **PROA-02**: `maybe_reach_out()` actually sends via `channel_registry.get(channel_id).send()` when user has been silent 8h+ outside sleep window
- [ ] **PROA-03**: Proactive check-in is thermal-guarded (CPU < 20% AND plugged in) to match `GentleWorker` spirit
- [ ] **PROA-04**: Proactive sends emit a pipeline SSE event and are visible in the dashboard

### Supervisor + Watchdog

- [ ] **SUPV-01**: A watchdog detects 30+ min of inbound silence on a connected bridge and forces reconnect (port of `auto-reply/monitor.ts:308–337`)
- [ ] **SUPV-02**: Reconnect policy is configurable in `synapse.json` (`initialMs / maxMs / factor / jitter / maxAttempts`) with documented defaults
- [ ] **SUPV-03**: `/channels/whatsapp/status` exposes a `healthState` enum: `connected / logged-out / conflict / reconnecting / stopped`
- [ ] **SUPV-04**: Non-retryable close codes (440 conflict, logged-out) stop the reconnect loop and surface an operator-facing message

### Echo + Access Control

- [ ] **ACL-01**: Outbound message tracker records the last N sent messages (text + timestamp + chat_id)
- [ ] **ACL-02**: Inbound messages matching a recent outbound (self-echo) are dropped with an explicit "self-echo" reason and not re-processed
- [ ] **ACL-03**: DmPolicy access-control gate runs before FloodGate (inbound gating, not only pipeline-side)

### Observability

- [ ] **OBS-01**: Every gateway log line for a given message carries the same `runId` correlation ID from receipt through outbound send
- [ ] **OBS-02**: Phone numbers / JIDs in logs are redacted via a single `redact_identifier()` helper (no raw numbers in logs)
- [ ] **OBS-03**: Logs are structured (JSON or key=value) with `module / runId / level / chat_id_redacted` fields
- [ ] **OBS-04**: Log level is configurable per module (`gateway / pipeline / channel / llm`) via `synapse.json`

### Auth Persistence

- [ ] **AUTH-V31-01**: WhatsApp creds are saved atomically via a per-authDir queue — no concurrent writes can corrupt `creds.json`
- [ ] **AUTH-V31-02**: Corrupted `creds.json` on boot falls back to the most recent valid backup before forcing a re-pair
- [ ] **AUTH-V31-03**: Backup is only written when the current `creds.json` parses as valid JSON (never clobbers a good backup with corrupt data)

### Heartbeat Health Pings

- [ ] **HEART-01**: User can configure heartbeat recipients (phone JIDs) in `synapse.json`
- [ ] **HEART-02**: Heartbeat prompt is user-configurable with a sensible default
- [ ] **HEART-03**: Responses containing `HEARTBEAT_TOKEN` are stripped or suppressed (opt-out signal)
- [ ] **HEART-04**: Visibility flags control `showOk / showAlerts / useIndicator` independently per heartbeat
- [ ] **HEART-05**: Heartbeat failures never crash the gateway — emitted as warning events and retried on schedule

### Baileys Upgrade

- [ ] **BAIL-01**: `baileys-bridge/package.json` is upgraded from `^6.7.21` to the latest stable 7.x
- [ ] **BAIL-02**: QR pairing + multi-device login validated end-to-end on 7.x
- [ ] **BAIL-03**: Media (image / audio / document / voice) send + receive validated on 7.x
- [ ] **BAIL-04**: Group metadata fetch + group message routing validated on 7.x

### Multi-Account WhatsApp

- [ ] **MULT-01**: User can register multiple WhatsApp accounts in `synapse.json` under `channels.whatsapp.accounts`
- [ ] **MULT-02**: Each account has its own authDir under `~/.synapse/wa_auth/{accountId}/`
- [ ] **MULT-03**: Each account supports independent `allowFrom`, `groupPolicy`, and `mediaMaxMb` limits
- [ ] **MULT-04**: Inbound routing selects the correct account per self-JID; outbound resolves via `accountId`

### Pipeline Decomposition

- [ ] **PIPE-01**: `chat_pipeline.py` is split into phase modules (`normalize.py / debounce.py / access.py / enrich.py / route.py / reply.py`)
- [ ] **PIPE-02**: Each phase module has a single-purpose function with explicit typed inputs/outputs
- [ ] **PIPE-03**: `persona_chat()` becomes an orchestrator that threads a context object through phases
- [ ] **PIPE-04**: All existing `tests/` pass without modification after the split

### Bridge Hardening

- [ ] **BRIDGE-01**: Node bridge exposes `/health` returning `{status, last_inbound_at, last_outbound_at, uptime_ms, bridge_version}`
- [ ] **BRIDGE-02**: Python gateway polls bridge `/health` every 30s and records results in `/channels/whatsapp/status`
- [ ] **BRIDGE-03**: N consecutive bridge health failures (configurable, default 3) trigger a `WhatsAppChannel` subprocess restart
- [ ] **BRIDGE-04**: Bridge webhook POSTs are idempotent — duplicate `messageId` within 300s is silently accepted with `accepted:true, reason:duplicate` (matches current behavior, but explicitly contracted)

### v3.1 Traceability

Which v3.1 phases cover which v3.1 requirements. Filled after v3.1 ROADMAP.md creation (2026-04-21).

| Requirement | Phase | Status |
|-------------|-------|--------|
| WA-FIX-01 | Phase 12 | Pending |
| WA-FIX-02 | Phase 12 | Pending |
| WA-FIX-03 | Phase 12 | Pending |
| WA-FIX-04 | Phase 12 | Pending |
| WA-FIX-05 | Phase 12 | Pending |
| PROA-01 | Phase 12 | Pending |
| PROA-02 | Phase 12 | Pending |
| PROA-03 | Phase 12 | Pending |
| PROA-04 | Phase 12 | Pending |
| OBS-01 | Phase 13 | Pending |
| OBS-02 | Phase 13 | Pending |
| OBS-03 | Phase 13 | Pending |
| OBS-04 | Phase 13 | Pending |
| SUPV-01 | Phase 14 | Pending |
| SUPV-02 | Phase 14 | Pending |
| SUPV-03 | Phase 14 | Pending |
| SUPV-04 | Phase 14 | Pending |
| ACL-01 | Phase 14 | Pending |
| ACL-02 | Phase 14 | Pending |
| AUTH-V31-01 | Phase 15 | Pending |
| AUTH-V31-02 | Phase 15 | Pending |
| AUTH-V31-03 | Phase 15 | Pending |
| BAIL-01 | Phase 15 | Pending |
| BAIL-02 | Phase 15 | Pending |
| BAIL-03 | Phase 15 | Pending |
| BAIL-04 | Phase 15 | Pending |
| HEART-01 | Phase 16 | Pending |
| HEART-02 | Phase 16 | Pending |
| HEART-03 | Phase 16 | Pending |
| HEART-04 | Phase 16 | Pending |
| HEART-05 | Phase 16 | Pending |
| BRIDGE-01 | Phase 16 | Pending |
| BRIDGE-02 | Phase 16 | Pending |
| BRIDGE-03 | Phase 16 | Pending |
| BRIDGE-04 | Phase 16 | Pending |
| PIPE-01 | Phase 17 | Pending |
| PIPE-02 | Phase 17 | Pending |
| PIPE-03 | Phase 17 | Pending |
| PIPE-04 | Phase 17 | Pending |
| ACL-03 | Phase 17 | Pending |
| MULT-01 | Phase 18 | Pending |
| MULT-02 | Phase 18 | Pending |
| MULT-03 | Phase 18 | Pending |
| MULT-04 | Phase 18 | Pending |

**v3.1 Coverage:**
- v3.1 requirements: 44 total
- Mapped to phases: 44
- Unmapped: 0
- Coverage: 100%

---

## v3.0 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### LLM Providers

- [x] **PROV-01**: User can add OpenAI, Anthropic, DeepSeek, Mistral, or Together as providers via synapse.json
- [x] **PROV-02**: User can set per-provider rate limits and budget caps in config
- [x] **PROV-03**: litellm BudgetExceededError triggers fallback chain instead of hard error
- [x] **PROV-04**: Onboarding wizard offers all 10+ providers during setup

### Bundled Skills

- [ ] **SKILL-01**: User gets 10 bundled skills at first install (weather, reminders, notes, translate, summarize, web scrape, news, image describe, timer, dictionary)
- [ ] **SKILL-02**: Bundled skills live in workspace/skills/bundled/ as SKILL.md directories
- [x] **SKILL-03**: Skills declare `cloud_safe: true/false` metadata for Vault hemisphere enforcement
- [x] **SKILL-04**: User can disable any bundled skill without affecting others

### TTS Voice Output

- [x] **TTS-01**: User receives voice replies as playable WhatsApp voice notes (OGG Opus)
- [x] **TTS-02**: edge-tts is the default TTS provider (zero API key, 400+ voices)
- [x] **TTS-03**: ElevenLabs is available as premium opt-in TTS provider
- [x] **TTS-04**: TTS runs as BackgroundTask — never blocks the chat pipeline
- [x] **TTS-05**: User can configure preferred voice in synapse.json

### Image Generation

- [x] **IMG-01**: User can request image generation ("draw me X") and receive it in chat
- [x] **IMG-02**: Traffic Cop classifies image requests as IMAGE role
- [x] **IMG-03**: gpt-image-1 (OpenAI) is default; Flux (fal.ai) is configurable alternative
- [x] **IMG-04**: Image gen respects Vault hemisphere — blocked in spicy mode
- [x] **IMG-05**: Generation runs as BackgroundTask with immediate text acknowledgment

### Cron & Isolated Agents

- [x] **CRON-01**: Each cron job runs in an isolated agent context with separate memory
- [x] **CRON-02**: CronService execute_fn is wired to persona_chat() in gateway lifespan
- [x] **CRON-03**: Isolated agents get recent memory context injected as system prefix
- [x] **CRON-04**: Cron jobs have configurable timeout and cleanup on failure

### Web Control Panel

- [x] **DASH-01**: Dashboard shows real-time pipeline events via SSE
- [x] **DASH-02**: Dashboard displays active sessions, memory stats, and model routing decisions
- [x] **DASH-03**: User can send messages from the dashboard (existing pipeline/send endpoint)
- [x] **DASH-04**: Dashboard is loopback-only with session token auth
- [x] **DASH-05**: Dashboard uses vanilla JS + Tailwind (no React build step)

### Realtime Voice

- [x] **VOICE-01**: User can have real-time voice conversations via WebSocket from dashboard
- [x] **VOICE-02**: Silero VAD detects speech boundaries with conservative defaults
- [ ] **VOICE-03**: Groq Whisper handles streaming transcription
- [x] **VOICE-04**: TTS response streams back as audio chunks
- [x] **VOICE-05**: Barge-in (user interrupts AI response) cancels current TTS playback

## Future Requirements

Deferred beyond v3.0. Tracked but not in current roadmap.

### Extended Channels

- **CHAN-01**: User can interact via Matrix/Element channel
- **CHAN-02**: User can interact via Signal channel

### Advanced Media

- **MEDIA-01**: User can request video generation
- **MEDIA-02**: User can request music generation

### Native Apps

- **APP-01**: macOS companion app with system tray
- **APP-02**: iOS companion app

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| 47 provider integrations (OpenClaw parity) | Diminishing returns — 10 providers covers 99% of users |
| 21 channel integrations (OpenClaw parity) | 5 channels (WA/TG/Discord/Slack/Stub) covers all major platforms |
| Plugin SDK / marketplace | Skill system is simpler, AI-writable, no pip install needed |
| Docker/Fly.io deployment | Zero-Docker is a core design principle |
| Native iOS/Android apps | Too much scope — mobile access via WhatsApp/Telegram channels |
| Model fine-tuning | Synapse influences behavior through prompting, not weights |
| Multi-user collaboration | Architecture is per-user by design |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROV-01 | Phase 6 | Complete |
| PROV-02 | Phase 6 | Complete |
| PROV-03 | Phase 6 | Complete |
| PROV-04 | Phase 6 | Complete |
| SKILL-01 | Phase 7 | Pending |
| SKILL-02 | Phase 7 | Pending |
| SKILL-03 | Phase 7 | Complete |
| SKILL-04 | Phase 7 | Complete |
| TTS-01 | Phase 8 | Complete |
| TTS-02 | Phase 8 | Complete |
| TTS-03 | Phase 8 | Complete |
| TTS-04 | Phase 8 | Complete |
| TTS-05 | Phase 8 | Complete |
| IMG-01 | Phase 9 | Complete |
| IMG-02 | Phase 9 | Complete |
| IMG-03 | Phase 9 | Complete |
| IMG-04 | Phase 9 | Complete |
| IMG-05 | Phase 9 | Complete |
| CRON-01 | Phase 10 | Complete |
| CRON-02 | Phase 10 | Complete |
| CRON-03 | Phase 10 | Complete |
| CRON-04 | Phase 10 | Complete |
| DASH-01 | Phase 10 | Complete |
| DASH-02 | Phase 10 | Complete |
| DASH-03 | Phase 10 | Complete |
| DASH-04 | Phase 10 | Complete |
| DASH-05 | Phase 10 | Complete |
| VOICE-01 | Phase 11 | Complete |
| VOICE-02 | Phase 11 | Complete |
| VOICE-03 | Phase 11 | Pending |
| VOICE-04 | Phase 11 | Complete |
| VOICE-05 | Phase 11 | Complete |

**Coverage:**
- v3.0 requirements: 32 total
- Mapped to phases: 32
- Unmapped: 0

---
*Requirements defined: 2026-04-08*
*Last updated: 2026-04-21 — v3.1 traceability added (44 REQ-IDs mapped to phases 12-18 at 100% coverage)*
