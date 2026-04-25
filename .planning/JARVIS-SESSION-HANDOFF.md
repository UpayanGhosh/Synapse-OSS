# Jarvis Architecture Refactor — Session Handoff (2026-04-26 02:00–04:00)

**Previous handoff (2026-04-26 W1+W2+W3+W4 close-out) is superseded.** Today's session shipped the **Google Antigravity / Gemini 3 OAuth provider** — a 20th LLM provider in Synapse-OSS that gives free-or-paid Gemini 3 Pro/Flash access via the same CodeAssist OAuth flow the official `gemini` CLI and Antigravity IDE use. End-to-end usable on Telegram with the user's Google AI Pro subscription.

## Today's commits (in order, all on `feat/jarvis-architecture`)

```
ba3d663  test(antigravity): align with OpenClaw + cover new envelope/refresh paths
b73fce1  feat(antigravity): engage paid tier via enabled_credit_types
e0e0d06  fix(antigravity): correct CodeAssist v1internal envelope + OAuth resilience
f47400e  feat(provider): add Google Antigravity (Gemini 3 via OAuth) as 20th provider
```

4 commits + 1 codex-side patch (folded into ba3d663). Branch is **23 commits ahead of `develop`, not pushed yet.** No remote tracking.

## What shipped

### New modules
- `workspace/sci_fi_dashboard/google_oauth.py` (~870 lines) — PKCE OAuth flow + Gemini CLI credential extraction + token refresh + project/tier discovery (loadCodeAssist + onboardUser) + atomic state file at `~/.synapse/state/google-oauth.json` + WSL2 detection + EADDRINUSE fallback + friendly callback URL parser.
- `workspace/sci_fi_dashboard/antigravity_provider.py` (~700 lines) — `AntigravityClient` posting to `cloudcode-pa.googleapis.com/v1internal:generateContent` with the CodeAssist envelope. Translates OpenAI messages → Gemini contents + tools. Auto-refreshes 401/403. Maps 429 → `litellm.RateLimitError`. Engages paid Pro tier via `enabled_credit_types: ["GOOGLE_ONE_AI"]`. Pro reasoning level via `thinkingConfig.thinkingLevel = LOW|HIGH`.
- `workspace/tests/test_antigravity_provider.py` (8 tests) — model resolution, schema cleanup, envelope shape, G1 credit injection, response parsing, 401 refresh retry.

### Wizard + CLI integration
- `workspace/cli/provider_steps.py` — `google_antigravity` registered in `PROVIDER_GROUPS` (Self-Hosted/Special). New `google_antigravity_oauth_flow()` mirrors the Copilot device-flow pattern, surfaces OpenClaw's account-suspension warning verbatim.
- `workspace/cli/onboard.py` — Gemini 3 model variants in `_KNOWN_MODELS["google_antigravity"]`. Provider added to per-role priority lists (casual/analysis/review/kg). OAuth branch in `_collect_provider_keys`.
- `workspace/synapse_cli.py` — new `antigravity login | status | logout` Typer subcommand group.
- `synapse.json.example` — `providers.google_antigravity` placeholder block populated by the wizard.

### Router integration
- `workspace/sci_fi_dashboard/llm_router.py` — `_GOOGLE_ANTIGRAVITY_PREFIX` detection, `_antigravity_roles` set, `_invoke_antigravity()` dispatcher, `_build_antigravity_response_shim()` to return litellm-shaped responses so `call`, `call_with_metadata`, and `call_with_tools` all work uniformly. Branches added at top of `_do_call()` and after `normalize_tool_schemas` in `call_with_tools`.

## Critical wire-format discoveries (vs OpenClaw / Gemini CLI)

The provider went through **3 wrong wire formats** before landing:

1. **First attempt** — OpenClaw's HTTP path lifted naively → 404/403. OpenClaw's `google-transport-stream.ts` posts to `/v1beta/models/{id}:generateContent` (the public Generative AI path) which requires `x-goog-api-key`, not OAuth Bearer.

