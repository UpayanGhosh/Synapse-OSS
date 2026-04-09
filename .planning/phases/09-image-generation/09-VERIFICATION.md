---
phase: 09-image-generation
verified: 2026-04-09T20:00:00Z
status: passed
score: 6/6 must-haves verified
re_verification: false
---

# Phase 9: Image Generation Verification Report

**Phase Goal:** Image generation pipeline — BackgroundTask dispatch + Vault hemisphere block
**Verified:** 2026-04-09T20:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Saying "draw me X" returns immediate text ack + image delivered as separate message | VERIFIED | `chat_pipeline.py:790` returns ack text; `_generate_and_send_image` BackgroundTask calls `channel.send_media()` |
| 2 | Traffic Cop classifies image requests as IMAGE role | VERIFIED | `llm_wrappers.py:91-96` — IMAGE added as fifth classification with negative examples; image requests route to `role=image_gen` |
| 3 | gpt-image-1 is default provider; fal.ai FLUX is configurable alternative | VERIFIED | `engine.py:51` defaults to `"openai"`; `providers/openai_img.py` uses `model="gpt-image-1"`; `providers/fal_img.py` uses `fal-ai/flux/dev` |
| 4 | Image gen blocked in spicy/Vault sessions — no API calls made | VERIFIED | `chat_pipeline.py:737-744` — `session_mode == "spicy"` check fires BEFORE BackgroundTask dispatch; test `test_image_request_vault_blocked` confirms no `add_task` called |
| 5 | Generation runs as BackgroundTask with immediate text acknowledgment | VERIFIED | `chat_pipeline.py:780-794` — `background_tasks.add_task(_generate_and_send_image, ...)` then immediate ack return |
| 6 | If image_gen.enabled is false, returns soft decline; if API error, logs and does not crash | VERIFIED | `chat_pipeline.py:727-733` — enabled check; `engine.py:63-65` — try/except wraps all provider calls, returns None on failure |

**Score:** 6/6 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `workspace/sci_fi_dashboard/image_gen/__init__.py` | Re-exports ImageGenEngine | VERIFIED | Exists, exports `ImageGenEngine`, 10 lines |
| `workspace/sci_fi_dashboard/image_gen/engine.py` | ImageGenEngine with generate() returning bytes or None | VERIFIED | 97 lines; full implementation — truncation at 4000 chars, provider dispatch, error isolation, lazy imports |
| `workspace/sci_fi_dashboard/image_gen/providers/openai_img.py` | generate_openai_image() using gpt-image-1 | VERIFIED | 46 lines; uses `model="gpt-image-1"`, `b64_json` decode, no `response_format` param |
| `workspace/sci_fi_dashboard/image_gen/providers/fal_img.py` | generate_fal_image() using fal-ai/flux/dev | VERIFIED | 52 lines; sets `FAL_KEY` env var, calls `fal-ai/flux/dev`, downloads via httpx |
| `workspace/synapse_config.py` | image_gen dict field on SynapseConfig | VERIFIED | Line 107: `image_gen: dict = field(default_factory=dict)`; load() at line 164: `raw.get("image_gen", {})`; passed to constructor at line 195 |
| `workspace/sci_fi_dashboard/llm_wrappers.py` | route_traffic_cop() with IMAGE as fifth label | VERIFIED | Lines 91-96: IMAGE listed first with negative examples; docstring updated |
| `workspace/sci_fi_dashboard/chat_pipeline.py` | IMAGE branch with Vault block, enabled check, BackgroundTask dispatch, `_generate_and_send_image` | VERIFIED | Lines 721-794: all four components present in correct order |
| `workspace/sci_fi_dashboard/api_gateway.py` | StaticFiles mount for image_gen_outbound | VERIFIED | Lines 372-377: directory auto-created, mount at `/media/image_gen_outbound` |
| `workspace/tests/test_image_gen.py` | Unit tests covering engine, routing, Vault block, BackgroundTask delivery | VERIFIED | 577 lines, 10 tests across 3 test classes |
| `requirements.txt` | fal-client>=0.13.0 declared | VERIFIED | `fal-client>=0.13.0` present |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `image_gen/engine.py` | `providers/openai_img.py` | lazy import `generate_openai_image` when provider is `"openai"` | WIRED | `engine.py:77` — `from sci_fi_dashboard.image_gen.providers.openai_img import generate_openai_image` inside `_generate_openai()` |
| `image_gen/engine.py` | `providers/fal_img.py` | lazy import `generate_fal_image` when provider is `"fal"` | WIRED | `engine.py:93` — `from sci_fi_dashboard.image_gen.providers.fal_img import generate_fal_image` inside `_generate_fal()` |
| `image_gen/engine.py` | `synapse_config.py` | `SynapseConfig.load().image_gen` at construction | WIRED | `engine.py:9,29-30` — imports `SynapseConfig`, calls `.load()`, assigns `self._img_cfg = self._cfg.image_gen` |
| `chat_pipeline.py` | `image_gen/engine.py` | `ImageGenEngine().generate(prompt)` inside `_generate_and_send_image` | WIRED | `chat_pipeline.py:751,759-760` — lazy import and instantiation inside BackgroundTask helper |
| `chat_pipeline.py` | `media/store.py` | `save_media_buffer(img_bytes, "image/png", "image_gen_outbound")` | WIRED | `chat_pipeline.py:752,764-765` — imported and called with correct positional args (maps to `subdir` parameter) |
| `chat_pipeline.py` | `channels/whatsapp.py` | `channel.send_media(chat_id, img_url, media_type="image")` | WIRED | `chat_pipeline.py:770-772` — `deps.channel_registry.get("whatsapp")` then `channel.send_media()` call; `WhatsAppChannel.send_media()` confirmed at `whatsapp.py:396` |
| `api_gateway.py` | media store `image_gen_outbound` directory | FastAPI StaticFiles at `/media/image_gen_outbound` | WIRED | `api_gateway.py:372-377` — directory created via `mkdir(parents=True, exist_ok=True)`, then mounted |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| IMG-01 | 09-03-PLAN | User can request image generation and receive it in chat | SATISFIED | BackgroundTask delivers via `send_media()`; ack text returns immediately; `test_generate_and_send_image_success` verifies delivery |
| IMG-02 | 09-02-PLAN | Traffic Cop classifies image requests as IMAGE role | SATISFIED | `route_traffic_cop()` includes IMAGE with negative examples; `elif "IMAGE" in classification` routes to `role=image_gen` |
| IMG-03 | 09-01-PLAN | gpt-image-1 is default; Flux (fal.ai) configurable alternative | SATISFIED | Engine defaults to `"openai"` / `gpt-image-1`; `image_gen.provider: "fal"` routes to `fal-ai/flux/dev` |
| IMG-04 | 09-03-PLAN | Image gen respects Vault hemisphere — blocked in spicy mode | SATISFIED | `session_mode == "spicy"` check at `chat_pipeline.py:737` fires before BackgroundTask dispatch; returns `role=image_blocked` |
| IMG-05 | 09-03-PLAN | Generation runs as BackgroundTask with immediate text acknowledgment | SATISFIED | `background_tasks.add_task(_generate_and_send_image, ...)` at line 783, then immediate return of ack reply at line 791 |

