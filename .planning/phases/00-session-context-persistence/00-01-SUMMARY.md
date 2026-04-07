---
phase: 00-session-context-persistence
plan: "01"
subsystem: pipeline-infrastructure
tags: [conversation-cache, llm-adapter, deps-singleton, compaction-bridge]
dependency_graph:
  requires: []
  provides:
    - ConversationCache singleton in _deps.py (key: deps.conversation_cache)
    - _LLMClientAdapter class in pipeline_helpers.py
  affects:
    - workspace/sci_fi_dashboard/_deps.py
    - workspace/sci_fi_dashboard/pipeline_helpers.py
tech_stack:
  added: []
  patterns:
    - Module-level singleton pattern (ConversationCache follows brain/gate/toxic_scorer/dual_cognition)
    - Adapter pattern (_LLMClientAdapter bridges SynapseLLMRouter._do_call to acompletion contract)
key_files:
  created: []
  modified:
    - workspace/sci_fi_dashboard/_deps.py
    - workspace/sci_fi_dashboard/pipeline_helpers.py
decisions:
  - ConversationCache initialized with max_entries=200 (LRU eviction cap) and ttl_s=300 (5-min sliding TTL) per D-08
  - _LLMClientAdapter uses "casual" role for compaction LLM calls
  - max_tokens=2000 for compaction summaries (avoids truncation of large conversation summaries)
  - _do_call private method access is intentional — no public SynapseLLMRouter method returns raw litellm response
metrics:
  duration: "~8 minutes"
  completed: "2026-04-07T05:46:02Z"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
---

# Phase 00 Plan 01: ConversationCache Singleton and LLM Adapter Summary

**One-liner:** LRU ConversationCache singleton (max_entries=200, ttl_s=300) wired into _deps.py plus _LLMClientAdapter bridging SynapseLLMRouter._do_call to compaction's acompletion contract.

## What Was Built

Two prerequisites for Plan 00-02 session persistence wiring:

1. **ConversationCache singleton** in `_deps.py` — a module-level LRU cache for parsed conversation message lists, accessible as `deps.conversation_cache` throughout the pipeline. Follows the existing singleton pattern used by `brain`, `gate`, `toxic_scorer`, `memory_engine`, and `dual_cognition`.

2. **_LLMClientAdapter class** in `pipeline_helpers.py` — an adapter class that bridges `SynapseLLMRouter` (which has no `acompletion()` method) to the `compaction.py` contract (`await llm_client.acompletion(messages=[...])`). Uses `_do_call("casual", messages)` internally with `max_tokens=2000`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add ConversationCache singleton to _deps.py | 9ce9092 | workspace/sci_fi_dashboard/_deps.py |
| 2 | Create _LLMClientAdapter class in pipeline_helpers.py | 72fc661 | workspace/sci_fi_dashboard/pipeline_helpers.py |

## Decisions Made

- **max_entries=200**: Limits LRU cache to 200 session keys — prevents memory exhaustion on busy instances with many concurrent sessions (T-00-01 mitigation).
- **ttl_s=300**: 5-minute sliding TTL — sessions stay warm while active, evicted after 5 minutes of inactivity. Each `get()` slides the TTL forward.
- **"casual" role for compaction**: Compaction summaries use the casual model (typically Gemini Flash) — fast, cheap, adequate for summarization tasks.
- **max_tokens=2000**: Doubled from `_do_call` default (1000) to prevent truncation of multi-turn conversation summaries.
- **Private `_do_call` access**: Intentional design choice (Research Pitfall 2, Option A). No public SynapseLLMRouter method returns the raw litellm response object — `.call()` returns a plain string, which cannot satisfy compaction's `.choices[0].message.content` access pattern.

## Deviations from Plan

None — plan executed exactly as written.

Note: The plan assumed `conversation_cache.py` and the full `llm_router.py` (with `_do_call`) were already in the working tree. They were at HEAD (e585832 on refactor/optimize) but the worktree required a `git reset --soft` to reach the correct base. After reset, the necessary files were confirmed present at HEAD and on disk.

## Known Stubs

None. Both additions are concrete implementations:
- `ConversationCache` uses a real `OrderedDict`-based LRU implementation with proper TTL logic
- `_LLMClientAdapter.acompletion()` delegates to a real router method

## Threat Flags

No new trust boundaries or security-relevant surfaces introduced:
- `ConversationCache` is in-process memory, keyed by session_key — no cross-session access possible
- `_LLMClientAdapter` is internal wiring — no new network endpoints or auth paths

T-00-01 (DoS — unbounded cache growth) is mitigated by `max_entries=200` with LRU eviction.
T-00-02 (Info Disclosure — cross-session cache leakage) is accepted — single-process model, keyed by session_key.

## Self-Check: PASSED

Files verified:
- `workspace/sci_fi_dashboard/_deps.py` — contains `from sci_fi_dashboard.multiuser.conversation_cache import ConversationCache` (line 41) and `conversation_cache = ConversationCache(max_entries=200, ttl_s=300)` (line 116)
- `workspace/sci_fi_dashboard/pipeline_helpers.py` — contains `class _LLMClientAdapter:` (line 203) with `async def acompletion(...)` and `self._router._do_call("casual", messages, max_tokens=max_tokens)`

Commits verified:
- 9ce9092: feat(00-01): add ConversationCache singleton to _deps.py
- 72fc661: feat(00-01): add _LLMClientAdapter class to pipeline_helpers.py
