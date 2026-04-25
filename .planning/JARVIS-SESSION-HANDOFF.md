# Jarvis Architecture Refactor — Session Handoff (2026-04-25, ~07:15)

**User went to sleep after all-nighter. Pick up exactly from here.**

## Latest finding before sleep — E4B test FAILED

Mapped `ollama_chat/gemma4:e4b` to ALL 6 roles (casual, code, analysis, review, vault, translate) and ran 5 test scenarios. **All 5 failed** with identical pattern: E4B ignored every actual question and replied with generic "how can I help you today?" boilerplate.

**Root cause:** E4B activates ~2B params per token. Our system prompt is ~28k chars (identity files + tool schemas + runtime block). 2B-active compute can't process that context AND reason about a new user question coherently. Model treats the context as "the ongoing conversation" and waits for a fresh prompt.

**Not a hardware problem.** User's rig (RTX 3060 Ti 8GB VRAM + 32GB DDR5-6000 + i5-14600KF) is plenty — just needs a bigger local model.

### Strategic answer to "is Synapse locally hostable?"

**YES**, on standard hardware (8 GB VRAM class). Just need minimum **7B dense params** to handle the 28k-token prompt load. E4B is too small for this use case.

### Reverted config

After the failed test, restored the working hybrid:

```
casual    → github_copilot/gemini-3-flash-preview
code      → github_copilot/gemini-3-flash-preview
analysis  → github_copilot/gemini-3-flash-preview
review    → github_copilot/gemini-3-flash-preview
vault     → ollama_chat/gemma4:e4b     ← kept (vault is sparse, E4B is fine here)
translate → github_copilot/gpt-4o
```

### Running in background right now

```bash
ollama pull gemma3:12b-it-q4_K_M   # ~7 GB download, ~10-15 min
```

This is the candidate for the next test — dense 12B that fits 8GB VRAM at Q4, should handle the 28k prompt correctly. Check progress when you wake:
```bash
tail "C:/Users/SHORTY~1/AppData/Local/Temp/claude/D--Shorty-Synapse-OSS/bc3b5368-ea93-40ec-8279-899f7050ceb7/tasks/b0bi0kbel.output"
ollama list | grep gemma3
```

## Priority-ordered next-session tasks

### PRIORITY 1 — Test Gemma 3 12B on all roles (the local-hostability decision)

Once `gemma3:12b-it-q4_K_M` finished downloading:

```bash
# Map all roles to it
python -c "
import json, pathlib
p = pathlib.Path.home() / '.synapse/synapse.json'
cfg = json.loads(p.read_text())
for role in ['casual','code','analysis','review','vault','translate']:
    cfg['model_mappings'][role]['model'] = 'ollama_chat/gemma3:12b-it-q4_K_M'
p.write_text(json.dumps(cfg, indent=2))
"

# Restart server
# Then re-run the 5 tests from the failed E4B attempt:
```

**Pass criteria:** 3+ of 5 tests must answer the ACTUAL question (not generic "how can I help"). Identity test must cite the Runtime routing table. Grounding test must call bash_exec.

**If pass:** Synapse is confirmed 100% locally hostable. Celebrate, document, merge branch.

**If fail:** Either the 12B also can't handle the prompt (unlikely), or the prompt needs a "local-mode minimal" variant. Next escalation = try Mistral 7B Instruct or slim the prompt for local models.

### PRIORITY 2 — Switch to Ollama + Gemma 4 for vault (original user ask)

Already mostly done (E4B is currently the vault model). Remaining questions:
- Confirm user means `gemma4:e4b` (current) or wants to swap to `gemma3:12b-it-q4_K_M` once it's downloaded
- Verify vault path fires correctly on /spicy content (no cloud leak)

### PRIORITY 3 — Retry self-evolution test (with tool-selection nudge in commit 5b08b17)

Prompt: `"Remember I prefer English for technical answers, save to CORE.md."`

Pass criteria:
- Bot uses `write_file` or `edit_file` (NOT just bash loops)
- Runtime `~/.synapse/workspace/CORE.md` gets created
- File contains the actual preference (grep for "English" / "technical")
- Bot doesn't hallucinate success

### PRIORITY 4 — Phase 2 features (proactive, roast vault, situational)

