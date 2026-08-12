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

- [x] **AUTH-V31-01**: WhatsApp creds are saved atomically via a per-authDir queue — no concurrent writes can corrupt `creds.json`
- [x] **AUTH-V31-02**: Corrupted `creds.json` on boot falls back to the most recent valid backup before forcing a re-pair
- [x] **AUTH-V31-03**: Backup is only written when the current `creds.json` parses as valid JSON (never clobbers a good backup with corrupt data)

### Heartbeat Health Pings

- [ ] **HEART-01**: User can configure heartbeat recipients (phone JIDs) in `synapse.json`
- [ ] **HEART-02**: Heartbeat prompt is user-configurable with a sensible default
- [ ] **HEART-03**: Responses containing `HEARTBEAT_TOKEN` are stripped or suppressed (opt-out signal)
- [ ] **HEART-04**: Visibility flags control `showOk / showAlerts / useIndicator` independently per heartbeat
- [ ] **HEART-05**: Heartbeat failures never crash the gateway — emitted as warning events and retried on schedule

### Baileys Upgrade

- [x] **BAIL-01**: `baileys-bridge/package.json` is upgraded from `^6.7.21` to the latest stable 7.x
- [x] **BAIL-02**: QR pairing + multi-device login validated end-to-end on 7.x
- [x] **BAIL-03**: Media (image / audio / document / voice) send + receive validated on 7.x
- [x] **BAIL-04**: Group metadata fetch + group message routing validated on 7.x

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
| AUTH-V31-01 | Phase 15 | Complete |
| AUTH-V31-02 | Phase 15 | Complete |
| AUTH-V31-03 | Phase 15 | Complete |
| BAIL-01 | Phase 15 | Complete |
| BAIL-02 | Phase 15 | Complete |
| BAIL-03 | Phase 15 | Complete |
| BAIL-04 | Phase 15 | Complete |
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

## v4.0 Requirements — Bioinspired Memory Architecture

**Defined:** 2026-04-08 | **Migrated to `develop`:** 2026-08-12 (from `refactor/optimize`)
**Status:** Planned — next milestone after v3.1. No v4.0 requirement is in flight.

Requirements derived from 29 research papers, 57 Q&As, 7 follow-ups.
Master spec: `memory-vault/research/architecture-spec.md`.

> **Dangling reference warning:** `memory-vault/research/architecture-spec.md` does **not** exist in
> this repository on any branch or in any commit — it is an external / uncommitted artifact. The 42
> requirements below are the authoritative in-repo definition; do not plan work that assumes the
> spec can be opened from the repo. See the v4.0 Overview in `.planning/ROADMAP.md`.

**Phase numbering note:** the source documents on `refactor/optimize` mapped these requirements to
Phases 6-11. Those numbers belong to v3.0 on `develop`, so v4.0 phases are renumbered **19-24**
(6→19, 7→20, 8→21, 9→22, 10→23, 11→24). Requirement IDs are unchanged.

### Retrieval Architecture

- [ ] **RETR-01**: Memory queries use both dense (LanceDB ANN) and sparse (SQLite FTS5 BM25) channels in parallel, returning merged results
- [ ] **RETR-02**: RRF fusion (score = Σ 1/(k + rank), k=20) replaces the hardcoded weighted-sum scoring
- [ ] **RETR-03**: MMR diversification (λ=0.5) removes near-duplicate results before reranking
- [ ] **RETR-04**: Hemisphere parameter (safe/spicy) is passed from chat pipeline to memory_engine.query() — spicy queries only search spicy memories
- [ ] **RETR-05**: Query router classifies queries as entity_lookup | semantic | temporal_range | multi-hop and extracts time hints + named entities
- [ ] **RETR-06**: Retrieval runs 4 parallel channels: dense, sparse, graph neighborhood, and Hopfield co-activation

### Memory Lifecycle

