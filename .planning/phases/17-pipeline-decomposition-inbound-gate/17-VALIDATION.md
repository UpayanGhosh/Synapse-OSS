---
phase: 17
slug: pipeline-decomposition-inbound-gate
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-24
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (python 3.11) |
| **Config file** | `workspace/pyproject.toml` (pytest.ini_options section) |
| **Quick run command** | `cd workspace && pytest tests/ -m "unit or integration" -x --ff -q` |
| **Full suite command** | `cd workspace && pytest tests/ -v` |
| **Estimated runtime** | ~90 seconds full suite; ~25s quick path |

---

## Sampling Rate

- **After every task commit:** Run quick path against the tests relevant to the module touched (see Per-Task Verification Map)
- **After every plan wave:** Run full suite — PIPE-04 demands zero test modifications AND unchanged pass count
- **Before `/gsd-verify-work`:** Full suite + access-gate rejection stress test (100-message blocked-sender scenario) must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

> Plans fill in concrete task IDs once `/gsd-plan-phase 17` completes. This table is the Nyquist skeleton.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 17-00-01 | 00 | 0 | PIPE-04 | — | Pre-refactor test count + hash captured | unit | `cd workspace && pytest tests/ --collect-only -q \| tail -1` | ✅ | ⬜ pending |
| 17-01-01 | 01 | 1 | PIPE-01, PIPE-02 | — | `pipeline/` package exists with six module stubs + `PipelineContext` dataclass importable | unit | `cd workspace && python -c "from sci_fi_dashboard.pipeline import normalize, debounce, access, enrich, route, reply; from sci_fi_dashboard.pipeline.context import PipelineContext"` | ❌ W0 | ⬜ pending |
| 17-02-01 | 02 | 2 | ACL-03 | T-17-01 (bypass gate) | Blocked sender produces zero FloodGate enqueue and zero dedup entries | integration | `cd workspace && pytest tests/test_inbound_gate.py::test_acl_blocks_before_floodgate -v` | ❌ W0 | ⬜ pending |
| 17-02-02 | 02 | 2 | ACL-03 | T-17-02 (log omission) | Rejection emits `module: access, reason: dm-policy, sender: <redacted>, runId: <id>` | integration | `cd workspace && pytest tests/test_inbound_gate.py::test_acl_structured_log -v` | ❌ W0 | ⬜ pending |
| 17-0X-YY | 0X | 3 | PIPE-01, PIPE-03 | — | Each phase module extracted with contract test green | unit | `cd workspace && pytest tests/pipeline/test_<module>.py -v` | ❌ W0 | ⬜ pending |
| 17-0X-YY | 0X | 4 | PIPE-03 | — | `persona_chat()` orchestrator is ≤80 lines and threads PipelineContext | unit | `cd workspace && pytest tests/pipeline/test_orchestrator.py -v` | ❌ W0 | ⬜ pending |
| 17-0X-YY | 0X | 5 | PIPE-04 | T-17-03 (regression) | Full test suite passes with zero test-file modifications and equal test count | integration | `cd workspace && pytest tests/ -v && git diff --stat tests/ \| grep -c "^$" \|\| true` | ✅ | ⬜ pending |
| 17-0X-YY | 0X | 5 | ACL-03 | T-17-04 (leak) | 100-msg blocked-sender stress: zero downstream phase entries | integration | `cd workspace && pytest tests/test_inbound_gate.py::test_acl_stress -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Planner MUST fill in final task IDs and granular per-module rows before executor starts Wave 1.**

---

## Wave 0 Requirements

- [ ] `workspace/tests/pipeline/__init__.py` — new package for phase-module contract tests
- [ ] `workspace/tests/pipeline/test_context.py` — stubs for `PipelineContext` invariants (mutability rule, required fields, runId propagation)
- [ ] `workspace/tests/pipeline/test_normalize.py`, `test_debounce.py`, `test_access.py`, `test_enrich.py`, `test_route.py`, `test_reply.py` — per-module contract stubs (one `@pytest.mark.skip("Wave 1")` stub each so pytest sees the names)
- [ ] `workspace/tests/pipeline/test_orchestrator.py` — orchestrator line-count + PipelineContext threading stub
- [ ] `workspace/tests/test_inbound_gate.py` — ACL-03 stubs covering: (a) blocks before FloodGate, (b) structured log, (c) 100-msg stress
- [ ] `workspace/tests/conftest.py` — add fixture for a `blocked_sender_policy` DmPolicy helper (shared by ACL tests)
- [ ] Pre-refactor baseline capture: `pytest --collect-only -q` output + `ruff check` output committed as artifact in Wave 0 (used to prove PIPE-04 equality at end of Wave 5)

*Pytest framework already installed in workspace/ — no framework install required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end WhatsApp pipeline with a real bridge | PIPE-01, PIPE-03 | Requires Baileys bridge + real WhatsApp pairing | Start stack → send message from allowed sender → verify reply arrives → send message from blocked sender → verify zero log emission downstream of access module |
| Latency parity before/after refactor | PIPE-04 | Cloud-model latency too variable for CI gate | Run 20 canned messages pre-split (record p50/p95) → run same 20 post-split → planner asserts delta within ±15% |
| Emergency rollback flag toggle | PIPE-03 | `pipeline.use_modular=false` must fail-back to legacy `chat_pipeline.py` path without restart → exercised manually | Toggle flag in `synapse.json` → observe live conversation still works → toggle back → observe modular path resumes |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (pipeline test package + ACL test file)
- [ ] No watch-mode flags (pytest runs in single-shot mode)
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter after planner finalises task IDs

**Approval:** pending
