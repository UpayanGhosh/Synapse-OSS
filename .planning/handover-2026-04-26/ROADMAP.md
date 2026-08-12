# Synapse-OSS Fix Handover — 2026-04-26

> **Handover doc for Codex (or any incoming agent) to pick up runtime stability fixes for Synapse-OSS.** Today's session (2026-04-26 04:00–07:30) shipped antigravity + claude_cli providers and merged to `develop` (commit `c4bcdb7`, pushed to `origin/develop`). This handover covers everything that's still broken or missing.

## Mission

Get Synapse-OSS from *"works on my machine"* to *"works on a fresh OSS fork running unattended for a week."* The provider work shipped today (antigravity + claude_cli) is fine; the issues are upstream — in the chat ingestion path, tool-loop control, dual-cognition routing, and a stale model reference.

## How to read this folder

| File | What it is |
|---|---|
| `ROADMAP.md` (this file) | Phase index, dependencies, sequencing, sign-off criteria |
| `EVIDENCE.md` | Raw data: sqlite query outputs, file paths, line refs, dates. **Read this first.** |
| `phase-N-*.md` | Per-phase plan: goal, current state, target state, tasks, success criteria, inline evidence, risks |

Each phase doc is **self-contained** — you can pick any phase and execute it without reading the others, except where `Dependencies` calls them out.

## Phase index

| Phase | Title | Severity | Effort | Blocks |
|---|---|---|---|---|
| 1 | Surface silent `add_memory` failure | P1 | S (~1 hr) | 2 |
| 2 | Fix vector-path failure in `_ingest_session_background` | P1+ | M (~3 hr) | 3 |
| 3 | Auto-flush session on idle / message-count threshold | P2 | M (~4 hr) | — |
| 4 | Deprecate `atomic_facts` + wire `kg_processed=1` at runtime | P3 | S (~1 hr) | — |
| 5 | W5 — Capability-tier auto-detect + warnings | P2 | M (~3 hr) | — |
| **6** | **W6 — Tool-loop convergence guard** | **P0 BLOCKING** | **M (~3 hr)** | **PR `develop → main`, OSS release** |
| 7 | W7 — Dual cognition off antigravity | P1 | S (~2 hr) | — |
| 8 | W8 — `gpt-5-mini` residue in `route_traffic_cop` | P1 | XS (~30 min) | — |

> **P0 BLOCKING** = prevents `develop → main` merge. Until tool-loop guard lands, any chat that fires tools on a low-RPM provider (Gemini Pro, free tiers) will burn quota in 28s via 12 immediate retries.

## Dependency graph

```
                            ┌──── Phase 1 (surface failure) ────┐
                            │                                    │
                            ▼                                    ▼
                     Phase 2 (fix vector-path)            (deeper diagnosis)
                            │
                            ▼
                     Phase 3 (auto-flush) ◄── independent ── Phase 4 (cleanup)

  Independent / parallel-safe:
    Phase 5 (W5 capability-tier)
    Phase 6 (W6 tool-loop guard)        ← P0, do this FIRST
    Phase 7 (W7 dual-cog routing)
    Phase 8 (W8 gpt-5-mini residue)
```

**Sequencing recommendation:**

1. **Phase 6** first — unblocks main merge. Independent of everything else.
2. **Phase 1** next — gets visibility into Phase 2's actual error. ~1 hr.
3. **Phase 2** — fix whatever Phase 1 surfaces.
4. **Phase 8** — 30 min cleanup, no dependencies. Squeeze in anywhere.
5. **Phase 7** + **Phase 5** — independent, can run in parallel.
6. **Phase 3** — needs Phase 2 stable first.
7. **Phase 4** — pure cleanup, last.

## Sign-off criteria (when this handover is done)

You've finished this handover when:

- [ ] `develop` merges cleanly to `main` via PR
- [ ] A 24h soak test on a fresh OSS install (Linux, fresh user, no `entities.json`) completes without:
  - silent ingest failures
  - tool-loop quota burn
  - dual-cognition rate-limit cascade
  - `gpt-5-mini` cost spikes
- [ ] `~/.synapse/workspace/db/memory.db` `documents` table grows organically as user chats — no manual `/new` required for ingestion to fire
- [ ] `kg_processed = 1` for documents that have been KG-extracted (currently always 0)
- [ ] `atomic_facts` either has fresh entity-tagged rows OR has been formally deprecated

## What was JUST DONE (2026-04-26 session) — context only

Already complete, mentioned for context:

