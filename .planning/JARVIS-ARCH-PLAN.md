# Jarvis-Level Autonomy Refactor — Implementation Plan

**Goal:** Transform Synapse from "LLM with 12 overlapping tools that surrenders on errors" into "LLM-as-brain with tight primitive tool surface + markdown skill library + battle-hardened agent discipline files" — matching Jarvis (OpenClaw) architecture.

**Non-goal:** Change LLM model. Must work with any tool-capable LLM (gpt-4o, claude, gemini, ollama).

---

## The Architecture (Jarvis Pattern)

```
┌─────────────────────────────────────────────────────────┐
│ Layer 1: AGENT WORKSPACE (markdown files = the soul)    │
│   workspace/sci_fi_dashboard/agent_workspace/           │
│     AGENTS.md     — rules, TURN BUDGET, discipline      │
│     SOUL.md       — vibe, boundaries                    │
│     CORE.md       — user + relationships + hard paths   │
│     IDENTITY.md   — name, creature, emoji               │
│     USER.md       — detailed user profile               │
│     TOOLS.md      — env-specific notes                  │
│     MEMORY.md     — durable facts                       │
│                                                          │
│ Runtime override: ~/.synapse/workspace/*.md             │
│ (user-editable copies, fall back to repo templates)     │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ Layer 2: PRIMITIVES (10 generic tools, never grow)      │
│   bash_exec, read_file, edit_file, write_file,          │
│   grep_tool, glob_tool, list_directory,                 │
│   web_fetch, message, (memory_search, memory_get)       │
│                                                          │
│ REMOVED: edit_synapse_config, list_available_models     │
│   → replaced by skills/ markdown teaching bash+curl     │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ Layer 3: SKILLS (markdown man-pages, infinite growth)   │
│   workspace/skills/                                      │
│     synapse-config/SKILL.md                             │
│     memory-ops/SKILL.md                                 │
│     browser/SKILL.md                                    │
│     model-switch/SKILL.md                               │
│                                                          │
│ System prompt injects <available_skills> XML index.     │
│ LLM reads SKILL.md via read_file when task matches.     │
└─────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│ Layer 4: PYTHON FASTAPI (capability server)             │
│   Existing: POST /chat, /query, /add, /ingest           │
│   NEW:      POST /reload_config (hot-reload synapse.json)│
│   NEW:      POST /browse (Playwright/crawl4ai)          │
│                                                          │
│ LLM calls via bash_exec("curl -X POST ...").            │
│ NOT exposed as tool schemas.                            │
└─────────────────────────────────────────────────────────┘
```

---

## Concrete Past Failures (from user's screenshot 2026-04-25)

Bot on Telegram surrendered repeatedly when asked to update memory.db:

1. Bot: "Can't access memory.db directly due to system restrictions" → asked user for path
2. Bot: "Workspace directory doesn't have subdirectory?" → confused two different "workspace" concepts
3. Bot: "Hit permission wall reading memory.db. Looks like binary file..."

