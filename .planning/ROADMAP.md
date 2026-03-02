# Roadmap: Synapse-OSS Provider & Channel Independence

## Overview

This milestone cuts all three hard OpenClaw dependencies from Synapse-OSS: the LLM proxy gateway (port 8080), the WhatsApp bridge (openclaw CLI), and the session metrics CLI. The work progresses in strict dependency order: config foundation first (everything reads from SynapseConfig), then the LLM provider layer (litellm), then the channel abstraction skeleton, then WhatsApp via a self-managed Baileys microservice, then the three pure-Python channels (Telegram, Discord, Slack) in parallel, then the onboarding wizard that validates the full live stack, and finally session metrics and health endpoints that clean up the last remaining openclaw references. When Phase 7 completes, `grep -r openclaw workspace/` returns zero results and any user can run Synapse-OSS on any machine with zero dependency on any external binary.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation & Config** - Replace ~/.openclaw/ data root with ~/.synapse/, provide safe migration, eliminate openclaw path dependency (completed 2026-03-02)
- [x] **Phase 2: LLM Provider Layer** - Replace openclaw proxy at port 8080 with litellm.acompletion() — all 25+ providers routable without openclaw running (completed 2026-03-02)
- [x] **Phase 3: Channel Abstraction Layer** - Establish BaseChannel ABC, ChannelRegistry, and unified webhook router before any channel is implemented (completed 2026-03-02)
- [ ] **Phase 4: WhatsApp — Baileys Bridge** - Replace openclaw message send CLI with a self-managed Baileys Node.js microservice
- [ ] **Phase 5: Core Channels — Telegram, Discord, Slack** - Add the three most widely used chat platforms as native channel integrations
- [ ] **Phase 6: Onboarding Wizard** - A user with zero prior Synapse experience can run synapse onboard and have a fully configured system in one session
- [ ] **Phase 7: Session Metrics, Health & Cleanup** - Remove all remaining openclaw CLI calls; zero openclaw references in codebase

## Phase Details

### Phase 1: Foundation & Config
**Goal**: Any user can run Synapse-OSS using ~/.synapse/ as the data root, with existing ~/.openclaw/ users able to migrate all data without loss and without downtime
**Depends on**: Nothing (first phase)
**Requirements**: CONF-01, CONF-02, CONF-03, CONF-04, CONF-05, CONF-06, CONF-07
**Success Criteria** (what must be TRUE):
  1. Synapse-OSS boots and processes a message without the openclaw binary installed or running on the host
  2. `SynapseConfig.load()` reads credentials from ~/.synapse/synapse.json with env var overrides taking precedence over file values, which take precedence over defaults
  3. ~/.synapse/synapse.json has file permissions 600 after creation — confirmed with `ls -la ~/.synapse/synapse.json`
  4. Running the migration script against a real ~/.openclaw/ workspace produces an identical row count in memory.db and knowledge_graph.db in the new location, with a migration_manifest.json checksum file written, and the original data untouched
  5. The system rejects startup if SYNAPSE_HOME points to a path where synapse.json cannot be created, with a clear error message
**Key Risks**:
  - C5: shutil.move() across filesystems is non-atomic — must WAL checkpoint before copy, use staging dir + row count verify + os.rename() to final; refuse to run if port 8000 is open
  - Migration must copy the triplet .db + .db-wal + .db-shm for every SQLite database, not just .db
  - M4: do not use Python keyring — use os.open(..., 0o600) for synapse.json at creation and os.chmod on every write
**Plans**: 6 plans

Plans:
- [x] 01-01-PLAN.md — Create workspace/synapse_config.py (SynapseConfig dataclass) + test_config.py
- [x] 01-02-PLAN.md — Wire db.py, sqlite_graph.py, emotional_trajectory.py, memory_engine.py to SynapseConfig
- [x] 01-03-PLAN.md — Remove openclaw from api_gateway.py + sender.py default + comment out openclaw calls in onboard scripts
- [x] 01-04-PLAN.md — Create migration script (migrate_openclaw.py) + test_migration.py
- [x] 01-05-PLAN.md — Sweep workspace/ root + sci_fi_dashboard/ files (11 files): replace ~/.openclaw/ with SynapseConfig
- [x] 01-06-PLAN.md — Sweep workspace/scripts/ + workspace/skills/ files (19 files): replace ~/.openclaw/ with SynapseConfig

