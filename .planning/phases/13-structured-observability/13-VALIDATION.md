---
phase: 13
slug: structured-observability
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-22
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `13-RESEARCH.md` Validation Architecture section.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (existing) |
| **Config file** | `workspace/pytest.ini` |
| **Quick run command** | `cd workspace && pytest tests/test_logging_core.py tests/test_redact.py -v -x` |
| **Full suite command** | `cd workspace && pytest tests/ -v -m "unit or integration"` |
| **Estimated runtime** | ~30s (quick) / ~90s (full) |

---

## Sampling Rate

- **After every task commit:** Run quick command (redact + child-logger unit tests)
- **After every plan wave:** Run full suite (includes runId propagation integration test)
- **Before `/gsd-verify-work`:** Full suite must be green + manual smoke (send one WhatsApp msg, `jq` the log)
- **Max feedback latency:** ~30s per commit

---

## Per-Task Verification Map

Tasks are placeholders — planner will finalize IDs. Each row ties a task to a requirement + secure behavior + automated test.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-00-W0 | 00 | 0 | — | — | Test scaffold present before feature work | scaffold | `cd workspace && pytest tests/test_logging_core.py --collect-only` | ✅ | ⬜ pending |
| 13-01-01 | 01 | 1 | OBS-02 | T-13-PII | `redact_identifier(JID)` never emits raw 10+ digit runs | unit | `cd workspace && pytest tests/test_redact.py::test_jid_redaction_golden -v` | ✅ | ⬜ pending |
| 13-01-02 | 01 | 1 | OBS-02 | T-13-PII | Redaction is deterministic (same input → same output) | unit | `cd workspace && pytest tests/test_redact.py::test_redaction_idempotent -v` | ✅ | ⬜ pending |
| 13-01-03 | 01 | 1 | OBS-02 | T-13-PII | Salt loaded from env or generated at startup | unit | `cd workspace && pytest tests/test_redact.py::test_salt_sourced_correctly -v` | ✅ | ⬜ pending |
| 13-01-04 | 01 | 1 | OBS-02 | T-13-PII | Fuzz: 1000 JIDs → zero raw-digit leaks | unit | `cd workspace && pytest tests/test_redact.py::test_fuzz_no_digit_leak -v` | ✅ | ⬜ pending |
| 13-01-05 | 01 | 1 | OBS-02 | T-13-PLACEHOLDER-01 | Bracketed sentinels (`<none>`, `<empty>`, `<no-run>`, `<unknown>`) short-circuit — pass through unchanged, never hashed | unit | `cd workspace && pytest tests/test_redact.py::test_bracketed_placeholders_passthrough -v` | ✅ | ⬜ pending |
| 13-02-01 | 02 | 1 | OBS-03 | — | JSON formatter emits parseable lines with `module/runId/level` | unit | `cd workspace && pytest tests/test_logging_core.py::test_json_formatter_fields -v` | ✅ | ⬜ pending |
| 13-02-02 | 02 | 1 | OBS-03 | — | `ensure_ascii=True` — Windows cp1252 safe | unit | `cd workspace && pytest tests/test_logging_core.py::test_formatter_ascii_safe -v` | ✅ | ⬜ pending |
| 13-02-03 | 02 | 1 | OBS-01 | — | `get_child_logger(module, runId)` returns adapter with both fields in `extra` | unit | `cd workspace && pytest tests/test_logging_core.py::test_child_logger_extras -v` | ✅ | ⬜ pending |
| 13-02-04 | 02 | 1 | OBS-01 | — | ContextVar propagates runId across `asyncio.create_task` | unit | `cd workspace && pytest tests/test_logging_core.py::test_contextvar_across_tasks -v` | ✅ | ⬜ pending |
| 13-03-01 | 03 | 2 | OBS-01 | — | Worker inherits runId from enqueued `MessageTask` (per-task ContextVar seeding) | unit | `cd workspace && pytest tests/test_run_id_propagation.py::test_worker_inherits_task_run_id -v` | ✅ | ⬜ pending |
| 13-03-02 | 03 | 2 | OBS-01 | — | runId survives FloodGate → Dedup → Queue → Worker hops | integration | `cd workspace && pytest tests/test_run_id_propagation.py::test_end_to_end_run_id -v` | ✅ | ⬜ pending |
| 13-03-03 | 03 | 2 | OBS-01 | — | FloodGate last-wins runId documented + tested | unit | `cd workspace && pytest tests/test_run_id_propagation.py::test_flood_batch_last_wins -v` | ✅ | ⬜ pending |
| 13-04-01 | 04 | 2 | OBS-01 | — | `pipeline_emitter.start_run()` reads runId from ContextVar (no race) | unit | `cd workspace && pytest tests/test_pipeline_emitter.py::test_concurrent_runs_isolated -v` | ✅ | ⬜ pending |
| 13-04-02 | 04 | 2 | OBS-01 | — | Chat pipeline + LLM router + channel.send all log with same runId | integration | `cd workspace && pytest tests/test_run_id_propagation.py::test_all_hops_share_run_id -v` | ✅ | ⬜ pending |
| 13-05-01 | 05 | 2 | OBS-04 | — | `logging.modules.<name>: LEVEL` from synapse.json applied at boot | unit | `cd workspace && pytest tests/test_logging_config.py::test_per_module_levels_applied -v` | ✅ | ⬜ pending |
| 13-05-02 | 05 | 2 | OBS-04 | — | Third-party loggers (litellm, httpx, uvicorn) tamed via config | unit | `cd workspace && pytest tests/test_logging_config.py::test_third_party_loggers_quieted -v` | ✅ | ⬜ pending |
| 13-05-03 | 05 | 2 | OBS-04 | — | `dual_cognition` (non-`__name__` logger) responds to config key | unit | `cd workspace && pytest tests/test_logging_config.py::test_dual_cognition_logger_configurable -v` | ✅ | ⬜ pending |
| 13-06-01 | 06 | 3 | OBS-01, OBS-02, OBS-03, OBS-04 | T-13-PII, T-13-SMOKE-05 | E2E smoke: fake WhatsApp msg → `jq '.runId == X'` returns 1 conversation, no raw digits in log, structured JSON only, zero null-runId on critical path | integration | `cd workspace && pytest tests/test_observability_smoke.py -v` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `workspace/tests/test_logging_core.py` — stubs for OBS-01, OBS-03 (JSON formatter, child logger, ContextVar)
- [x] `workspace/tests/test_redact.py` — stubs for OBS-02 (golden values, idempotency, fuzz, bracketed passthrough)
- [x] `workspace/tests/test_run_id_propagation.py` — stubs for OBS-01 end-to-end threading + worker-inherit unit test
- [x] `workspace/tests/test_pipeline_emitter.py` — stubs for concurrent runId isolation
- [x] `workspace/tests/test_logging_config.py` — stubs for OBS-04 per-module level config
- [x] `workspace/tests/test_observability_smoke.py` — stub for E2E smoke (includes null-runId-on-critical-path assertion)
- [x] `workspace/tests/conftest.py` — ensure fixtures exist for `caplog` structured parsing and a fake inbound WhatsApp payload factory (extend existing conftest if present)