All 5 IMG requirements satisfied. No orphaned requirements — every IMG requirement in REQUIREMENTS.md is claimed by exactly one plan.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `chat_pipeline.py` | 754 | `TODO: multi-channel support — resolve channel_id from request context` | Info | `_channel_id` is hardcoded to `"whatsapp"` inside `_generate_and_send_image`. Images can only be delivered via WhatsApp. This is a known design limitation documented in the plan and matches the pattern used by `continue_conversation()`. Not a blocker for phase goal. |
| `chat_pipeline.py` | 789 | `print(f"[ROUTE] Classification=IMAGE -> ...")` | Info | Raw print statement rather than `logger.info()`. Minor style issue — does not affect behavior. |

No blocker anti-patterns. No stub implementations. No empty handlers.

---

### Human Verification Required

The following behaviors cannot be verified programmatically against the static codebase:

#### 1. End-to-end image delivery timing

**Test:** Send "draw me a sunset over a cyberpunk city" via WhatsApp. Observe message timestamps.
**Expected:** Text acknowledgment ("Generating your image — it'll be with you in a moment!") arrives within 1 second. Generated image arrives as a second WhatsApp message within ~30 seconds (gpt-image-1 latency).
**Why human:** Requires live OpenAI API key, running gateway, and WhatsApp connection. Cannot verify timing from static code.

#### 2. fal.ai provider routing

**Test:** Set `image_gen.provider: "fal"` and `providers.fal.api_key` in synapse.json. Send an image request.
**Expected:** fal-client API call appears in logs showing `fal-ai/flux/dev` model used.
**Why human:** Requires valid fal.ai credentials and live network call.

#### 3. Traffic Cop false-positive rejection

**Test:** Send "draw up a plan for the project" and "draw conclusions from this data".
**Expected:** Neither message is classified as IMAGE — they should route as CASUAL or ANALYSIS.
**Why human:** Requires live LLM call to validate prompt's negative-example effectiveness. Static analysis confirms the negative examples exist in the prompt but cannot validate the LLM's decision.

#### 4. Vault block in normal pipeline flow

**Test:** Start a spicy-hemisphere session (vault mode) and send "draw me X".
**Expected:** Soft decline text returned — no image generated, no outbound call to api.openai.com.
**Why human:** The outer vault routing block (line 622) catches spicy sessions before reaching the IMAGE branch. Integration test confirmed no BackgroundTask fires, but live network interception is needed to assert zero outbound HTTP calls to api.openai.com.

---

### Gaps Summary

No gaps. All automated checks passed.

- All 10 artifacts exist and are substantive (non-stub)
- All 7 key links are wired with correct call patterns
- All 5 IMG requirements are covered by implementation evidence
- No blocker anti-patterns
- 2 commits per plan (6 total) all verified present in git history: `19c74bb`, `a5874bc`, `5163d0a`, `6c6c53a`, `0c8427a`, `0856eec`

---

_Verified: 2026-04-09T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