**Root causes (architectural):**
- Bot tried to READ memory.db as text (it's binary SQLite). Should use `sqlite3` CLI via bash.
- Bot doesn't know the hardcoded path (`~/.synapse/workspace/db/memory.db`).
- Bot confuses repo `workspace/` (code) with runtime `~/.synapse/workspace/` (data).
- When blocked, bot surrenders instead of trying alternatives.

**Fixes delivered by this plan:**
- AGENTS.md: "Be resourceful before asking. Try 2+ alternatives first."
- AGENTS.md: "ON TOOL ERROR: do NOT surrender. Read error → investigate → retry."
- CORE.md: hardcoded paths (memory.db, synapse.json, skills/ dir)
- TOOLS.md: user's env nicknames + which CLI tools are installed
- skills/memory-ops/SKILL.md: teaches "query memory.db via `sqlite3 ~/.synapse/workspace/db/memory.db 'SELECT ...'`"
- skills/synapse-config/SKILL.md: teaches model-switch flow

---

## Task Breakdown

Tasks are ordered. Some parallelizable (marked).

### T1 — Agent Workspace Markdown Files [~2h, independent]

**Deliverable:** `workspace/sci_fi_dashboard/agent_workspace/` with 7 template files.

**Files to create:**
- `AGENTS.md.template` — response protocol, TURN BUDGET (0 for chat / 3 for heartbeat / 10 max for complex), SELECTIVE RAG rule, "Be resourceful before asking", "ON TOOL ERROR: do NOT surrender — try 2+ alternatives", past-failure log section, safety defaults
- `SOUL.md.template` — vibe ("Be genuinely helpful, not performatively helpful", opinions, resourcefulness, trust-through-competence), boundaries
- `CORE.md.template` — user (Upayan / Bhai), relationship (Shreya placeholder), hardcoded paths (`~/.synapse/workspace/db/memory.db`, `~/.synapse/synapse.json`, `workspace/skills/`), prime directives (Unfiltered Mode toggle, Benglish preference, Anti-AI-slop, Selective RAG, Interim Updates, Context Briefing format)
- `IDENTITY.md.template` — name (Synapse), vibe, emoji
- `USER.md.template` — user profile scaffold
- `TOOLS.md.template` — env-specific notes scaffold (phone nicknames, installed CLIs)
- `MEMORY.md.template` — durable facts scaffold

**Content rules:**
- Each file should be ≤200 lines markdown
- Direct, specific, opinionated — like Jarvis's files (see `D:/Shorty/Jarvis-V2` branch `origin/Jarvis-revived-1`)
- AGENTS.md must include "What Went Wrong Before (Never Repeat)" section with the memory.db surrender incident documented

**Acceptance:**
- 7 `.template` files exist, each has frontmatter-free markdown
- AGENTS.md contains explicit TURN BUDGET + "never surrender, try 2+ alternatives" rules
- CORE.md has hardcoded paths to memory.db and synapse.json
- All files reference each other consistently (AGENTS.md says "read SOUL.md first")

**Test:** Diff-read each file, verify tone is "Jarvis-style" not corporate.

---

### T2 — Markdown Skills (4 initial skills) [~2h, independent]

**Deliverable:** `workspace/skills/` with 4 skill directories.

**Files to create:**
- `workspace/skills/synapse-config/SKILL.md` — frontmatter (name, description), instructions for: check model list via `curl localhost:11434/api/tags` (Ollama) + Copilot `/models` endpoint, read/edit `~/.synapse/synapse.json` via read_file/edit_file, hot-reload via `curl -X POST localhost:8000/reload_config`
- `workspace/skills/memory-ops/SKILL.md` — query memory via `sqlite3` CLI OR `curl -X POST localhost:8000/query` with JSON body, add memory via `curl /add`, inspect knowledge graph via `sqlite3 ~/.synapse/workspace/db/knowledge_graph.db "SELECT * FROM nodes LIMIT 10"`
- `workspace/skills/browser/SKILL.md` — fetch URL via `curl -X POST localhost:8000/browse` (once T6 lands) with JSON `{"url":"..."}`; fallback to `curl -sL <url>` for simple fetches
- `workspace/skills/model-switch/SKILL.md` — step-by-step: (1) list models, (2) pick closest to user's request, (3) edit synapse.json, (4) reload, (5) tell user which model was picked

**Content rules:**
- Each `SKILL.md` starts with YAML frontmatter: `name`, `description` (one-line, used for skill index), `use_when`
- Body uses markdown with ` ```bash ` fenced blocks for exact commands
- Include "when NOT to use this skill" section (prevents LLM from over-invoking)
- Reference concrete paths (`~/.synapse/synapse.json` not "the config file")

**Acceptance:**
- 4 SKILL.md files exist with frontmatter
- Each contains at least 3 concrete `bash` command examples
- Each has "use when" and "NOT use when" sections

**Test:** YAML frontmatter parses via Python `yaml.safe_load`. Commands in code blocks are syntactically valid bash.

---

### T3 — AgentWorkspace Loader Module [~2h, depends on T1, T2]

**Deliverable:** `workspace/sci_fi_dashboard/agent_workspace.py` — single module that loads MD files + skills index.

**Public API:**
```python
class AgentWorkspace:
    def __init__(self, repo_dir: Path, runtime_dir: Path): ...
    def load_identity_files(self) -> dict[str, str]:
        """Returns {file_name: content} for AGENTS, SOUL, CORE, IDENTITY, USER, TOOLS, MEMORY.
        Runtime overrides (at ~/.synapse/workspace/*.md) win over repo templates."""
    def build_skills_index(self) -> str:
        """Scans workspace/skills/*/SKILL.md, builds <available_skills> XML for system prompt."""
    def build_stable_prefix(self) -> str:
        """Full stable system-prompt prefix: identity files + skills index + tool guidance preamble."""
```

**Behavior:**
- Resolve runtime dir to `~/.synapse/workspace/`; repo dir to `workspace/sci_fi_dashboard/agent_workspace/`
- For each expected file: if runtime exists use it; else fall back to `<name>.template` in repo dir
- Skills: scan both `workspace/skills/` (repo) AND `~/.synapse/workspace/skills/` (user-added); parse YAML frontmatter from each `SKILL.md`; build `<available_skills>` XML matching OpenClaw format:
  ```xml
  <available_skills>
    <skill>
      <name>synapse-config</name>
      <description>...</description>
      <location>/abs/path/to/skills/synapse-config/SKILL.md</location>
    </skill>
  </available_skills>
  ```
- `build_stable_prefix()` concatenates identity files in documented order (SOUL → CORE → IDENTITY → USER → TOOLS → MEMORY → AGENTS) + skills index

**Acceptance:**
- Module imports cleanly, no circular deps
- `load_identity_files()` returns 7 non-empty strings
- `build_skills_index()` returns valid XML with ≥4 `<skill>` entries
- Missing file falls back to template; missing template raises clear error

**Test:** Unit tests in `workspace/tests/test_agent_workspace.py`:
- `test_loads_all_template_files()`
- `test_runtime_override_wins()`
- `test_skills_index_has_valid_xml()`
- `test_missing_template_raises()`

---

### T4 — Wire AgentWorkspace into Chat Pipeline [~1.5h, depends on T3]

**Deliverable:** `chat_pipeline.py` injects AgentWorkspace stable prefix into system prompt.

**Changes:**
- Import `AgentWorkspace` in `_deps.py`, instantiate singleton
- In `chat_pipeline.py` `persona_chat()` (or wherever tool_schemas gets attached), build system prompt as:
  1. `agent_workspace.build_stable_prefix()` (cacheable, changes rarely)
  2. SBS compiled persona layer (dynamic — keep existing behavior)
  3. Tool guidance line (existing nudge, TRIMMED since AGENTS.md now handles discipline)
- REMOVE the current 5-rule ad-hoc nudge (replaced by AGENTS.md TURN BUDGET + prime directives)

**Acceptance:**
- Bot's system prompt on Telegram chat contains AGENTS.md content, SOUL.md content, etc.
- Context briefing at end of reply still works (existing behavior preserved)
- No regression: existing tests still pass

**Test:** Manual via Telegram — send "who are you?" → expect persona from SOUL.md + IDENTITY.md tone. Capture server log showing assembled system prompt.

---

### T5 — Trim Tools + Add Missing Primitives [~2h, depends on T2]

**Deliverable:** Clean `tool_sysops.py` with 10 primitives, no overlaps.

**Remove:**
- `edit_synapse_config` → replaced by read_file + edit_file + `curl /reload_config` (taught via SKILL.md)
- `list_available_models` → replaced by bash + curl (taught via SKILL.md)

**Keep as-is:**
- `bash_exec` (already exists, keep)
- `edit_file` (already exists)
- `grep_tool`, `glob_tool`, `list_directory` (already exist)

**Add:**
- `read_file` — if not already a primitive, add it (simple file reader, Sentinel-gated)
- `write_file` — new file creation, Sentinel-gated
- `web_fetch` — `curl`-equivalent, accepts URL, returns text/markdown (max 10KB). NO SSRF guard needed because it's LLM-driven (user trust boundary).
- `message` — sends interim progress message to user mid-loop (for long tasks). Signature: `message(text: str) -> {"sent": true}`. Needs a handle on the current channel/peer — pass via closure or context param in tool registration.
- `memory_search` — wraps `MemoryEngine.query(text, limit=5)` returning top results. Already used by pipeline internally; also expose to LLM.
- `memory_get` — wraps a direct key lookup for specific memory IDs.

**Acceptance:**
- `tool_sysops.py` exports exactly 10 primitives (bash_exec, edit_file, read_file, write_file, grep_tool, glob_tool, list_directory, web_fetch, message, memory_search, memory_get — 11 OK if message counted separately)
- `register_sysops_tools()` registers all into ToolRegistry
- Old `edit_synapse_config`, `list_available_models` factories are DELETED (not just unregistered)

**Test:** `pytest workspace/tests/test_tool_sysops.py` — test each new primitive executes its action and returns correct shape.

---

### T6 — /reload_config and /browse FastAPI Endpoints [~2h, independent of T5]

**Deliverable:** Two new endpoints in `api_gateway.py`.

**POST /reload_config:**
- Gated by `SYNAPSE_GATEWAY_TOKEN` auth
- Calls `deps.synapse_llm_router._rebuild_router()` (triggers reread of synapse.json + model re-registration)
- Returns `{"status": "reloaded", "model_mappings": {...current mappings...}}`
- Logs each reload

**POST /browse:**
- Gated by token auth
- Request: `{"url": "https://...", "timeout": 30}`
- Uses existing crawl4ai if installed (check `import crawl4ai`); else falls back to `httpx.get` + `readability-lxml` for markdown extraction
- Returns `{"url": ..., "title": ..., "markdown": ..., "truncated": bool}`
- Max 50KB output (truncate with indicator)
- Timeout 30s hard cap

**Acceptance:**
- Both endpoints respond 200 to valid requests, 401 without token
- `/reload_config` causes subsequent `/chat` calls to use new model (verified via integration test)
- `/browse` returns markdown for `https://example.com` in < 5s

**Test:** `pytest workspace/tests/test_api_gateway_reload.py` + `test_api_gateway_browse.py`.

---

### T7 — E2E Autonomy Smoke Test [~1h, depends on all]

**Deliverable:** Documented manual test + automated harness showing bot can autonomously resolve common tasks without surrender.

**Test scenarios:**
1. **Model swap**: User says "change casual model to gemini-3-flash". Bot should chain:
   - `read_file("~/.synapse/workspace/skills/model-switch/SKILL.md")` → learn flow
   - `bash_exec("curl localhost:11434/api/tags")` OR existing discovery path → list models
   - Find closest (gemini-3-flash doesn't exist; closest `github_copilot/gemini-2.0-flash-001` or `gemini/gemini-2.5-flash`)
   - `edit_file(~/.synapse/synapse.json, ...)`
   - `bash_exec("curl -X POST localhost:8000/reload_config ...")`
   - Reply: "Switched to X (closest available to your request)"
2. **Memory query**: User says "what do you remember about Shreya?". Bot should:
   - Try memory_search tool first (or read memory-ops SKILL.md)
   - If tool fails, fall back to `bash_exec("sqlite3 ~/.synapse/workspace/db/memory.db 'SELECT...'")`
   - Never say "I can't access memory.db"
3. **Browser fetch**: User sends a URL. Bot should:
   - `bash_exec("curl -X POST localhost:8000/browse -d '{\"url\":\"...\"}'")` (after T6 ships)
   - Summarize content in reply

**Acceptance:**
- All 3 scenarios produce correct behavior on fresh Telegram chat
- No "I can't" / "Let me know if" / "Could you provide" surrender phrases in any reply
- Context briefing at end of each reply present

**Test:** Manual via Telegram; record screenshots of successful autonomy; document failures with corrective action.

---

## Execution Notes

- Work on branch `feat/jarvis-architecture` (created).
- Commit after each task completes spec+quality review.
- Reference this plan file in commit messages.
- Subagent-Driven Development: dispatch implementer per task, spec-review, code-review, mark complete.
