# Requirements: Synapse-OSS Provider & Channel Independence

**Defined:** 2026-03-02
**Core Value:** A user can run Synapse-OSS on any machine, connect to their messaging apps and LLM providers, and have a fully working AI assistant — with zero dependency on any external binary or bridge service.

---

## v1 Requirements

### Foundation & Configuration

- [ ] **CONF-01**: User can run Synapse-OSS without the openclaw binary installed or running
- [x] **CONF-02**: System reads provider credentials and channel configs from `~/.synapse/synapse.json`
- [x] **CONF-03**: `SYNAPSE_HOME` env var overrides the default `~/.synapse/` data root
- [x] **CONF-04**: `SynapseConfig.load()` enforces precedence: env vars > synapse.json > defaults
- [x] **CONF-05**: Credentials stored in synapse.json with `chmod 600` file permissions
- [x] **CONF-06**: Migration script moves all data from `~/.openclaw/workspace/` to `~/.synapse/workspace/` with checksums, WAL checkpoint, and rollback on failure
- [x] **CONF-07**: Existing users can migrate without data loss (memory.db, knowledge_graph.db, emotional_trajectory.db, SBS profiles)

### LLM Provider Layer

- [ ] **LLM-01**: `llm_router.py` routes all LLM calls via `litellm.acompletion()` (no openclaw proxy)
- [ ] **LLM-02**: System supports Anthropic Claude (claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5)
- [ ] **LLM-03**: System supports OpenAI GPT (gpt-4o, gpt-4o-mini, gpt-4-turbo)
- [ ] **LLM-04**: System supports Google Gemini (gemini/gemini-2.0-flash, gemini/gemini-2.0-pro)
- [ ] **LLM-05**: System supports Groq (groq/llama-3.3-70b-versatile, groq/mixtral-8x7b-32768)
- [ ] **LLM-06**: System supports Ollama local models (ollama_chat/llama3.3, etc.)
- [ ] **LLM-07**: System supports OpenRouter (openrouter/auto, openrouter/mistralai/mixtral-8x7b)
- [ ] **LLM-08**: System supports Mistral AI (mistral/mistral-large-latest)
- [ ] **LLM-09**: System supports Together AI (together_ai/meta-llama/Llama-3-70b-chat-hf)
- [ ] **LLM-10**: System supports xAI Grok (xai/grok-2-latest, xai/grok-3)
- [ ] **LLM-11**: System supports Bedrock Claude (bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0)
- [ ] **LLM-12**: System supports Chinese providers: MiniMax (minimax/abab6.5s-chat), Moonshot/Kimi (moonshot/moonshot-v1-128k), Zhipu Z.AI (zai/glm-4-plus — note: zai/ prefix, NOT zhipu/)
- [ ] **LLM-13**: System supports Volcano Engine/BytePlus (volcengine/doubao-pro-4k), Baidu Qianfan (qianfan/ERNIE-4.0)
- [ ] **LLM-14**: System supports self-hosted vLLM (openai/<model> + api_base override), HuggingFace Inference Endpoints, NVIDIA NIM
- [ ] **LLM-15**: System supports GitHub Copilot (copilot/<model> via OAuth device flow)
- [ ] **LLM-16**: Provider model string mapping table is defined in `synapse.json` — no hardcoded strings scattered across codebase
- [ ] **LLM-17**: LLM call errors (rate limits, auth failures, timeouts) are handled per-provider with appropriate retry/fallback logic
- [ ] **LLM-18**: Existing mixture-of-agents routing logic (casual → Gemini Flash, code → Claude Sonnet, etc.) continues to work via new provider layer

### Channel Abstraction Layer

