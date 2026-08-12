# Phase 7 — W7 Dual Cognition Off Antigravity Pro

## TL;DR

Re-route `DualCognitionEngine`'s 2 LLM calls off the `analysis` role (currently `gemini-3-pro-high` @ 1 RPM) onto a dedicated cheap `oracle` role so dual cognition can be re-enabled without instant 429 cascade, restoring chat depth.

## Goal

Get `session.dual_cognition_enabled` back to `true` (it is currently `false` as a runtime workaround) without triggering the 1-RPM ceiling on `gemini-3-pro-high`. Add a config-driven `oracle` role that the dual-cog inner-monologue + tension-merge calls use, defaulting to a cheap fast model with light reasoning (e.g. `gemini-3-flash-lite-preview` with `thinkingLevel: LOW`). Long-term, replace the second LLM call entirely with the Gemini 3 Pro `thoughtSignature` mechanism Openclaw already uses.

## Severity & Effort

- **Severity:** P1 (chat depth degrades without dual cog; user explicitly noticed "AI-type and shallow" responses on 2026-04-26)
- **Effort:** S-M (~2 hr for Option A, ~6 hr for Option C)
- **Blocks:** None directly, but the workaround (`dual_cognition_enabled: false`) is degrading user-visible chat quality
- **Blocked by:** None

## Why this matters (with evidence)

Dual cognition is what makes Synapse's replies feel like a friend who actually thought before answering: an inner-monologue + tension-score pass runs *before* the persona reply, then the tone, strategy, and memory insights it produces are injected into the system prompt (see `dual_cognition.py:574-608` `build_cognitive_context`). Disable that pass and the chat path drops to a vanilla persona reply — same model, same prompt scaffold, but with no internal "what does this person actually need?" step. The user's verbatim feedback on 2026-04-26 was "responses are very you know AI type and very shallow!!" — that's the symptom of the workaround, not a model regression.

The reason the workaround had to go on at all is the LLM call math. Per chat, Synapse already fires somewhere around 14+ LLM calls across traffic-cop classification, persona reply, optional tool loop, optional auto-continue, narrative/SBS background, etc. Dual cognition layers on **2 more** calls to whatever role the wrapper resolves: one inner-monologue (`_analyze_present`) and one merge (`_merge_streams`). Both currently hit `call_ag_oracle` in `llm_wrappers.py:42`, which routes through `synapse_llm_router.call("analysis", ...)`. Today's `synapse.json` pins `analysis = google_antigravity/gemini-3-pro-high` (E3.1, E2.4). Pro-high is rated at 1 RPM on the user's tier — so a single chat fires 2 oracle calls back-to-back and the second one 429s instantly. Once that error path trips, the wider tool-loop retry (E2.1, the W6 phase) hammers it 12 more times in ~28 s, frying the budget for the next 60 s and cascading into the casual reply path too.

The current mitigation in `~/.synapse/synapse.json` is to flip the engine off: `session.dual_cognition_enabled = false` (E3.1). `chat_pipeline.py:651` honors that flag and substitutes an empty `CognitiveMerge()` (`chat_pipeline.py:705`) — replies still ship, but with zero inner monologue, zero tension scoring, zero memory-insight injection, zero tone calibration. That's exactly the "AI type and shallow" surface the user is reacting to.

The cheap structural fix is to give dual cognition its own role. The wrapper hardcodes `"analysis"` (`llm_wrappers.py:43-47`) but every other helper in that file is one-line — splitting `oracle` out is mechanical. Pair it with a model that's still capable of light reasoning JSON output (Gemini 3 Flash Lite with `thinkingLevel: LOW`, or a Groq / Ollama small-model option) and dual cog can be re-enabled without ever touching pro-high. Cross-reference E2.1 (compounding tool-loop retries on the same role) — the two phases are independent but reduce each other's blast radius.

## Current state — what's there now

### `DualCognitionEngine.think()` — 2-LLM-call surface