2. **Second attempt** — bare body without envelope → 404 NOT_FOUND. The OAuth path requires the **CodeAssist envelope** `{model, project, user_prompt_id, request: {contents, ..., session_id}}` posted to `cloudcode-pa.googleapis.com/v1internal:generateContent`. Confirmed by reading the actual `@google/gemini-cli` bundle source (`packages/core/dist/src/code_assist/server.js`).

3. **Third attempt** — envelope correct but no identification headers → 403 PERMISSION_DENIED. Google whitelists known clients via `User-Agent: google-api-nodejs-client/9.15.1` + `X-Goog-Api-Client: gl-node/22.0.0` + `Client-Metadata: {"ideType":"IDE_UNSPECIFIED","platform":"PLATFORM_UNSPECIFIED","pluginType":"GEMINI"}`.

4. **Final correctness** — `enabled_credit_types: ["GOOGLE_ONE_AI"]` required to engage paid tier. Without it, Pro accounts bill against `standard-tier` quota. With it, requests bill against `g1-pro-tier`.

## Live verification

User has Google One AI Pro subscription. `loadCodeAssist` reports:
- `currentTier.id: "standard-tier"`
- `paidTier.id: "g1-pro-tier"`
- `paidTier.name: "Gemini Code Assist in Google One AI Pro"`
- Project: `root-shadow-ffvtg` (auto-discovered)

Live model coverage (verified on this account):
| API model id | User-facing alias | Status |
|---|---|---|
| `gemini-3-flash-preview` | `gemini-3-flash` / `gemini-3-flash-lite` | ✓ 200 |
| `gemini-3.1-pro-preview` | `gemini-3-pro-low` / `gemini-3-pro-high` | ✓ 200 |
| `gemini-3-pro-preview` | `gemini-3-pro` (legacy) | ⚠ 429-prone (separate quota pool) |

Bare aliases (`gemini-3-pro`, `gemini-3.1-pro`, `gemini-3.1-flash-preview`) return 404 NOT_FOUND. Only `-preview`-suffixed IDs are valid.

### Telegram E2E
First message ("Hiii") → "Hii bhai!" via gemini-3-flash-preview, 4.1s, 18,998 in / 53 out.

### CLI tests via `/chat/the_creator`

| Test | Component | Time | Status |
|---|---|---|---|
| T1 — "Who is your master?" | SBS persona + RAG | 6.1s | ✓ "Upayan bhai is my master..." |
| T2 — "What do you remember about Shreya?" | KG + vector RAG | 2.9s | ✓ "Shreya, or Boumuni... fan of momos and pastries... heart of your high-agency partnership" |
| T4 — "Tell me about my partner" | KG-augmented recall | 3.3s | ✓ "...your Rapido rides... 'love as an act of active defense'..." |
| Dual Cognition | Inner monologue + tension | n/a | ⚠ Architecture works; pro-high RPM (1 RPM) blocks merge call |
| T3 — Tool execution | bash_exec via tool loop | 27.5s | ✗ Tool loop fires 12 immediate retries on 429 |

## Recommended local model picks (verified live)

User's role mapping in `~/.synapse/synapse.json`:
```
casual    → google_antigravity/gemini-3-flash
code      → google_antigravity/gemini-3-pro-low  (fallback: flash)
analysis  → google_antigravity/gemini-3-pro-high (fallback: pro-low)
review    → google_antigravity/gemini-3-pro-high (fallback: pro-low)
vault     → ollama_chat/gemma4:e4b               (local, unchanged)
translate → google_antigravity/gemini-3-flash
```

`session.dual_cognition_enabled: false` — disabled because each chat fires 14+ LLM calls (2 dual-cog + 12 tool-loop + 1 main) which immediately exhausts even Pro Flash's RPM cap.

