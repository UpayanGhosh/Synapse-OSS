# Phase 6 — W6 Tool-Loop Convergence Guard (P0 BLOCKING)

## TL;DR
Cap the chat-pipeline tool loop's burst behavior on 429: parse `Retry-After`, apply jittered backoff, bound total wall-clock, and fall through to `<role>_fallback` after two consecutive rate-limit hits — so a single tool-using chat on a 1 RPM provider stops burning quota in 28 seconds.

## Goal
Replace the current "12 immediate retries with fixed `await asyncio.sleep(2)`" pattern in `chat_pipeline.py` with a quota-aware retry/backoff/fallback ladder modeled on OpenClaw's `provider-transport-fetch.ts`. The pipeline must (a) honor `Retry-After` when the provider sends one, (b) cap the total wall-clock budget independently of the round count, (c) cap the round count itself to 3 by default (down from 12), and (d) cut over to the role's fallback model after two strikes — all driven by `synapse.json → tool_loop.{...}` keys with safe defaults.

## Severity & Effort
- **Severity:** P0 BLOCKING (blocks `develop → main` merge, blocks OSS release)
- **Effort:** M (~3 hr)
- **Blocks:** PR `develop → main`, OSS release tag, daily Pro-tier user reliability
- **Blocked by:** None

## Why this matters (with evidence)

Per **E2.1**, the user observed the failure mode directly during 2026-04-26 dual-cognition testing:

> **T3 — Tool execution (`bash_exec` via tool loop)**: 27.5s → ✗ Tool loop fires 12 immediate retries on 429.

The "12" matches the exact value of `MAX_TOOL_ROUNDS` defined in `workspace/sci_fi_dashboard/_deps.py:94`:

```python
# workspace/sci_fi_dashboard/_deps.py:94
MAX_TOOL_ROUNDS = 12  # bumped from 5 — Jarvis-like chains need 8-10 steps
```

This constant is consumed in `chat_pipeline.py:1141` via `_dep_int("MAX_TOOL_ROUNDS", 5)`. Inside the loop, every `RateLimitError` is caught by the substring match `if "rate" in error_str:`, then the pipeline sleeps a fixed two seconds and falls through to `continue` — **without** decrementing or aborting:

```python
# workspace/sci_fi_dashboard/chat_pipeline.py:1234-1237
elif "rate" in error_str:
    _log.warning("tool_loop_rate_limited", extra={"round": round_num})
    await asyncio.sleep(2)
    continue
```

A single tool-bearing chat therefore fires up to 12 attempts spaced ~2.3s apart (sleep + request RTT). On `casual = google_antigravity/gemini-3-flash` (10 RPM) that empties the bucket in ≈28 s — exactly the user's observed 27.5 s burn. On `analysis = google_antigravity/gemini-3-pro-high` (1 RPM, per **E2.4**), even a single tool round consumes the per-minute quota, after which all 11 subsequent rounds 429-burst into the next minute window. By the time `tool_loop_wall_clock_s = 180.0` triggers, two minutes of quota have been incinerated. With dual cognition off (per **E3.1** today's workaround), one tool-using chat fires `1 traffic_cop + 12 tool-loop = 13` calls; with dual cognition re-enabled per Phase 7's plan that becomes `2 + 1 + 12 + 1 = 16+` calls per chat — multiply by 1 RPM and the math does not work.

The provider layer makes the situation worse rather than better: `antigravity_provider.py:503-508` maps 429 to `litellm.RateLimitError` but **discards the response headers** before raising, so the `Retry-After` value Google's CodeAssist API sometimes attaches is never inspected:

```python
# workspace/sci_fi_dashboard/antigravity_provider.py:503-508
if resp.status_code == 429 or _QUOTA_HINTS.search(body or ""):
    raise RateLimitError(
        message=f"Antigravity quota exceeded for {model}: {snippet}",
        llm_provider="google_antigravity",
        model=model,
    )
```

And `llm_router.py:1996-1998` simply re-raises:

```python
# workspace/sci_fi_dashboard/llm_router.py:1996-1998
except RateLimitError as exc:
    logger.warning("Rate limit for role '%s' (tools): %s", role, exc)
    raise
```

