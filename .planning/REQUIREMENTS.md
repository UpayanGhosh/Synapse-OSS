# Requirements: Synapse-OSS v3.0 — OpenClaw Feature Harvest

**Defined:** 2026-04-08
**Core Value:** An AI that knows you deeply, grows with you continuously, and reaches out to you first — on your machine, under your full control.

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

- [ ] **IMG-01**: User can request image generation ("draw me X") and receive it in chat
- [x] **IMG-02**: Traffic Cop classifies image requests as IMAGE role
- [x] **IMG-03**: gpt-image-1 (OpenAI) is default; Flux (fal.ai) is configurable alternative
- [ ] **IMG-04**: Image gen respects Vault hemisphere — blocked in spicy mode
- [ ] **IMG-05**: Generation runs as BackgroundTask with immediate text acknowledgment

### Cron & Isolated Agents

- [ ] **CRON-01**: Each cron job runs in an isolated agent context with separate memory
- [ ] **CRON-02**: CronService execute_fn is wired to persona_chat() in gateway lifespan
- [ ] **CRON-03**: Isolated agents get recent memory context injected as system prefix
- [ ] **CRON-04**: Cron jobs have configurable timeout and cleanup on failure

### Web Control Panel

- [ ] **DASH-01**: Dashboard shows real-time pipeline events via SSE
- [ ] **DASH-02**: Dashboard displays active sessions, memory stats, and model routing decisions
- [ ] **DASH-03**: User can send messages from the dashboard (existing pipeline/send endpoint)
- [ ] **DASH-04**: Dashboard is loopback-only with session token auth
- [ ] **DASH-05**: Dashboard uses vanilla JS + Tailwind (no React build step)

### Realtime Voice

- [ ] **VOICE-01**: User can have real-time voice conversations via WebSocket from dashboard
- [ ] **VOICE-02**: Silero VAD detects speech boundaries with conservative defaults
- [ ] **VOICE-03**: Groq Whisper handles streaming transcription
- [ ] **VOICE-04**: TTS response streams back as audio chunks
- [ ] **VOICE-05**: Barge-in (user interrupts AI response) cancels current TTS playback

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
| IMG-01 | Phase 9 | Pending |
| IMG-02 | Phase 9 | Complete |
| IMG-03 | Phase 9 | Complete |
| IMG-04 | Phase 9 | Pending |
| IMG-05 | Phase 9 | Pending |
| CRON-01 | Phase 10 | Pending |
| CRON-02 | Phase 10 | Pending |
| CRON-03 | Phase 10 | Pending |
| CRON-04 | Phase 10 | Pending |
| DASH-01 | Phase 10 | Pending |
| DASH-02 | Phase 10 | Pending |
| DASH-03 | Phase 10 | Pending |
| DASH-04 | Phase 10 | Pending |
| DASH-05 | Phase 10 | Pending |
| VOICE-01 | Phase 11 | Pending |
| VOICE-02 | Phase 11 | Pending |
| VOICE-03 | Phase 11 | Pending |
| VOICE-04 | Phase 11 | Pending |
| VOICE-05 | Phase 11 | Pending |

**Coverage:**
- v3.0 requirements: 32 total
- Mapped to phases: 32
- Unmapped: 0

---
*Requirements defined: 2026-04-08*
*Last updated: 2026-04-08 — traceability filled after roadmap creation*
