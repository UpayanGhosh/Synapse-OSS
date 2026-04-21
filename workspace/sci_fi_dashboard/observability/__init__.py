"""Phase 13 — Structured observability package.

Public API:
    redact_identifier(value) -> str    # HMAC-SHA256 identifier redaction (OBS-02)
"""

from sci_fi_dashboard.observability.redact import redact_identifier

__all__ = ["redact_identifier"]