*pytest.ini + requirements-dev.txt already verified present in RESEARCH.md — no framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real WhatsApp message produces single-runId conversation in production log | OBS-01 | Requires live Baileys bridge + real phone, cannot be fully reproduced in pytest without mocking every hop | Start stack → send one WhatsApp message → `jq -r 'select(.runId != null and .runId != "<no-run>") \| .module' ~/.synapse/logs/app.jsonl \| sort -u` shows at least {flood, dedup, queue, worker, pipeline, llm, channel}; also `jq -r 'select(.runId == null and (.module \| test("flood\|dedup\|queue\|worker\|pipeline\|llm\|channel"))) \| .module' ~/.synapse/logs/app.jsonl \| wc -l` MUST equal `0` |
| No raw digits in production logs over a real session | OBS-02 | Fuzz unit test gives high confidence; live grep is final acceptance | `grep -E '[0-9]{10}@' ~/.synapse/logs/app.jsonl` returns zero lines after a 10-message session |
| Setting LLM to DEBUG actually changes runtime verbosity | OBS-04 | Config reload semantics vary; operators need to see the toggle work | Edit `synapse.json` → `logging.modules.llm: "DEBUG"` → restart → send message → confirm LLM payload lines appear; set `channel: "WARNING"` → confirm channel INFO lines vanish |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags (pytest runs one-shot)
- [x] Feedback latency < 30s (quick command)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-04-22 (Wave 0 scaffold committed)
