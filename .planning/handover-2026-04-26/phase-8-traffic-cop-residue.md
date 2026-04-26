# Phase 8 — W8 `gpt-5-mini` Residue in `route_traffic_cop`

## TL;DR

The traffic-cop classifier has no dedicated model role — it piggybacks on `casual` via `call_gemini_flash`. When a stale `synapse.json` has `casual.model = "openai/gpt-5-mini"`, every chat silently fires the OpenAI classifier and bills OpenAI. Add a dedicated `traffic_cop` role with a sane default and decouple the classifier from the chat reply model.

## Goal

Make the traffic-cop classifier route through its own `model_mappings.traffic_cop.<model>` slot with a sensible default (`google_antigravity/gemini-3-flash-lite-preview`), so swapping the chat reply model never accidentally reroutes the classifier. Eliminate the silent-billing risk and the dual-model display in Telegram context blocks.

## Severity & Effort

- **Severity:** P1 (silent OpenAI billing risk + UX confusion in Telegram context display)
- **Effort:** XS (~30 min)
- **Blocks:** None
- **Blocked by:** None — fully isolated change

## Why this matters (with evidence)

Per **E4.1** in EVIDENCE.md, a Telegram first-message context block on 2026-04-26 showed two `**Model:**` entries: `gpt-5-mini` (the traffic_cop classifier) and `gemini-3-flash-preview` (the actual reply). Two model entries on a single user turn means two LLM calls — one for classification, one for the reply. The classifier call is invisible in the chat UI but very visible in OpenAI billing.

**Per E4.3, this is a silent-billing risk.** If the user has `OPENAI_API_KEY` set in the environment AND their `casual` role still references an OpenAI model (legacy from when GitHub Copilot was the primary provider), every single chat — even one routed to a Gemini reply — fires `route_traffic_cop` against OpenAI. The user pays per-chat for a classifier they never explicitly configured. Worse: the classifier prompt is only ~150 tokens but it fires on every turn, so cost compounds linearly with chat volume. A bot averaging 200 turns/day at gpt-5-mini's rate produces a non-trivial monthly OpenAI bill from a feature the user thinks is on Gemini.

**The hidden coupling, per code-graph evidence:** `route_traffic_cop` (`workspace/sci_fi_dashboard/llm_wrappers.py:89-116`) does NOT hardcode `gpt-5-mini`. It calls `call_gemini_flash` (line 109), which routes to the `casual` role. So the traffic_cop's model is whatever the chat's casual role is — they share. The `gpt-5-mini` reference the user saw in Telegram came from THEIR `synapse.json` having `casual.model = "openai/gpt-5-mini"` at the time. Today (`~/.synapse/synapse.json` snapshot 2026-04-26 07:30) all roles are pinned to `google_antigravity/gemini-3-flash`, so the immediate symptom is gone — but the architectural defect (no dedicated classifier role) remains, and the silent-billing footgun re-arms the moment a user pins `casual` to OpenAI.

**Privacy follow-on:** the same coupling means the traffic_cop classifier sees every user message — including spicy/private content that *should* route to the local `vault` role. If a user wants their chat replies on a local model but the traffic_cop is still firing against OpenAI, the classifier leaks their first-message metadata to the cloud anyway. Decoupling fixes this: a privacy-conscious user can pin `traffic_cop` to a local Ollama model (`ollama_chat/qwen2.5:7b` with the small prompt tier) and keep classification fully local even when the reply role is cloud.

**Why a 30-minute fix:** there is **no hardcoded `gpt-5-mini` string in the source tree**. Searches confirm the only references are (1) a comment in `llm_router.py:65` about restricted models that drop temperature/top_p, and (2) entity counts in `entities.json:52`. The fix is purely a config + indirection change in `llm_wrappers.py`, plus a one-line addition to `synapse.json.example`, plus tests.

## Current state — what's there now

**`route_traffic_cop` shares the casual role's model (`workspace/sci_fi_dashboard/llm_wrappers.py:89-116`):**

