# Jarvis Architecture Refactor — Session Handoff (2026-04-26 04:00–08:00)

**Previous handoff is superseded.** This session shipped: (1) `claude_cli` provider — Pro/Max subscription auth via local `claude` binary subprocess; (2) `claude_max` → `claude_cli` router refactor; (3) OSS-distributable wizard wiring for both new providers; (4) merge `feat/jarvis-architecture` → `develop`; (5) B-scope `/review` of today's diff; (6) two P0 fixes from review; (7) push `develop` to `origin`.

## Today's commits (in order, all on `develop`)

```
9cfc610  fix(claude_cli+antigravity): unbreak OSS onboarding for both providers ← P0 review fixes
2a03b45  merge: feat/jarvis-architecture → antigravity + claude_cli + OSS wiring
39b7b9c  feat(claude_cli): wire into onboarding wizard for OSS-distributable setup
7a4c2c0  fix(claude_cli): replace default system prompt instead of appending
689b62d  feat(router): replace claude_max direct-API path with claude_cli subprocess
9186001  fix(claude_cli): pass system prompt via temp file to dodge Win32 32k arg cap
6ba9e03  docs(handoff): close out antigravity provider session — Gemini 3 OAuth shipped
ba3d663  test(antigravity): align with OpenClaw + cover new envelope/refresh paths
b73fce1  feat(antigravity): engage paid tier via enabled_credit_types
e0e0d06  fix(antigravity): correct CodeAssist v1internal envelope + OAuth resilience
f47400e  feat(provider): add Google Antigravity (Gemini 3 via OAuth) as 20th provider
```

**Branch state:** `develop` is ~105 commits ahead of `origin/main`. Pushed to `origin/develop` at HEAD `9cfc610` this session.

## What shipped in addition to antigravity (which was covered in prior handoff)

### Claude Code CLI subscription provider — `claude_cli`

