# Requirements: Synapse-OSS

**Defined:** 2026-04-06 (v2.0) | 2026-04-08 (v4.0)
**Core Value:** An AI that knows you deeply, grows with you continuously, and reaches
out to you first — on your machine, under your full control.

---

## v4.0 Requirements — Bioinspired Memory Architecture

Requirements derived from 29 research papers, 57 Q&As, 7 follow-ups.
Master spec: `memory-vault/research/architecture-spec.md`.

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

---

## v2.0 Requirements — The Adaptive Core

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

- [x] **AGENT-01**: The main conversation can spawn an isolated sub-agent with a task description and optional context
- [x] **AGENT-02**: Sub-agents run in isolated asyncio tasks — a crashed sub-agent does not affect the parent conversation
- [x] **AGENT-03**: Sub-agent results return to the parent conversation as a structured message
- [x] **AGENT-04**: Multiple sub-agents can run in parallel — independent tasks do not wait on each other
- [x] **AGENT-05**: Sub-agents have access to memory and tools but operate with a scoped context window — they do not receive the full parent conversation history by default
- [x] **AGENT-06**: Long-running sub-agents (> 30s) send progress updates to the parent at configurable intervals
- [x] **AGENT-07**: `GET /agents` lists active and recently completed sub-agent tasks with status

### Onboarding Wizard v2 (Phase 8)

- [x] **ONBOARD2-01**: `python -m synapse setup` completes full setup — model selection, API key entry, validation, persona configuration — in under 5 minutes for a fresh user
- [x] **ONBOARD2-02**: The wizard builds an initial SBS profile via targeted questions (communication style, interests, privacy preferences) — user reaches a meaningful baseline without prior conversations
- [x] **ONBOARD2-03**: The wizard offers WhatsApp history import during setup — python scripts/import_whatsapp.py is presented as an option, not a required step
- [x] **ONBOARD2-04**: The wizard supports `--non-interactive` flag with env vars for headless/Docker/CI setups
- [x] **ONBOARD2-05**: After wizard completion, `python -m synapse setup --verify` confirms all configured providers and channels respond correctly

### Browser Tool (Phase 9)

- [x] **BROWSE-01**: Synapse can fetch and read web pages during a conversation when the user asks about current information
- [x] **BROWSE-02**: Web content is summarized and injected into the conversation context — raw HTML is never passed to the LLM
- [x] **BROWSE-03**: Browser requests respect the Zone 1/Zone 2 privacy boundary — private/spicy hemisphere conversations never trigger web fetches
- [x] **BROWSE-04**: Browser tool is implemented as a skill (SKILL.md) — it can be disabled or replaced without touching the core pipeline
- [x] **BROWSE-05**: Search results include source URLs — the user can verify provenance

---

## v5.0 Requirements (Deferred — Proactive Architecture Evolution)

To be detailed at v5.0 milestone initialization.

### Proactive Proposals
- **PROACT-01**: Synapse observes patterns and proposes architecture extensions
- **PROACT-02**: All proposals follow the same consent protocol
- **PROACT-03**: User can suppress proactive proposals per category

### Pattern Recognition
- **PATTERN-01**: Synapse tracks recurring manual requests over a configurable window
- **PATTERN-02**: Recurring patterns trigger a proposal — not an automatic change

### Advanced Memory
- **ADV-01**: Working memory buffer with rapid decay (LIDA-inspired)
- **ADV-02**: Expectation codelets monitor action outcomes for prediction errors
- **ADV-03**: Predictive prefetching based on conversation trajectory (GWT-inspired)

---

## v6.0 Requirements (Deferred — The Jarvis Threshold)

To be detailed at v6.0 milestone initialization.