- ✅ Antigravity (Gemini 3 OAuth) provider live on Telegram + CLI
- ✅ Claude Code CLI subscription provider via local `claude` subprocess
- ✅ B-scope `/review` of today's diff (49 findings: 2 P0 fixed, 17 P1, 30 P2)
- ✅ P0 review fixes: `binary_path` vs `command` mismatch, `code_input` callback wiring (commit `9cfc610`)
- ✅ `develop` branch merged from `feat/jarvis-architecture` (commit `2a03b45`)
- ✅ Pushed to `origin/develop` (HEAD `c4bcdb7`)
- ✅ Memory.db pollution cleanup: 18 `MagicMock`-tainted rows deleted, FTS cascaded via trigger, `_archived_memories/persistent_log.jsonl` cleaned (65 → 47 lines), test fixture patched (commit `26556e8`)
- ✅ Backup at `~/.synapse/workspace/db/memory.db.bak_1777166450` (226 MB)

**Do NOT undo any of the above.** They're load-bearing for OSS-readiness.

## Tools & environment notes (Codex specifics)

- **OS**: Windows 11 Pro 10.0.26200 (the dev env). Tests run on Linux CI.
- **Working dir**: `D:\Shorty\Synapse-OSS`
- **Shell**: bash via Git Bash (use forward slashes in paths)
- **Python**: 3.13.6 system, but project pins to 3.11 syntax
- **Gateway**: `http://127.0.0.1:8000` — currently UP (verified `/health` ok at 07:30)
- **Branch**: `develop` (not `main` — that's the PR target)
- **synapse.json**: `~/.synapse/synapse.json` (user already has the file open in IDE — they may be tuning model_mappings)
- **Backups exist**: `memory.db.bak_1777166450` and `.bak_1777066874` (older). Copy to `.bak_<timestamp>` before any DESTRUCTIVE DB action.

## Execution rules (read before starting any phase)

1. **Read `EVIDENCE.md` first** — the raw data anchors every claim in the phase docs.
2. **Branch naming**: each phase gets its own branch off `develop`: `fix/phase-N-<slug>` (e.g. `fix/phase-6-tool-loop-guard`).
3. **Per-phase commit cadence**: one commit per task within the phase. Don't bundle unrelated changes.
4. **Verify before claiming done**: each phase has explicit `Success criteria` checkboxes — every box must be ticked AND have a one-line evidence pointer before you mark the phase complete.
5. **Atomicity**: if you can't finish a phase in one sitting, leave it on its branch with a `STATUS.md` in the phase dir saying what's left.
6. **OSS hygiene** (per repo `CLAUDE.md`): never commit `entities.json`, real tokens, or personal `synapse.json` content. Stage explicit files (`git add path/file.py`), never `git add .`.
7. **Don't re-introduce test pollution**: any new test that touches `chat_pipeline.persona_chat()` or any code that calls `MemoryEngine.add_memory()` MUST mock `add_memory` (see `workspace/tests/pipeline/conftest.py:296-300` for the canonical pattern after commit `26556e8`).

## When to escalate / stop

Stop and ask the user (Upayan, GitHub `UpayanGhosh`, Telegram identity = `the_creator`) if:

- You discover a phase needs a design choice beyond what's in the phase doc (e.g. Phase 3's idle-timeout vs message-count gating threshold)
- A "fix" would touch >5 files outside the phase's stated scope
- A test that was passing on `develop` before you started now fails — surface it before pressing on
- You hit the same root cause as a previous phase (suggests phases need re-scoping)

The user prefers terse direct comms ("caveman mode" is active in their Claude Code sessions). Don't over-explain. Show diff, state evidence, ask one question.

## Where to find more context

| Topic | Source |
|---|---|
| Architecture overview | `D:/Shorty/Synapse-OSS/CLAUDE.md` |
| Antigravity / claude_cli session | `.planning/JARVIS-SESSION-HANDOFF.md` (commit `c4bcdb7`) |
| OpenClaw retry/backoff reference | `D:/Shorty/openclaw/src/agents/provider-transport-fetch.ts` |
| Gemini CLI bundle (auth header reference) | `node_modules/@google/gemini-cli/packages/core/dist/src/code_assist/server.js` if installed |
| Code graph (MCP) | `code-review-graph` MCP server — 26,798 nodes / 154,488 edges built on `develop` @ `2a03b45` |

## Final note

The user's preferred working style is small commits, atomic phases, evidence-anchored claims. Don't propose a "big-bang refactor" — incremental landing on `develop` with a PR per phase is what they want. When in doubt, keep diffs small.