- `workspace/sci_fi_dashboard/claude_cli_provider.py` (498 lines) — `ClaudeCliClient` with `asyncio.create_subprocess_exec` shell-out to local `claude` binary (Pro/Max subscription auth lives inside Claude Code, no API key in synapse.json, no OAuth dance from Synapse).
- Win32 32k arg-cap workaround: system prompt written to `tempfile.NamedTemporaryFile` and passed via `--system-prompt-file` (REPLACE, not APPEND — `--append-system-prompt-file` produced terse/agentic output because Claude Code's default agent prompt biased the model).
- Token-trim flags: `--exclude-dynamic-system-prompt-sections`, `--mcp-config '{"mcpServers":{}}'`, ephemeral cwd via `tempfile.mkdtemp()` to skip CLAUDE.md auto-walk.
- `CLAUDE_CLI_PREFIXES = ("claude_cli/", "claude-cli/", "claude_max/")` — last is legacy alias.
- 9 tests in `workspace/tests/test_claude_cli_provider.py`, all green.

### Router refactor — `claude_max` direct-API → `claude_cli` subprocess

- Removed `_get_claude_max_token`, `_claude_max_litellm_params`, `_CLAUDE_MAX_BETA_HEADERS`.
- Added `_CLAUDE_CLI_PROVIDER_KEYS = ("claude_cli", "claude-cli", "claude_max")`, `is_claude_cli_model()`, `_claude_cli_roles` set, `_invoke_claude_cli()` dispatcher.
- Branches in `_do_call()` and `call_with_tools()` for both antigravity and claude_cli.

### Wizard + config wiring (the OSS-readiness pass)

- `workspace/cli/provider_steps.py` — `claude_cli_setup()` verifies `claude` binary is on PATH (no OAuth dance, points user to `claude /login`).
- `workspace/cli/onboard.py` — `_KNOWN_MODELS["claude_cli"]` lists `claude_cli/sonnet`, `opus`, `haiku`. Provider added to per-role priority lists (casual #2 / code, analysis, review #1).
- `synapse.json.example` — `providers.claude_cli` block with `binary_path: "claude"` + comment about ~50k token system-prompt overhead (subscription = unlimited tokens, only message-count limit applies).

### Live verification

- Telegram chat E2E with `casual → claude_cli/sonnet` worked on real subscription auth.
- CLI `/chat/the_creator` SBS persona + RAG returned the right "Upayan bhai is my master..." identity response.
- Gemini 3 Flash A/B vs Sonnet 4.6 done via Brave + Claude in Chrome MCP (depth questions modeled on `WhatsApp Chat with Jarvis.txt`).

## /review B-scope verdict (today's antigravity + claude_cli, 12 files / 3,507 lines)

**49 findings: 2 P0 (fixed in `9cfc610`), 17 P1, 30 P2.**

### P0 fixes already applied

1. **`llm_router.py:1515`** — wizard saved `binary_path`, router read `command` → custom paths silently ignored. Fixed: read both, prefer `binary_path`.
2. **`provider_steps.py:451-466`** — `google_antigravity_oauth_flow` never passed `code_input` callback to `login_pkce` → WSL2 + port-busy users got hard `OAuthCallbackBindError`. Fixed: wired `_paste_fallback(url)` using `console.input`.

40/40 unit tests green after both fixes.

### P1 mechanical cleanups (still owed, ~30 min total)

| File:line | Problem |
|-----------|---------|
| `antigravity_provider.py:191` | `resolve_inference_model_id` is "backward-compat helper" but new file has no callers — dead from day 1 |
| `antigravity_provider.py:796` | `shutdown_default_client` defined, never wired into FastAPI lifespan — httpx pool leaks on shutdown |
| `llm_router.py:1785` | `call()` early-branches to `call_with_metadata` for claude_cli roles, but `_do_call()` already routes there — redundant indirection |
| `_flatten_message_content` | Duplicated in `antigravity_provider.py:201` + `claude_cli_provider.py:145`, subtle behavioral drift on non-string blocks. Extract to shared `_message_utils.py` |
| `claude_cli_provider.py:428` | NamedTemporaryFile created BEFORE try/finally cleanup. Leak risk if `create_subprocess_exec` raises (rare) |
| `antigravity_provider.py:629` | `_build_envelope` docstring claims tier-gated `enabled_credit_types`, code unconditionally adds it for `_G1_OVERAGE_MODELS`. Fix docstring or add tier gate |

### P2 test coverage gaps (specialist generated 13 stubs ready to drop in)

- **`google_oauth.py` (999 lines, security-critical) has zero direct tests.** Uncovered: `parse_oauth_callback_input` (state-mismatch CSRF defense), `refresh_access_token` (token rotation), `save_credentials` atomic-write + chmod 0600, `OAuthCallbackBindError` EADDRINUSE fallback, `_is_vpc_sc_violation`, `_onboard_user` LRO polling.
- **`_raise_for_status()`** in `antigravity_provider.py:490` — central HTTP-error mapper, only the 401-then-200 retry path is tested. 400 / 403 / 429 / 500 / quota-hint mappings unverified.
- **`claude_cli_provider.py`** subprocess error / timeout / temp-file-cleanup paths all untested. The 32k arg-cap workaround is asserted only by path-substring; the actual >32k system-prompt scenario is never executed.
- **Concurrent refresh dedup** (`_refresh_if_needed` double-checked locking) untested.
- **Mocks in `test_antigravity_provider.py`** use lambdas that ignore arguments — would pass even if production code refreshed with stale creds.

Specialist's stubs are reproducible from this session's transcript (search "test_stub" in the security/maintainability/testing agent outputs).

## Outstanding work — priority order for next session

### W6 — Tool loop convergence guard (P0, blocks main merge)

**Problem:** `pipeline.chat.call_with_tools` fires up to 12 immediate retries on 429. Each round ~2s flat, no backoff. Burns through any tier with RPM < 14 in 28s.

**Fix shape:**
- Cap `max_rounds` 12 → 3 (configurable)
- On 429 / `RateLimitError`: parse `Retry-After` header, wait `min(parsed, 30s)` instead of immediate retry
- Jittered exponential backoff between rounds (1s → 2s → 5s)
- After 2 consecutive 429s, fall through to `model_mappings.<role>.fallback`

Reference: `D:/Shorty/openclaw/src/agents/provider-transport-fetch.ts` for OpenClaw's pattern.

### W7 — Dual cognition off antigravity (currently disabled)

**Problem:** `DualCognitionEngine.think()` fires 2 calls to the analysis role per chat. With analysis=pro-high (1 RPM), instant 429.

**Workaround active:** `session.dual_cognition_enabled: false` in synapse.json.

**Fix options:**
- **A:** Route `call_ag_oracle` (`llm_wrappers.py:42`) at `google_antigravity/gemini-3-flash-lite-preview` with `thinkingLevel: LOW`, or local Ollama.
- **B:** Consolidate stream + merge into one prompt (single LLM call, two output sections).
- **C:** Use Gemini 3 Pro's native `thoughtSignature` instead of separate LLM call (per OpenClaw `google-transport-stream.ts:134-139`).

Recommend A short-term, C long-term.

### W8 — `gpt-5-mini` residue in traffic cop

Telegram first-message context block showed two model entries — one is `gpt-5-mini` (legacy classifier model). With Copilot detached from synapse.json, this should fall back to a configured antigravity model. Find + fix the hardcoded reference in `route_traffic_cop` (api_gateway.py).

### Other follow-ups

| # | Item | Severity |
|---|---|---|
| 1 | `docs/antigravity-setup.md` walkthrough | medium (OSS blocker) |
| 2 | `docs/claude-cli-setup.md` walkthrough | medium (OSS blocker) |
| 3 | `workspace/tests/test_google_oauth.py` from specialist stubs | medium |
| 4 | `_raise_for_status` parametrized tests | medium |
| 5 | `claude_cli_provider` subprocess-error tests | medium |
| 6 | 4 mechanical P1 cleanups (table above) | low (~30 min) |
| 7 | Open PR `develop → main` | low (after W6) |
| 8 | W5 (capability-tier auto-detect + warnings) — last item from MODEL-AGNOSTIC-ROADMAP | low |
| 9 | Add `google_gemini_cli/<model>` provider in parallel — different concurrency model | low |

### Deferred bugs (carried)

1. **Claude via Copilot broken** — `llm_router` rewrites `github_copilot/claude-...` → `openai/...`, Copilot OpenAI endpoint refuses Claude. Workaround now moot (Copilot detached). Real fix still wanted.
2. **`/reload_config` endpoint missing** — referenced in `CORE.md` as T6+, returns 404. Restart works fine. Low priority.
3. **sqlite3 CLI not on Windows PATH** — bot needs `python -c "import sqlite3"` fallback. Documented in TOOLS.md.
4. **WhatsApp bridge crashloop** — Baileys 7.x exits code 1 on each restart attempt. Synapse keeps trying with backoff. Not blocking.

## Confidence levels (post-push)

- **Push to `origin/develop`:** ✓ done (HEAD `9cfc610`)
- **Open PR `develop → main`:** 8/10 — pending W6 + W7
- **OSS release tag:** 7/10 — pending W6 + setup docs + `google_oauth.py` tests
- **Daily Telegram use:** ✓ verified
- **Fresh-fork OSS install (Linux/Mac/Windows):** P0s caught in review now fixed; not yet validated on a clean checkout

## Working tree state

```
 M workspace/sci_fi_dashboard/entities.json   ← personal data, intentionally skipped per OSS rules
?? .planning/JARVIS-ARCH-PLAN.md             ← separate planning doc, untracked
?? workspace/tests/state/                    ← test scratch, untracked
```

## DB state

- `memory.db`: 10,401 documents
- `knowledge_graph.db`: 876 nodes / 703 edges
- SBS profiles + KG triples: alive at `~/.synapse/workspace/sci_fi_dashboard/synapse_data/the_creator/profiles/current/`

## Architecture principles (unchanged)

1. No new tools unless mandatory + unique to Synapse
2. Jarvis → OpenClaw → plan → implement
3. Local-first grounding
4. Self-evolution via CORE.md writes
5. 1st-person voice in md templates
6. **OSS-friendliness:** every default must work on 4 GB VRAM. No personal-rig tuning for global defaults.
7. Antigravity OAuth client_id/secret are NEVER shipped in repo — extracted from local `@google/gemini-cli` install OR sourced from env vars (`SYNAPSE_GEMINI_OAUTH_CLIENT_ID`/_SECRET).
8. Claude Code CLI auth NEVER reaches Synapse — subprocess hands off to local `claude` binary, subscription auth stays inside Claude Code.

## User preferences (unchanged)

- English only, no Banglish for documentation, commits, comments. Bot persona may use Banglish per CORE.md.
- Local-hostable Synapse on 8 GB VRAM hardware — proven with qwen2.5:7b at mid_open tier (vault role).
- OSS-distributable defaults — example files must work on a fresh fork without personal data.

## Resume checklist (first thing next session)

```bash
# 1. Verify pushed state
git log --oneline -5
# expect: 9cfc610 at HEAD on develop, also on origin/develop

# 2. Verify tests still green
cd workspace && pytest tests/test_antigravity_provider.py tests/test_claude_cli_provider.py tests/test_llm_router_tools.py -q
# expect: 40/40 pass

# 3. Read this handoff
cat .planning/JARVIS-SESSION-HANDOFF.md

# 4. Verify antigravity creds (if testing antigravity path)
cd workspace && python synapse_cli.py antigravity status

# 5. Verify claude binary still on PATH (if testing claude_cli path)
where claude  # Windows
which claude  # Mac/Linux

# 6. Pick: W6 (tool-loop guard, P0), or P1 cleanup PR, or setup docs.
```
