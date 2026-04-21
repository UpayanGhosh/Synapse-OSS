"""Phase 13 -- Structured observability package.

Public API:
    redact_identifier(value) -> str           # HMAC-SHA256 identifier redaction (OBS-02)
    mint_run_id() -> str                       # Mint runId + store in ContextVar (OBS-01)
    set_run_id(run_id) -> Token                # Restore runId after queue handoff (OBS-01)
    get_run_id() -> str | None                 # Read current runId (OBS-01)
    get_child_logger(module, **extra) -> ...   # Child logger factory (OBS-01)
    JsonFormatter                              # Structured JSON formatter (OBS-03)
    RunIdFilter                                # Attaches runId to every LogRecord (OBS-01)
"""

from sci_fi_dashboard.observability.context import (
    get_run_id,
    mint_run_id,
    set_run_id,
)
from sci_fi_dashboard.observability.filters import RunIdFilter
from sci_fi_dashboard.observability.formatter import JsonFormatter
from sci_fi_dashboard.observability.logger_factory import get_child_logger
from sci_fi_dashboard.observability.redact import redact_identifier

__all__ = [
    "JsonFormatter",
    "RunIdFilter",
    "get_child_logger",
    "get_run_id",
    "mint_run_id",
    "redact_identifier",
    "set_run_id",
]