- [ ] **CHAN-01**: `BaseChannel` ABC defines the interface all channel implementations must satisfy: `receive()`, `send()`, `send_typing()`, `mark_read()`, `health_check()`
- [ ] **CHAN-02**: `ChannelRegistry` singleton manages channel lifecycle: register, start, stop, restart on crash
- [ ] **CHAN-03**: All channels normalize inbound messages to a unified `ChannelMessage` dataclass (channel_id, user_id, chat_id, text, timestamp, is_group, raw)
- [ ] **CHAN-04**: Unified FastAPI router at `POST /channels/{channel_id}/webhook` replaces channel-specific endpoints
- [ ] **CHAN-05**: `POST /whatsapp/enqueue` is kept as a backwards-compatibility shim that delegates to the unified handler
- [ ] **CHAN-06**: Channel adapters use the asyncio coroutine pattern (not blocking `.run()` / `.run_polling()` calls) so all channels share the FastAPI event loop
- [ ] **CHAN-07**: `sender.py` is generalized from WhatsApp-only to route outbound messages to the correct channel via ChannelRegistry

### WhatsApp Channel (Baileys Bridge)

- [ ] **WA-01**: Synapse ships a `baileys-bridge/index.js` (~150 lines) Node.js Express microservice in the repo
- [ ] **WA-02**: FastAPI lifespan starts/stops the Baileys bridge as a managed subprocess (`asyncio.create_subprocess_exec`)
- [ ] **WA-03**: Bridge exposes HTTP endpoints: `POST /send`, `POST /typing`, `POST /seen`, `GET /health`, `GET /qr`
- [ ] **WA-04**: Bridge implements atomic writes for Baileys auth state files (prevents session corruption on unclean shutdown)
- [ ] **WA-05**: Bridge uses `cachedGroupMetadata` to avoid triggering WhatsApp rate limits on group messages
- [ ] **WA-06**: Bridge auto-restarts on crash with a Python supervisor loop (exponential backoff, max 5 retries)
- [ ] **WA-07**: QR code for WhatsApp auth is accessible via `GET /qr` and printed to the onboarding wizard terminal
- [ ] **WA-08**: Node.js 18+ on host PATH is validated at startup; clear error message if missing

### Telegram Channel

- [ ] **TEL-01**: Telegram channel uses python-telegram-bot v22+ in async Application mode (coroutine API, not `run_polling()`)
- [ ] **TEL-02**: Inbound DMs and group messages (when bot is mentioned) are handled
- [ ] **TEL-03**: Outbound text send, typing action, and message reply work correctly
- [ ] **TEL-04**: Bot token is stored in synapse.json under `channels.telegram.token`

### Discord Channel

- [ ] **DIS-01**: Discord channel uses discord.py v2.4+ with the async `on_message` event coroutine (not blocking runner)
- [ ] **DIS-02**: Inbound DMs and server messages (when bot is mentioned or in designated channels) are handled
- [ ] **DIS-03**: Outbound text send and typing indicator work correctly
- [ ] **DIS-04**: Bot token and allowed channel/server IDs stored in synapse.json under `channels.discord`

### Slack Channel

- [ ] **SLK-01**: Slack channel uses slack-bolt async with Socket Mode by default (no public URL required for self-hosters)
- [ ] **SLK-02**: Inbound DMs and app mentions in channels are handled
- [ ] **SLK-03**: Outbound text send works correctly
- [ ] **SLK-04**: Bot token and app-level token stored in synapse.json under `channels.slack`

### Onboarding Wizard

- [ ] **ONB-01**: `synapse onboard` CLI command launches an interactive setup wizard (typer + questionary + rich)
- [ ] **ONB-02**: Wizard presents all 25 supported LLM providers grouped by category; user selects one or more
- [ ] **ONB-03**: For each selected provider, wizard prompts for API key (masked input), then makes a live `max_tokens=1` validation call before accepting
- [ ] **ONB-04**: Wizard presents all supported channels; user selects which to enable
- [ ] **ONB-05**: For each enabled channel, wizard collects required credentials and validates connectivity
- [ ] **ONB-06**: For WhatsApp, wizard triggers QR code display and waits for scan confirmation
- [ ] **ONB-07**: Wizard writes completed config to `~/.synapse/synapse.json` with `chmod 600`
- [ ] **ONB-08**: Wizard detects existing `~/.openclaw/` data and offers to run migration script
- [ ] **ONB-09**: `synapse onboard --non-interactive` supports automation via env vars or flags (CI/Docker use case)
- [ ] **ONB-10**: GitHub Copilot uses OAuth device flow in the wizard (open browser → user enters code → wizard polls for token)

