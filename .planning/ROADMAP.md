# Roadmap: Synapse-OSS v2.0 — The Adaptive Core

## Overview

v1.0 gave Synapse a body (model-agnostic, multi-channel, fully self-hosted). v2.0 gives
it the ability to grow. This milestone ships the five foundational capabilities that turn
Synapse from a fixed architecture into a living, extensible one: a skill system where
capability lives in directories not code, a safe self-modification engine with
user-consented rollback, a subagent system for parallel work, an improved onboarding
wizard that gets fresh users to a meaningful baseline fast, and a browser tool that
closes the knowledge cutoff gap.

Phase 2 (Safe Self-Modification) is the most architecturally sensitive. It MUST ship
with rollback — self-modification without rollback is not an option (learned from Jarvis).
Phase 1 (Skill Architecture) must ship before Phase 2 because the self-mod engine uses
skills as its output format — every modification produces a skill, not raw code.

## Milestone Context

**v1.0 (COMPLETE — 2026-03-03):** OSS independence — all OpenClaw deps removed,
all channels live, full health/sessions API. 38 plans, 10 phases, 100% complete.

**v2.0 (CURRENT):** The Adaptive Core — Phases 5–9 from the vision document.
6 phases, est. 27+ plans.

**v3.0 (FUTURE — 2027):** Proactive Architecture Evolution — Synapse observes patterns
and proposes its own extensions. Details at v3.0 milestone init.

**v4.0 (FUTURE — 2028):** The Jarvis Threshold — mature instance manages parts of
the user's digital life, has its own name and personality shaped through conversation.
Details at v4.0 milestone init.

## Phase Numbering

- Integer phases (1–5): v2.0 milestone work
- Decimal phases (N.1, N.2): Urgent insertions between planned phases
- Previous v1.0 phases archived in `.planning/phases/`

## Phases

- [ ] **Phase 0: Session & Context Persistence** — Wire the multiuser/ session infrastructure into the WhatsApp pipeline; every message builds on conversation history instead of starting fresh
- [ ] **Phase 1: Skill Architecture** — Skills-as-directories: SKILL.md format, startup discovery, description-based routing, skill-creator skill (vision Phase 5)
- [ ] **Phase 2: Safe Self-Modification + Rollback** — Full consent protocol + snapshot engine + Zone 1/Zone 2 hard enforcement + rollback by date/description (vision Phase 6)
- [ ] **Phase 3: Subagent System** — Spawn isolated async sub-agents, parallel execution, result return, progress updates (vision Phase 7)
- [x] **Phase 4: Onboarding Wizard v2** — `python -m synapse setup` under 5 min, initial SBS profile from questions, history import offer (vision Phase 8) (completed 2026-04-07)
- [ ] **Phase 5: Browser Tool** — Live web access as a skill, summarized injection, privacy-boundary enforcement (vision Phase 9)

---

## Phase Details

### Phase 0: Session & Context Persistence
**Goal**: Every WhatsApp conversation maintains history across messages. The existing
`multiuser/` session infrastructure (SessionStore, JSONL transcripts, ConversationCache,
context_assembler, compaction engine) is wired into `process_message_pipeline()` so
that `history=[]` is replaced by real conversation history loaded from disk.
**Depends on**: Nothing. The multiuser/ module is already built — this is wiring only.
**Requirements**: SESS-01 through SESS-08
**Success Criteria** (what must be TRUE):
  1. Send 10 messages in a WhatsApp conversation — message 10 references context from message 1; LLM uses it correctly
  2. Restart the server — message 11 in the same conversation continues the thread (transcript persisted to disk)
  3. Two different WhatsApp senders get separate conversation histories (dmScope=per-channel-peer)
  4. After 50 back-and-forth turns, compaction triggers automatically — conversation continues without errors
  5. `GET /sessions` returns the active sessions with turn counts and timestamps
  6. `POST /sessions/{key}/reset` clears the history — next message starts fresh
  7. `entities.json` is `{}` (OSS-safe) — EntityGate loads from KG, not from personal data file
  8. Sending `/new` in WhatsApp archives the current session and starts fresh — next message sees empty history
**Key Risks**:
  - ConversationCache in `_deps.py` must be a singleton — if instantiated per-request, cache never warms
  - `build_session_key()` needs `agent_id` (from `deps._resolve_target()`) and `channel` — must be consistent across restarts
  - Compaction calls the LLM synchronously — must be async and non-blocking to the response path
  - Token estimation uses chars/4 heuristic — Banglish is ~2 chars/token so context budget is tighter
**Plans**: 5 plans