`workspace/sci_fi_dashboard/dual_cognition.py:209-336`. Routes through fast/standard/deep paths via a zero-LLM `classify_complexity()` triage (`dual_cognition.py:90-207`). Both standard and deep paths fire **two** oracle calls:

```python
# dual_cognition.py:254-281 (standard path)
present, memory = await asyncio.gather(
    self._analyze_present(user_message, conversation_history, llm_fn),  # LLM call #1
    self._recall_memory(user_message, chat_id, target, pre_cached_memory),  # NO LLM (uses cache)
)
...
merge = await self._merge_streams(present, memory, target, llm_fn, use_cot=False)  # LLM call #2
```

Deep path is the same shape but `_merge_streams(use_cot=True)` (`dual_cognition.py:324`). Fast path returns immediately with no LLM (`dual_cognition.py:235-244`). Note: `_extract_search_intent` exists at `dual_cognition.py:532-572` but is **dead code** (the L-01 comment at line 287 confirms it was removed from the deep path; result was never used downstream). Confirmed 2 calls, not 3.

### `call_ag_oracle` — the wrapper

`workspace/sci_fi_dashboard/llm_wrappers.py:42-47` — six lines, hardcoded role:

```python
async def call_ag_oracle(messages: list, temperature: float = 0.7, max_tokens: int = 1500) -> str:
    """AG_ORACLE (The Architect): routes to 'analysis' role in model_mappings."""
    print("[BLDG] Calling The Architect (analysis role)...")
    return await deps.synapse_llm_router.call(
        "analysis", messages, temperature=temperature, max_tokens=max_tokens
    )
```

The role name `"analysis"` is a literal string, not config-driven. Both dual-cog LLM calls flow through this single wrapper.

### Wiring from `chat_pipeline.persona_chat()`

`workspace/sci_fi_dashboard/chat_pipeline.py:648-707`. The relevant block:

```python
# chat_pipeline.py:651-666
if deps._synapse_cfg.session.get("dual_cognition_enabled", True):
    dc_timeout = deps._synapse_cfg.session.get("dual_cognition_timeout", 5.0)
    try:
        from sci_fi_dashboard.llm_wrappers import call_ag_oracle

        cognitive_merge = await asyncio.wait_for(
            deps.dual_cognition.think(
                user_message=user_msg,
                chat_id=request.user_id or "default",
                conversation_history=request.history,
                target=target,
                llm_fn=call_ag_oracle,            # <-- both internal LLM calls funnel through this
                pre_cached_memory=mem_response,
            ),
            timeout=dc_timeout,
        )
```

`call_ag_oracle` is passed as `llm_fn` and used by both `_analyze_present` (line 377) and `_merge_streams` (line 503) inside `dual_cognition.py`. Replace what `call_ag_oracle` resolves to and you replace both calls in one edit.

### Antigravity provider already supports `thinkingLevel`

`workspace/sci_fi_dashboard/antigravity_provider.py:163-188` exposes `resolve_model_with_thinking()` which translates `gemini-3-pro-low`/`-high` suffixes into `thinkingConfig.thinkingLevel = "LOW"|"HIGH"`. Flash IDs map through `_FLASH_USER_IDS` (line 85-96), and `gemini-3-flash-lite-preview` is in that set. The thinking config is applied at line 696-698:

```python
if resolution.thinking_level:
    gen_config = dict(gen_config or {})
    gen_config["thinkingConfig"] = {"thinkingLevel": resolution.thinking_level}
```

Note: `resolve_model_with_thinking` currently maps Flash variants to `thinking_level=None` unless the id contains `flash-lite`, in which case it sets `LOW` (line 183-184). So `google_antigravity/gemini-3-flash-lite-preview` already implies `thinkingLevel: LOW` end-to-end without further code changes. That makes Option A cheap to wire.

## Target state — three options, recommend Option A short-term + Option C long-term

### Option A — Route oracle at a cheap model (recommended short-term)

Add a dedicated `oracle` role in `synapse.json.example`:

```jsonc
"oracle": {
  "model": "google_antigravity/gemini-3-flash-lite-preview",
  "prompt_tier": "small",
  "fallback": "google_antigravity/gemini-3-flash"
}
```

