# Phase 5 — W5 Capability-Tier Auto-Detect + Warnings

## TL;DR

Detect each role's prompt tier from the model string at config load, compare against the user's explicit `prompt_tier`, and warn (or refuse) when the choice is undersized for the role's prompt complexity.

## Goal

W2 (`37a1dea`) shipped tier-aware prompt compilation. W3 (`eb1ffc0`) shipped a `prompt_tier_for_role()` resolver with model-name → tier inference baked in. What's still missing is the **warning loop**: when a user pins `prompt_tier=frontier` on a role whose model name infers to `small` (e.g. `ollama_chat/gemma:4b`), nothing surfaces the mismatch — the bot silently renders 19k-token frontier prompts to a model that can hold 8k. Phase 5 closes that gap with a `MODEL_TIER_MAP` heuristic, a config-load comparator, and an actionable warning (or hard error) on mismatch.

## Severity & Effort

- **Severity:** P2 (no chat-path failure today; degrades silently into "boilerplate replies" or context overflow on undersized models)
- **Effort:** M (~3 hr)
- **Blocks:** None
- **Blocked by:** None — W2 + W3 are already shipped (`37a1dea`, `eb1ffc0`)

## Why this matters (with evidence)

Per **E5.1** in EVIDENCE.md, Synapse's prompt-tier system is currently set per-role manually in `synapse.json`. The infrastructure to USE the tier is live: `chat_pipeline.py:912-913` calls `prompt_tier_for_role(model_mappings, role)` then `get_prompt_tier_policy(prompt_tier)` to pick rendering size. But `prompt_tier_for_role()` (in `prompt_tiers.py:115-135`) honors explicit config first and only falls back to inference — so a typo or a stale config wins silently.

**Concrete failure mode** documented in `MODEL-AGNOSTIC-ROADMAP.md:148-157` (the W1 sweep): with `num_ctx=8192` on Gemma E4B, the prompt was truncated and the bot replied with generic boilerplate. The user only caught it because they ran an explicit identity test ("What is 7×8?" → "56."). On a normal chat day, an undersized config produces *plausible but worse* replies — the bot stays "alive" but with degraded persona depth, no memory recall, no KG context. That's the silent-rot failure mode this phase prevents.

The open question raised in `MODEL-AGNOSTIC-ROADMAP.md:222` ("should we WARN when inference disagrees with explicit config?") is exactly W5's mandate. Code-graph evidence (`prompt_tier_for_role` already wires explicit > inference) confirms inference is computed but discarded when explicit config is present. The function just needs to emit a structured warning when those two disagree.

A second concern: tier inference today lives inside `prompt_tier_for_role()` and only fires when the user did NOT set explicit config. There's no shared `MODEL_TIER_MAP` other tools (UI, health endpoint, onboarding wizard) can consult. Phase 5 should extract the heuristic into a public, regex-driven map so the same source of truth feeds the warning logic, the future health endpoint, and the onboarding tier-suggestion UX.

## Current state — what's there now

**Tier resolution lives in `workspace/sci_fi_dashboard/prompt_tiers.py`:**

```python
# prompt_tiers.py:115-135 — explicit config wins, inference is fallback only
def prompt_tier_for_role(model_mappings, role, default="frontier"):
    cfg = (model_mappings or {}).get(role) or {}
    explicit = _cfg_get(cfg, "prompt_tier") or _cfg_get(cfg, "capability_tier") or _cfg_get(cfg, "tier")
    if explicit:
        return normalize_prompt_tier(explicit, default)
    model = str(_cfg_get(cfg, "model") or "")
    inferred = infer_prompt_tier_from_model(model, cfg)
    return inferred or default
```

**Inference heuristic (`prompt_tiers.py:138-177`)** is local-model-only:

```python
def infer_prompt_tier_from_model(model: str, role_cfg=None) -> PromptTier | None:
    is_local = model_l.startswith(("ollama_chat/", "hosted_vllm/", "vllm/", "lm_studio/", "local/"))
    if not is_local:
        return None  # ← cloud models always return None — no warning fires for them
    # num_ctx-based, then size_b in name, then keyword fallback (phi/mini/3b/4b → small, etc.)
```

