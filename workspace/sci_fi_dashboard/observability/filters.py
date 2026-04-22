"""OBS-01: RunIdFilter -- attaches the current ContextVar runId to every LogRecord.

Existing modules use logger.getLogger(__name__) without extra={}. A Filter at the
handler level lets those legacy call sites emit correlated log lines without any code change.
"""

from __future__ import annotations

import logging

from sci_fi_dashboard.observability.context import get_run_id


class RunIdFilter(logging.Filter):
    """Enrich every LogRecord with `run_id` from the ContextVar.

    Always returns True -- adds a field, never drops records.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = get_run_id()
        return True