The chat path therefore has **no retry-after awareness, no jitter, no fallback fall-through, and no ceiling shorter than 180 s**. This blocks `develop → main`: an OSS user on a free Gemini tier (Flash 10 RPM, Pro 2 RPM) will trip this immediately on their first tool-using message and a downstream support burden lands on us.

## Current state — what's there now

### Where the loop lives

The chat-pipeline tool loop is in `workspace/sci_fi_dashboard/chat_pipeline.py:1131-1376`. The relevant control surface (lines 1139-1145):

```python
# workspace/sci_fi_dashboard/chat_pipeline.py:1139-1145
_loop_start = time.time()
_cumulative_tokens = 0
max_tool_rounds = _dep_int("MAX_TOOL_ROUNDS", 5)
tool_loop_wall_clock_s = _dep_float("TOOL_LOOP_WALL_CLOCK_S", 30.0)
tool_loop_token_ratio_abort = _dep_float("TOOL_LOOP_TOKEN_RATIO_ABORT", 0.85)
tool_result_max_chars = _dep_int("TOOL_RESULT_MAX_CHARS", 4000)
max_total_tool_result_chars = _dep_int("MAX_TOTAL_TOOL_RESULT_CHARS", 20_000)
```

`_dep_int` and `_dep_float` (defined `chat_pipeline.py:333-340`) read the value from `_deps` module attributes — **not** from `synapse.json`. The defaults inside `_dep_int(...)` are dead code because `_deps.py` already defines the constants:

```python
# workspace/sci_fi_dashboard/_deps.py:94-98
MAX_TOOL_ROUNDS = 12  # bumped from 5 — Jarvis-like chains need 8-10 steps
TOOL_RESULT_MAX_CHARS = 4000
MAX_TOTAL_TOOL_RESULT_CHARS = 20_000
TOOL_LOOP_WALL_CLOCK_S = 180.0  # hard timeout on full agent loop
TOOL_LOOP_TOKEN_RATIO_ABORT = 0.8  # abort if cumulative tokens > 80% of model context
```

So the runtime values are 12 / 180.0 / 0.8 / 4000 / 20_000.

### Where 429 is handled inside the loop

The catch-all exception handler at `chat_pipeline.py:1225-1241` does substring matching on `str(e).lower()`:

```python
# workspace/sci_fi_dashboard/chat_pipeline.py:1225-1241
except Exception as e:
    error_str = str(e).lower()
    if "context" in error_str or "token" in error_str:
        _log.warning("tool_loop_context_overflow", extra={"round": round_num})
        tool_schemas = None
        continue
    elif "rate" in error_str:
        _log.warning("tool_loop_rate_limited", extra={"round": round_num})
        await asyncio.sleep(2)
        continue
    else:
        _log.error("tool_loop_llm_error", extra={"round": round_num, "error": str(e)})
        reply = "I encountered an error processing your request. Please try again."
        break
```

This is the burst source. Twelve rounds × `await asyncio.sleep(2)` + RTT ≈ 28 s of attempts on the same 1 RPM bucket.

### Where 429 is propagated by the router

`llm_router.py:1996-1998` (inside `call_with_tools`):

```python
# workspace/sci_fi_dashboard/llm_router.py:1996-1998
except RateLimitError as exc:
    logger.warning("Rate limit for role '%s' (tools): %s", role, exc)
    raise
```

Notably, the `litellm.Router` itself is constructed with `num_retries=0, retry_after=0` (`llm_router.py:1084-1085`), so SDK-level retries are already disabled. The retries we are seeing originate **only** from the `chat_pipeline.py` loop above, not from litellm.

### Where 429 is mapped from the provider

`antigravity_provider.py:503-508` (already quoted above) maps 429 to `RateLimitError` without reading the `Retry-After` header off the `httpx.Response`. The provider also does not surface the underlying `httpx.Response.headers` mapping — it constructs the `RateLimitError` only from the body snippet.

### What exists already that we can leverage

