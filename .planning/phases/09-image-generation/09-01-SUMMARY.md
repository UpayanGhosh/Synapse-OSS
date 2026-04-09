---
phase: 09-image-generation
plan: 01
subsystem: image-gen
tags: [openai, gpt-image-1, fal-ai, flux, image-generation, synapse-config]

# Dependency graph
requires: []
provides:
  - ImageGenEngine class with generate() returning bytes or None
  - generate_openai_image() async function using gpt-image-1 (b64_json decoding)
  - generate_fal_image() async function using fal-ai/flux/dev (httpx download)
  - SynapseConfig.image_gen dict field loaded from synapse.json
  - fal-client>=0.13.0 declared in requirements.txt
affects:
  - 09-image-generation
  - phase 10 (dashboard SSE events for image gen)

# Tech tracking
tech-stack:
  added:
    - fal-client>=0.13.0 (fal.ai FLUX provider)
  patterns:
    - Lazy imports for optional provider SDKs (openai, fal-client imported inside function body)
    - Provider dispatch via config string ("openai" | "fal")
    - Missing API key returns None with logged error, never crashes
    - Prompt silently truncated at MAX_PROMPT_CHARS (4000), never raised as error
    - Provider config extends SynapseConfig with dict field pattern (same as providers, channels, embedding, etc.)

key-files:
  created:
    - workspace/sci_fi_dashboard/image_gen/__init__.py
    - workspace/sci_fi_dashboard/image_gen/engine.py
    - workspace/sci_fi_dashboard/image_gen/providers/__init__.py
    - workspace/sci_fi_dashboard/image_gen/providers/openai_img.py
    - workspace/sci_fi_dashboard/image_gen/providers/fal_img.py
  modified:
    - workspace/synapse_config.py
    - requirements.txt

key-decisions:
  - "gpt-image-1 used (not dall-e-3 which is deprecated May 12 2026) — always returns b64_json, never URL, response_format param omitted"
  - "fal-client reads FAL_KEY from environment — set os.environ[FAL_KEY] = api_key before fal_client.run_async() call"
  - "Lazy imports for both providers — neither openai nor fal-client are required for core Synapse operation"
  - "image_gen field in SynapseConfig uses same dict pattern as providers/channels — controls provider, size, quality, enabled flag"

patterns-established:
  - "Provider error isolation: all provider calls wrapped in try/except in engine.py; providers never catch their own errors"
  - "API key validation in engine._generate_*() helpers, not in provider functions — keeps provider functions pure"
  - "Config field pattern: add to SynapseConfig dataclass + initialize default in load() + pass to cls() constructor"

requirements-completed:
  - IMG-03

# Metrics
duration: 3min
completed: 2026-04-09
---

# Phase 9 Plan 01: Image Generation Engine Summary

**Dual-provider image generation engine (OpenAI gpt-image-1 + fal.ai FLUX) with SynapseConfig integration and zero-crash error isolation**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-09T13:16:19Z
- **Completed:** 2026-04-09T13:19:30Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- ImageGenEngine class dispatches to OpenAI gpt-image-1 or fal.ai FLUX based on `image_gen.provider` in synapse.json
- Both providers implemented with proper async patterns, lazy imports, and error isolation (missing key logs + returns None)
- SynapseConfig extended with `image_gen: dict` field using the same additive pattern as all other config dicts
- fal-client declared in requirements.txt; openai and httpx confirmed already present

## Task Commits

Each task was committed atomically:

1. **Task 1: Create image_gen package with OpenAI and fal providers** - `19c74bb` (feat)
2. **Task 2: Extend SynapseConfig with image_gen field and update requirements.txt** - `a5874bc` (feat)

**Plan metadata:** (see final state update commit)

## Files Created/Modified
- `workspace/sci_fi_dashboard/image_gen/__init__.py` - Package init, re-exports ImageGenEngine
- `workspace/sci_fi_dashboard/image_gen/engine.py` - ImageGenEngine class; dispatch, truncation, error isolation
- `workspace/sci_fi_dashboard/image_gen/providers/__init__.py` - Empty providers package init
- `workspace/sci_fi_dashboard/image_gen/providers/openai_img.py` - generate_openai_image() using gpt-image-1 + b64_json decode
- `workspace/sci_fi_dashboard/image_gen/providers/fal_img.py` - generate_fal_image() using fal_client.run_async + httpx download
- `workspace/synapse_config.py` - Added image_gen field to SynapseConfig dataclass + load() method
- `requirements.txt` - Added fal-client>=0.13.0

## Decisions Made
- gpt-image-1 used (not dall-e-3 which is deprecated May 12, 2026). gpt-image-1 always returns b64_json, never URL. `response_format` parameter is explicitly omitted.
- fal-client reads `FAL_KEY` from the environment, so `os.environ["FAL_KEY"] = api_key` is set before calling `fal_client.run_async()`.
- Both provider SDKs are lazy-imported inside the function body — neither openai nor fal-client are required for Synapse to start (zero import-time side effects).
- API key validation happens in engine's `_generate_openai()` / `_generate_fal()` helpers, not inside provider functions. This keeps provider functions pure and testable.

## Deviations from Plan

None - plan executed exactly as written. Initial import failure (AttributeError on `SynapseConfig.image_gen`) was resolved by completing Task 2 before running Task 1 verification, as designed.

## Issues Encountered
- Initial Task 1 verification failed because `SynapseConfig.image_gen` didn't exist yet. Task 2 was completed first, then both tasks verified together. This matches expected plan execution order (Task 2 adds the config field that Task 1's engine depends on at runtime).

## User Setup Required
None - no external service configuration required to run. Users configure image generation in `synapse.json` under `image_gen` and `providers.openai`/`providers.fal` when they want to use the feature.

## Next Phase Readiness
- ImageGenEngine is standalone and independently testable — no pipeline dependencies
- Plan 09-02 can wire ImageGenEngine into the chat pipeline via BackgroundTask pattern
- Plan 09-03 can add image detection (classify whether a message requests image generation)
- SynapseConfig.image_gen field is ready to receive `provider`, `size`, `quality`, `enabled` from synapse.json

---
*Phase: 09-image-generation*
*Completed: 2026-04-09*

## Self-Check: PASSED

- FOUND: workspace/sci_fi_dashboard/image_gen/__init__.py
- FOUND: workspace/sci_fi_dashboard/image_gen/engine.py
- FOUND: workspace/sci_fi_dashboard/image_gen/providers/__init__.py
- FOUND: workspace/sci_fi_dashboard/image_gen/providers/openai_img.py
- FOUND: workspace/sci_fi_dashboard/image_gen/providers/fal_img.py
- FOUND: .planning/phases/09-image-generation/09-01-SUMMARY.md
- FOUND: commit 19c74bb (Task 1 — image_gen package)
- FOUND: commit a5874bc (Task 2 — SynapseConfig + requirements.txt)