### Phase 2: LLM Provider Layer
**Goal**: All LLM calls route through litellm.acompletion() with zero calls to the openclaw proxy at port 8080 — all 25 OpenClaw providers work, existing mixture-of-agents routing logic is preserved
**Depends on**: Phase 1
**Requirements**: LLM-01, LLM-02, LLM-03, LLM-04, LLM-05, LLM-06, LLM-07, LLM-08, LLM-09, LLM-10, LLM-11, LLM-12, LLM-13, LLM-14, LLM-15, LLM-16, LLM-17, LLM-18
**Success Criteria** (what must be TRUE):
  1. A message routed to each of the five primary providers (Anthropic, OpenAI, Gemini, Groq, Ollama) returns a valid assistant-role response without the openclaw proxy running
  2. The model string mapping table in synapse.json lists every provider's litellm prefix — no model strings are hardcoded in llm_router.py or api_gateway.py
  3. Sending a message with an invalid API key produces a provider-specific error log entry and falls back to the configured fallback provider, not a 500 crash
  4. A chat-format message sent to Ollama uses the ollama_chat/ prefix and returns a response with role == "assistant" — confirmed by integration test asserting response.choices[0].message.role
  5. The existing mixture-of-agents routing (casual to Gemini Flash, code to Claude Sonnet, Vault to local Ollama) produces the correct provider selection observable in the request log
**Key Risks**:
  - C3 (critical): ollama/ routes to /api/generate; ollama_chat/ routes to /api/chat — wrong prefix silently corrupts SBS system prompt injection; build the full mapping table before touching any call site
  - C4: buffer full response before sending; track finish_reason; set fallback_continuation=False; set explicit timeout on all acompletion calls to prevent silent truncation
  - Zhipu Z.AI must use zai/ prefix NOT zhipu/ — confirmed via litellm issue tracker
  - Pin litellm to minor version in pyproject.toml; validate with litellm.get_supported_openai_params() before writing call sites
**Plans**: 4 plans

Plans:
- [x] 02-01-PLAN.md — TDD scaffold: extend SynapseConfig.model_mappings + create test_llm_router.py (RED phase) + mock_acompletion fixture
- [x] 02-02-PLAN.md — Create workspace/sci_fi_dashboard/llm_router.py (SynapseLLMRouter + build_router + _inject_provider_keys) + pin litellm in pyproject.toml
- [x] 02-03-PLAN.md — Rewrite workspace/skills/llm_router.py: replace _call_antigravity() with SynapseLLMRouter; preserve generate()/embed() interface
- [x] 02-04-PLAN.md — Rewrite api_gateway.py LLM section: replace call_gemini_direct/call_gateway_model/MODEL_* with SynapseLLMRouter.call(); turn test_no_hardcoded_models GREEN

### Phase 3: Channel Abstraction Layer
**Goal**: A single unified channel infrastructure exists that any chat platform adapter can plug into — the asyncio coroutine pattern is established so all future channels share the FastAPI event loop
**Depends on**: Phase 2
**Requirements**: CHAN-01, CHAN-02, CHAN-03, CHAN-04, CHAN-05, CHAN-06, CHAN-07
**Success Criteria** (what must be TRUE):
  1. A stub channel implementation registered with ChannelRegistry receives a test webhook POST to /channels/{channel_id}/webhook and the inbound message reaches the existing FloodGate pipeline
  2. POST /whatsapp/enqueue continues to work as a backwards-compatible shim — existing webhook configurations do not need to be changed
  3. worker.py dispatches outbound messages via ChannelRegistry.get(task.channel_id).send() with no WhatsApp-specific branching in the worker
  4. Starting two stub channels simultaneously in the FastAPI lifespan event does not produce RuntimeError: This event loop is already running — both run as asyncio tasks within the uvicorn event loop
**Key Risks**:
  - M5 (critical): discord.py client.run() and PTB application.run_polling() both call asyncio.run() and block — must establish the asyncio.create_task() coroutine pattern in THIS phase before any real channel adapter is written
  - No channel-specific if/elif branching allowed in worker.py — registry dispatch only
**Plans**: 4 plans

