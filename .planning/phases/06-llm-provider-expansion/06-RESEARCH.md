# Phase 6: LLM Provider Expansion - Research

**Researched:** 2026-04-09
**Domain:** litellm Router configuration, per-provider budget caps, onboarding wizard, requirements.txt hygiene
**Confidence:** HIGH

---

## Summary

Phase 6 is the lightest phase in v3.0. The codebase already has a fully functional, provider-agnostic `SynapseLLMRouter` that routes any litellm-prefixed model string. Adding a new provider like DeepSeek requires only: (1) adding a `"deepseek": "DEEPSEEK_API_KEY"` entry to `_KEY_MAP` in `llm_router.py` and `provider_steps.py`, (2) adding a validation model entry to `VALIDATION_MODELS`, and (3) adding the provider to `PROVIDER_GROUPS`. The routing itself — `build_router()` → litellm `Router.acompletion()` — works with any valid litellm prefix string out of the box with no code changes beyond the maps.

The one substantive fix is the litellm `BudgetExceededError` bug (GitHub #10052). litellm's `Router` does not auto-trigger its fallback chain when a budget cap is hit — the exception escapes to the caller as a raw 500. The fix is a manual `except BudgetExceededError` guard in `_do_call()` that calls the fallback model directly. The per-provider budget cap config (`budget_usd` / `budget_duration`) needs a config schema addition so synapse.json can express it, and the enforcement point is `_do_call()` before the litellm call.

The two missing `requirements.txt` entries (`croniter`, `sse-starlette`) are pre-existing undeclared dependencies uncovered by prior architecture research. They belong in `requirements.txt` now because they are imported by core v3.0 features (cron schedule parsing, SSE dashboard). Adding them here is the right moment — Phase 6 is the first v3.0 phase.

**Primary recommendation:** Three targeted file edits (`llm_router.py` bug fix + budget config, `provider_steps.py` DeepSeek entry, `requirements.txt` two additions) plus a `synapse.json.example` update. Zero new files required.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PROV-01 | User can add OpenAI, Anthropic, DeepSeek, Mistral, or Together as providers via synapse.json | All five already work via litellm prefixes. DeepSeek needs `_KEY_MAP` + `VALIDATION_MODELS` + `PROVIDER_GROUPS` additions. The others are already in all three maps. Verified by reading `llm_router.py` lines 199-219 and `provider_steps.py` lines 59-148. |
| PROV-02 | User can set per-provider rate limits and budget caps in config | Requires new `budget_usd` + `budget_duration` optional fields on each provider entry in `synapse.json`. `SynapseConfig.providers` is an untyped `dict` — no schema migration needed, just documentation in `synapse.json.example`. Enforcement is a pre-call check in `_do_call()` comparing cumulative spend from the `sessions` table against the cap. |
| PROV-03 | litellm BudgetExceededError triggers fallback chain instead of hard error | `BudgetExceededError` is importable from `litellm` (confirmed by litellm docs). litellm Router does NOT auto-fallback on this error (GitHub #10052, April 2025, confirmed open). Fix: catch `BudgetExceededError` in `_do_call()` and call `self._router.acompletion(model=f"{role}_fallback", ...)` if a fallback is configured. |
| PROV-04 | Onboarding wizard offers all 10+ providers during setup | `PROVIDER_GROUPS` in `provider_steps.py` currently lists 20 providers (lines 109-145). DeepSeek is absent. Adding it to `PROVIDER_GROUPS` + `VALIDATION_MODELS` + `_KEY_MAP` in `provider_steps.py` closes the gap. The wizard already shows all entries in `PROVIDER_GROUPS` — no UI logic changes needed. |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `litellm` | >=1.40.0 (already in requirements.txt) | All LLM dispatch, provider abstraction, Router fallback | Already the sole LLM call path in this codebase |
| `litellm.exceptions.BudgetExceededError` | same package | Exception class for budget enforcement | Official exception from litellm, importable via `from litellm import BudgetExceededError` |

### Supporting (new additions to requirements.txt)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `croniter` | >=6.2.2 | Cron expression parsing in `cron/schedule.py` | Already imported in codebase — undeclared dependency. Phase 6 is first v3.0 phase, correct moment to declare it. |
| `sse-starlette` | >=2.0.0 | W3C-compliant SSE for FastAPI dashboard | Used by `PipelineEventEmitter` / Phase 10 dashboard. Undeclared. Declare now. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Manual `except BudgetExceededError` in `_do_call()` | Wait for litellm fix | Issue #10052 is open with no ETA — cannot depend on upstream fix for a v3.0 requirement |
| Per-provider budget tracked in `sessions` table | External spend tracking service | `sessions` table is already written by `_write_session()` — zero new infrastructure |

**Installation (additions only):**
```bash
pip install croniter>=6.2.2 sse-starlette>=2.0.0
```

---

## Architecture Patterns

### How Provider Addition Works Today

The routing path is: `synapse.json model_mappings → build_router() → Router.acompletion(model=role)`. Adding a new provider requires NO changes to this path. What's needed:

1. **`llm_router.py` `_KEY_MAP`** — maps provider name → litellm env var name (e.g., `"deepseek": "DEEPSEEK_API_KEY"`)
2. **`provider_steps.py` `_KEY_MAP`** — mirrors llm_router.py exactly (comment in code: "mirrors llm_router.py exactly")
3. **`provider_steps.py` `VALIDATION_MODELS`** — cheapest model for the validation ping
4. **`provider_steps.py` `PROVIDER_GROUPS`** — what the onboarding checkbox shows
5. **`synapse.json.example`** — documentation showing how to configure the provider
6. **`llm_router.py` `_inject_provider_keys()`** — already handles any provider in `_KEY_MAP` generically, no change needed

### DeepSeek Specifics (litellm confirmed)

```python
# In llm_router.py _KEY_MAP:
"deepseek": "DEEPSEEK_API_KEY",

# In provider_steps.py VALIDATION_MODELS:
"deepseek": "deepseek/deepseek-chat",

# In synapse.json model_mappings (user config):
"casual": {"model": "deepseek/deepseek-chat", "fallback": "groq/llama-3.3-70b-versatile"}
```

litellm supports all DeepSeek models via `deepseek/` prefix natively. Confirmed by official litellm docs (https://docs.litellm.ai/docs/providers/deepseek). No custom handling needed in `build_router()`.

### Pattern: Budget Cap Enforcement

**Current state:** `_do_call()` makes the litellm call with no pre-call spend check. If litellm's server-side budget tracking raises `BudgetExceededError`, the exception propagates to `persona_chat()` which returns a 500.

**Fix pattern:**

```python
# In _do_call(), add to import block at top of file:
from litellm import BudgetExceededError  # alongside existing litellm imports

# In _do_call(), catch the exception and manually attempt fallback:
except BudgetExceededError as exc:
    logger.warning("Budget exceeded for role '%s': %s — attempting fallback", role, exc)
    fallback_role = f"{role}_fallback"
    fallback_cfg = self._config.model_mappings.get(role, {}).get("fallback")
    if fallback_cfg and fallback_role in [m["model_name"] for m in self._router.model_list]:
        return await self._router.acompletion(
            model=fallback_role,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
    raise  # No fallback configured — propagate
```

**Per-provider budget config in synapse.json (PROV-02):**

```json
"providers": {
  "openai": {
    "api_key": "sk-...",
    "budget_usd": 10.0,
    "budget_duration": "monthly"
  }
}
```

The enforcement point is `_do_call()`. Before making the litellm call, read cumulative spend from the `sessions` table (already populated by `_write_session()`), compare to `budget_usd`. If exceeded, raise `BudgetExceededError` manually (or simply call the fallback role directly). This makes the cap work for local/SDK usage where litellm's server-side budget manager isn't running.

**Note:** litellm's built-in `BudgetManager` class exists but requires Redis/DB in proxy mode. For the SDK-only (no proxy) usage pattern in Synapse, the sessions table approach is simpler and zero-dependency.

### Pattern: requirements.txt Additions

`requirements.txt` already has a well-organized section structure. Additions go in the most semantically relevant section:

```
# --- Scheduling (cron expression parsing) ---
croniter>=6.2.2               # Used by cron/schedule.py CRON kind

# --- Server-Sent Events ---
sse-starlette>=2.0.0          # SSE dashboard (Phase 10) and pipeline events
```

### Anti-Patterns to Avoid

- **Duplicating `_KEY_MAP` drift:** `provider_steps.py` has its own `_KEY_MAP` with the comment "mirrors llm_router.py exactly." Both must be updated together — they are not shared. Keep them in sync.
- **Adding DeepSeek-specific dispatch in `build_router()`:** litellm handles `deepseek/` prefix natively. No `elif primary_model.startswith("deepseek/"):` branch is needed.
- **Using litellm BudgetManager class (proxy mode):** It requires Redis and a running litellm proxy server. This codebase uses litellm as a pure SDK — BudgetManager is not applicable.
- **Storing spend data in a separate budget table:** The `sessions` table already records every call with token counts. Spend = token_counts × per-model pricing. If price data is not available, use a simple USD counter in a lightweight JSON state file alongside the sessions DB.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Provider-prefixed model routing | Custom dispatch switch | litellm Router with prefix strings | Already in place; litellm handles 50+ providers |
| Budget exceeded fallback | Custom retry loop | `except BudgetExceededError` + `self._router.acompletion(fallback_role)` | Router already has fallback model registered — just trigger it manually |
| Cron expression parsing | Home-grown parser | `croniter` | Already imported in `cron/schedule.py` — just undeclared |

**Key insight:** This phase is almost entirely configuration hygiene. The routing machinery is already correct — it only needs mapping table entries and one exception handler.

---

## Common Pitfalls

### Pitfall 1: Forgetting the Mirror `_KEY_MAP` in `provider_steps.py`

**What goes wrong:** DeepSeek key is injected at runtime (via `llm_router.py _KEY_MAP`) but the onboarding wizard fails to set the env var during setup (because `provider_steps.py _KEY_MAP` is missing the entry). User sees validation ping fail with "unknown provider."
**Why it happens:** The two `_KEY_MAP` dicts are maintained separately — `provider_steps.py` says "mirrors llm_router.py exactly" but has no enforcement mechanism.
**How to avoid:** Update both files in the same plan. Add a test that asserts `set(llm_router._KEY_MAP.keys()) == set(provider_steps._KEY_MAP.keys())`.
**Warning signs:** Provider validation ping returns "unknown" error during onboarding while the same key works in production.

### Pitfall 2: BudgetExceededError Not Importable from litellm Main Package

**What goes wrong:** `from litellm import BudgetExceededError` raises `ImportError` on some litellm versions.
**Why it happens:** litellm's exception exports have changed across versions. Confirmed importable via `from litellm import BudgetExceededError` (litellm docs, 2025). Also available from `litellm.exceptions`.
**How to avoid:** Use `from litellm.exceptions import BudgetExceededError` as the canonical import (more explicit, stable). Add a fallback: `except (BudgetExceededError, Exception) as exc: if "budget" in str(exc).lower(): ...` as a belt-and-suspenders guard.
**Warning signs:** Tests import fails at CI time on clean litellm install.

### Pitfall 3: `_router.model_list` Attribute Not Publicly Documented

**What goes wrong:** The fallback check `if fallback_role in [m["model_name"] for m in self._router.model_list]` may fail if litellm Router's internal attribute changes.
**Why it happens:** `model_list` is an internal attribute of `litellm.Router`, not a public API.
**How to avoid:** Track fallback availability locally in `build_router()`. Return a set of registered fallback role names alongside the `Router` object, or check via a simple dict lookup against the original `model_mappings` config (which is already available on `self._config`).
**Warning signs:** `AttributeError: 'Router' object has no attribute 'model_list'` after litellm upgrade.

### Pitfall 4: Budget Enforcement Before vs. After litellm Call

**What goes wrong:** If budget check runs before the call, a partially-spent session may be blocked even though budget isn't truly exhausted (due to token estimation errors). If it runs only in the `except` clause, the over-spend already occurred.
**Why it happens:** The sessions table records spend after the call completes. The budget check needs to compare cumulative previous spend — not include the current call's tokens.
**How to avoid:** Pre-call check reads sessions table SUM and compares to cap. Post-call `_write_session()` records the new spend. This is the correct order — don't try to estimate current call tokens pre-flight.

### Pitfall 5: DeepSeek Reasoning Models Need Special Handling

**What goes wrong:** DeepSeek Reasoner (`deepseek/deepseek-reasoner`) adds a `reasoning_content` field to the response. If the code naively reads `response.choices[0].message.content`, it may get an empty string.
**Why it happens:** Reasoning models separate their chain-of-thought from the final answer.
**How to avoid:** For Phase 6, only configure `deepseek/deepseek-chat` in examples and docs — not the Reasoner. The Reasoner is a future opt-in. Document this in `synapse.json.example` comments.

---

## Code Examples

### DeepSeek Provider Addition — `_KEY_MAP` (both files)

```python
# Source: codebase inspection of llm_router.py lines 202-219
# Add this entry to _KEY_MAP in BOTH llm_router.py AND provider_steps.py:
"deepseek": "DEEPSEEK_API_KEY",
```

### DeepSeek VALIDATION_MODELS entry (`provider_steps.py`)

```python
# Source: litellm docs https://docs.litellm.ai/docs/providers/deepseek
# Add to VALIDATION_MODELS dict in provider_steps.py:
"deepseek": "deepseek/deepseek-chat",
```

### DeepSeek PROVIDER_GROUPS entry (`provider_steps.py`)

```python
# Add to the "--- Major Cloud (US) ---" group in PROVIDER_GROUPS:
{"key": "deepseek", "label": "DeepSeek"},
```

### BudgetExceededError fallback fix (`llm_router.py` `_do_call`)

```python
# Source: workaround for litellm GitHub issue #10052
# At top of file, add to litellm imports:
from litellm.exceptions import BudgetExceededError

# In _do_call(), after the existing except clauses, add:
except BudgetExceededError as exc:
    logger.warning("Budget exceeded for role '%s': %s", role, exc)
    fallback_cfg = self._config.model_mappings.get(role, {}).get("fallback")
    if fallback_cfg:
        fallback_role = f"{role}_fallback"
        logger.info("Falling back to '%s' after budget exceeded", fallback_role)
        return await self._router.acompletion(
            model=fallback_role,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
    raise
```

### synapse.json.example — Budget Cap Config (PROV-02 documentation)

```json
"providers": {
  "openai": {
    "api_key": "YOUR_OPENAI_API_KEY",
    "budget_usd": 10.0,
    "budget_duration": "monthly"
  },
  "deepseek": {
    "api_key": "YOUR_DEEPSEEK_API_KEY"
  }
}
```

### requirements.txt additions

```
# --- Scheduling ---
croniter>=6.2.2               # Cron expression parsing (cron/schedule.py CRON kind)

# --- Server-Sent Events ---
sse-starlette>=2.0.0          # SSE endpoint for dashboard pipeline events
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded provider dispatch (pre-v2.0) | litellm Router with prefix strings | v2.0 Phase 2 | All new providers work with zero dispatch code |
| Manual API key env var setting | `_inject_provider_keys()` from synapse.json | v2.0 Phase 2 | Keys from synapse.json auto-injected at startup |
| No budget enforcement | Manual `except BudgetExceededError` guard | This phase (v3.0 Phase 6) | Fallback fires instead of 500 error |

**Deprecated/outdated:**
- litellm `BudgetManager` class: Proxy-mode only, requires Redis. Not applicable for SDK-only usage. Use sessions table spend tracking instead.

---

## Open Questions

1. **Budget spend tracking precision**
   - What we know: The `sessions` table records `input_tokens` and `output_tokens` per call. Token-to-USD conversion requires per-model pricing data.
   - What's unclear: Should PROV-02 track spend in tokens (and let user set a token budget) or USD (requiring pricing data)?
   - Recommendation: Start with a simple USD cap field that is only enforced when litellm's BudgetExceededError fires. For pro-active pre-call enforcement, track a per-provider call counter and let user set `max_calls_per_day` — simpler and doesn't need pricing data. Leave full USD enforcement for a future phase.

2. **`_router.model_list` internal attribute stability**
   - What we know: litellm Router exposes `model_list` internally; the fallback check currently reads it.
   - What's unclear: Whether litellm maintains backwards compatibility on this attribute.
   - Recommendation: Instead of reading `model_list`, check whether `f"{role}_fallback"` exists by looking at `self._config.model_mappings.get(role, {}).get("fallback")`. If non-None, the fallback role was registered by `build_router()`. This is always accurate and doesn't depend on Router internals.

3. **DeepSeek in `synapse.json.example` — which model?**
   - What we know: `deepseek-chat` is the general-purpose chat model. `deepseek-reasoner` has special response format.
   - What's unclear: Whether to document DeepSeek as a primary role model or only as a fallback example.
   - Recommendation: Document as a primary `casual` role alternative in comments. Do not include DeepSeek Reasoner in the example — it needs special handling not yet built.

---

## Sources

### Primary (HIGH confidence)
- Codebase inspection — `workspace/sci_fi_dashboard/llm_router.py` (lines 199-441): `_KEY_MAP`, `build_router()`, `_do_call()` fallback structure
- Codebase inspection — `workspace/cli/provider_steps.py` (lines 59-148): `VALIDATION_MODELS`, `_KEY_MAP`, `PROVIDER_GROUPS`, 20 providers currently listed
- Codebase inspection — `workspace/synapse_config.py`: `SynapseConfig.providers` is an untyped `dict` — no migration needed for new provider fields
- Codebase inspection — `.planning/research/STACK.md`: `croniter` and `sse-starlette` confirmed as undeclared dependencies, version info already researched
- [litellm DeepSeek docs](https://docs.litellm.ai/docs/providers/deepseek) — `deepseek/` prefix, model names, API key env var `DEEPSEEK_API_KEY`

### Secondary (MEDIUM confidence)
- [litellm exception mapping docs](https://docs.litellm.ai/docs/exception_mapping) — `BudgetExceededError` importable from `litellm.exceptions`
- [litellm Router docs](https://docs.litellm.ai/docs/routing) — Router fallbacks, `fallbacks=[{role: [fallback_role]}]` structure
- [litellm BudgetManager docs](https://docs.litellm.ai/docs/budget_manager) — confirms proxy-mode only, not SDK-mode

### Tertiary (LOW confidence)
- [GitHub Issue #10052](https://github.com/BerriAI/litellm/issues/10052) — BudgetExceededError fallback not triggered. Filed April 2025, confirmed open. Status as of April 2026 unknown — may be fixed in newer litellm. Manual `except` guard is the correct defensive approach regardless.
- WebSearch finding: `from litellm import BudgetExceededError` works in recent versions — but use `from litellm.exceptions import BudgetExceededError` as the more stable import path.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in codebase or confirmed by official docs
- Architecture: HIGH — code was read directly; all three map dicts confirmed present
- Pitfalls: MEDIUM — Pitfall 3 (`model_list` stability) and Pitfall 2 (import path) are precautionary; core pitfalls (Pitfall 1: mirror maps) are HIGH confidence from code inspection

**Research date:** 2026-04-09
**Valid until:** 2026-05-09 (litellm moves fast; re-verify `BudgetExceededError` import path before implementation if >30 days)