## What's left

### W6 — Tool loop convergence guard (P0 next session)

**Problem:** `pipeline.chat.call_with_tools` fires up to 12 immediate retries on 429. Each round spaced ~2s flat. No backoff. Burns through Pro Flash quota in 28s.

**Fix shape:**
- Cap `max_rounds` 12 → 3 (configurable)
- On 429 / `RateLimitError`: parse `Retry-After` header, wait min(parsed, 30s) instead of immediate retry
- Add jittered exponential backoff between rounds (1s → 2s → 5s)
- After 2 consecutive 429s, fall through to fallback model (configured via `model_mappings.<role>.fallback`)

Reference: `D:/Shorty/openclaw/src/agents/provider-transport-fetch.ts` for OpenClaw's retry/backoff pattern. (Audit dispatched but not delivered this session — re-spawn next time.)

### W7 — Dual cognition off Antigravity

**Problem:** DualCognitionEngine fires 2 calls to the analysis role per chat. With analysis=pro-high (1 RPM), instant 429.

**Fix options:**
- **A:** Route `call_ag_oracle` (in `llm_wrappers.py:42`) at a dedicated cheap model — local Ollama or `google_antigravity/gemini-3-flash-lite-preview` with `thinkingLevel: LOW`.
- **B:** Consolidate stream + merge into one prompt (single LLM call, two output sections).
- **C:** Use Gemini 3 Pro's native `thoughtSignature` instead of separate LLM call (per OpenClaw's `google-transport-stream.ts:134-139`).

Recommend A short-term (cheap), C long-term (architecturally cleanest).

### W8 — gpt-5-mini residue in traffic cop

Telegram first-message context block showed two model entries:
```
**Context Usage:** 15.6% / 1,048,576 ... **Model:** gpt-5-mini
**Context Usage:** 19,205 / 1,048,576 (1.8%) ... **Model:** gemini-3-flash-preview
```

The `gpt-5-mini` is the legacy traffic cop classifier model. With Copilot detached from synapse.json, this should fall back to a configured antigravity model. Find + fix the hardcoded reference in `route_traffic_cop` (api_gateway.py).

### Other follow-ups

| # | Item | Severity |
|---|---|---|
| 1 | Push branch to remote (`git push -u origin feat/jarvis-architecture`) | low |
| 2 | Rebase / merge to `develop` once W6+W7 land | low |
| 3 | W5 (capability-tier auto-detect + warnings) — last item from MODEL-AGNOSTIC-ROADMAP | low |
| 4 | Write `docs/antigravity-setup.md` walkthrough | medium |
| 5 | Add gemini CLI subprocess as parallel provider (`google_gemini_cli/<model>`) — different concurrency model, fallback target | low |

### Deferred bugs (carried from previous sessions)

1. **Claude via Copilot broken** — `llm_router` rewrites `github_copilot/claude-...` → `openai/...`, Copilot OpenAI endpoint refuses Claude. Workaround now moot (Copilot detached). Real fix still wanted.
2. **`/reload_config` endpoint missing** — referenced in `CORE.md` as T6+, returns 404. Restart works fine. Low priority.
3. **sqlite3 CLI not on Windows PATH** — bot needs `python -c "import sqlite3"` fallback. Documented in TOOLS.md.
4. **WhatsApp bridge crashloop** — Baileys 7.x exits code 1 on each restart attempt. Synapse keeps trying with backoff. Not blocking; investigate next session.

## Branch state

**Branch:** `feat/jarvis-architecture` — 23 commits ahead of `develop`, not pushed.

