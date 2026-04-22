"""
Phase 13 -- end-to-end observability smoke test.

Proves all four OBS invariants hold simultaneously on a single inbound
WhatsApp message traversing the full pipeline via FastAPI TestClient.

Failure messages carry sha256 fingerprints + match offsets, NOT raw
content, to avoid leaking unredacted identifiers into CI logs (T-13-SMOKE-02).
"""

from __future__ import annotations

import hashlib
import re
import time

import pytest

pytest.importorskip(
    "sci_fi_dashboard.observability.redact",
    reason="Phase 13 observability module not yet installed",
)
pytest.importorskip(
    "sci_fi_dashboard.observability.config",
    reason="Phase 13 apply_logging_config not yet installed",
)

# 10+ digit runs that must NEVER appear in log lines (raw JIDs, phone numbers)
_RAW_DIGIT_RUN = re.compile(r"[0-9]{10,}")

# Critical-path modules where runId MUST be propagated
_CRITICAL_PATH_MODULE_RX = re.compile(
    r"flood|dedup|queue|worker|pipeline|llm|channel",
)

# Phase 13 modules -- at least 2 must emit under our runId
_EXPECTED_MODULES_ANY_OF = {
    "route.whatsapp",
    "gateway.worker",
    "pipeline.chat",
    "llm.router",
    "channel.whatsapp",
}


def _assert_no_raw_digits(captured: list[tuple[dict, str]]) -> None:
    """OBS-02: no 10+ digit run in any serialized log line."""
    offenders: list[tuple[int, str, int]] = []
    for idx, (_, line) in enumerate(captured):
        m = _RAW_DIGIT_RUN.search(line)
        if m:
            sha = hashlib.sha256(line.encode()).hexdigest()[:16]
            offenders.append((idx, sha, m.start()))
    if offenders:
        pytest.fail(
            f"OBS-02 failure: {len(offenders)} log line(s) contain raw 10+ digit runs. "
            f"Offenders (index, sha256[:16], match_offset): {offenders[:5]}"
        )


def _assert_all_json_parseable(captured: list[tuple[dict, str]]) -> None:
    """OBS-03: every captured line must parse as valid JSON."""
    for idx, (parsed, line) in enumerate(captured):
        if "_capture_error" in parsed:
            sha = hashlib.sha256(line.encode()).hexdigest()[:16]
            pytest.fail(
                f"OBS-03 failure: line idx={idx} sha256[:16]={sha} "
                f"failed JSON parse: {parsed['_capture_error']}"
            )


def _assert_no_null_runid_on_critical_path(
    captured: list[tuple[dict, str]],
) -> None:
    """OBS-01 null-guard: critical-path hops must NOT emit runId=null.

    Mirrors the manual jq command:
        jq -r 'select(.runId == null and (.module | test("flood|dedup|queue|worker|pipeline|llm|channel"))) | .module' | wc -l
    MUST equal 0.
    """
    null_critical: list[tuple[int, str, str]] = []
    for idx, (parsed, line) in enumerate(captured):
        module = parsed.get("module") or ""
        run_id = parsed.get("runId")
        if (run_id is None or run_id == "<no-run>") and _CRITICAL_PATH_MODULE_RX.search(module):
            sha = hashlib.sha256(line.encode()).hexdigest()[:16]
            null_critical.append((idx, module, sha))
    if null_critical:
        pytest.fail(
            f"OBS-01 null-runId failure: {len(null_critical)} critical-path "
            f"hop log line(s) emitted with runId=null. "
            f"Offenders (index, module, sha256[:16]): {null_critical[:5]}. "
            f"Count must equal 0."
        )


def _assert_single_run_id(captured: list[tuple[dict, str]]) -> str:
    """OBS-01: all records must share exactly one runId.

    Mirrors jq filter: select(.runId != null and .runId != "<no-run>")
    """
    run_ids: set[str] = set()
    for p, _ in captured:
        rid = p.get("runId")
        if rid is not None and rid != "<no-run>":
            run_ids.add(rid)
    if len(run_ids) == 0:
        pytest.fail(
            "OBS-01 failure: no runId found in any captured line "
            "(all records were null or '<no-run>')"
        )
    if len(run_ids) > 1:
        pytest.fail(
            f"OBS-01 failure: {len(run_ids)} distinct runIds in captured output. "
            f"Expected exactly 1. Got: {sorted(run_ids)[:5]}"
        )
    return next(iter(run_ids))