- [ ] **MEM-01**: Documents table has `strength` column (REAL, default 5.0) tracking memory strength via Ebbinghaus decay curve
- [ ] **MEM-02**: Documents table has `retrieval_count` (INTEGER) and `last_accessed` (REAL) columns for access tracking
- [ ] **MEM-03**: Retrieval count only increments when (now - last_accessed) > 1 hour (minimum reinforcement interval prevents cramming)
- [ ] **MEM-04**: Memory strength formula: `base_importance * exp(-forgetting_rate * days_since_last_access) * min(retrieval_count, 20)^0.3`
- [ ] **MEM-05**: Documents table has `emotional_state` column (TEXT) populated at write time by DualCognition sentiment analysis
- [ ] **MEM-06**: Documents table has `context_tags` column (TEXT, JSON array) with multi-label context classification [work, health, relationships, creative, financial, personal]
- [ ] **MEM-07**: Documents table has `schema_id` column (INTEGER, nullable FK) linking to consolidated schema patterns
- [ ] **MEM-08**: Schema nodes table exists with id, name, pattern_description, domain, observation_count, confidence, timestamps

### Consolidation Engine

- [ ] **CONSOL-01**: SWS gist pass clusters episodic memories by topic/entity and extracts semantic patterns when cluster size >= 8 episodes
- [ ] **CONSOL-02**: Schema-congruent memories integrate in one shot; schema-incongruent require multiple interleaved exposures
- [ ] **CONSOL-03**: Episodic memories survive consolidation — linked to schema via schema_episodes table, never replaced
- [ ] **CONSOL-04**: REM association pass finds cross-domain structural similarities and writes cross_domain_edge to KG with shares_pattern relation
- [ ] **CONSOL-05**: Causal edge promotion triggers when correlation edge has observation_count >= 5 AND distinct_context_count >= 3 with consistent direction
- [ ] **CONSOL-06**: Edges table has causal columns: is_causal, observation_count, distinct_context_count, causal_strength, exception_count
- [ ] **CONSOL-07**: Ebbinghaus decay sweep marks memories with strength < 0.1 as dormant (retrieval-suppressed, not deleted)
- [ ] **CONSOL-08**: Contradicted memories (flagged by reconsolidation) get strength *= 0.3 suppression factor
- [ ] **CONSOL-09**: Consolidation prioritizes by: emotional valence > novelty > frequency

### Associative & Contextual Memory

- [ ] **ASSOC-01**: Modern Hopfield co-activation layer returns memories that co-occur with retrieved results via softmax attention over memory matrix
- [ ] **ASSOC-02**: Hopfield matrix X only stores memories with cosine similarity < 0.95 to all existing patterns (dedup threshold)
- [ ] **ASSOC-03**: State-dependent retrieval boosts mood-congruent memories by ~25% based on current emotional state from DualCognition
- [ ] **ASSOC-04**: Sustained negative mood activates mood repair — boosts positive/achievement memories alongside congruent ones
- [ ] **ASSOC-05**: Contextual integrity filter suppresses memories whose context_tags don't overlap with current conversation context (last 5 messages)
- [ ] **ASSOC-06**: Multi-context memories must satisfy ALL overlapping context norms; user can override explicitly

### Query Intelligence

- [ ] **QUERY-01**: HyDE generates 5 hypothetical memory entries for vague/abstract queries, averages their embeddings for search
- [ ] **QUERY-02**: HyDE is skipped for entity-specific or numerical queries (raw embedding used instead)
- [ ] **QUERY-03**: Query2doc expansion available as lightweight alternative to HyDE for moderately unclear queries
- [ ] **QUERY-04**: Metamemory FOK pre-check (<5ms) estimates retrieval confidence before full search using entity_exists + doc_count heuristics
- [ ] **QUERY-05**: FOK returns confidence levels: high (entity exists + doc_count > 3), partial (doc_count > 0), none (can say "I don't think we've discussed that")

### Post-Retrieval