Plans:
- [x] 03-01-PLAN.md — Create channels/ subpackage (BaseChannel ABC, ChannelRegistry, ChannelMessage, StubChannel)
- [x] 03-02-PLAN.md — TDD scaffold: write test_channels.py covering all CHAN requirements (RED phase for 04/05/07)
- [x] 03-03-PLAN.md — Wire ChannelRegistry into api_gateway.py: unified webhook, /whatsapp/enqueue shim, channel_id in MessageTask
- [x] 03-04-PLAN.md — Generalize worker.py: dispatch outbound via ChannelRegistry.get(task.channel_id).send()

### Phase 4: WhatsApp — Baileys Bridge
**Goal**: WhatsApp inbound and outbound works end-to-end via a self-managed Baileys Node.js microservice that Synapse starts, stops, and restarts — no openclaw binary involved at any stage
**Depends on**: Phase 3
**Requirements**: WA-01, WA-02, WA-03, WA-04, WA-05, WA-06, WA-07, WA-08
**Success Criteria** (what must be TRUE):
  1. Running synapse with no openclaw installed, a WhatsApp message sent to the linked number arrives at the FastAPI pipeline and produces an LLM response delivered back to WhatsApp
  2. The Baileys bridge process is started automatically at FastAPI lifespan boot and its PID is tracked — confirmed by GET /health reporting bridge: running
  3. Killing the bridge process externally triggers the Python supervisor to restart it within 10 seconds using exponential backoff — the restart is logged and visible in health endpoint
  4. After an unclean shutdown (SIGKILL to bridge), Baileys auth state files are intact and the bridge reconnects without requiring a new QR scan
  5. A startup attempt on a host without Node.js 18+ on PATH produces a clear error message naming the missing dependency — not a cryptic subprocess failure
**Key Risks**:
  - C1 (critical): useMultiFileAuthState() writes non-atomically — must wrap auth writes with tmp file + fs.rename() in the JS layer on day one; keep rolling backup of auth_state/; detect 401 DisconnectReason as health alert not auto-reconnect
  - C2 (critical): missing cachedGroupMetadata triggers WhatsApp spam detection — enable in bridge config in initial commit, not as a follow-up; add 1-3s random delay between outbound sends; reply-only pattern, never cold-message
  - C6: use HTTP webhook for bridge-to-Python communication, not stdout pipe — eliminates pipe buffer deadlock entirely
  - Pin exact @whiskeysockets/baileys version and commit package-lock.json on day one; verify current API for useMultiFileAuthState() and cachedGroupMetadata before writing bridge JS
  - Node.js 18+ validation must happen at Python startup, not after first message attempt
**Plans**: 4 plans

Plans:
- [ ] 04-01-PLAN.md — TDD scaffold: write test_whatsapp_channel.py with 8 RED tests covering WA-01 through WA-08
- [ ] 04-02-PLAN.md — Create baileys-bridge/ Node.js project (index.js + package.json + .gitignore)
- [ ] 04-03-PLAN.md — Implement WhatsAppChannel(BaseChannel) in channels/whatsapp.py + export from __init__.py
- [ ] 04-04-PLAN.md — Wire WhatsAppChannel into api_gateway.py + extend GET /health with bridge status

### Phase 5: Core Channels — Telegram, Discord, Slack
**Goal**: Users on Telegram, Discord, and Slack can interact with Synapse using the same message pipeline as WhatsApp — each channel is independently operational and health-monitored
**Depends on**: Phase 4
**Requirements**: TEL-01, TEL-02, TEL-03, TEL-04, DIS-01, DIS-02, DIS-03, DIS-04, SLK-01, SLK-02, SLK-03, SLK-04
**Success Criteria** (what must be TRUE):
  1. A direct message to the Telegram bot produces an LLM response delivered back to the sender — bot token stored in synapse.json under channels.telegram.token
  2. A Discord DM and a server message that mentions the bot both produce responses — bot token and allowed channel IDs stored in synapse.json under channels.discord
  3. A Slack DM and an app mention in a channel both produce responses using Socket Mode (no public webhook URL required) — both xapp- and xoxb- tokens stored in synapse.json under channels.slack
  4. Starting all three channels simultaneously in the FastAPI lifespan produces no event loop conflicts — each runs as an asyncio task coroutine
  5. GET /health reports each active channel's status — a channel that fails to start due to bad credentials shows a clear per-channel error, not a generic 500
