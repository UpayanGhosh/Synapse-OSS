<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

## Token Efficiency

Default communication mode for this repo: Caveman ultra.

- Keep answers terse.
- Prefer fragments over full prose when meaning stays clear.
- Use short status updates only when there is a meaningful state change.
- Do not spend tokens on pleasantries, recap, or repeated framing.
- If a warning or destructive action needs precision, switch briefly to normal
  clarity, then return to terse mode.

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

`code-review-graph` is the primary graph for this repo. Treat `graphify` or
`graphify-out/` as secondary export artifacts, not the default exploration
surface.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes - gives risk-scored analysis |
| `get_review_context` | Need source snippets for review - token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.

## Default Combo Workflow (Graph + MemPalace)

Run this combo as the default operating loop for repo work:

1. **Task start (context pull):**
   - `mempalace search "<task or topic>"`
   - then orient with graph tools (`semantic_search_nodes`, `query_graph`, `get_review_context`).
2. **During implementation (structure truth):**
   - use `code-review-graph` first for tracing/impact.
3. **Before handoff or closeout (memory + risk refresh):**
   - run `synapse_context_sync.bat` (Windows) or `./synapse_context_sync.sh` (Mac/Linux)
   - this updates graph state, runs risk scan, and mines MemPalace.

If MemPalace context conflicts with repo state, repo + graph win.

## Reference Parity Gate

Developer-only instruction for Codex and local maintainers. This is not a
Synapse runtime instruction, must not be seeded into `.synapse`, and must not be
shown to end users.

Synapse is being rebuilt against the maintainer's local reference assistant as
a behavioral reference. After any fix that touches personality, memory, tools,
proactivity, channels, background work, or delivery reliability:

1. Recheck the matching local reference behavior when that private reference is
   available on the developer machine.
2. Compare concept, not private user specifics.
3. Verify Synapse has the same product-level guarantee, or record the gap.
4. Run at least one Synapse regression/canary that proves the guarantee.
5. Do not call the fix complete until the reference parity result is known, or
   explicitly record that the private reference was unavailable.

Current reference loop:

`recognize state -> choose social stance -> do useful action -> report evidence -> remember pattern`

Important parity surfaces:

- background task status and worker health;
- durable inbound capture before processing;
- verified action receipts for search/write/send/schedule claims;
- outbound retry/dead-letter behavior;
- cron/proactive delivery proof;
- memory/KG/affect writes with timestamps;
- no raw diagnostics, reasoning tags, or fake tool claims in user chat.

## MemPalace (Default Behavior)

This repo uses MemPalace as the default external memory layer for Codex.

### When to use MemPalace

- At the start of a task, use MemPalace for prior project context that may not
  be checked into the repo:
  - prior decisions
  - research notes
  - handoff context
  - planning notes
  - earlier session memory
- Use MemPalace before asking the user to restate project context that may
  already exist in memory.

### Source-of-truth rules

- The repo and the code-review graph remain the source of truth for code,
  architecture, and current implementation state.
- If MemPalace conflicts with the current code or checked-in docs, prefer the
  repo and explicitly call out the mismatch.
- Do not make code changes from MemPalace context alone; verify against the
  current codebase first.

### Reliability notes (Windows)

- Use UTF-8 env for MemPalace commands to avoid Windows `cp1252` decode issues:
  - `set PYTHONUTF8=1`
  - `set PYTHONIOENCODING=utf-8`