Plans:
- [x] 00-01-PLAN.md — ConversationCache singleton in _deps.py + _LLMClientAdapter class
- [x] 00-02-PLAN.md — Wire session key + history load/save + compaction into process_message_pipeline
- [x] 00-03-PLAN.md — Rewrite routes/sessions.py: GET /sessions from SessionStore + POST reset
- [x] 00-04-PLAN.md — Tests: session key, history load/save, isolation, compaction, sessions API
- [x] 00-05-PLAN.md — /new command: archive transcript + rotate session ID + confirm reset

---

### Phase 1: Skill Architecture
**Goal**: Any capability Synapse gains lives in a skill directory, not the core codebase.
Skills are discovered at startup, routed by description, and can be created from within
conversation by the skill-creator skill itself.
**Depends on**: Nothing (first v2.0 phase). Requires refactor/optimize merged to develop.
**Requirements**: SKILL-01, SKILL-02, SKILL-03, SKILL-04, SKILL-05, SKILL-06, SKILL-07
**Success Criteria** (what must be TRUE):
  1. A new skill dropped into ~/.synapse/skills/ is discovered and routable without restarting the server — confirmed by POST /chat triggering the new skill after a hot-reload
  2. `GET /skills` returns JSON listing all loaded skills with name, description, version — no hardcoded skill list in api_gateway.py
  3. A skill that raises an unhandled exception is caught at the runner boundary — the conversation continues and the user receives a clear error message, not a 500
  4. The skill-creator skill, when triggered, produces a correctly structured skill directory with valid SKILL.md YAML in ~/.synapse/skills/<new-skill-name>/
  5. Installing a community skill by copying its directory into ~/.synapse/skills/ makes it available without pip install or code changes
**Key Risks**:
  - Hot-reload without restart requires a file-watcher (watchdog or similar) — must not race with an in-flight request that is currently executing the skill being reloaded
  - SKILL.md YAML schema must be validated at load time with clear errors — bad community skills should fail loudly at discovery, not silently at routing
  - The skill-creator skill writes to ~/.synapse/ (Zone 2) — Sentinel must approve this write path; document the approved Zone 2 write paths list
**Plans**: 5 plans

Plans:
- [ ] 01-01-PLAN.md — Define SKILL.md schema (YAML frontmatter + instructions body) + create SkillLoader class with validation
- [ ] 01-02-PLAN.md — Implement SkillRegistry: startup scan, hot-reload watcher, GET /skills endpoint
- [ ] 01-03-PLAN.md — Implement description-based SkillRouter: embed descriptions at load, cosine-match incoming intent
- [ ] 01-04-PLAN.md — Wire SkillRegistry + SkillRouter into api_gateway.py pipeline (post-traffic-cop routing step)
- [ ] 01-05-PLAN.md — Create skill-creator skill: SKILL.md template + scripts/create_skill.py + test coverage

---

### Phase 2: Safe Self-Modification + Rollback
**Goal**: Synapse can modify its own Zone 2 architecture through conversation — every
change is explained, confirmed, executed, snapshotted, and reversible. Zone 1 is
cryptographically immutable to model writes. Ships together with rollback — non-negotiable.
**Depends on**: Phase 1 (skill system is the output format for self-modification)
**Requirements**: MOD-01, MOD-02, MOD-03, MOD-04, MOD-05, MOD-06, MOD-07, MOD-08, MOD-09, MOD-10
**Success Criteria** (what must be TRUE):
  1. When a user says "remind me to take my medication at 8am every day", Synapse responds with a plain-language description of what it will build (a cron skill), waits for yes, then creates the skill and confirms success
  2. A snapshot is written to ~/.synapse/snapshots/ before every Zone 2 modification — confirmed by listing the directory before and after
  3. After a failed modification (intentionally broken test skill), Synapse auto-reverts and the conversation resumes with a description of what went wrong
  4. "Undo the last change" restores the previous snapshot and the removed capability is gone — confirmed by attempting to trigger it
  5. "Go back to how you were on [date]" restores the snapshot closest to that date — confirmed by checking which skills exist after restore
  6. `grep -r "Zone1\|IMMUTABLE" workspace/sci_fi_dashboard/sbs/sentinel/` confirms Sentinel enforces Zone 1 write rejection with a clear error