Cloud models (`gemini/`, `anthropic/`, `openai/`, `google_antigravity/`, etc.) return `None` from inference today. That means a user setting `prompt_tier=small` on `gemini/gemini-2.0-pro` (frontier) gets no warning, and a user setting `prompt_tier=frontier` on `gemini/gemini-2.0-flash-lite` (mid_open at best) gets no warning either.

**Schema already supports tier fields (`workspace/config/schema.py:57-58`):**

```python
class AgentModelConfig(BaseModel):
    ...
    prompt_tier: Literal["frontier", "mid_open", "small"] | None = None
    capability_tier: Literal["frontier", "mid_open", "small"] | None = None
```

**Where the resolved tier is consumed (`workspace/sci_fi_dashboard/chat_pipeline.py:912-913`):**

```python
prompt_tier = prompt_tier_for_role(model_mappings, role)
prompt_policy = get_prompt_tier_policy(prompt_tier)
```

**No comparator exists today.** No callsite compares explicit vs inferred. No warning logger fires. No startup health-check surfaces a mismatch.

## Target state

1. **`MODEL_TIER_MAP` is a public, regex-driven dict** at the top of `prompt_tiers.py` (or a new sibling `model_tiers.py` if it grows). Each entry maps a regex → `PromptTier`. Examples:
   - `r"gemini-.*-pro($|-)"` → `frontier`
   - `r"gemini-.*-flash($|-preview$)"` → `mid_open`
   - `r"gemini-.*-flash-lite"` → `small`
   - `r"claude-.*-(opus|sonnet)-"` → `frontier`
   - `r"claude-.*-haiku-"` → `mid_open`
   - `r"gpt-(4|5)-?(turbo|o)?"` → `frontier`
   - `r"gpt-.*-mini"` → `mid_open`
   - `r"o1|o3|o4"` → `frontier`
   - Local: extend the existing `_model_size_b` heuristic so `:7b`, `:13b`, `:70b` all map cleanly.

2. **A new `infer_tier_from_any_model(model: str) -> PromptTier | None`** function consults `MODEL_TIER_MAP` regex-by-regex, then falls back to `infer_prompt_tier_from_model()` for local-only logic, then returns `None` if no rule matches. Cloud models that have no rule still return `None` — that's fine, the comparator just skips them.

3. **A new `validate_role_tier(role, cfg, *, on_mismatch="warn") -> None`** function called once per role at config load. When explicit `prompt_tier` exists AND inferred tier differs, emit a structured log:
   - `WARNING — role 'casual' configured prompt_tier='frontier' but model 'ollama_chat/gemma:4b' infers to 'small'. Identity prompt may exceed model's effective context. Suggest prompt_tier='small' (or swap model to a 7B+ class).`
   - On `on_mismatch="error"` (opt-in via `synapse.json → session.tier_strict_mode: true`), raise `ConfigError` and halt boot. This becomes the "refuse to start with undersized config" path.