Recent commits:
```
ba3d663  test(antigravity): align with OpenClaw + cover new envelope/refresh paths
b73fce1  feat(antigravity): engage paid tier via enabled_credit_types
e0e0d06  fix(antigravity): correct CodeAssist v1internal envelope + OAuth resilience
f47400e  feat(provider): add Google Antigravity (Gemini 3 via OAuth) as 20th provider
c7389ba  docs(handoff): close out 2026-04-25/26 session — W1+W2+W3+W4 shipped
f672989  feat(parity): W4 golden behavior test suite + CI
57c2451  docs(planning): roadmap reflects W1+W2+W3 shipped same day
37a1dea  feat(runtime): wire tier-aware prompt compilation into chat pipeline
eb1ffc0  Add local tool-call resilience
bdaa25a  fix(runtime): set Ollama num_ctx default — unbreak local-mode chat
```

## Working tree (clean per OSS rules)

```
 M workspace/sci_fi_dashboard/entities.json   ← personal data, intentionally skipped
?? .planning/JARVIS-ARCH-PLAN.md             ← separate doc, untracked
?? workspace/tests/state/                    ← test scratch, untracked
```

## DB state (from previous session, not advanced)

- `memory.db`: 10,401 documents
- `knowledge_graph.db`: 876 nodes / 703 edges
- SBS `persistent_log.jsonl`: alive
- 8-layer profile JSONs: alive at `~/.synapse/workspace/sci_fi_dashboard/synapse_data/the_creator/profiles/current/`

## Architecture principles (unchanged)

1. No new tools unless mandatory + unique to Synapse
2. Jarvis → OpenClaw → plan → implement
3. Local-first grounding
4. Self-evolution via CORE.md writes
5. 1st-person voice in md templates
6. **OSS-friendliness:** every default must work on 4 GB VRAM. No personal-rig tuning for global defaults.
7. **NEW:** Antigravity OAuth client_id/secret are NEVER shipped in repo — extracted from local `@google/gemini-cli` install OR sourced from env vars (`SYNAPSE_GEMINI_OAUTH_CLIENT_ID`/_SECRET).

## User preferences (unchanged)

- **English only, no Banglish** — for documentation, commits, comments. Bot persona may use Banglish per CORE.md.
- **Local-hostable Synapse** on 8 GB VRAM hardware — proven with qwen2.5:7b at mid_open tier (vault role).
- **OSS-distributable defaults** — example files must work on a fresh fork without personal data.

## Resume checklist (first thing next session)

```bash
# 1. Server state
curl -s http://127.0.0.1:8000/health

# 2. Read this handoff
cat .planning/JARVIS-SESSION-HANDOFF.md

# 3. Verify antigravity creds
cd D:/Shorty/Synapse-OSS/workspace && python synapse_cli.py antigravity status

# 4. Check git state
git status --short
git log --oneline -10

# 5. Pick next:
#    - W6 tool-loop convergence (P0): cap max_rounds + Retry-After header parsing + jittered backoff
#    - W7 dual cognition off antigravity (P0): route call_ag_oracle at flash-lite or local Ollama
#    - W8 gpt-5-mini residue: find hardcoded reference in route_traffic_cop
#    - Push branch + open PR
```

## Known limitations (transparent to user)

- **Pro RPM caps are real and tight.** Per-account observation:
  - `gemini-3-pro-preview` (used by pro-high): ~1 RPM
  - `gemini-3.1-pro-preview` (used by pro-low/high): tighter than expected
  - `gemini-3-flash-preview`: ~30 RPM burst, sustains under spaced load
  - `enabled_credit_types: ["GOOGLE_ONE_AI"]` engages paid tier billing but does NOT raise per-minute caps — those are tier-defined limits Google enforces server-side.
- **TOS gray area.** Both OpenClaw and our integration warn that some users have reported account restrictions/suspensions after using third-party Gemini CLI / Antigravity OAuth clients.
- **WhatsApp bridge currently crashlooping** (Baileys 7.x). Telegram works fine; investigate next session.

Total session output: 4 commits + 1 codex patch, ~2200 lines added, full antigravity provider + tests + wizard + CLI integration, live-verified end-to-end on Telegram with Google One AI Pro account.