**Key Risks**:
  - CRITICAL: Phase 6 must ship with rollback — self-mod without rollback is not an option. Do not split these into separate phases.
  - Snapshot atomicity: write to a temp path then os.rename() — partial writes must never corrupt the current state
  - Zone 1 enforcement must happen at the filesystem write level (Sentinel), not just as a prompt instruction — LLMs can be manipulated
  - Cron job creation is Zone 2 but requires OS-level scheduling (schtasks on Windows, cron on Linux) — test both platforms
  - Rollback of a cron job must also remove the scheduled task from the OS, not just the skill directory
**Plans**: 6 plans (estimated)

Plans:
- [ ] 02-01-PLAN.md — Create SnapshotEngine: write/list/restore snapshot lifecycle + test_snapshot_engine.py
- [ ] 02-02-PLAN.md — Implement Zone 1/Zone 2 registry in Sentinel: IMMUTABLE_PATHS + WRITABLE_ZONES constants, enforce at write time
- [ ] 02-03-PLAN.md — Implement ConsentProtocol: explain → confirm → execute → snapshot orchestration with timeout and no-answer handling
- [ ] 02-04-PLAN.md — Wire ConsentProtocol into api_gateway.py: detect modification intents, invoke protocol before any Zone 2 write
- [ ] 02-05-PLAN.md — Implement rollback: by snapshot ID, by date string, by natural language description ("undo last", "go back to last week")
- [ ] 02-06-PLAN.md — Integration tests: full consent → execute → snapshot → rollback cycle; Zone 1 write rejection; auto-revert on failure

---

### Phase 3: Subagent System
**Goal**: The main conversation can delegate work to isolated async sub-agents that run
in parallel, report progress, and return results — without blocking the parent or
crashing it if they fail.
**Depends on**: Phase 2 (sub-agents use skills; spawning is a Zone 2 action requiring consent)
**Requirements**: AGENT-01, AGENT-02, AGENT-03, AGENT-04, AGENT-05, AGENT-06, AGENT-07
**Success Criteria** (what must be TRUE):
  1. A message "research the latest Python packaging best practices and summarize for me" spawns a sub-agent, returns immediately with "on it, I'll update you when done", and delivers results as a follow-up message
  2. Two parallel sub-agent tasks complete in total time ≈ max(task1_time, task2_time), not sum — confirmed by timing both
  3. A sub-agent that raises an unhandled exception is caught — the parent conversation continues and the user receives the error description
  4. `GET /agents` returns active and recently completed agent tasks with status, task description, start time, and duration
  5. A sub-agent running > 30s sends a "still working..." progress update to the parent at the configured interval
**Key Risks**:
  - Sub-agent memory access must be read-only by default — prevent agents from accidentally writing to the parent's memory context
  - asyncio task cancellation on sub-agent timeout must be clean — no dangling connections or partially-written memory entries
  - The result delivery path (sub-agent → parent conversation) requires a callback or queue mechanism compatible with the existing channel send architecture
**Plans**: 4 plans

Plans:
- [ ] 03-01-PLAN.md — SubAgent dataclass + AgentRegistry CRUD lifecycle + GET /agents endpoint
- [ ] 03-02-PLAN.md — SubAgentRunner: isolated asyncio execution, scoped memory snapshots, ProgressReporter callbacks
- [ ] 03-03-PLAN.md — Spawn intent keyword gate + pipeline wiring in chat_pipeline.py + result delivery via channel.send()
- [ ] 03-04-PLAN.md — Unit + integration tests: parallel timing, crash isolation, progress updates, result delivery, API endpoint

---

### Phase 4: Onboarding Wizard v2
**Goal**: A brand-new user runs `python -m synapse setup` and reaches a personalized,
meaningful baseline in under 5 minutes — with an initial SBS profile built from targeted
questions, not just blank defaults.
**Depends on**: Phase 3 (wizard can use sub-agents for parallel provider validation)
**Requirements**: ONBOARD2-01, ONBOARD2-02, ONBOARD2-03, ONBOARD2-04, ONBOARD2-05
**Success Criteria** (what must be TRUE):
  1. A fresh install (no ~/.synapse/) runs `python -m synapse setup` and completes with a working, personalized config in ≤ 5 minutes — timed on a clean machine
  2. After the wizard, the SBS profile has at least 3 non-empty layers (linguistic, emotional_state, interaction) populated from the wizard's questions — not from default placeholders
  3. The wizard's question set covers: preferred communication style, topics of interest, privacy sensitivity level, and whether to import existing chat history
  4. `python -m synapse setup --non-interactive` with all required env vars set completes without any interactive prompts — exit code 0
  5. `python -m synapse setup --verify` on an existing installation tests each configured provider and channel and reports pass/fail per item