Alternatives the user can pick at install time:

- `google_antigravity/gemini-3-flash-lite-preview` (default — already implies `thinkingLevel: LOW`, generous RPM, JSON-clean output)
- `ollama_chat/qwen2.5:7b` (zero cost, slower — bump `dual_cognition_timeout` to 10s)
- A free-tier Groq / OpenRouter small model

Change `call_ag_oracle` (`llm_wrappers.py:42`) to read role from config, default to `oracle`, fall through to `analysis` if `oracle` isn't configured (backwards-compat for users on the previous schema). Re-enable `dual_cognition_enabled: true` in the example default. Done.

### Option B — Consolidate inner-monologue + tension scoring into one prompt

Merge `_analyze_present` + `_merge_streams` into a single LLM call returning a structured JSON with both sections. Cuts 2 calls -> 1, halves the role pressure regardless of which model is configured. Higher refactor surface, more risk to existing tests. Not recommended without a strong driver — Option A solves the symptom.

### Option C — Use Gemini 3 Pro `thoughtSignature` (architectural)

Reference Openclaw's extraction: `D:/Shorty/openclaw/src/agents/openai-transport-stream.ts:1631-1646` (the `extractGoogleThoughtSignature` helper — note: the original handover prompt cited `google-transport-stream.ts:134-139`, but that file does not exist in this repo; the canonical helper lives in `openai-transport-stream.ts` at the line range above). Pro models can return a thought-signature in a single response, which Openclaw threads through subsequent tool calls. Adapting the same idea to Synapse: surface `thoughtSignature` on `AntigravityResponse` (`antigravity_provider.py:128-138`), then use it as the inner-monologue source instead of firing a second LLM call. Net: 2 calls -> 1 call on Pro, with full reasoning depth retained. Cleanest, but architecturally invasive.

## Tasks for Option A (2 hr, do this first)

- [ ] **7.1** — Add `oracle` role to `synapse.json.example` with `gemini-3-flash-lite-preview` default and explanatory comment (note: `flash-lite` already implies `thinkingLevel: LOW` via `antigravity_provider.resolve_model_with_thinking`)
- [ ] **7.2** — Update `call_ag_oracle` (`llm_wrappers.py:42`) to read role from config, default `oracle`, fall through to `analysis` if `oracle` not configured (backwards compat). Suggested shape: try `deps._synapse_cfg.session.get("dual_cognition_role", "oracle")`, then check `model_mappings`, fall back to `"analysis"` on miss.
- [ ] **7.3** — Verify `dual_cognition.py` does not need to plumb the role explicitly — it currently just receives `llm_fn=call_ag_oracle`, so 7.2 is sufficient. (Confirm via read of `dual_cognition.py:209-336`.)
- [ ] **7.4** — Add unit test in `workspace/tests/test_dual_cognition.py`: dual cog invoked with mocked router, assert `call_ag_oracle` resolves to `oracle` role when configured, falls back to `analysis` when not.
- [ ] **7.5** — Re-enable `dual_cognition_enabled: true` in `synapse.json.example` default
- [ ] **7.6** — Smoke: chat on Telegram with dual cog ON + oracle = flash-lite, observe no 429 cascade, observe `cognition.merge_done` emit fires with non-empty `inner_monologue`
- [ ] **7.7** — Document in `CLAUDE.md`: dual cog routing config, the new `oracle` role, and the `dual_cognition_role` session knob

## Tasks for Option C (separate phase, after Option A lands)

- [ ] **7.8** — Read OpenClaw `openai-transport-stream.ts:1631-1646` thoughtSignature extraction; adapt the access pattern for the CodeAssist v1internal payload shape Synapse uses (parts may carry `thoughtSignature` as a peer key, not under `extra_content.google` — confirm against a live response).
- [ ] **7.9** — Update `antigravity_provider.py` (`parse_response_payload`, `AntigravityResponse`) to surface `thoughtSignature` when present.
- [ ] **7.10** — Update `dual_cognition.py` to consume thoughtSignature instead of firing the second `_merge_streams` LLM call when the provider supports it. Keep the existing two-call path as a fallback for non-Antigravity providers.
- [ ] **7.11** — Tests + integration smoke (live Pro call asserting non-empty `thoughtSignature`).