### Session Metrics & Health

- [ ] **SESS-01**: System tracks per-session token usage (input, output, total) in SQLite `sessions` table in `memory.db`
- [ ] **SESS-02**: `GET /api/sessions` endpoint returns JSON matching the schema previously returned by `openclaw sessions list --json`
- [ ] **SESS-03**: `state.py` reads session metrics from internal SQLite instead of shelling out to `openclaw sessions list`
- [ ] **HLTH-01**: `GET /health` reports status of: LLM provider connectivity, each active channel, Baileys bridge subprocess, SQLite databases
- [ ] **HLTH-02**: `synapse_health.sh` is updated to check internal health endpoint instead of openclaw process
- [ ] **HLTH-03**: `synapse_start.sh` / `synapse_stop.sh` no longer reference or depend on the openclaw binary

---

## v2 Requirements

### Extended Channels

- **EXT-01**: Matrix channel (nio-bot) — encrypted room support optional (requires libolm)
- **EXT-02**: IRC channel (jaraco/irc asyncio mode) — low-traffic bots only; asyncio write limitation documented
- **EXT-03**: Signal channel (signal-cli JSON-RPC + signalbot Python wrapper) — requires Java 17+, phone number registration
- **EXT-04**: Google Chat channel (google-apps-chat async SDK) — requires Google Cloud project + public webhook URL
- **EXT-05**: Mattermost channel (mattermostdriver)
- **EXT-06**: LINE channel (line-bot-sdk)
- **EXT-07**: Zalo channel
- **EXT-08**: Feishu/Lark channel
- **EXT-09**: Nostr channel
- **EXT-10**: Twitch channel

### Advanced Provider Features

- **PROV-01**: Venice AI support (openai-compat pattern + confirmed endpoint URL)
- **PROV-02**: Xiaomi MiLM support (needs endpoint URL confirmation)
- **PROV-03**: Qwen/DashScope native prefix (verify dashscope/ vs openai-compat)
- **PROV-04**: LiteLLM gateway (custom LiteLLM deployment as proxy)
- **PROV-05**: Cloudflare AI Gateway and Vercel AI Gateway prefix support

### Identity & UX

