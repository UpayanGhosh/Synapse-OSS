# Jarvis Architecture Refactor — Session Handoff (2026-04-25 07:00)

**User sleeping after an all-nighter. Resume exactly from here when they wake.**

## TL;DR — What to do when you wake

1. **Read this file first.**
2. **Next test**: switch vault role from `ollama_chat/llama3.2:3b` to Ollama + **Gemma 4** (user's explicit ask). Verify local-only inference works for private/spicy content.
3. **Retry self-evolution test** — the 12-round failure last night pushed a tool-selection nudge into AGENTS.md; needs verification.
4. **Continue Phase 2** (proactive reach-out, roast vault, situational awareness) after the above pass.

## Branch state

Branch: `feat/jarvis-architecture`. 12 commits since `develop`:

```
5b08b17 fix(agents): tool-selection nudge in self-evolution protocol
31d53c5 feat(agents): rewrite agent_workspace templates in 1st-person voice + sharpen self-evolution
f89bee6 fix(runtime): inject model routing table + identity protocol; unbreak Copilot model discovery
970586f feat(memory-protocol): explicit memory ingestion guide in MEMORY.md + binary-file guard in write_file
773de05 feat(rt3.6): trust-prefix fallback in edit_synapse_config
e67e286 fix(rt3): empty-cache bug + stale description + direct _digit_compat tests (review I1, I2, M2)
7532a4f feat(rt3.7): document provider /models curl recipes in TOOLS.md
9a51b34 feat(rt3): fuzzy-match invalid model names in edit_synapse_config
4807343 feat(rt2): wire agent workspace markdown prefix into system prompt
8b78389 fix(t1): remove AGENTS/CORE duplication per code review
ecf3be3 feat(t1): agent workspace markdown templates (AGENTS/SOUL/CORE/IDENTITY/USER/TOOLS/MEMORY)
3663a35 wip: save pre-jarvis-refactor state
```

Not yet merged to develop. 12 commits ahead.

## Running server state (as of 07:00)

- Server on port 8000 (uvicorn, workers=1)
- Baileys bridge on port 5010 (auto-spawned by WhatsAppChannel)
- Logs: `~/.synapse/logs/gateway.log` + background task file `C:\Users\SHORTY~1\AppData\Local\Temp\claude\D--Shorty-Synapse-OSS\bc3b5368-ea93-40ec-8279-899f7050ceb7\tasks\bmsenkfzn.output`
- **Model mappings** (current `~/.synapse/synapse.json`):
  - casual: `github_copilot/gemini-3-flash-preview`
  - code: `github_copilot/gemini-3-flash-preview`
  - analysis: `github_copilot/gemini-3-flash-preview`
  - review: `github_copilot/gemini-3-flash-preview`
  - vault: `ollama_chat/llama3.2:3b` ← **user wants this switched to Gemma 4 after waking**
  - translate: `github_copilot/gpt-4o`
- Owner: telegram channel, user_id `1988095919` (registered in `~/.synapse/state/owners.json`)

## DB state (verified 07:00)

- `memory.db`: 23,954 documents (last ID is WhatsApp session 2026-04-25)
- `knowledge_graph.db`: 843 nodes / 658 edges
- `emotional_trajectory.db`: 97 trajectory points
- SBS `persistent_log.jsonl`: 238 entries
- 8-layer profile: all 8 JSON files present at `~/.synapse/workspace/sci_fi_dashboard/synapse_data/the_creator/profiles/current/`

## What's confirmed working

1. **Agent workspace prefix loader** (RT2) — 28,343-char prefix loads, mtime cache invalidates on file edits, works across the 7 template files.
2. **Model Identity Protocol** — bot correctly answers "what model are you?" with the runtime routing table (was hallucinating "I am GPT-4o" before).
3. **Fuzzy match + trust-prefix** (RT3/RT3.6) — `edit_synapse_config` fuzzy-matches Copilot/Ollama models, auto-applies close matches (sim ≥ 0.85, digit-compat guard), accepts configured-provider prefixes (anthropic/, openai/, etc.).
4. **Copilot model discovery** (fixed I1/I2/cache/TypeError) — `_discover_reachable_models` returns 43 real models including gpt-5-mini, claude-opus-4.7, gemini-3-flash-preview.
5. **SBS + Dual Cognition + Trajectory + Memory RAG + KG** — ALL alive and auto-updating per turn. Verified via direct DB queries + SBS log.
6. **Owner-scoped tools** — when user_id=`1988095919` is passed, bot sees `bash_exec` + all owner-only tools. Confirmed via CLI test: bot made 3× bash_exec calls for memory.db question.
7. **Banglish persona** — "Bol bhai" kicks in naturally for casual messages.

## Known bugs / open issues (pick up next session)

### Bug 1 — Self-evolution still failing (HIGH priority)

User's ask: "remember I prefer English for technical answers, save to CORE.md."

**Last attempt (2026-04-25 06:57):** bot ran 12 rounds, mostly `bash_exec` (11×), NO `write_file` / `edit_file` calls, eventually said "I wasn't able to complete that request" (honest failure — progress from earlier hallucination). Runtime `~/.synapse/workspace/CORE.md` was NOT created.

**Fix shipped in commit `5b08b17`:** explicit nudge in AGENTS.md Self-Evolution Protocol that says:
- Use `write_file` / `edit_file` directly — NOT bash `cat > file` loops
- Looping bash attempts on a file = signal to switch tool class

**To verify:** after waking, re-run the self-evolution test. If still failing, the next escalation is:
- Split the procedure into a skill that pre-builds the full file content + calls write_file once
- OR switch analysis-role to a stronger model (claude-opus if the Copilot shim is fixed, otherwise direct Anthropic API)

### Bug 2 — sqlite3 CLI not on Windows PATH (MEDIUM)

Bot tried `bash_exec("sqlite3 ...")` — got "command not found". Couldn't get memory.db count via the documented path.

**Options:**
- Install sqlite3 on Windows PATH (user-side)
- Add Python fallback to TOOLS.md: `bash_exec("python -c \"import sqlite3; print(sqlite3.connect(...).execute(...).fetchone()[0])\"")` — built-in, always available
- Extend MemoryEngine with a `.get_doc_count()` helper exposed as query_memory variant

**Recommendation:** document Python fallback in TOOLS.md (fits the "TOOLS.md teaches recipes" pattern).

### Bug 3 — Claude via Copilot broken (MEDIUM, deferred)

`llm_router.py` rewrites `github_copilot/claude-...` → `openai/claude-...` for the OpenAI-compat shim. Copilot's OpenAI endpoint refuses Claude models. Error: "The requested model is not supported."

**Workarounds:**
- Use direct Anthropic API (needs real api_key in synapse.json → providers.anthropic)
- Add Claude-aware routing path in `llm_router.py` that bypasses the openai shim for Claude models — use anthropic-compat endpoint instead

**Not blocking** — Gemini 3 Flash works fine via Copilot; user is currently on it.

### Bug 4 — `/reload_config` endpoint missing (LOW)

Attempted `POST /reload_config` — returned `{"detail": "Not Found"}`. The endpoint is referenced in CORE.md and MEMORY.md as "T6+, not yet live." Should either add it (hot-reload synapse.json without restart) or remove the reference.

**Current workaround:** restart server after synapse.json edits. Works but annoying.

### Bug 5 — TURN BUDGET vs Grounding tension

AGENTS.md says "0 tools for direct chat." But Local-First Grounding says "read file when user asks about local state." For casual chat this is fine (no grounding needed), but borderline questions ("what's my memory count?") can confuse the bot about whether to use tools.

**Status:** currently acceptable — bot mostly distinguishes well. If it misfires, add explicit "questions about local state are COMPLEX, use tools" clause.

## Next session test plan

### Test 1 — Switch vault to Gemma 4 (USER'S EXPLICIT ASK)

```bash
# 1. Check Ollama running + has gemma
ollama list | grep -i gemma

# 2. If gemma not pulled, pull it:
ollama pull gemma:7b   # or whichever version user wants

# 3. Edit synapse.json
python -c "
import json, pathlib
p = pathlib.Path.home() / '.synapse/synapse.json'
cfg = json.loads(p.read_text())
cfg['model_mappings']['vault']['model'] = 'ollama_chat/gemma:7b'  # or the actual tag
p.write_text(json.dumps(cfg, indent=2))
"

# 4. Restart server (no /reload_config endpoint yet)

# 5. Test vault path with a /spicy prefix or private content
curl -s -X POST http://127.0.0.1:8000/chat/the_creator \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer synapse-dev-token" \
  -d '{"message":"/spicy test the vault path","user_id":"1988095919"}'

# Expect: route to vault role → local Ollama + Gemma 4 → zero cloud latency
```

**Note:** Ask user for exact Gemma variant. "Gemma 4" is unusual naming — might mean Gemma 2 9B or Gemma 3 variant. Verify with `ollama list`.

### Test 2 — Retry self-evolution with tool nudge

After Test 1 passes, retry the exact same prompt:

```
"Remember this as a durable preference: I want English for all technical answers, not Banglish. Save it to CORE.md properly — read the template first, then add one rule, then verify it landed."
```

**Pass criteria:**
- Bot uses `write_file` or `edit_file` (not just bash_exec loops)
- Runtime `~/.synapse/workspace/CORE.md` gets created
- File contains the actual preference (grep for "English" / "technical" / "banglish")
- Bot confirms what it did (not a hallucination)

**Fail escalation:** If still failing, consider the bigger fix — build a dedicated skill module that handles runtime override creation atomically. This would be a Synapse-specific primitive (justified per the "unique to Synapse" bar since it encapsulates the template-read + override-write + verify flow).

### Test 3 — CLI grounding / memory.db count

Pending the sqlite3 PATH fix (Bug 2). Options:
- Install sqlite3 first
- Update TOOLS.md with Python fallback first

Either way, then test:
```
"How many documents in my memory.db right now? Use actual DB."
```
Expect: `bash_exec("python -c ...")` or `bash_exec("sqlite3 ...")` returning 23,954+ (will be higher after more chats).

## Phase 2 still queued (after Tests 1-3 pass)

- **PT1** — Proactive reach-out (`maybe_reach_out()` in `ProactiveAwarenessEngine`, 15-min poll, unprompted messages after 8h silence; vault P0.1)
- **PT2** — Roast vault as HTTP endpoint + TOOLS.md curl recipe (no new tool; vault P0.2)
- **PT3** — Situational awareness block (time-of-day, gap_hours, peak_hours injected into prompt; vault P1)

## Files not tracked in git (leave as-is)

- `~/.synapse/synapse.json` — runtime config, has real tokens
- `~/.synapse/synapse.json.bak.*` — rollback safety (keep for now)
- `workspace/sci_fi_dashboard/entities.json` — personal data, OSS rule says don't commit
- `.planning/JARVIS-ARCH-PLAN.md` — planning doc, optional to commit as separate docs PR
- `workspace/tests/state/` — test artifacts

## Architecture principles locked in (don't forget when sleep fog lifts)

1. **No new tools unless mandatory + unique to Synapse.** Generic primitives (bash, read, edit, grep, glob, web_fetch, message, memory_search, memory_get) + skills markdown + HTTP routes. New capabilities = markdown/HTTP route, not function schemas.
2. **Jarvis → OpenClaw → plan → implement.** Research before code, every time.
3. **Local-first grounding.** Bot reads actual files / DBs / configs before answering. Training data is the LAST fallback.
4. **Self-evolution via CORE.md writes.** Bot updates its own runtime override md files when user gives durable feedback. Read-before-edit + verify-after-write.
5. **1st-person voice.** All agent_workspace templates address the bot as "you" / "your master".

## How to resume exactly

```bash
# 1. Make sure server is still running
curl -s http://127.0.0.1:8000/health/ready
# If not, restart:
cd D:/Shorty/Synapse-OSS
PYTHONUTF8=1 ./.venv/Scripts/python.exe -X utf8 -m uvicorn \
  --app-dir ./workspace sci_fi_dashboard.api_gateway:app \
  --host 0.0.0.0 --port 8000 --workers 1

# 2. Read this handoff file
cat .planning/JARVIS-SESSION-HANDOFF.md

# 3. Start with Test 1 (Ollama + Gemma 4)
ollama list
```

All good. Sleep well, bhai. 🛌