def _assert_modules_coverage(
    captured: list[tuple[dict, str]],
    run_id: str,
) -> None:
    """OBS-01: at least 2 Phase-13 modules must emit under our runId."""
    modules = {p.get("module") for p, _ in captured if p.get("runId") == run_id and p.get("module")}
    hit = modules & _EXPECTED_MODULES_ANY_OF
    if len(hit) < 2:
        pytest.fail(
            f"OBS-01 failure: only {len(hit)} Phase 13 modules emitted under "
            f"runId={run_id}. Got modules={sorted(modules)}; "
            f"expected any 2+ of {sorted(_EXPECTED_MODULES_ANY_OF)}"
        )


def _get_app():
    """Import api_gateway.app, skipping if the environment lacks required deps.

    api_gateway has module-level side effects that require the full singleton
    chain (torch for LazyToxicScorer, etc.). In CI without those deps the
    tests skip cleanly; in a full-stack environment they run end-to-end.
    """
    try:
        from sci_fi_dashboard.api_gateway import app  # noqa: PLC0415

        return app
    except Exception as exc:
        pytest.skip(f"api_gateway import failed (env missing deps): {exc}")


@pytest.mark.integration
def test_single_inbound_smoke(
    fake_whatsapp_payload,
    json_log_capture,
    # monkeypatch: add back + monkeypatch.setenv("DISABLE_LLM_CALLS", "1") when T-13-SMOKE-04 hook is needed
):
    """Send one synthetic WhatsApp inbound; verify all four OBS invariants.

    Uses sync TestClient + time.sleep so the FloodGate 3s batch window
    flushes without requiring asyncio.
    """
    from fastapi.testclient import TestClient
    from sci_fi_dashboard.observability import apply_logging_config

    apply_logging_config(
        {
            "level": "DEBUG",
            "modules": {
                "pipeline.chat": "DEBUG",
                "llm.router": "DEBUG",
                "gateway.worker": "DEBUG",
                "route.whatsapp": "DEBUG",
                "channel.whatsapp": "DEBUG",
            },
        }
    )

    app = _get_app()

    payload = fake_whatsapp_payload(
        text="ping",
        chat_id="5551234567890@s.whatsapp.net",
        sender_name="Smoke",
    )

    with TestClient(app) as client:
        response = client.post("/channels/whatsapp/webhook", json=payload)
        assert response.status_code in (
            200,
            202,
            204,
        ), f"Webhook returned unexpected status {response.status_code}"
        time.sleep(3.5)  # FloodGate 3s debounce + pipeline flush

    # OBS-03: every line is valid JSON
    _assert_all_json_parseable(json_log_capture)
    # OBS-02: no raw 10+ digit runs
    _assert_no_raw_digits(json_log_capture)
    # OBS-01 null-guard: no critical-path hop with runId=null
    _assert_no_null_runid_on_critical_path(json_log_capture)
    # OBS-01: exactly one runId + at least 2 Phase-13 modules
    run_id = _assert_single_run_id(json_log_capture)
    _assert_modules_coverage(json_log_capture, run_id)


@pytest.mark.integration
def test_per_module_level_toggle(
    fake_whatsapp_payload,
    json_log_capture,
):
    """OBS-04: setting pipeline.chat to CRITICAL drops its INFO emissions,
    proving per-module levels take effect at runtime."""
    from fastapi.testclient import TestClient
    from sci_fi_dashboard.observability import apply_logging_config

    apply_logging_config(
        {
            "level": "INFO",
            "modules": {
                "pipeline.chat": "CRITICAL",  # silence INFO from this module
                "route.whatsapp": "INFO",
                "gateway.worker": "INFO",
            },
        }
    )
    app = _get_app()

    payload = fake_whatsapp_payload(text="quiet please")
    with TestClient(app) as client:
        client.post("/channels/whatsapp/webhook", json=payload)
        time.sleep(3.5)

    assert len(json_log_capture) > 0, (
        "OBS-04 precondition: no log lines were captured at all — "
        "cannot verify that pipeline.chat INFO was silenced (test environment issue)"
    )
    pipeline_chat_lines = [
        p
        for p, _ in json_log_capture
        if p.get("module") == "pipeline.chat" and p.get("level") == "INFO"
    ]
    assert len(pipeline_chat_lines) == 0, (
        f"OBS-04 failure: pipeline.chat emitted {len(pipeline_chat_lines)} INFO "
        "lines despite level being set to CRITICAL"
    )