- **IDEN-01**: Cross-channel user identity unification (same person on Telegram + WhatsApp = one profile)
- **IDEN-02**: Per-channel SBS persona overrides

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| iMessage | macOS-only closed platform; incompatible with self-hosted OSS goal |
| BlueBubbles relay | Niche iOS relay; not widely used; defer indefinitely |
| Tlon/Urbit | Too niche for v1 |
| Official WhatsApp Cloud API | Requires Meta Business approval; not accessible to self-hosters |
| Voice channels | High complexity; out of scope for text assistant |
| Porting OpenClaw TypeScript code directly | Python-native implementations are cleaner; MIT allows copying but not necessary |
| E2EE Matrix (v1) | libolm system dep adds complexity; defer to v2 |
| OpenClaw backwards compatibility | Synapse must run without openclaw — no shims that require it |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CONF-01 | Phase 1: Foundation & Config | Pending |
| CONF-02 | Phase 1: Foundation & Config | Complete |
| CONF-03 | Phase 1: Foundation & Config | Complete |
| CONF-04 | Phase 1: Foundation & Config | Complete |
| CONF-05 | Phase 1: Foundation & Config | Complete |
| CONF-06 | Phase 1: Foundation & Config | Complete |
| CONF-07 | Phase 1: Foundation & Config | Complete |
| LLM-01 | Phase 2: LLM Provider Layer | Pending |
| LLM-02 | Phase 2: LLM Provider Layer | Pending |
| LLM-03 | Phase 2: LLM Provider Layer | Pending |
| LLM-04 | Phase 2: LLM Provider Layer | Pending |
| LLM-05 | Phase 2: LLM Provider Layer | Pending |
| LLM-06 | Phase 2: LLM Provider Layer | Pending |
| LLM-07 | Phase 2: LLM Provider Layer | Pending |
| LLM-08 | Phase 2: LLM Provider Layer | Pending |
| LLM-09 | Phase 2: LLM Provider Layer | Pending |
| LLM-10 | Phase 2: LLM Provider Layer | Pending |
| LLM-11 | Phase 2: LLM Provider Layer | Pending |
| LLM-12 | Phase 2: LLM Provider Layer | Pending |
| LLM-13 | Phase 2: LLM Provider Layer | Pending |
| LLM-14 | Phase 2: LLM Provider Layer | Pending |
| LLM-15 | Phase 2: LLM Provider Layer | Pending |
| LLM-16 | Phase 2: LLM Provider Layer | Pending |
| LLM-17 | Phase 2: LLM Provider Layer | Pending |
| LLM-18 | Phase 2: LLM Provider Layer | Pending |
| CHAN-01 | Phase 3: Channel Abstraction Layer | Pending |
| CHAN-02 | Phase 3: Channel Abstraction Layer | Pending |
| CHAN-03 | Phase 3: Channel Abstraction Layer | Pending |
| CHAN-04 | Phase 3: Channel Abstraction Layer | Pending |
| CHAN-05 | Phase 3: Channel Abstraction Layer | Pending |
| CHAN-06 | Phase 3: Channel Abstraction Layer | Pending |
| CHAN-07 | Phase 3: Channel Abstraction Layer | Pending |
| WA-01 | Phase 4: WhatsApp — Baileys Bridge | Pending |
| WA-02 | Phase 4: WhatsApp — Baileys Bridge | Pending |
| WA-03 | Phase 4: WhatsApp — Baileys Bridge | Pending |
| WA-04 | Phase 4: WhatsApp — Baileys Bridge | Pending |
| WA-05 | Phase 4: WhatsApp — Baileys Bridge | Pending |
| WA-06 | Phase 4: WhatsApp — Baileys Bridge | Pending |
| WA-07 | Phase 4: WhatsApp — Baileys Bridge | Pending |
| WA-08 | Phase 4: WhatsApp — Baileys Bridge | Pending |
| TEL-01 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| TEL-02 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| TEL-03 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| TEL-04 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| DIS-01 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| DIS-02 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| DIS-03 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| DIS-04 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| SLK-01 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| SLK-02 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| SLK-03 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| SLK-04 | Phase 5: Core Channels — Telegram, Discord, Slack | Pending |
| ONB-01 | Phase 6: Onboarding Wizard | Pending |
| ONB-02 | Phase 6: Onboarding Wizard | Pending |
| ONB-03 | Phase 6: Onboarding Wizard | Pending |
| ONB-04 | Phase 6: Onboarding Wizard | Pending |
| ONB-05 | Phase 6: Onboarding Wizard | Pending |
| ONB-06 | Phase 6: Onboarding Wizard | Pending |
| ONB-07 | Phase 6: Onboarding Wizard | Pending |
| ONB-08 | Phase 6: Onboarding Wizard | Pending |
| ONB-09 | Phase 6: Onboarding Wizard | Pending |
| ONB-10 | Phase 6: Onboarding Wizard | Pending |
| SESS-01 | Phase 7: Session Metrics, Health & Cleanup | Pending |
| SESS-02 | Phase 7: Session Metrics, Health & Cleanup | Pending |
| SESS-03 | Phase 7: Session Metrics, Health & Cleanup | Pending |
| HLTH-01 | Phase 7: Session Metrics, Health & Cleanup | Pending |
| HLTH-02 | Phase 7: Session Metrics, Health & Cleanup | Pending |
| HLTH-03 | Phase 7: Session Metrics, Health & Cleanup | Pending |

**Coverage:**
- v1 requirements: 71 total
- Mapped to phases: 71
- Unmapped: 0 (verified 2026-03-02)

---
*Requirements defined: 2026-03-02*
*Last updated: 2026-03-02 — traceability expanded to per-requirement rows; phase names aligned with ROADMAP.md*
