# Requirements: Synapse-OSS v2.0 — The Adaptive Core

**Defined:** 2026-04-06
**Core Value:** An AI that knows you deeply, grows with you continuously, and reaches
out to you first — on your machine, under your full control.

---

## v2.0 Requirements

Requirements for the v2.0 milestone. Maps to vision document Phases 5–9.

### Skill Architecture (Phase 5)

- [ ] **SKILL-01**: A skill is a directory containing SKILL.md (YAML metadata + instructions), an optional scripts/ subdirectory, an optional references/ subdirectory, and optional assets/
- [ ] **SKILL-02**: Skills are discovered at startup by scanning ~/.synapse/skills/ for valid SKILL.md files — no restart required to detect new skills added while running
- [ ] **SKILL-03**: Each skill's SKILL.md declares a `description` field used for routing — the router matches incoming intent to skill descriptions without hardcoded dispatch tables
- [ ] **SKILL-04**: A skill-creator skill exists at ~/.synapse/skills/skill-creator/ — it generates a new skill directory from within conversation, including SKILL.md, scripts/, and references/
- [ ] **SKILL-05**: Community skills can be installed by dropping a directory into ~/.synapse/skills/ — no package manager or pip install required
- [ ] **SKILL-06**: Skill execution is sandboxed — a failing skill does not crash the main conversation loop; errors are caught, logged, and reported to the user
- [ ] **SKILL-07**: Skill metadata (name, description, version, author) is readable via `GET /skills` endpoint

### Safe Self-Modification + Rollback (Phase 6)

- [ ] **MOD-01**: Before any Zone 2 modification, Synapse explains in plain language what it will change and why — and waits for explicit yes
- [ ] **MOD-02**: After confirmation, Synapse executes the modification and writes a timestamped snapshot to ~/.synapse/snapshots/
- [ ] **MOD-03**: On modification failure, Synapse auto-reverts to the pre-modification state and informs the user what happened
- [ ] **MOD-04**: User can roll back to a prior snapshot by date: "go back to how you were on March 15"
- [ ] **MOD-05**: User can roll back to a prior snapshot by description: "undo the last change", "you were better last week"
- [ ] **MOD-06**: Rolling back never destroys forward history — the user can roll forward again
- [ ] **MOD-07**: Zone 1 components (api_gateway.py, auth, core loop, self-modification engine, rollback) are immutable to model-initiated writes — Sentinel enforces this
- [ ] **MOD-08**: Zone 2 components are explicitly listed and writable with consent — cron, MCP integrations, model routing, memory arch, SBS profile depth, pipeline stages, AI name/personality
- [ ] **MOD-09**: `GET /snapshots` lists all snapshots with timestamps and change descriptions
- [ ] **MOD-10**: Each snapshot is self-contained and restorable in isolation — restoring snapshot N does not require all prior snapshots to be intact

### Subagent System (Phase 7)

- [ ] **AGENT-01**: The main conversation can spawn an isolated sub-agent with a task description and optional context
- [x] **AGENT-02**: Sub-agents run in isolated asyncio tasks — a crashed sub-agent does not affect the parent conversation
- [x] **AGENT-03**: Sub-agent results return to the parent conversation as a structured message
- [x] **AGENT-04**: Multiple sub-agents can run in parallel — independent tasks do not wait on each other
- [x] **AGENT-05**: Sub-agents have access to memory and tools but operate with a scoped context window — they do not receive the full parent conversation history by default
- [x] **AGENT-06**: Long-running sub-agents (> 30s) send progress updates to the parent at configurable intervals
- [ ] **AGENT-07**: `GET /agents` lists active and recently completed sub-agent tasks with status

### Onboarding Wizard v2 (Phase 8)

- [ ] **ONBOARD2-01**: `python -m synapse setup` completes full setup — model selection, API key entry, validation, persona configuration — in under 5 minutes for a fresh user
- [ ] **ONBOARD2-02**: The wizard builds an initial SBS profile via targeted questions (communication style, interests, privacy preferences) — user reaches a meaningful baseline without prior conversations
- [ ] **ONBOARD2-03**: The wizard offers WhatsApp history import during setup — python scripts/import_whatsapp.py is presented as an option, not a required step
- [ ] **ONBOARD2-04**: The wizard supports `--non-interactive` flag with env vars for headless/Docker/CI setups
- [x] **ONBOARD2-05**: After wizard completion, `python -m synapse setup --verify` confirms all configured providers and channels respond correctly