4. **Severity matrix for the warning:**
   - **Downgrade** (configured > inferred — e.g. user sets frontier on a small model) → `WARNING` always. This is the silent-truncation case.
   - **Upgrade** (configured < inferred — e.g. user sets small on a frontier model) → `INFO` only. They're deliberately shedding context for cost or speed; no harm.
   - **Match** → silent (don't spam logs).
   - **Unknown model** (no map hit, no local size signal) → `DEBUG`. Don't pollute INFO with maps we haven't taught yet.

5. **Suggest a fallback** in the warning text. For `frontier`-on-small-model: `"Suggested fix: set prompt_tier='small' on this role, OR set model to a frontier-tier model (gemini-3-pro, claude-sonnet-4, gpt-4o)."` Don't auto-rewrite the config — just surface the mismatch.

6. **Callsite:** wire `validate_role_tier` into `synapse_config.py: SynapseConfig.load()` after `model_mappings` is populated. One pass over all roles, one warning per mismatch, no per-chat-turn cost.

## Tasks (ordered)

- [ ] **5.1** — Add `MODEL_TIER_MAP: list[tuple[re.Pattern, PromptTier]]` at the top of `workspace/sci_fi_dashboard/prompt_tiers.py`. Order matters — most-specific patterns first (`flash-lite` before `flash`). Cover: Gemini 1.5/2.0/3.x (flash-lite/flash/pro variants), Claude 3.x/4.x (haiku/sonnet/opus), GPT-4o/4-turbo/5/5-mini, o-series reasoning models, Llama 3.x by size, Mistral/Qwen/Gemma by size. Aim for ~30-40 rules; gold-plating risks staleness, undershooting risks misses.

- [ ] **5.2** — Add `infer_tier_from_any_model(model: str) -> PromptTier | None`. Walk `MODEL_TIER_MAP`. If no hit AND `model.startswith(<local_prefixes>)`, fall back to existing `infer_prompt_tier_from_model()`. Else `None`. Strip provider prefix before regex match (`gemini/`, `anthropic/`, `openai/`, `google_antigravity/`, etc.) so the same rule fires regardless of provider routing.

- [ ] **5.3** — Add `validate_role_tier(role: str, cfg: dict, *, strict: bool = False) -> None`. Computes explicit tier, computes inferred tier, classifies as `match` / `downgrade` / `upgrade` / `unknown`, emits the appropriate log line. On `strict=True` AND `downgrade` AND inferred is two tiers below configured (e.g. frontier configured, small inferred) → raise `ConfigError`. (Off-by-one downgrade just warns; this avoids breaking users who deliberately set frontier on a `gemini-2.0-flash` and want the bigger prompt to be tried.)

- [ ] **5.4** — Wire `validate_role_tier` into `SynapseConfig.load()` (`workspace/synapse_config.py`) after `model_mappings = raw.get("model_mappings", {})` is populated and before returning. Iterate roles, call validator, swallow `ConfigError` only when `session.tier_strict_mode` is unset (default = lenient). Read the strict flag from `raw.get("session", {}).get("tier_strict_mode", False)`.

- [ ] **5.5** — Document `tier_strict_mode` in `synapse.json.example`. Add a commented block:

  ```json
  "session": {
    "_tier_strict_mode_comment": "When true, refuse to boot if any role's prompt_tier is two or more tiers above the model's inferred tier (e.g. frontier prompt on a 4B model). Default false (warn-only).",
    "tier_strict_mode": false
  }
  ```

- [ ] **5.6** — Add tests in `workspace/tests/test_prompt_tiers.py`:
  - `test_model_tier_map_covers_canonical_models` — assert every model string in `synapse.json.example.model_mappings` resolves to a non-None tier.
  - `test_validate_role_tier_warns_on_downgrade` — caplog-based, fixture sets frontier on `ollama_chat/gemma:4b`, asserts WARNING fires.
  - `test_validate_role_tier_silent_on_match` — caplog asserts no WARNING when configured tier matches inferred.
  - `test_validate_role_tier_info_on_upgrade` — frontier model + small config → INFO, not WARNING.
  - `test_validate_role_tier_strict_mode_raises` — frontier configured on a 3B model with `strict=True` → `ConfigError`.
  - `test_unknown_model_does_not_warn` — `r"some-future-model-x9"` resolves to None, no log spam.

- [ ] **5.7** — Update `workspace/synapse_config.py` docstring on `SynapseConfig.load()` to mention the validation pass. Update `D:/Shorty/Synapse-OSS/CLAUDE.md` "Configuration" section with one-line note: `model_mappings.<role>.prompt_tier is auto-validated at load — see prompt_tiers.MODEL_TIER_MAP`.

- [ ] **5.8** — Smoke-test on the user's actual `~/.synapse/synapse.json`. Current state has every role on `google_antigravity/gemini-3-flash` (mid_open / frontier ambiguous — Gemini 3 Flash is a frontier-class fast model per spec). Confirm zero false-positive warnings on a sane config. If `gemini-3-flash` is genuinely ambiguous, add an `_unknown_disambig` test case rather than guessing.

## Dependencies

- **Hard:** W2 (`37a1dea`) shipped — `prompt_tier_for_role()`, `get_prompt_tier_policy()`, and the policy dict already exist. W5 is purely additive.
- **Soft:** Phase 8 (W8 traffic_cop residue) — if Phase 8 lands first and adds a dedicated `traffic_cop` role to `model_mappings`, this validator will tier-check it automatically. Either order works.
- **Provides:** A foundation for the future `/health` endpoint to surface "you are running 'casual' in mid_open mode" (called out in `MODEL-AGNOSTIC-ROADMAP.md:113-114`). Phase 5 doesn't have to ship the endpoint, just the inference primitives the endpoint will use.

## Success criteria

- [ ] `MODEL_TIER_MAP` exists and exports as a top-level symbol from `prompt_tiers.py`.
- [ ] `infer_tier_from_any_model("gemini/gemini-3-flash-lite-preview")` → `"small"` (or `"mid_open"` — pick one based on Gemini 3 specsheet, document in code comment).
- [ ] `infer_tier_from_any_model("anthropic/claude-3-5-sonnet-20241022")` → `"frontier"`.
- [ ] `infer_tier_from_any_model("ollama_chat/qwen2.5:7b")` → `"mid_open"`.
- [ ] Booting Synapse with `prompt_tier=frontier` on `ollama_chat/gemma:4b` produces a single WARNING in startup logs naming both the role and the suggested fix.
- [ ] Booting with the canonical `synapse.json.example` produces zero warnings.
- [ ] All 6 new tests pass: `cd workspace && pytest tests/test_prompt_tiers.py -v`.
- [ ] No regressions: `cd workspace && pytest tests/ -m unit -k "tier or prompt or config"` is green.

## Verification recipe

```bash
# 1. Install branch
cd D:/Shorty/Synapse-OSS
git checkout -b fix/phase-5-capability-tier-detect develop

# 2. Run the new test file in isolation
cd workspace && pytest tests/test_prompt_tiers.py -v

# 3. Manual smoke: corrupt a role to frontier-on-small, boot, verify warning
python -c "
from sci_fi_dashboard.prompt_tiers import validate_role_tier
validate_role_tier('casual', {'model': 'ollama_chat/gemma:4b', 'prompt_tier': 'frontier'})
"
# Expected stderr: WARNING ... role 'casual' configured prompt_tier='frontier' but model 'ollama_chat/gemma:4b' infers to 'small' ...

# 4. Run the gateway and confirm no warnings on the user's actual config
cd workspace/sci_fi_dashboard && uvicorn api_gateway:app --host 0.0.0.0 --port 8000 --reload 2>&1 | grep -i "tier"
# Expected: empty (or only DEBUG-level "tier resolved" lines)

# 5. Strict-mode boot test
echo '{"session": {"tier_strict_mode": true}, "model_mappings": {"casual": {"model": "ollama_chat/gemma:4b", "prompt_tier": "frontier"}}}' > /tmp/strict_test.json
SYNAPSE_HOME=/tmp/strict_test_dir mkdir -p /tmp/strict_test_dir
cp /tmp/strict_test.json /tmp/strict_test_dir/synapse.json
SYNAPSE_HOME=/tmp/strict_test_dir python -c "from synapse_config import SynapseConfig; SynapseConfig.load()"
# Expected: ConfigError raised

# 6. Lint + format
ruff check workspace/sci_fi_dashboard/prompt_tiers.py workspace/synapse_config.py
black workspace/sci_fi_dashboard/prompt_tiers.py workspace/synapse_config.py
```

## Risks & gotchas

- **Regex ordering matters** — `gemini-.*-flash` will eat `gemini-.*-flash-lite` if the lite rule is registered second. Tests must cover the ambiguous cases (lite vs full flash, sonnet vs sonnet-old).

- **Provider-prefix stripping** — Synapse uses provider/model strings like `google_antigravity/gemini-3-flash`. The Gemini regex must match against the bare model name post-strip. Don't include provider prefix in the regex.

- **`google_antigravity/gemini-3-flash`** is a Gemini 3 Flash routed via the OAuth provider. Tier-wise it's the same as `gemini/gemini-3-flash` — treat them identically. Provider-string-stripping handles this.

- **`gpt-5-mini` is mid_open, not small.** It's smaller than gpt-5 but still has frontier-class context windows. Don't downgrade it accidentally — that interacts with Phase 8 (where the user previously had `gpt-5-mini` set as `casual`).

- **Tier mismatch on `vault` role** — the vault role is intentionally local + small for privacy. The current `synapse.json.example` sets it to `qwen2.5:7b` with `prompt_tier=small`. Inference says `mid_open` for a 7B model — this is the ONE case where `small` configured + `mid_open` inferred should NOT warn (deliberate downgrade for privacy). Either: (a) make the vault role exempt from the validator by name, or (b) tighten the off-by-one rule so a one-tier downgrade is silent and only two-tier downgrades warn. Option (b) is cleaner and what's specified in 5.3.

- **Don't auto-rewrite config.** Tempting, but breaks the explicit-config-wins contract. Warn only.

- **`tier_strict_mode=true` will block boots** for users with miscalibrated `entities.json`-era configs. Default it to `false`. Document the migration path: warn for two releases, then flip default to `true` in v0.X+2.

- **Ollama discovery (`models_catalog.py:79`)** runs async at startup and discovers context_window from the model itself. Phase 5 doesn't depend on it, but be aware: if the discovered `num_ctx` disagrees with the regex inference, prefer the discovered value (it's ground truth). Optional refinement, not required for first ship.