## Dependencies

- **Hard:** None
- **Soft:** Phase 6 (W6 tool-loop guard) — reduces compound rate-limit pressure; complementary. Once Phase 6 lands, even if dual cog briefly 429s on a future config drift, the cascade will be bounded.
- **Provides:** Removes the `dual_cognition_enabled: false` workaround, restores chat depth.

## Success criteria

- [ ] `dual_cognition_enabled: true` works without 429 cascade on the default `synapse.json.example` model_mappings
- [ ] `oracle` role is configurable independently from `analysis`
- [ ] When `oracle` is unset in `model_mappings`, behavior matches the pre-change baseline (route to `analysis`) — backwards compat confirmed via test
- [ ] User's chat quality (subjective) returns to non-shallow depth — verify via 3-5 deep questions on Telegram, look for tension-aware tone shifts
- [ ] No regression in existing `tests/test_dual_cognition.py`
- [ ] (Option C only) `thoughtSignature` extracted and consumed when available; fallback to two-call path is exercised by a unit test

## Verification recipe

```bash
# 1. Re-enable dual cog and add the oracle role.
# Edit ~/.synapse/synapse.json:
#   "session": { "dual_cognition_enabled": true, ... }
#   "model_mappings": {
#     ...,
#     "oracle": {
#       "model": "google_antigravity/gemini-3-flash-lite-preview",
#       "prompt_tier": "small",
#       "fallback": "google_antigravity/gemini-3-flash"
#     }
#   }

# 2. Restart gateway (no --reload, it caches deps singletons).
#    Mac/Linux:
./synapse_stop.sh && ./synapse_start.sh
#    Windows:
synapse_start.bat   # after killing the existing python process

# 3. Send a depth-probing chat. Telegram or curl both work; curl shown for reproducibility:
curl -X POST http://127.0.0.1:8000/chat/the_creator \
  -H "Content-Type: application/json" \
  -H "X-Synapse-Token: $SYNAPSE_GATEWAY_TOKEN" \
  -d '{"message": "What is the failure mode you most worry about for me? Not the obvious one. The blind spot."}'

# Expected:
#   - HTTP 200 with non-empty reply
#   - Reply shows inner-monologue depth: tone is calibrated, references prior memory, picks
#     a non-default response_strategy ("challenge" or "quiz"), avoids generic-assistant boilerplate
#   - Gateway logs show TWO oracle calls completing (search "[BLDG] Calling The Architect")
#   - NO 429 cascade in logs (search "RateLimitError" / "429")
#   - cognition.merge_done emit fires with non-empty inner_monologue (visible in /events stream)

# 4. Run unit tests
cd workspace && pytest tests/test_dual_cognition.py -v

# 5. Confirm fallback: temporarily remove the "oracle" entry from model_mappings, restart,
#    send another chat. Should still work via the analysis-role fallback path.
```

## Risks & gotchas

- **Risk:** flash-lite's reasoning may be too shallow for tension scoring -> user-visible depth drop. Mitigation: `thinkingLevel: LOW` (already implied by the `flash-lite` id resolution in `antigravity_provider.py:183-184`) keeps light reasoning. Monitor on the first 5 deep chats; if depth is unsatisfying, swap `oracle` model to `gemini-3-pro-low`. Pro-low has higher RPM than pro-high.
- **Risk:** local Ollama (qwen2.5:7b) too slow for the 5s `dual_cognition_timeout`. Mitigation: bump `session.dual_cognition_timeout` to 10s if user picks Ollama.
- **Risk:** Existing tests in `test_dual_cognition.py` may indirectly assert behavior tied to the `analysis` role (e.g. via mocked router). A grep in this repo at the time of writing showed no hardcoded `"analysis"` literal in that test file, but re-confirm before opening the PR.
- **Gotcha:** `call_ag_oracle` is currently only called by dual cognition (verified via grep — it shows up in `chat_pipeline.py:654` and nowhere else in the production path). Still, search for callers (`grep -rn call_ag_oracle workspace/`) before changing the signature.
- **Gotcha:** The phrase "AG_ORACLE (The Architect)" appears in the docstring at `llm_wrappers.py:43`. Update the docstring with the new role name to avoid confusing the next reader.
- **Gotcha:** `synapse.json` is in `.gitignore`; only `synapse.json.example` is checked in. Make sure both the user's local file (for the runtime smoke) AND the example file (for OSS) are updated.