`InferenceLoop` in `llm_router.py:2104-2333` already implements the right shape for `call()` (non-tools): exponential backoff with jitter on `RATE_LIMIT`, fallback rotation on `MODEL_NOT_FOUND`, profile rotation on `AUTH`. Specifically `llm_router.py:2275-2290`:

```python
# workspace/sci_fi_dashboard/llm_router.py:2275-2290
if reason == AuthProfileFailureReason.RATE_LIMIT:
    if attempt < self._max_attempts - 1:
        base_delay = 2 ** (attempt + 1)  # 2, 4, 8
        jitter = random.uniform(0, base_delay * 0.5)
        delay = base_delay + jitter
        logger.info("Rate limited — backing off %.1fs before retry", delay)
        if self._auth_store is not None and active_profile is not None:
            self._auth_store.report_failure(
                active_profile.id,
                AuthProfileFailureReason.RATE_LIMIT,
                model=role,
            )
        await asyncio.sleep(delay)
        continue
    raise
```

But `call_with_tools` does not route through `InferenceLoop` — it hits `_router.acompletion()` directly at `llm_router.py:1976`. That's the gap to close.

`channels/discord_channel.py:321-337` already does the right thing for Discord 429s (parse `retry_after`, add jitter, retry once) — useful precedent, but the Python value comes from `discord.HTTPException.retry_after`, not from raw HTTP headers. We need a header-based parser.

## Target state — what it should do after

After this phase, the tool loop has the following deterministic budget shape:

1. **Round cap.** `MAX_TOOL_ROUNDS` defaults to **3** (down from 12), driven by `synapse.json → tool_loop.max_rounds`. The 12-step Jarvis chain rationale in the comment at `_deps.py:94` is preserved as a config option (users can opt back in), but the OSS default is 3.
2. **Per-round retry on 429.** When `call_with_tools` raises `RateLimitError`:
   - Parse `Retry-After` from the underlying response (seconds-int form **and** HTTP-date form).
   - Sleep `min(parsed_retry_after, tool_loop.retry_after_max)` (default `retry_after_max = 30`).
   - If no `Retry-After` header is present, sleep `jittered_backoff(attempt) = base * 2**attempt * (1 ± 0.2)` with `base = tool_loop.backoff_base_sec` (default 1.0 s), capped at `retry_after_max`.
   - Retry **at most once** per round. A second consecutive 429 in the same round counts as a "strike" and exits the round.
