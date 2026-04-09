---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: OpenClaw Feature Harvest
status: unknown
last_updated: "2026-04-09T07:58:39.039Z"
progress:
  total_phases: 12
  completed_phases: 6
  total_plans: 47
  completed_plans: 31
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-08)

**Core value:** An AI that knows you deeply, grows with you continuously, and reaches out to you first — on your machine, under your full control.
**Current focus:** Phase 6 — LLM Provider Expansion (v3.0 first phase, ready to plan)

## Current Position

Phase: 7 of 11 (Bundled Skills Library)
Plan: 1 of TBD complete in current phase
Status: In progress
Last activity: 2026-04-09 — Phase 7 Plan 01 complete (SkillManifest cloud_safe/enabled fields, shadow warning, seed_bundled_skills)

Progress: [██░░░░░░░░] 8% (31/47 plans complete)

## Milestone Map

| Milestone | Target | Status | Description |
|-----------|--------|--------|-------------|
| v1.0 | 2026-03-03 | COMPLETE | OSS independence — all OpenClaw deps removed |
| v2.0 | 2026-04-08 | COMPLETE | The Adaptive Core — skills, self-mod, subagents, browser |
| v3.0 | 2026 | CURRENT | OpenClaw Feature Harvest — providers, skills library, TTS, image gen, cron v2, dashboard, voice |
| v4.0 | Future | Planned | The Jarvis Threshold |

## Accumulated Context

### Decisions

- v3.0 phases numbered 6-11 (continuous from v2.0 which ended at Phase 5)
- Phase 10 combines CRON + DASH (9 requirements) — tightly coupled; dashboard panels require TTS/image gen SSE events from Phases 8-9
- Phase 11 (Realtime Voice) is last — highest complexity, depends on Phase 8 TTS chain and Phase 10 dashboard WebSocket
- gpt-image-1 target for Phase 9 (DALL-E 3 deprecated May 12, 2026 — time-sensitive)
- litellm budget-fallback bug (GitHub #10052) patched in Phase 6 — critical correctness dependency for all LLM-reliant phases
- BackgroundTask pattern used for all media outputs (TTS, image gen) — never inline await in persona_chat()
- Vault hemisphere isolation enforced at every cloud-API dispatch point across Phases 8-9
- [06-01] DeepSeek placed in Major Cloud (US) group — USD pricing, globally accessible; not Chinese Providers
- [06-01] deepseek/deepseek-chat chosen as validation model; deepseek-reasoner excluded (special response format not yet handled)
- [06-01] together_ai key renamed to togetherai in synapse.json.example to match _KEY_MAP contract (was silently dropping Together AI keys)
- [06-01] budget_usd/budget_duration documented on openai entry as canonical example for PROV-02 budget enforcement
- [06-02] BudgetExceededError import-guarded for older litellm version compatibility — placeholder class never matches real exceptions so except clause is inert on old versions
- [06-02] Budget check uses token count as USD proxy (1M tokens ~$1) — safety net, not billing system; avoids per-model pricing tables that change frequently
- [06-02] get_provider_spend() is non-fatal (returns zeros on error) so DB issues never block LLM calls
- [06-02] Fallback uses model_mappings.get(role).get('fallback') NOT self._router.model_list to avoid litellm Router internal coupling
- [Phase 07-bundled-skills-library]: cloud_safe defaults to True — all existing skills are cloud_safe by default; only new bundled cloud-API skills need to explicitly set False
- [Phase 07-bundled-skills-library]: synapse.* namespace reserved for bundled skills; user skills shadowing them trigger startup WARNING (not error) — both load but user is informed
- [Phase 06-llm-provider-expansion]: BudgetExceededError must be raised with (current_cost, max_budget, message) signature matching litellm.exceptions.BudgetExceededError — production code was passing a single string and was fixed
- [Phase 06-llm-provider-expansion]: qianfan is an intentional _KEY_MAP divergence — provider_steps only, not in llm_router._KEY_MAP; encoded as _PS_ONLY_KEYS in test for documentation

### Pending Todos

- Phase 2 (v2.0): 02-06-PLAN.md integration tests still pending
- Merge develop → main for v2.0 release

### Blockers/Concerns

None active.

## Session Continuity

Last session: 2026-04-09 (Phase 6 Plan 03 execution)
Stopped at: Completed 06-03-PLAN.md — Phase 6 provider expansion regression tests (10 tests, all passing); BudgetExceededError constructor bug fixed
Resume file: None
Next step: Execute 07-02-PLAN.md (author bundled skills: synapse.weather, synapse.reminders)