```python
async def route_traffic_cop(user_message: str) -> str:
    """TRAFFIC COP: Classifies message as CASUAL, CODING, ANALYSIS, REVIEW, or IMAGE."""
    system = (
        "Classify this message. Reply with EXACTLY ONE WORD: "
        "CASUAL, CODING, ANALYSIS, REVIEW, or IMAGE.\n\n"
        ...
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message},
    ]
    try:
        # Use Flash for speed; Increase tokens for thinking
        resp = await call_gemini_flash(messages, temperature=0.0, max_tokens=100)
        ...
```

And `call_gemini_flash` (`llm_wrappers.py:29-33`) routes to `casual`:

```python
async def call_gemini_flash(input_messages: list, temperature: float = 0.7, max_tokens: int = 500) -> str:
    """AG_CASUAL / TRAFFIC COP: routes to 'casual' role in model_mappings."""
    return await deps.synapse_llm_router.call("casual", input_messages, temperature, max_tokens)
```

The docstring on `call_gemini_flash` already admits the dual purpose ("AG_CASUAL / TRAFFIC COP"). The function literally cannot tell the two contexts apart at the router level — they're the same role.

**Other callsites of `call_gemini_flash`** (per Grep):
- `llm_wrappers.py:109` — the traffic_cop itself.
- `pipeline_helpers.py:170` — `auto-continue` continuation reply (legitimately uses the chat reply model).
- `_deps.py:293` — `DiaryEngine` (background diary summarization).

Of those three, only the traffic_cop case wants to be on a different (cheap, low-latency, ideally local) model than the chat reply. The other two should keep firing on `casual`.

**Config schema:** `workspace/config/schema.py:50-58` defines `AgentModelConfig` with `model`, `fallback`, `prompt_tier`, etc. No special handling for arbitrary role names — adding `traffic_cop` to `model_mappings` just works as long as `prompt_tier` is one of the allowed Literal values (or `None`). Phase 5 (capability-tier auto-detect) will then validate the new role automatically.

**`synapse.json.example`** has roles: `casual`, `code`, `analysis`, `review`, `vault`, `translate`, `kg`. No `traffic_cop`.

**The user's current `~/.synapse/synapse.json`** has all roles on `google_antigravity/gemini-3-flash`. So the bug is dormant on this specific config — the user is paying Google for the classifier, not OpenAI. But on a fresh OSS install where someone copies an old config or follows old docs, the OpenAI billing risk is one keystroke away.

## Target state

1. **`route_traffic_cop` calls `synapse_llm_router.call("traffic_cop", ...)`** directly via a new wrapper (e.g. `call_traffic_cop_classifier`), bypassing `call_gemini_flash`. The new wrapper resolves `traffic_cop` role from `model_mappings`, with a sensible default if the role is missing.

