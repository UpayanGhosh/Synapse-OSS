# Model-Agnostic Architecture Roadmap

**Author:** Upayan + Claude
**Created:** 2026-04-25
**Status:** Active

## Vision

Synapse is owned by the user, not by any model provider. The architecture (memory, KG, SBS, persona, tools, retrieval, routing) lives locally and is the source of identity. The model is a swappable computational substrate.

**Goal:** swap Claude → GPT → Gemini → Ollama with **synapse.json edit only**, no code changes, and get responses that are 95–99% similar within the same capability tier.

**Why:** privacy (data never leaves the machine), continuity (model-vendor lock-in is a liability as the local-LLM curve climbs toward Claude-3 quality by ~2027), and architectural rigor (the bot's "soul" should not be a hostage to one company's roadmap).

## Capability tiers — calibrated similarity ceilings

The "99% similarity" claim is achievable, but **only between models in the same capability tier**:

| Tier | Examples | Cross-tier similarity |
|------|----------|-----------------------|
| Frontier | Claude Sonnet 4.x, GPT-5, Gemini 3 Pro | **95–99%** within tier |
| Strong open | Llama 70B, Qwen2.5 72B, Mixtral 8x22B | 85–92% within tier |
| Mid open | Mistral 7B, Qwen2.5 7B, Gemma 3 12B | 70–85% within tier |
| Small | Gemma E4B, Phi-3.5 mini, Llama 3.2 3B | 50–70% within tier |

Synapse must declare a target tier per role and ship a prompt variant suited to that tier.

## Current state audit (2026-04-25)

| Concern | Status | Notes |
|---------|--------|-------|
| Privacy / data ownership | DONE | memory.db, KG, SBS local |
| Identity continuity | DONE | persona files survive model swap |
| Retrieval | DONE | RAG returns same docs regardless of model |
| Tool primitives | DONE | bash_exec, read_file, edit_file, etc. — generic |
| Wire format normalization | DONE | litellm handles OpenAI ↔ Anthropic |
| Provider auth shims | DONE | Copilot OAuth, Claude Max OAuth, Gemini, etc. |
| Per-engine config defaults | **GAP** | num_ctx not set for Ollama (the bug we just diagnosed) |
| Prompt portability | **GAP** | 28k system prompt assumes frontier reasoning |
| Tool-call resilience | **GAP** | smaller models freelance on tool schemas; no parser/retry |
| Behavior test suite | **MISSING** | no golden tests for cross-model parity |
| Capability-tier system | **MISSING** | model entries don't declare tier; no prompt variant selection |

## Five workstreams

### W1 — Per-engine config defaults (in adapter)

**Goal:** baseline runtime parameters for every engine, with override per-role.

**Scope:**
- Ollama: `num_ctx`, `num_predict`, `temperature`, `repeat_penalty`, `num_gpu` (layers)
- vLLM / hosted_vllm: `max_tokens`, `temperature`, `top_p`
- Cloud providers: already handled by litellm; verify max_tokens normalization
- Per-role override path: `model_mappings.<role>.<engine>_options.<key>`

