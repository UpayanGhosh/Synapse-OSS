"""OBS-01..04 E2E smoke -- fake WhatsApp inbound -> all hops share runId, no raw digits, JSON only."""
from __future__ import annotations

import pytest

pytest.importorskip(
    "sci_fi_dashboard.observability.formatter",
    reason="Plans 13-01..05 create the full stack",
)


@pytest.mark.integration
@pytest.mark.smoke
def test_single_inbound_smoke(monkeypatch, tmp_path):
    """Send one fake inbound, capture all logs, assert:
      1. Exactly one distinct runId across all observability-tagged lines
      2. No raw 10+ digit JID appears in any line
      3. Every line parseable as JSON
    Implementation of this test body lives in Plan 13-06. Stub raises NotImplementedError until then."""
    pytest.skip("Plan 13-06 implements E2E smoke -- Wave 0 stub")