### Browser Tool (Phase 9)

- [x] **BROWSE-01**: Synapse can fetch and read web pages during a conversation when the user asks about current information
- [x] **BROWSE-02**: Web content is summarized and injected into the conversation context — raw HTML is never passed to the LLM
- [ ] **BROWSE-03**: Browser requests respect the Zone 1/Zone 2 privacy boundary — private/spicy hemisphere conversations never trigger web fetches
- [x] **BROWSE-04**: Browser tool is implemented as a skill (SKILL.md) — it can be disabled or replaced without touching the core pipeline
- [ ] **BROWSE-05**: Search results include source URLs — the user can verify provenance

---

## v3.0 Requirements (Deferred — Proactive Architecture Evolution)

To be detailed at v3.0 milestone initialization.

### Proactive Proposals
- **PROACT-01**: Synapse observes patterns and proposes architecture extensions: "You ask me to check your email every morning. Want me to just do that automatically?"
- **PROACT-02**: All proposals follow the same consent protocol as explicit user requests — explain → confirm → execute → snapshot
- **PROACT-03**: User can suppress proactive proposals per category (cron, integrations, routing changes)

### Pattern Recognition
- **PATTERN-01**: Synapse tracks recurring manual requests over a configurable window (default: 3 occurrences in 7 days)
- **PATTERN-02**: Recurring patterns trigger a proposal — not an automatic change

---

## v4.0 Requirements (Deferred — The Jarvis Threshold)

To be detailed at v4.0 milestone initialization.

- A mature instance manages parts of the user's digital life
- The AI has its own name, personality, and relationship — shaped through conversation
- Feels less like software, more like a presence
- Not superhuman intelligence — deep familiarity, persistent context, proactive capability

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Real-time multi-user sessions | Per-user architecture by design; sharing would require rearchitecting Zone 1 |
| Hosted/cloud service | Self-hosted only — user data, user machine, user control |
| Mobile native app | Web-first; mobile via existing channels (WhatsApp, Telegram) |
| Model fine-tuning | Synapse influences behavior via prompting, not weights |
| Plugin marketplace with pip packages | Skills-as-directories is simpler, safer, AI-writable without code execution |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SKILL-01 | Phase 1 | Pending |
| SKILL-02 | Phase 1 | Pending |
| SKILL-03 | Phase 1 | Pending |
| SKILL-04 | Phase 1 | Pending |
| SKILL-05 | Phase 1 | Pending |
| SKILL-06 | Phase 1 | Pending |
| SKILL-07 | Phase 1 | Pending |
| MOD-01 | Phase 2 | Pending |
| MOD-02 | Phase 2 | Pending |
| MOD-03 | Phase 2 | Pending |
| MOD-04 | Phase 2 | Pending |
| MOD-05 | Phase 2 | Pending |
| MOD-06 | Phase 2 | Pending |
| MOD-07 | Phase 2 | Pending |
| MOD-08 | Phase 2 | Pending |
| MOD-09 | Phase 2 | Pending |
| MOD-10 | Phase 2 | Pending |
| AGENT-01 | Phase 3 | Pending |
| AGENT-02 | Phase 3 | Complete |
| AGENT-03 | Phase 3 | Complete |
| AGENT-04 | Phase 3 | Complete |
| AGENT-05 | Phase 3 | Complete |
| AGENT-06 | Phase 3 | Complete |
| AGENT-07 | Phase 3 | Pending |
| ONBOARD2-01 | Phase 4 | Pending |
| ONBOARD2-02 | Phase 4 | Pending |
| ONBOARD2-03 | Phase 4 | Pending |
| ONBOARD2-04 | Phase 4 | Pending |
| ONBOARD2-05 | Phase 4 | Complete |
| BROWSE-01 | Phase 5 | Complete |
| BROWSE-02 | Phase 5 | Complete |
| BROWSE-03 | Phase 5 | Pending |
| BROWSE-04 | Phase 5 | Complete |
| BROWSE-05 | Phase 5 | Pending |

**Coverage:**
- v2.0 requirements: 34 total
- Mapped to phases: 34
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-06*
*Last updated: 2026-04-06 after v2.0 milestone initialization*