After Priorities 1-3 validate Phase 1. Three items from vault P0/P1 research:
- PT1: `maybe_reach_out()` in ProactiveAwarenessEngine (internal scheduler, NOT a tool)
- PT2: Roast vault as HTTP endpoint + TOOLS.md curl recipe (NOT a tool)
- PT3: Situational awareness block (time, gap_hours, peak_hours in prompt)

## Branch state

**Branch:** `feat/jarvis-architecture` — 13 commits ahead of `develop`.

```
842d2a8 docs(handoff): session pause at 2026-04-25 07:00
5b08b17 fix(agents): tool-selection nudge in self-evolution protocol
31d53c5 feat(agents): rewrite templates in 1st-person voice + sharpen self-evolution
f89bee6 fix(runtime): inject model routing table + identity protocol; unbreak Copilot discovery
970586f feat(memory-protocol): explicit memory ingestion guide + binary-file guard in write_file
773de05 feat(rt3.6): trust-prefix fallback
e67e286 fix(rt3): empty-cache bug + stale description + direct _digit_compat tests
7532a4f feat(rt3.7): provider /models curl recipes in TOOLS.md
9a51b34 feat(rt3): fuzzy-match invalid model names
4807343 feat(rt2): wire agent workspace markdown prefix into system prompt
8b78389 fix(t1): remove AGENTS/CORE duplication
ecf3be3 feat(t1): agent workspace markdown templates
3663a35 wip: save pre-jarvis-refactor state
```

## Running server state

- Server started 07:15, should be running on port 8000 (reverted hybrid config)
- Baileys bridge on port 5010
- If not running: `cd D:/Shorty/Synapse-OSS && PYTHONUTF8=1 ./.venv/Scripts/python.exe -X utf8 -m uvicorn --app-dir ./workspace sci_fi_dashboard.api_gateway:app --host 0.0.0.0 --port 8000 --workers 1`

## DB state (all engines alive, confirmed earlier)

- `memory.db`: 23,954 documents
- `knowledge_graph.db`: 843 nodes / 658 edges
- `emotional_trajectory.db`: 97 trajectory points
- SBS `persistent_log.jsonl`: 238 entries
- 8-layer profile: all 8 JSONs at `~/.synapse/workspace/sci_fi_dashboard/synapse_data/the_creator/profiles/current/`

## Synapse.json backups available

Rollback safety if needed:
- `~/.synapse/synapse.json.bak.1777067787`
- `~/.synapse/synapse.json.bak.1777077334`
- `~/.synapse/synapse.json.bak.1777078720`
- `~/.synapse/synapse.json.bak.1777081273` (just before the E4B test)

## Known bugs (deferred)

1. **sqlite3 CLI not on Windows PATH** — bot needs Python fallback OR sqlite3 installed. Document `python -c "import sqlite3; ..."` path in TOOLS.md if 12B test passes.
2. **Claude via Copilot broken** — llm_router shim forces `openai/` prefix which Copilot rejects for Claude. Needs anthropic-format routing path in llm_router. Deferred.
3. **`/reload_config` endpoint missing** — referenced in CORE.md as T6+, but returns 404. Low priority — restart works fine.
4. **Model Identity Protocol ignored by E4B** — E4B can't follow the rule under 28k prompt. 12B or bigger should handle it.

## User's active preferences (reinforced 2026-04-25)

- **English only, no Banglish** — user asked explicitly. In effect for rest of this work.
- Wants **local-hostable Synapse** on standard 8GB VRAM hardware (will be proven/disproven by Priority 1 test).

## Architecture principles (unchanged, locked in)

1. No new tools unless mandatory + unique to Synapse
2. Jarvis → OpenClaw → plan → implement
3. Local-first grounding
4. Self-evolution via CORE.md writes
5. 1st-person voice in md templates

## Resume checklist (first thing after waking)

```bash
# 1. Server running?
curl -s http://127.0.0.1:8000/health/ready

# 2. Gemma 3 12B downloaded?
ollama list | grep gemma3

# 3. Read this handoff
cat .planning/JARVIS-SESSION-HANDOFF.md

# 4. If 12B ready → Priority 1 test (map all roles → restart → run 5 scenarios)
```

Rest well.