3. **Total wall-clock budget.** A new `tool_loop.total_budget_sec` (default 60) caps the *entire* loop including all sleeps. If `time.monotonic() - start > total_budget_sec`, abort cleanly and return whatever text we have. This replaces the 180 s `TOOL_LOOP_WALL_CLOCK_S` for OSS users (the 180 s value can stay as the upper bound but the new key is the operational ceiling).
4. **Two-strike fallback.** Track consecutive 429s across the loop. After **2** strikes, swap `role` to `f"{role}_fallback"` and re-enter the next round through `call_with_tools(role=fallback_role, ...)`. The fallback is sourced from `model_mappings[<role>].fallback`. If the fallback role does not have tool-calling support (per its provider's known capability table), log a warning, drop tool schemas, and call `call_with_metadata(fallback_role, ...)` for a final text-only reply. **Do not** keep retrying on the original role.
5. **Provider-side header preservation.** Update `antigravity_provider._raise_for_status` to attach `response.headers` to the `RateLimitError` it raises (litellm already supports `response_headers` on the error object). The chat-pipeline retry layer reads the headers off the exception.
6. **All numbers configurable.** New `synapse.json` block:
   ```json
   "tool_loop": {
     "max_rounds": 3,
     "max_wait_sec": 30,
     "retry_after_max": 30,
     "total_budget_sec": 60,
     "backoff_base_sec": 1.0,
     "max_strikes_before_fallback": 2
   }
   ```
   Add to `SynapseConfig` as a `tool_loop: dict` field (mirrors `session`, `bridge`).
7. **Telemetry.** Each retry/backoff/fallback decision emits a structured log line with `role`, `attempt`, `retry_after_sec`, `decision` ∈ `{retry, backoff, fallback, abort}`. The existing `_log.warning("tool_loop_rate_limited", ...)` becomes `_log.info("tool_loop_decision", extra={...})`.

## Tasks (ordered)

- [ ] **6.1** — Add `tool_loop: dict` field to `SynapseConfig` (`workspace/synapse_config.py:79-117`). Wire it through `load()` (mirror the `session = raw.get("session", {})` pattern at line 175). Add fallback defaults in a small `_TOOL_LOOP_DEFAULTS` constant. Files: `workspace/synapse_config.py`.
- [ ] **6.2** — Replace the hard-coded `MAX_TOOL_ROUNDS = 12` in `_deps.py:94` with a runtime-resolved value: `MAX_TOOL_ROUNDS = _synapse_cfg.tool_loop.get("max_rounds", 3)` (after `_synapse_cfg` is constructed at line 256). Same for `TOOL_LOOP_WALL_CLOCK_S` (becomes `total_budget_sec`). Files: `workspace/sci_fi_dashboard/_deps.py`.
- [ ] **6.3** — Add a `_parse_retry_after(headers: Mapping[str, str] | None) -> float | None` helper in `llm_router.py` (or a new `workspace/sci_fi_dashboard/retry_helpers.py`). Must handle: (a) integer-seconds string (`"30"`), (b) float-seconds string (`"2.5"`), (c) HTTP-date per RFC 7231 (`"Wed, 21 Oct 2025 07:28:00 GMT"`). Returns `None` if header absent/unparseable. Mirror the OpenClaw `parseRetryAfterSeconds` logic — see Reference section below. Files: `workspace/sci_fi_dashboard/llm_router.py` (or new `retry_helpers.py`).
- [ ] **6.4** — Update `antigravity_provider._raise_for_status` (`antigravity_provider.py:490-525`) to capture `resp.headers` and attach them to the raised `RateLimitError` via the `response_headers` kwarg (litellm exception API supports this). Files: `workspace/sci_fi_dashboard/antigravity_provider.py`.
- [ ] **6.5** — Replace the chat-pipeline 429 branch (`chat_pipeline.py:1234-1237`) with a per-round retry block that: (a) extracts headers from the exception, (b) calls `_parse_retry_after`, (c) sleeps `min(parsed, retry_after_max)` if header present, else `jittered_backoff(round_num, backoff_base_sec)` capped at `retry_after_max`, (d) retries once, (e) on a second 429 in the same round increments a `consecutive_429_strikes` counter. Files: `workspace/sci_fi_dashboard/chat_pipeline.py`.
- [ ] **6.6** — Add the two-strike fallback inside the same loop. When `consecutive_429_strikes >= max_strikes_before_fallback`, switch `role` to `f"{role}_fallback"` for the remainder of the loop, reset the strike counter, and log `tool_loop_fallback_engaged`. Detect at config-load time whether the fallback model supports tool-calling; if not, drop `tool_schemas` and switch to `call_with_metadata` for a final round. Files: `workspace/sci_fi_dashboard/chat_pipeline.py`, possibly `workspace/sci_fi_dashboard/llm_router.py` for a `supports_tools(role)` helper.
- [ ] **6.7** — Add the total-budget timeout. At the top of each round iteration (currently `chat_pipeline.py:1147-1160`), compute `time.monotonic() - _loop_start` against `total_budget_sec` (new), and abort returning whatever `result.text` exists. The existing `tool_loop_wall_clock_exceeded` path is the right shape — just rename its key and lower the threshold. Files: `workspace/sci_fi_dashboard/chat_pipeline.py`.
- [ ] **6.8** — Update `synapse.json.example` to add the `"tool_loop": {...}` block with all six keys, sane defaults, and a `_comment` explaining what each does. Files: `synapse.json.example`.
- [ ] **6.9** — Add `workspace/tests/test_tool_loop_guard.py`. Required cases:
  - `test_retry_after_seconds_int_form` — feed `"Retry-After: 2"`, assert sleep is ≈2 s.
  - `test_retry_after_http_date_form` — feed `"Retry-After: Wed, 21 Oct 2025 07:28:00 GMT"`, assert sleep matches `(parsed_date - now)`.
  - `test_retry_after_caps_at_max_wait` — feed `"Retry-After: 120"` with `retry_after_max=30`, assert sleep is 30 s, not 120.
  - `test_jittered_backoff_bounds` — for round_num ∈ {0, 1, 2}, assert delay ∈ [`base * 2**n * 0.8`, `base * 2**n * 1.2`].
  - `test_total_budget_aborts_loop` — mock `time.monotonic` to exceed `total_budget_sec` at round 1, assert loop returns early with a partial reply.
  - `test_two_strike_fallback` — return RateLimitError twice on `casual`, assert third round fires on `casual_fallback`.
  - `test_fallback_without_tool_support` — fallback role flagged `supports_tools=False`, assert pipeline drops schemas and uses `call_with_metadata`.
  - `test_no_retry_after_header_falls_through_to_jitter` — RateLimitError with empty headers, assert backoff path is taken.
  Files: `workspace/tests/test_tool_loop_guard.py` (new).
- [ ] **6.10** — Run integration smoke. With `casual = google_antigravity/gemini-3-pro-high` (1 RPM), send a tool-using prompt, observe logs for: ≤3 rounds, ≤1 retry per round, fallback firing on 2nd 429, total wall time ≤ 60 s. Capture log excerpt in commit message. Files: none — runtime verification.
- [ ] **6.11** — Update `CLAUDE.md` "Configuration" section to document the new `tool_loop` keys. Files: `CLAUDE.md`.

## Dependencies

- **Hard:** None.
- **Soft:** Phase 7 (W7 dual-cog routing) reduces overall tool-loop traffic and is complementary — landing 7 first would slightly reduce the urgency of 6, but 6 is the harder requirement. Land 6 first.
- **Provides:** Unblocks the `develop → main` PR. Indirect benefit to Phase 7: with the budget guard in place, Phase 7 can re-enable dual cognition without compounding the burn.

## Success criteria

- [ ] `tool_loop.max_rounds` defaults to 3, configurable via `synapse.json`. Verify: `grep MAX_TOOL_ROUNDS workspace/sci_fi_dashboard/_deps.py` shows the runtime-resolved value, not `12`.
- [ ] `Retry-After` header is honored. Verify: `pytest workspace/tests/test_tool_loop_guard.py::test_retry_after_seconds_int_form workspace/tests/test_tool_loop_guard.py::test_retry_after_http_date_form -v` passes.
- [ ] No more than 3 immediate retries on 429 before fallback kicks in. Verify: integration smoke (task 6.10) log shows `tool_loop_fallback_engaged` after the 2nd 429.
- [ ] Jittered backoff between rounds (1 / 2 / 4 s × ±20%, base configurable). Verify: `test_jittered_backoff_bounds`.
- [ ] Total tool-loop wall time bounded by configurable budget (default 60 s). Verify: `test_total_budget_aborts_loop` plus the smoke shows total elapsed ≤ 60 s in the abort path.
- [ ] On 2 consecutive 429s, fallback model fires. Verify: `test_two_strike_fallback`.
- [ ] Antigravity provider attaches headers to `RateLimitError`. Verify: a probe test in `test_tool_loop_guard.py` mocks `httpx.Response` with a `Retry-After: 5` header and asserts the raised exception's `response_headers` contains it.
- [ ] All config keys documented in `synapse.json.example` + `CLAUDE.md`. Verify: `grep tool_loop synapse.json.example CLAUDE.md`.
- [ ] Integration smoke: tool-using chat on a 1 RPM provider does **not** burn quota past one minute window. Verify: capture from task 6.10.

## Verification recipe

```bash
# 1. Unit tests
cd workspace && pytest tests/test_tool_loop_guard.py -v

# 2. Lint
ruff check workspace/sci_fi_dashboard/ workspace/tests/test_tool_loop_guard.py
black --check workspace/sci_fi_dashboard/ workspace/tests/test_tool_loop_guard.py

# 3. Force a 429 cascade in a controlled environment.
#    Edit ~/.synapse/synapse.json:
#      "model_mappings": {
#        "casual": { "model": "google_antigravity/gemini-3-pro-high",
#                    "fallback": "google_antigravity/gemini-3-flash" }
#      }
#    Restart the gateway, then:
curl -X POST http://127.0.0.1:8000/chat/the_creator \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SYNAPSE_GATEWAY_TOKEN" \
  -d '{"message": "use bash_exec to run pwd"}'

#    Watch logs for:
#      - tool_round_start  round=0
#      - tool_loop_rate_limited  round=0  retry_after=<X>
#      - tool_round_start  round=1
#      - tool_loop_rate_limited  round=1
#      - tool_loop_fallback_engaged  fallback_role=casual_fallback
#      - tool_loop_done  total_time_s<=60

# 4. Verify the chat still completes successfully on fallback.
#    Response body should contain the bash_exec output (cwd path), not
#    "I encountered an error processing your request."

# 5. Confirm flipping dual_cognition back on does not regress.
#    Edit synapse.json: "session.dual_cognition_enabled": true
#    Re-send the curl above. Should still complete within total_budget_sec.
#    (Phase 7 owns the formal flip — this is just a smoke check.)
```

## Risks & gotchas

- **Risk:** Removing the 12-retry burst may break legitimate flaky-network recovery on stable providers. Mitigation: jittered backoff (1 / 2 / 4 s) + the 2-strike fallback covers transient flakes; the previous 12 immediate retries with no backoff weren't actually helping recovery, they were just emptying the bucket faster.
- **Risk:** `Retry-After` from antigravity may be missing — Google's CodeAssist API does not always send the header on 429, especially the upstream "RESOURCE_EXHAUSTED" path. Mitigation: when header absent, fall through to the jittered-backoff path. Both are bounded by `retry_after_max`.
- **Risk:** Fallback model may not have tool-calling support (e.g. user configures `casual_fallback = ollama_chat/qwen2.5:7b` which Synapse currently text-mode-only). Mitigation: detect at config-load time; if `supports_tools(fallback_role) is False`, log a warning at startup and on engagement, drop `tool_schemas`, and call `call_with_metadata` for the final round. Test case `test_fallback_without_tool_support` covers this.
- **Risk:** The change to `antigravity_provider._raise_for_status` to attach `response_headers` to `RateLimitError` may interact with other callers that catch and inspect the exception. Mitigation: `RateLimitError(response_headers=...)` is the litellm-native kwarg; existing callers use `str(exc)` only. Search-verified: `grep -rn "RateLimitError" workspace/sci_fi_dashboard/ | grep -v 'raise\|except' → 0 hits` for header inspection today, so this is additive.
- **Risk:** `tool_loop.total_budget_sec = 60` may cut off legitimately long tool chains (e.g. a multi-step bash sequence). Mitigation: keep the existing `TOOL_LOOP_WALL_CLOCK_S = 180.0` as the upper safety bound, treat the new `total_budget_sec` as the OSS-default; users running Jarvis-class chains can raise both via config.
- **Gotcha:** `_dep_int / _dep_float` in `chat_pipeline.py:333-340` reads from the `_deps` module attribute, not from `SynapseConfig`. The clean fix is to set the `_deps` constants from the config at import time (task 6.2). Don't try to thread the config object into the loop function — too invasive.
- **Gotcha:** litellm's `RateLimitError` lives in `litellm.exceptions`. The optional `response_headers` parameter is supported on litellm 1.40+; verify the project's pinned version (`grep litellm workspace/requirements*.txt`) supports it before relying on it. If not, attach headers to a custom subclass or via `exc.headers = {...}` after construction.
- **Gotcha:** `dual_cognition_enabled: false` workaround in `synapse.json` (per **E3.1**) compounds and is removable after this lands — but explicitly test before flipping. Phase 7 owns flipping it; this phase only needs to not regress when it's `false`.
- **Gotcha:** The chat_pipeline 429 catch uses `if "rate" in error_str:`, which is brittle. After this phase, switch to `isinstance(e, RateLimitError)` directly. The substring fallback can stay as a secondary guard for non-litellm errors.

## Out of scope

- Re-enabling dual cognition globally (Phase 7 owns that).
- Routing dual cog at a cheaper model (Phase 7).
- Replacing tool-loop architecture entirely (out of all phases — too big).
- Provider-level rate-limit budgeting / token bucket awareness (future work; this phase is reactive, not proactive).
- Adapting `InferenceLoop` to wrap `call_with_tools` (architecturally cleaner but ~2x effort; defer to a follow-up phase).

## Evidence references

- **E2.1** — Symptom from session log (12 retries, 27.5 s burn). `.planning/handover-2026-04-26/EVIDENCE.md:202-208`.
- **E2.2** — Code locations (`api_gateway`, `chat_pipeline`, `llm_router`). `EVIDENCE.md:210-223`.
- **E2.3** — OpenClaw retry/backoff reference pattern. `EVIDENCE.md:225-249`.
- **E2.4** — Current `synapse.json` model picks (1 RPM analysis = instant exhaustion). `EVIDENCE.md:251-262`.
- **E3.1** — Why dual cognition is currently disabled (compounds the problem). `EVIDENCE.md:268-278`.
- **E8** — Index of relevant code paths (`Tool loop` row). `EVIDENCE.md:418-432`.

## Files touched (expected)

- `workspace/sci_fi_dashboard/_deps.py` — replace hard-coded `MAX_TOOL_ROUNDS = 12` with config-driven value (task 6.2).
- `workspace/sci_fi_dashboard/llm_router.py` — add `_parse_retry_after` helper, optional `supports_tools(role)` helper (tasks 6.3, 6.6).
- `workspace/sci_fi_dashboard/chat_pipeline.py` — replace 429 branch with retry/backoff/fallback ladder; rename wall-clock guard to `total_budget_sec` (tasks 6.5, 6.6, 6.7).
- `workspace/sci_fi_dashboard/antigravity_provider.py` — preserve `response.headers` on `RateLimitError` (task 6.4).
- `workspace/synapse_config.py` — add `tool_loop: dict` field, plumb through `load()` (task 6.1).
- `synapse.json.example` — new `tool_loop` block with comments (task 6.8).
- `workspace/tests/test_tool_loop_guard.py` — new test file (task 6.9).
- `CLAUDE.md` — document new config keys under "Configuration → synapse.json" (task 6.11).

## Reference: OpenClaw retry pattern

OpenClaw's `provider-transport-fetch.ts` (see `D:/Shorty/openclaw/src/agents/provider-transport-fetch.ts:11-76`) handles `Retry-After` with the precise shape we want. The key excerpt:

```ts
// D:/Shorty/openclaw/src/agents/provider-transport-fetch.ts:11-76
const DEFAULT_MAX_SDK_RETRY_WAIT_SECONDS = 60;

function parseRetryAfterSeconds(headers: Headers): number | undefined {
  const retryAfterMs = headers.get("retry-after-ms");
  if (retryAfterMs) {
    const milliseconds = Number.parseFloat(retryAfterMs);
    if (Number.isFinite(milliseconds) && milliseconds >= 0) {
      return milliseconds / 1000;
    }
  }

  const retryAfter = headers.get("retry-after");
  if (!retryAfter) {
    return undefined;
  }

  const seconds = Number.parseFloat(retryAfter);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return seconds;
  }

  const retryAt = Date.parse(retryAfter);
  if (Number.isNaN(retryAt)) {
    return undefined;
  }

  return Math.max(0, (retryAt - Date.now()) / 1000);
}

function shouldBypassLongSdkRetry(response: Response): boolean {
  const maxWaitSeconds = resolveMaxSdkRetryWaitSeconds();
  if (maxWaitSeconds === undefined) {
    return false;
  }
  const status = response.status;
  const stainlessRetryable = status === 408 || status === 409 || status === 429 || status >= 500;
  if (!stainlessRetryable) {
    return false;
  }
  const retryAfterSeconds = parseRetryAfterSeconds(response.headers);
  if (retryAfterSeconds !== undefined) {
    return retryAfterSeconds > maxWaitSeconds;
  }
  return status === 429;
}
```

Three properties to mirror in Python:

1. **Two header names accepted.** OpenClaw checks `retry-after-ms` first (millisecond precision, used by some Anthropic endpoints) and falls back to `retry-after` (seconds or HTTP-date). Synapse should do the same.
2. **Two value forms for `retry-after`.** Number-parseable as seconds, OR `Date.parse`-able as an HTTP date — fall through gracefully when neither parses.
3. **Cap by max-wait policy.** If the parsed value exceeds the cap (`OPENCLAW_SDK_RETRY_MAX_WAIT_SECONDS`, default 60), OpenClaw refuses to retry that long and throws back to the caller. Synapse's equivalent is `tool_loop.retry_after_max` — same intent: don't trust a server that says "wait 5 minutes" inside a 60 s pipeline budget.

Python translation sketch (target shape; not a final patch):

```python
# workspace/sci_fi_dashboard/llm_router.py (or new retry_helpers.py)
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Mapping

def _parse_retry_after(headers: Mapping[str, str] | None) -> float | None:
    """Parse Retry-After / Retry-After-Ms headers per RFC 7231.

    Returns seconds-to-wait as float, or None if header absent/unparseable.
    Mirrors openclaw/src/agents/provider-transport-fetch.ts:13-38.
    """
    if not headers:
        return None
    # Millisecond form (Anthropic convention)
    ms = headers.get("retry-after-ms") or headers.get("Retry-After-Ms")
    if ms:
        try:
            v = float(ms)
            if v >= 0:
                return v / 1000.0
        except ValueError:
            pass
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if not raw:
        return None
    # Numeric seconds form
    try:
        v = float(raw)
        if v >= 0:
            return v
    except ValueError:
        pass
    # HTTP-date form
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    delta = (when - datetime.now(timezone.utc)).total_seconds()
    return max(0.0, delta)


import random

def _jittered_backoff(attempt: int, base_sec: float, jitter_pct: float = 0.2) -> float:
    """Exponential backoff with multiplicative jitter.

    attempt=0 → base (1.0 s default); attempt=1 → 2*base; attempt=2 → 4*base.
    Final value scaled by uniform(1 - jitter_pct, 1 + jitter_pct).
    """
    raw = base_sec * (2 ** attempt)
    factor = 1.0 + random.uniform(-jitter_pct, jitter_pct)
    return raw * factor
```

And the loop-level wrapper inside `chat_pipeline.py` (replacing lines 1234-1237):

```python
# Sketch — see task 6.5 for the full integration
elif isinstance(e, RateLimitError) or "rate" in error_str:
    headers = getattr(e, "response_headers", None) or getattr(e, "headers", None)
    parsed = _parse_retry_after(headers)
    if parsed is not None:
        delay = min(parsed, retry_after_max)
        decision = "retry_after"
    else:
        delay = min(_jittered_backoff(round_num, backoff_base_sec), retry_after_max)
        decision = "backoff"
    _log.info(
        "tool_loop_decision",
        extra={
            "round": round_num,
            "decision": decision,
            "delay_sec": round(delay, 2),
            "strikes": consecutive_429_strikes,
        },
    )
    consecutive_429_strikes += 1
    if consecutive_429_strikes >= max_strikes_before_fallback:
        fallback_role = f"{role}_fallback"
        if fallback_role in deps._synapse_cfg.model_mappings:
            _log.warning(
                "tool_loop_fallback_engaged",
                extra={"from_role": role, "to_role": fallback_role},
            )
            role = fallback_role
            consecutive_429_strikes = 0
        else:
            _log.warning("tool_loop_fallback_unavailable", extra={"role": role})
            reply = "I'm hitting rate limits and have no fallback configured."
            break
    await asyncio.sleep(delay)
    continue
```

The implementer should verify litellm's `RateLimitError` exposes `response_headers` on the project's pinned version; if not, fall back to constructing a custom subclass or attaching `exc.headers` post-hoc inside `antigravity_provider._raise_for_status`.
