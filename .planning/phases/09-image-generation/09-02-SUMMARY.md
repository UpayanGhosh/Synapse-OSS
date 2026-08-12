---
phase: 09-image-generation
plan: "02"
subsystem: api
tags: [traffic-cop, routing, image-gen, classification, llm-router]

# Dependency graph
requires:
  - phase: 09-image-generation/09-01
    provides: image generation infrastructure (ImageGenerator, synapse.json image_gen key)
provides:
  - route_traffic_cop() returns IMAGE for image requests (fifth classification label)
  - chat_pipeline.py has IMAGE routing branch that returns placeholder response and sets role=image_gen
affects:
  - 09-03-image-generation (wires BackgroundTask dispatch into the IMAGE branch created here)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "IMAGE classification listed first in traffic cop prompt (new categories most likely confused go first)"
    - "Negative examples in classification prompts prevent false-positive triggers ('draw up a plan', 'create a document')"
    - "IMAGE branch returns early with placeholder — BackgroundTask wired in next plan, not inline"
    - "image_gen role skips LLM router entirely via early return before Tool Execution Loop"

key-files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/llm_wrappers.py
    - workspace/sci_fi_dashboard/chat_pipeline.py

key-decisions:
  - "IMAGE placed first in traffic cop bullet list — new category most likely to be confused; LLM attention front-loaded"
  - "Placeholder return (not role=casual fallback) — ensures IMAGE is never silently misrouted until Plan 03 wires full dispatch"
  - "STRATEGY_TO_ROLE intentionally not modified — image requests must always go through traffic cop, never skipped"
  - "Early return on IMAGE classification skips Tool Execution Loop and model_mappings lookup entirely"

patterns-established:
  - "Placeholder branch pattern: add routing classification now, wire full dispatch in next plan — reduces atomic change size"

requirements-completed:
  - IMG-02

# Metrics
duration: 2min
completed: "2026-04-09"
---

# Phase 9 Plan 02: Image Classification Routing Summary

**IMAGE added as fifth traffic cop classification with negative examples; chat_pipeline.py routes IMAGE to image_gen role with early-return placeholder pending Plan 03 BackgroundTask dispatch**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-04-09T13:16:07Z
- **Completed:** 2026-04-09T13:17:33Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Updated `route_traffic_cop()` prompt in `llm_wrappers.py`: fifth classification label IMAGE added, listed first with negative examples to prevent false positives on "draw up a plan", "create a document", "draw conclusions"
- Added `elif "IMAGE" in classification:` branch in `chat_pipeline.py` routing block, before `else: role = "casual"`, returning a placeholder dict immediately so IMAGE is never silently swallowed by casual
- STRATEGY_TO_ROLE confirmed unmodified — image requests always go through the traffic cop LLM call

## Task Commits

Each task was committed atomically:

1. **Task 1: Add IMAGE to Traffic Cop classification prompt** - `5163d0a` (feat)
2. **Task 2: Add IMAGE routing branch in chat_pipeline.py** - `6c6c53a` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `workspace/sci_fi_dashboard/llm_wrappers.py` - route_traffic_cop() now includes IMAGE as fifth classification with docstring and prompt updated
- `workspace/sci_fi_dashboard/chat_pipeline.py` - elif IMAGE branch added before else:casual; early return placeholder response for image_gen role

## Decisions Made

- IMAGE placed first in traffic cop bullet list (before CODING) so the LLM receives the new category with highest attention weight
- Negative examples ("NOT 'draw up a plan', 'create a document', or 'draw conclusions'") included directly in the IMAGE bullet to prevent false-positive classification
- Placeholder early return (not casual fallback) ensures no IMAGE request is silently misrouted — Plan 03 will replace return with BackgroundTask dispatch
- STRATEGY_TO_ROLE not modified — image requests must always go through traffic cop (never pre-classified by dual cognition response_strategy)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 03 (09-03) can now wire the BackgroundTask image generation dispatch into the IMAGE branch established here
- The IMAGE branch placeholder return acts as an explicit marker for Plan 03: replace `return {"reply": "Image generation is being set up.", ...}` with actual BackgroundTask dispatch + Vault hemisphere block

---
*Phase: 09-image-generation*
*Completed: 2026-04-09*