**Key Risks**:
  - M1 (Telegram): call bot.delete_webhook() before starting polling; log webhook URL info at startup to diagnose 409 Conflict
  - M2 (Discord): validate MESSAGE_CONTENT privileged intent on first message — log CRITICAL and disable adapter if content is empty; document in onboarding that the intent must be enabled in the Discord developer portal
  - M6 (Slack): require both xapp- and xoxb- tokens; validate prefix format at startup with clear error before attempting Socket Mode connection
  - All three channels are independent and can be built in parallel
**Plans**: TBD

### Phase 6: Onboarding Wizard
**Goal**: A user with zero prior Synapse experience can run synapse onboard and complete full system configuration — LLM providers validated, channels configured, data migrated if needed — in a single terminal session
**Depends on**: Phase 5
**Requirements**: ONB-01, ONB-02, ONB-03, ONB-04, ONB-05, ONB-06, ONB-07, ONB-08, ONB-09, ONB-10
**Success Criteria** (what must be TRUE):
  1. Running synapse onboard on a fresh machine (no ~/.synapse/) walks through provider selection, API key entry with masked input, live validation call, channel selection, and writes ~/.synapse/synapse.json with chmod 600 — confirmed by ls -la output shown at end of wizard
  2. For each selected LLM provider, the wizard makes a max_tokens=1 validation call and rejects the key with a clear message if it fails — the user cannot proceed to the next provider with an invalid key
  3. For WhatsApp, the wizard displays a QR code in the terminal and waits for scan confirmation before proceeding to the next step
  4. Running synapse onboard on a machine with an existing ~/.openclaw/ directory presents a migration offer — accepting it runs the migration script and confirms row counts match
  5. Running synapse onboard --non-interactive with all required env vars set completes without any interactive prompts — suitable for Docker and CI use
**Key Risks**:
  - M4: use os.open(..., 0o600) for synapse.json, never keyring — headless Linux and Docker lack D-Bus
  - m1: structure all async validation as standalone coroutines, not asyncio.run() inside typer commands — avoids event loop conflict in tests
  - m6: regex-validate API key format before making any live call; enforce 5s minimum delay between retries to avoid rate-limit hammering
  - GitHub Copilot OAuth device flow requires opening a browser and polling — must handle timeout gracefully with clear retry instructions
**Plans**: TBD

### Phase 7: Session Metrics, Health & Cleanup
**Goal**: All remaining openclaw CLI calls are removed from the codebase — session metrics come from internal SQLite, health checks call the internal health endpoint, start/stop scripts have no openclaw references
**Depends on**: Phase 6
**Requirements**: SESS-01, SESS-02, SESS-03, HLTH-01, HLTH-02, HLTH-03
**Success Criteria** (what must be TRUE):
  1. GET /api/sessions returns JSON with per-session token usage (input, output, total) matching the schema previously returned by openclaw sessions list --json — confirmed by running the old schema against the new endpoint
  2. state.py reads session data from internal SQLite without any subprocess calls — confirmed by removing the openclaw binary from PATH and verifying state.py still returns data
  3. GET /health reports status of LLM provider connectivity, each active channel, Baileys bridge subprocess, and all SQLite databases in a single response
  4. `grep -r openclaw workspace/` returns zero results — no openclaw references remain in the workspace directory
  5. synapse_start.sh and synapse_stop.sh run successfully on a machine with no openclaw installed — no commands fail due to missing binary
**Key Risks**:
  - Audit all scripts (not just Python files) for openclaw references — shell scripts, .sh files, .bat files
  - The grep zero-result criterion is the hard acceptance test for this phase; run it before marking phase complete
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & Config | 6/6 | Complete   | 2026-03-02 |
| 2. LLM Provider Layer | 4/4 | Complete    | 2026-03-02 |
| 3. Channel Abstraction Layer | 4/4 | Complete   | 2026-03-02 |
| 4. WhatsApp — Baileys Bridge | 1/4 | In Progress|  |
| 5. Core Channels — Telegram, Discord, Slack | 0/TBD | Not started | - |
| 6. Onboarding Wizard | 0/TBD | Not started | - |
| 7. Session Metrics, Health & Cleanup | 0/TBD | Not started | - |