## Out of scope

- Live `/health` endpoint exposing per-role tier (mentioned in `MODEL-AGNOSTIC-ROADMAP.md:113`). Phase 5 builds the inference primitives; a future phase wires them to HTTP.
- Onboarding-wizard tier suggestions ("we detected gemma:4b — set prompt_tier=small?"). Same story — primitives now, UX later.
- Auto-rewriting `synapse.json` to fix mismatches. Out by design.
- Per-tier model recommendations in CLAUDE.md beyond a single doc-line. The `synapse.json.example` already shows the canonical mappings; don't duplicate.
- Cross-tier similarity scoring (W4's territory — `f672989`).
- Tracking the `gpt-5-mini`-as-traffic_cop residue. That's Phase 8.

## Evidence references

- **E5.1 / E5.2 / E5.3** in EVIDENCE.md — background, files involved, search recipe.
- **MODEL-AGNOSTIC-ROADMAP.md:105-118** — W5 spec.
- **MODEL-AGNOSTIC-ROADMAP.md:222** — open question that defines this phase ("should we WARN when inference disagrees").
- **MODEL-AGNOSTIC-ROADMAP.md:148-157** — concrete failure mode (E4B sweep showing silent boilerplate when prompt is undersized for context).
- Commit `37a1dea` (`feat(runtime): wire tier-aware prompt compilation into chat pipeline`) — wiring W5 builds on.
- Commit `eb1ffc0` (`Add local tool-call resilience`) — the prompt_tiers.py module W5 extends.

## Files touched (expected)

- `workspace/sci_fi_dashboard/prompt_tiers.py` — add `MODEL_TIER_MAP`, `infer_tier_from_any_model`, `validate_role_tier`. ~80-120 new lines.
- `workspace/synapse_config.py` — call `validate_role_tier` once per role in `SynapseConfig.load()`. ~10 new lines.
- `workspace/tests/test_prompt_tiers.py` — 6 new tests. ~80-100 new lines.
- `synapse.json.example` — document `tier_strict_mode`. ~5 new lines.
- `D:/Shorty/Synapse-OSS/CLAUDE.md` — one-line note in Configuration section. ~1 new line.

No edits to `chat_pipeline.py`, `llm_router.py`, or `models_catalog.py`. The validator runs at config-load only, not on the hot path.