2. **Default fallback chain when `traffic_cop` role is unset:**
   - Try `model_mappings.traffic_cop.model` first.
   - If that key doesn't exist OR points to a provider with no API key configured, fall back to `model_mappings.casual.model` (preserves current behavior so this isn't a breaking change for existing configs).
   - Log the fallback at INFO level once per process (don't spam): `traffic_cop role unset, falling back to casual role for classification`.

3. **`synapse.json.example` adds the `traffic_cop` role:**

   ```json
   "traffic_cop": {
     "_model_comment": "Cheap classifier — runs on every chat turn to pick CASUAL/CODING/ANALYSIS/REVIEW/IMAGE. Should be small and fast. Default routes to a Gemini Flash Lite or local Ollama. Avoid OpenAI here unless you want per-turn billing.",
     "model": "google_antigravity/gemini-3-flash-lite-preview",
     "prompt_tier": "small",
     "fallback": "google_antigravity/gemini-3-flash"
   }
   ```

4. **Privacy-friendly variant** documented in a comment in `synapse.json.example`:

   ```json
   "_traffic_cop_privacy_alternative": "For zero-cloud classification, set: \"traffic_cop\": {\"model\": \"ollama_chat/qwen2.5:7b\", \"prompt_tier\": \"small\"}. The classifier sees every user message including spicy ones — keeping it local prevents metadata leakage to cloud providers."
   ```

5. **Tests verify the new role is used.** Existing tests in `workspace/tests/test_api_gateway.py:428-475` and `workspace/tests/pipeline/test_phase6_end_to_end.py` patch `route_traffic_cop` directly — those keep working. New tests assert the router is called with role `"traffic_cop"` and that fallback to `"casual"` triggers when `traffic_cop` is unset.

6. **Telegram context display** continues to show `**Model:**` from the chat reply — the classifier is internal infrastructure and shouldn't appear in user-facing footers. Verify by checking `chat_pipeline.py:1419-1426` (the stats footer builder) — it uses `result.model` from the reply LLMResult, not the classifier's. So no change needed in the footer; only the *root cause* of the dual-`Model:` display is the classifier model leaking into the footer when both used the same `casual` role. Once decoupled, the footer naturally shows only the reply model.

## Tasks (ordered)

- [ ] **8.1** — Add a new `call_traffic_cop_classifier` async wrapper in `workspace/sci_fi_dashboard/llm_wrappers.py`. Signature: `async def call_traffic_cop_classifier(messages: list, *, temperature: float = 0.0, max_tokens: int = 100) -> str`. Calls `deps.synapse_llm_router.call("traffic_cop", ...)`. Place it just above `route_traffic_cop` so the dependency is locally visible.

- [ ] **8.2** — Update `route_traffic_cop` to call `call_traffic_cop_classifier(messages, temperature=0.0, max_tokens=100)` instead of `call_gemini_flash(...)`. Single-line swap on `llm_wrappers.py:109`.

- [ ] **8.3** — Update `SynapseLLMRouter.call()` (or its role-resolution helper — see `workspace/sci_fi_dashboard/llm_router.py`) to fall back to `casual` when `traffic_cop` role is unset in `model_mappings`. The pattern likely already exists for `kg` role per `synapse_config.KGExtractionConfig`. Mirror that. If the fallback path doesn't exist, the cleanest spot is at the top of `call()`: `if role == "traffic_cop" and role not in self._model_mappings: role = "casual"; self._log_fallback_once()`.

- [ ] **8.4** — Update the docstring on `call_gemini_flash` (`llm_wrappers.py:29-33`) to remove the "/ TRAFFIC COP" note, since it's no longer dual-purpose. Now reads: `"AG_CASUAL: routes to 'casual' role in model_mappings."`.

- [ ] **8.5** — Add `traffic_cop` role to `synapse.json.example` in the `model_mappings` block. Default model: `google_antigravity/gemini-3-flash-lite-preview` with `prompt_tier: "small"`, fallback to `google_antigravity/gemini-3-flash`. Add the privacy-alternative comment. ~10 new lines.

- [ ] **8.6** — Add unit tests in `workspace/tests/test_llm_wrappers.py` (create file if it doesn't exist):
  - `test_route_traffic_cop_uses_traffic_cop_role` — patches `synapse_llm_router.call`, asserts called with role `"traffic_cop"`, not `"casual"`.
  - `test_route_traffic_cop_falls_back_to_casual_when_role_unset` — `model_mappings = {"casual": {...}}` (no traffic_cop key), assert classification still completes via casual.
  - `test_route_traffic_cop_returns_default_on_router_failure` — when the router raises, return `"CASUAL"` (preserves current behavior in `llm_wrappers.py:115-116`).
  - `test_route_traffic_cop_strips_punctuation` — regex cleanup at line 112 still works.

- [ ] **8.7** — Update existing tests that mock `call_gemini_flash` for traffic_cop scenarios. Search: `workspace/tests/test_api_gateway.py:446` and similar lines patch `sci_fi_dashboard.api_gateway.call_gemini_flash`. Those become stale — they should patch `sci_fi_dashboard.llm_wrappers.call_traffic_cop_classifier` instead. Audit all 6 callsites in `test_api_gateway.py` and update those that test traffic_cop classification (the others, e.g. continuation, stay on `call_gemini_flash`).

- [ ] **8.8** — Smoke-test on the user's actual config. Their `~/.synapse/synapse.json` has no `traffic_cop` role today, so the fallback path is exercised on every chat. Verify boot logs show one INFO line about the fallback, then silence. Verify a Telegram chat produces a single `**Model:**` line in the context footer (not two).

- [ ] **8.9** — Update `D:/Shorty/Synapse-OSS/CLAUDE.md` "LLM Routing (Traffic Cop → MoA)" section. Add `traffic_cop` to the role table:

  ```
  | traffic_cop | Gemini Flash Lite (default) | classifier — picks role for every chat turn |
  ```

  Add a note: `traffic_cop is a separate role from casual as of Phase 8. If unset in synapse.json, falls back to casual for backward compat.`

## Dependencies

- **Hard:** None.
- **Soft:** Phase 5 (capability-tier validator) — if Phase 5 lands first, the new `traffic_cop` role gets tier-validated for free. If Phase 8 lands first, Phase 5's validator picks it up automatically once it ships. Either order works; recommend Phase 8 first because it's smaller and fixes a real-world billing risk.
- **Provides:** Cleaner role separation that makes future per-role telemetry trivial (e.g. "you spent $X on classifier this month"). Also enables the dashboard to show classifier-vs-reply latency separately.

## Success criteria

- [ ] `grep -rn "call_gemini_flash" workspace/sci_fi_dashboard/` shows it's only used by `pipeline_helpers.py` (continuation) and `_deps.py` (DiaryEngine), NOT by `route_traffic_cop`.
- [ ] `grep -rn "traffic_cop" workspace/sci_fi_dashboard/llm_wrappers.py` shows the new `call_traffic_cop_classifier` wrapper.
- [ ] `synapse.json.example` has a `traffic_cop` role under `model_mappings`.
- [ ] All 4 new tests in `test_llm_wrappers.py` pass.
- [ ] Existing `test_api_gateway.py` and `test_phase6_end_to_end.py` test suites stay green after the patch updates.
- [ ] On the user's live `~/.synapse/synapse.json` (no `traffic_cop` role), startup logs show exactly one INFO line about the fallback to `casual`, and chat continues to work without errors.
- [ ] Telegram context block on a chat shows ONE `**Model:**` line, not two (matches reply model only).
- [ ] No new entries in OpenAI billing dashboard after a 1-hour soak with the user's current Gemini-only config (sanity check that we didn't accidentally route the classifier somewhere unexpected).

## Verification recipe

```bash
# 1. Branch
cd D:/Shorty/Synapse-OSS
git checkout -b fix/phase-8-traffic-cop-residue develop

# 2. Confirm the residue is config-only, not code (sanity check)
grep -rn "gpt-5-mini\|gpt5-mini" workspace/sci_fi_dashboard/
# Expected: only llm_router.py:65 (comment) and entities.json:52 (count). No source-code hardcode.

# 3. Run the new test file
cd workspace && pytest tests/test_llm_wrappers.py -v

# 4. Run regression on existing traffic_cop tests
pytest tests/test_api_gateway.py -k "traffic_cop" -v
pytest tests/pipeline/test_phase6_end_to_end.py -k "traffic_cop or strategy" -v

# 5. Live smoke (gateway must be running)
curl -s -X POST http://127.0.0.1:8000/chat/the_creator \
  -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"What is 2+2?","session_key":"test","user_id":"the_creator"}' \
  | grep -o '\*\*Model:\*\* [^\\n]*' | sort -u
# Expected: single Model line (the chat reply model). Pre-fix: two lines.

# 6. Telegram smoke (manual): send "What is 2+2?" via Telegram. Verify the bot's reply shows
# only ONE "**Model:**" line in the context-usage footer.

# 7. Lint + format
ruff check workspace/sci_fi_dashboard/llm_wrappers.py workspace/sci_fi_dashboard/llm_router.py
black workspace/sci_fi_dashboard/llm_wrappers.py
```

## Risks & gotchas

- **Backward compat is critical** — existing OSS users have configs without `traffic_cop`. The fallback-to-casual path MUST work silently on day one. One INFO log per process is fine; per-turn warnings are NOT.

- **DiaryEngine and auto-continue still use `call_gemini_flash`.** Don't accidentally change those callsites — they legitimately want to share the chat reply model. Audit both before committing.

- **`drop_params=True` in `llm_router.py:67`** is set globally because `gpt-5-mini` rejects `temperature`. Even if the user pins `traffic_cop` to gpt-5-mini, calls work — but they bill OpenAI. Don't remove that workaround in this phase; it's load-bearing for `analysis` role users on o1/o3-mini reasoning models too.

- **Telegram context block fix** — the dual-`Model:` display is a downstream symptom of the role coupling. Once decoupled, only the chat reply emits a context block (the classifier doesn't go through `chat_pipeline.py` at all — it's a pure `llm_router.call()` invocation that returns a single token). Verify with the curl recipe; if a second `Model:` line still appears, there's a separate bug in the footer assembly.

- **Tests that mock `call_gemini_flash` for traffic_cop scenarios** are at `test_api_gateway.py:446, 456, 465, 474, 642, 731`. Not all of those test traffic_cop — some test continuation. Read each carefully before swapping the mock target. The traffic_cop ones are around lines 428-475 (the dedicated TestRouteTrafficCop class).

- **`route_traffic_cop` still returns `"CASUAL"` on error** (current line 115-116). Keep that behavior. A hard failure in classification should not break the chat — fall through to the safest default role.

- **Don't remove `call_gemini_flash`.** It's still used by `pipeline_helpers.py:170` and `_deps.py:293`. Leave it; just stop calling it from `route_traffic_cop`.

- **The `traffic_cop` role doesn't need a `prompt_tier`** because it doesn't use the tier-aware compiler — it builds its own 6-line system prompt inline in `route_traffic_cop`. That said, for forward-compat with Phase 5 validation, default `prompt_tier=small` in the example config so the validator stays quiet.

## Out of scope

- Adding token/cost telemetry for the classifier (separate phase, requires DB schema change).
- Replacing the classifier with a deterministic regex/heuristic ("CODING if message contains code-fence" etc.) — that's an architectural shift, not a residue cleanup.
- Removing `route_traffic_cop` entirely in favor of always-on dual-cognition strategy mapping (`STRATEGY_TO_ROLE` in `llm_wrappers.py:79-86`). Today the cop still fires when `cognitive_merge.response_strategy` doesn't map to a known role. That's by design.
- Migrating the existing user's `~/.synapse/synapse.json` to add `traffic_cop`. The fallback handles existing configs cleanly; the user can opt in when they want.
- Phase 5's capability-tier warning system. Phase 5 will pick up the new role automatically.

## Evidence references

- **E4.1 / E4.2 / E4.3** in EVIDENCE.md — symptom (dual `Model:` in Telegram), search recipe, cost impact.
- `JARVIS-SESSION-HANDOFF.md:110-112` — original W8 description.
- `ROADMAP.md:30` — phase summary, severity, effort estimate.
- `workspace/sci_fi_dashboard/llm_wrappers.py:29-116` — current coupled implementation.
- `workspace/sci_fi_dashboard/chat_pipeline.py:801, 824` — callsite of `route_traffic_cop`.
- User's actual `~/.synapse/synapse.json` (snapshot 2026-04-26 07:30) confirming `casual` is currently `google_antigravity/gemini-3-flash` — symptom is dormant on this config, defect is architectural.

## Files touched (expected)

- `workspace/sci_fi_dashboard/llm_wrappers.py` — add `call_traffic_cop_classifier`, swap caller in `route_traffic_cop`, update docstring on `call_gemini_flash`. ~15 line delta.
- `workspace/sci_fi_dashboard/llm_router.py` — add fallback when `traffic_cop` role unset (resolve to `casual`). ~5 line delta.
- `synapse.json.example` — add `traffic_cop` role to `model_mappings`. ~10 new lines.
- `workspace/tests/test_llm_wrappers.py` — new file or 4 new tests. ~60 new lines.
- `workspace/tests/test_api_gateway.py` — update mock targets for traffic_cop tests. ~5 line delta across 4-6 sites.
- `D:/Shorty/Synapse-OSS/CLAUDE.md` — one row added to LLM Routing table, one note. ~3 new lines.

No edits to `chat_pipeline.py`, `api_gateway.py`, or `pipeline_helpers.py`. Pure indirection swap inside `llm_wrappers.py` plus router fallback plus docs.