**Key Risks**:
  - The 5-minute target includes API key validation live calls — parallel validation (Phase 3 sub-agents) needed to meet the target
  - SBS profile initialization from wizard answers must use the same profile layer schema as the live SBS engine — no parallel data formats
  - `--non-interactive` must handle partial env var sets gracefully (clear error listing what's missing, not a cryptic KeyError)
**Plans**: 4 plans

Plans:
- [ ] 04-01-PLAN.md — Setup entrypoint + SBS profile init module + persona questions in interactive wizard
- [ ] 04-02-PLAN.md — Verify subcommand: parallel provider + channel validation with pass/fail output
- [ ] 04-03-PLAN.md — Non-interactive SBS env var support + input validation
- [ ] 04-04-PLAN.md — Test coverage for all v2 wizard features (ONBOARD2-01 through ONBOARD2-05)

---

### Phase 5: Browser Tool
**Goal**: Synapse can access live web content during conversations, summarize it, and
inject it into context — implemented as a skill so it can be disabled, replaced, or
community-extended without touching the core pipeline.
**Depends on**: Phase 1 (browser tool is a skill), Phase 2 (fetching requires Zone 2 consent on first use)
**Requirements**: BROWSE-01, BROWSE-02, BROWSE-03, BROWSE-04, BROWSE-05
**Success Criteria** (what must be TRUE):
  1. "What's the latest Python release?" triggers a web fetch, summarizes the result, and returns a response that includes the current version number — not training-data stale information
  2. The raw HTML of the fetched page is never sent to the LLM — confirmed by logging the actual prompt content and asserting no `<html>` tags
  3. A conversation in the spicy hemisphere never triggers a web fetch — confirmed by sending a privacy-flagged message and asserting no outbound HTTP requests
  4. Disabling the browser skill by removing its directory from ~/.synapse/skills/ makes web fetches return a graceful "I can't browse right now" — not a 500
  5. Every response that used a web fetch includes the source URL(s) used
**Key Risks**:
  - SSRF guard: must reject requests to private IPs (10.x, 192.168.x, 127.x, localhost) — same guard pattern used in the existing media pipeline
  - Content extraction quality: raw HTML summarization produces poor results for JS-heavy SPAs — use a readability/article-extraction library (trafilatura or similar), not naive HTML strip
  - Rate limiting: search engines will block repeated unthrottled fetches — implement exponential backoff + configurable request delay
**Plans**: 4 plans

Plans:
- [x] 05-01-PLAN.md — Create browser skill directory: SKILL.md + scripts/fetch_and_summarize.py + SSRF guard reuse + trafilatura content extraction
- [x] 05-02-PLAN.md — Implement web search via DuckDuckGo (DDGS): rate limiting, result ranking, source URL attribution
- [ ] 05-03-PLAN.md — Wire browser skill orchestrator: hemisphere privacy guard + search->fetch->summarize chain + SkillRunner session context
- [ ] 05-04-PLAN.md — Integration tests: SSRF rejection, HTML-free LLM prompts, hemisphere guard, source URLs, skill-disabled fallback

---

## Future Milestones

### v3.0: Proactive Architecture Evolution (Target: 2027)
Synapse stops waiting to be asked. It observes recurring patterns and proposes its own
extensions. "You've asked me to check your email every morning 5 times this week. Want
me to just do that automatically?" Same consent protocol — but Synapse initiates.

Key capabilities:
- Pattern tracker: configurable window (default: 3 occurrences / 7 days) triggers proposal
- Proposal engine: generates a plain-language description of the proposed change
- Suppression: user can mute proposals per category
- Divergence metric: track how differently each instance has evolved from the baseline

### v4.0: The Jarvis Threshold (Target: 2028)
A mature Synapse instance manages parts of the user's digital life. It has its own name,
its own personality, its own relationship with its user — shaped entirely through
conversation, not configuration panels.

Not superhuman intelligence. Deep familiarity. Persistent context. Proactive capability.
An architecture that was literally built by the person it serves.

---

## Progress

**Execution Order:**
Phases execute in dependency order: 0 → 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Session & Context Persistence | 0/4 | Planned | — |
| 1. Skill Architecture | 0/5 | Planned | — |
| 2. Safe Self-Modification + Rollback | 0/6 | Pending | — |
| 3. Subagent System | 2/4 | In Progress|  |
| 4. Onboarding Wizard v2 | 4/4 | Complete   | 2026-04-07 |
| 5. Browser Tool | 2/4 | In Progress | — |

**v1.0 Archive:** All 10 phases, 38 plans — COMPLETE (2026-03-03)
See archived ROADMAP in `.planning/phases/` for historical reference.