- [ ] **POST-01**: Reconsolidation check fires when 0.3 < tension_level < 0.8 — updates retrieved memory's emotional_tags + importance within 6-hour window
- [ ] **POST-02**: High tension (> 0.8) triggers extinction — creates NEW competing memory trace; old memory gets strength penalty
- [ ] **POST-03**: Reconsolidation threshold scales with memory strength — strong memories require higher prediction error to destabilize
- [ ] **POST-04**: Retrieval-induced forgetting applies small strength penalty to competing near-duplicates (cosine > 0.85) that were NOT returned
- [ ] **POST-05**: Retrieval-induced forgetting penalties are temporary — decay over 7 days

### Embedding Migration

- [ ] **EMBED-01**: bge-m3 replaces nomic-embed-text as the default embedding model (multilingual, 1024 dims, Matryoshka-compatible)
- [ ] **EMBED-02**: Re-embedding pipeline migrates all existing documents to bge-m3 vectors without data loss
- [ ] **EMBED-03**: Embedding cache invalidation triggers on model swap (current lru_cache has no invalidation)

### v4.0 Traceability

Which v4.0 phases cover which v4.0 requirements. Phase numbers are develop-renumbered (19-24).

| Requirement | Phase | Status |
|-------------|-------|--------|
| RETR-01 | Phase 19 | Pending |
| RETR-02 | Phase 19 | Pending |
| RETR-04 | Phase 19 | Pending |
| RETR-05 | Phase 19 | Pending |
| MEM-01 | Phase 20 | Pending |
| MEM-02 | Phase 20 | Pending |
| MEM-03 | Phase 20 | Pending |
| MEM-04 | Phase 20 | Pending |
| MEM-05 | Phase 20 | Pending |
| MEM-06 | Phase 20 | Pending |
| MEM-07 | Phase 20 | Pending |
| MEM-08 | Phase 20 | Pending |
| CONSOL-01 | Phase 21 | Pending |
| CONSOL-02 | Phase 21 | Pending |
| CONSOL-03 | Phase 21 | Pending |
| CONSOL-07 | Phase 21 | Pending |
| CONSOL-08 | Phase 21 | Pending |
| CONSOL-09 | Phase 21 | Pending |
| RETR-03 | Phase 21 | Pending |
| QUERY-04 | Phase 21 | Pending |
| QUERY-05 | Phase 21 | Pending |
| RETR-06 | Phase 22 | Pending |
| ASSOC-01 | Phase 22 | Pending |
| ASSOC-02 | Phase 22 | Pending |
| CONSOL-04 | Phase 22 | Pending |
| POST-01 | Phase 22 | Pending |
| POST-02 | Phase 22 | Pending |
| POST-03 | Phase 22 | Pending |
| POST-04 | Phase 22 | Pending |
| POST-05 | Phase 22 | Pending |
| ASSOC-03 | Phase 23 | Pending |
| ASSOC-04 | Phase 23 | Pending |
| ASSOC-05 | Phase 23 | Pending |
| ASSOC-06 | Phase 23 | Pending |
| CONSOL-05 | Phase 23 | Pending |
| CONSOL-06 | Phase 23 | Pending |
| QUERY-01 | Phase 23 | Pending |
| QUERY-02 | Phase 23 | Pending |
| QUERY-03 | Phase 23 | Pending |
| EMBED-01 | Phase 24 | Pending |
| EMBED-02 | Phase 24 | Pending |
| EMBED-03 | Phase 24 | Pending |

**v4.0 Coverage:**
- v4.0 requirements: 42 total (0 complete, 42 pending)
- Mapped to phases: 42
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
*Last updated: 2026-08-12 — v4.0 Bioinspired Memory Architecture requirements migrated from `refactor/optimize` (42 REQ-IDs mapped to renumbered phases 19-24 at 100% coverage). Previously: 2026-04-21 — v3.1 traceability added (44 REQ-IDs mapped to phases 12-18 at 100% coverage).*