**Effort:** S (today's num_ctx fix is starter; rest is ~1 hr)

**Done criteria:** every engine call produces full-context, full-output responses by default. No silent truncation. Per-role override works.

### W2 — Prompt portability (capability-tier-aware compiler)

**Goal:** Synapse compiles a different system prompt depending on the model's declared tier. Same identity, same memory, smaller footprint for weaker models.

**Scope:**
- Add `tier` field to `model_mappings.<role>` (e.g. `"tier": "small"`)
- Mark sections in identity files with `<frontier-only>` / `<all>` blocks
- `chat_pipeline._load_agent_workspace_prefix()` filters sections by tier
- Target sizes: frontier 28k chars, mid 12k, small 6k
- Identity, prime directives, tool list always present; long examples and edge-case rules become frontier-only

**Effort:** M (~3–4 hrs)

**Done criteria:** swapping a role from frontier→small drops prompt to ≤6k chars. Bot still answers core scenarios correctly (with degraded nuance, not generic boilerplate).

### W3 — Tool-call resilience (parser + retry)

**Goal:** smaller models that emit malformed tool calls (string instead of JSON, missing arg, wrong tool name) get caught and corrected, not surrendered.

**Scope:**
- JSON-extraction fallback: if tool_call payload isn't strict JSON, run a tolerant parser (extract first `{...}` block, fix common quote issues)
- Tool-name fuzzy match: leverages existing `_fuzzy_match_model` pattern from RT3
- Argument schema coercion: if model passes `path` instead of `file_path`, remap to schema
- Retry loop: 1 retry with explicit "your tool call was malformed, here is the schema" message
- Telemetry: log every coercion so we can see which models drift

**Effort:** M (~2–3 hrs)

**Done criteria:** Mistral 7B, Qwen 7B, Gemma 12B all complete a 5-tool-step task without manual intervention. Coercion log shows where each model drifted.

### W4 — Golden behavior test suite (cross-model parity)

**Goal:** automated test harness that runs identical scenarios across all configured roles and scores semantic equivalence of responses.

**Scope:**
- Test scenarios (10–15): identity question, grounding test (must call bash_exec), memory retrieval, tool chaining, persona consistency, error handling, etc.
- Run each scenario across N model configurations (e.g. casual=claude, casual=gpt-4, casual=mistral-7b)
- Scoring: embedding-based semantic similarity to a "gold" reference response per scenario
- Output: parity matrix — rows are scenarios, columns are models, cells are similarity scores
- Pass threshold per tier: frontier 0.92+, strong-open 0.85+, mid 0.75+, small 0.60+

**Effort:** L (~6–8 hrs)

**Done criteria:** `pytest tests/test_model_parity.py` produces a matrix. Regressions surface immediately when a swap happens.

### W5 — Capability-tier declaration in synapse.json

**Goal:** every role explicitly declares its target tier; chat_pipeline picks prompt variant; UI surfaces "you are running in mid-tier mode" when relevant.

**Scope:**
- Schema: `model_mappings.<role>.tier ∈ {"frontier", "strong_open", "mid_open", "small"}`
- Default: frontier (matches current behavior)
- chat_pipeline reads tier, calls `_load_agent_workspace_prefix(tier=...)` from W2
- Health endpoint exposes current tier per role
- Optional: warning log when tier doesn't match heuristic detection (e.g. you set frontier but the model is gemma 3B)

**Effort:** S (~1 hr) — but depends on W2 being done

**Done criteria:** synapse.json change picks correct prompt variant; health endpoint reports it.

## Sequencing (revised 2026-04-25 after E4B test)

**Major reordering after live test:** with `num_ctx=32768` E4B answered correctly. Prompt size measured at **19,107 tokens**. Implication: no consumer GPU under 12 GB VRAM can run Synapse locally with current prompt size. **W2 is now mandatory blocker**, not optional polish.

| Order | Workstream | Why this order |
|-------|------------|----------------|
| 1 | W1 (config defaults) | DONE today — num_ctx default + per-role override + overflow warning shipping |
| 2 | **W2 (prompt portability) — P0 escalated** | Without minimal-mode prompt, OSS local-host story is broken on 4-8 GB VRAM hardware. Must come before everything else. |
| 3 | W4 (test suite) | After W2 lands; needed to verify minimal-mode doesn't degrade quality below per-tier thresholds |
| 4 | W3 (tool resilience) | Independent; helps every smaller-tier swap |
| 5 | W5 (tier declaration) | Glue; depends on W2 |

**OSS-friendliness constraint (locked in):** every default in this codebase must work on 4 GB VRAM hardware out of box. Bigger hardware enjoys more headroom but baseline must run on commodity GPUs. No "this works on my rig" tuning for global defaults — that's per-role override territory.

Total effort estimate: ~14–20 hours across 5 workstreams (slightly bigger now that W2 is fully in scope, not just a stub).

## "Model-agnostic-ready" definition (when can we claim the vision is delivered)

Synapse is **model-agnostic-ready** when ALL of the following hold:

1. Every supported engine (cloud + local) ships with proper config defaults — no silent truncation, no missing parameters.
2. Tool calls succeed at ≥95% rate on mid-tier models (not just frontier).
3. Golden test suite passes the per-tier threshold for every model in synapse.json.
4. A user can swap the entire `model_mappings` block to a different tier and the bot still passes the suite (with appropriately lower similarity scores within that tier's threshold).
5. CLAUDE.md and synapse.json.example document the tier system and engine-options override syntax.

## Today's progress (2026-04-25)

- **W1 shipped:**
  - `_OLLAMA_DEFAULT_OPTS` constant in `llm_router.py` with `num_ctx=8192` (safe for 6-8 GB VRAM)
  - `_build_ollama_options()` helper merges per-role overrides on top of defaults so essential keys never get dropped
  - Both primary and fallback Ollama paths now use the helper
  - Pre-call instrumentation logs `est_tokens` for every LLM call
  - Overflow warning fires when an Ollama prompt likely exceeds configured `num_ctx`
  - `synapse.json.example` documents the override syntax with a worked example
  - `CLAUDE.md` Critical Gotchas section explains the truncation behavior and VRAM trade-off

- **Live test conclusion:** at `num_ctx=8192` E4B replied with generic "how can I help" boilerplate (truncation drops user message). At `num_ctx=16384` same boilerplate (still oversized). At `num_ctx=32768` E4B correctly answered "What is 7×8?" with "56." Real prompt size measured: **19,107 tokens**. Confirms W1 fix works AND that W2 is the next hard blocker.

- **Roadmap created** (this file). W2 escalated to P0.

## What this roadmap is NOT

- Not a commitment to ship all 5 workstreams immediately. Sequence is a plan; pace is whatever the user decides.
- Not a denial of frontier-model usefulness. Frontier remains the default for chat roles. The roadmap makes local-tier viable as fallback / vault / dev-mode.
- Not a rewrite. Every workstream is additive — no breaking changes to existing synapse.json or existing tools.

## Open questions

1. Which tier do we declare as "default" for OSS distribution? Frontier is highest-quality but requires API keys; small is offline-first but degraded. Probably ship synapse.json.example with frontier defaults + commented-out small-tier alternatives.
2. Do we ship reference models per tier (i.e. "for small tier, we recommend gemma3:4b-it-q4")? Helps OSS users but creates maintenance burden.
3. How aggressively to auto-detect tier from model string? (Could parse "claude-sonnet" → frontier, "gemma" + "<7b" → small.) Convenience vs explicit-config trade-off.
