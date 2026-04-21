"""OBS-04: per-module log level config from synapse.json. Wave 0 scaffold."""
from __future__ import annotations

import logging

import pytest

pytest.importorskip(
    "sci_fi_dashboard.observability.config",
    reason="Plan 13-05 creates this",
)
from sci_fi_dashboard.observability.config import apply_logging_config  # noqa: E402


def _make_cfg(logging_section: dict):
    """Return a duck-typed cfg with a `logging` attribute (matches SynapseConfig shape)."""
    class _Cfg:
        pass

    c = _Cfg()
    c.logging = logging_section
    return c


@pytest.mark.integration
def test_per_module_levels_applied():
    """OBS-04: synapse.json logging.modules.<name>: LEVEL is applied at lifespan."""
    cfg = _make_cfg({"level": "INFO", "modules": {"sci_fi_dashboard.llm_router": "WARNING"}})
    apply_logging_config(cfg)
    assert logging.getLogger("sci_fi_dashboard.llm_router").level == logging.WARNING


@pytest.mark.integration
def test_third_party_loggers_quieted():
    """OBS-04: litellm, httpx, uvicorn.access are tamed via config (not hard-coded)."""
    cfg = _make_cfg({
        "level": "INFO",
        "modules": {
            "litellm": "WARNING",
            "httpx": "WARNING",
            "uvicorn.access": "WARNING",
        },
    })
    apply_logging_config(cfg)
    assert logging.getLogger("litellm").level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


@pytest.mark.integration
def test_dual_cognition_logger_configurable():
    """OBS-04: dual_cognition uses logging.getLogger('dual_cognition') -- LITERAL key, not __name__."""
    # dual_cognition.py:17 uses the literal string "dual_cognition" -- verified in RESEARCH.md Pitfall 4
    cfg = _make_cfg({"level": "INFO", "modules": {"dual_cognition": "DEBUG"}})
    apply_logging_config(cfg)
    assert logging.getLogger("dual_cognition").level == logging.DEBUG, (
        "dual_cognition logger key must be the literal 'dual_cognition', not "
        "'sci_fi_dashboard.dual_cognition' -- see RESEARCH.md Pitfall 4"
    )


@pytest.mark.unit
def test_missing_section_defaults():
    """OBS-04: cfg.logging absent -> defaults applied without crash."""
    class _Cfg:
        pass

    c = _Cfg()  # no .logging attr
    apply_logging_config(c)  # must not raise
    assert logging.getLogger().level in (logging.INFO, logging.WARNING, logging.DEBUG), \
        "root level must default to a valid level"