## Out of scope

- Phase 6 (tool-loop guard) — separate phase, complementary
- Replacing the dual cognition architecture entirely
- Adding new "tertiary cognition" layers
- Rewriting `_extract_search_intent` (already dead code per the L-01 comment in `dual_cognition.py:287`; safe to leave or delete in a separate cleanup)

## Evidence references

- E3.1 — current state: `dual_cognition_enabled: false` workaround active in `~/.synapse/synapse.json`
- E3.2 — file paths and line refs (`llm_wrappers.py:42`, `dual_cognition.py`)
- E3.3 — OpenClaw `thoughtSignature` reference for Option C
- E2.1 — compounding effect with tool-loop quota burn (12 retries on a 1 RPM model)
- E2.4 — current `model_mappings`, `analysis = pro-high` (1 RPM)

## Files touched (expected)

- `workspace/sci_fi_dashboard/llm_wrappers.py` — `call_ag_oracle` role config (Option A)
- `workspace/sci_fi_dashboard/dual_cognition.py` — only if 7.3 reveals plumbing is needed (likely not)
- `workspace/sci_fi_dashboard/antigravity_provider.py` — Option C only, surface `thoughtSignature` on `AntigravityResponse`
- `synapse.json.example` — `oracle` role + `dual_cognition_enabled: true` default
- `workspace/tests/test_dual_cognition.py` — new test for oracle/fallback resolution
- `CLAUDE.md` — document oracle role and `dual_cognition_role` knob

## Reference: OpenClaw `thoughtSignature` excerpt

Location: `D:/Shorty/openclaw/src/agents/openai-transport-stream.ts:1631-1646`. (The original prompt cited `google-transport-stream.ts:134-139`; that file does not exist — the canonical extraction helper is in `openai-transport-stream.ts` at the lines below. Use this as the reference for Option C.)

```ts
function extractGoogleThoughtSignature(toolCall: unknown): string | undefined {
  const tc = toolCall as Record<string, unknown> | undefined;
  if (!tc) {
    return undefined;
  }
  const extra = (tc.extra_content as Record<string, unknown> | undefined)?.google as
    | Record<string, unknown>
    | undefined;
  const fromExtra = extra?.thought_signature;
  if (typeof fromExtra === "string" && fromExtra.length > 0) {
    return fromExtra;
  }
  const fromFunction = (tc.function as { thought_signature?: unknown } | undefined)
    ?.thought_signature;
  return typeof fromFunction === "string" && fromFunction.length > 0 ? fromFunction : undefined;
}
```

How Openclaw consumes it (same file, lines 1371-1395 abbreviated):

```ts
const initialSig = extractGoogleThoughtSignature(toolCall);
currentBlock = {
  type: "toolCall",
  id: toolCall.id || "",
  name: toolCall.function?.name || "",
  arguments: {},
  partialArgs: "",
  ...(initialSig ? { thoughtSignature: initialSig } : {}),
};
```

The signature is then re-injected on subsequent assistant messages (lines 1696-1700) so the model can resume its prior chain of thought without re-running the reasoning pass. For Synapse Option C, the equivalent is: parse `thoughtSignature` out of the CodeAssist response, surface it on `AntigravityResponse`, and let `dual_cognition.think()` use it as the `inner_monologue` source instead of running `_merge_streams` again.