- A mature instance manages parts of the user's digital life
- The AI has its own name, personality, and relationship — shaped through conversation
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
| GPU-accelerated Hopfield | CPU-only for OSS accessibility; GPU path deferred to scaling milestone |
| Multimodal memory (images, audio) | Text-only memory ceiling ~80% of human subsystems; multimodal is v6.0+ |
| External vector DB migration | LanceDB sufficient for personal scale (<100K docs); Qdrant upgrade path documented only |
| Real-time distributed memory sync | Per-user, single-machine architecture by design |

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
| AGENT-01 | Phase 3 | Complete |
| AGENT-02 | Phase 3 | Complete |
| AGENT-03 | Phase 3 | Complete |
| AGENT-04 | Phase 3 | Complete |
| AGENT-05 | Phase 3 | Complete |
| AGENT-06 | Phase 3 | Complete |
| AGENT-07 | Phase 3 | Complete |
| ONBOARD2-01 | Phase 4 | Complete |
| ONBOARD2-02 | Phase 4 | Complete |
| ONBOARD2-03 | Phase 4 | Complete |
| ONBOARD2-04 | Phase 4 | Complete |
| ONBOARD2-05 | Phase 4 | Complete |
| BROWSE-01 | Phase 5 | Complete |
| BROWSE-02 | Phase 5 | Complete |
| BROWSE-03 | Phase 5 | Complete |
| BROWSE-04 | Phase 5 | Complete |
| BROWSE-05 | Phase 5 | Complete |
| RETR-01 | Phase 6 | Pending |
| RETR-02 | Phase 6 | Pending |
| RETR-04 | Phase 6 | Pending |
| RETR-05 | Phase 6 | Pending |
| MEM-01 | Phase 7 | Pending |
| MEM-02 | Phase 7 | Pending |
| MEM-03 | Phase 7 | Pending |
| MEM-04 | Phase 7 | Pending |
| MEM-05 | Phase 7 | Pending |
| MEM-06 | Phase 7 | Pending |
| MEM-07 | Phase 7 | Pending |
| MEM-08 | Phase 7 | Pending |
| CONSOL-01 | Phase 8 | Pending |
| CONSOL-02 | Phase 8 | Pending |
| CONSOL-03 | Phase 8 | Pending |
| CONSOL-07 | Phase 8 | Pending |
| CONSOL-08 | Phase 8 | Pending |
| CONSOL-09 | Phase 8 | Pending |
| RETR-03 | Phase 8 | Pending |
| QUERY-04 | Phase 8 | Pending |
| QUERY-05 | Phase 8 | Pending |
| RETR-06 | Phase 9 | Pending |
| ASSOC-01 | Phase 9 | Pending |
| ASSOC-02 | Phase 9 | Pending |
| CONSOL-04 | Phase 9 | Pending |
| POST-01 | Phase 9 | Pending |
| POST-02 | Phase 9 | Pending |
| POST-03 | Phase 9 | Pending |
| POST-04 | Phase 9 | Pending |
| POST-05 | Phase 9 | Pending |
| ASSOC-03 | Phase 10 | Pending |
| ASSOC-04 | Phase 10 | Pending |
| ASSOC-05 | Phase 10 | Pending |
| ASSOC-06 | Phase 10 | Pending |
| CONSOL-05 | Phase 10 | Pending |
| CONSOL-06 | Phase 10 | Pending |
| QUERY-01 | Phase 10 | Pending |
| QUERY-02 | Phase 10 | Pending |
| QUERY-03 | Phase 10 | Pending |
| EMBED-01 | Phase 11 | Pending |
| EMBED-02 | Phase 11 | Pending |
| EMBED-03 | Phase 11 | Pending |

**Coverage:**
- v2.0 requirements: 34 total (17 complete, 17 pending)
- v4.0 requirements: 42 total (0 complete, 42 pending)
- Mapped to phases: 34 (v2.0) + 42 (v4.0) = 76 total
- Unmapped: 0

---
*Requirements defined: 2026-04-06 (v2.0) | 2026-04-08 (v4.0)*
*Last updated: 2026-04-08 after v4.0 roadmap creation — all 42 v4.0 requirements mapped to phases 6-11*
