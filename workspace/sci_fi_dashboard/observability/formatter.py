"""OBS-03: JsonFormatter -- emits structured JSON log lines with OBS fields.

Fields emitted on every line:
    ts        ISO-8601 timestamp
    level     INFO / WARNING / ERROR / DEBUG
    module    LoggerAdapter sticky "module" extra, or record.name fallback
    runId     current ContextVar value (None if unset)
    msg       rendered log message

Additional extras: sensitive fields (chat_id, user_id, jid, phone, sender_id)
are renamed to <field>_redacted and passed through redact_identifier().

Windows cp1252 safety: ensure_ascii=True escapes all non-ASCII as \\uXXXX.
"""

from __future__ import annotations

import json
import logging

from sci_fi_dashboard.observability.context import get_run_id
from sci_fi_dashboard.observability.redact import redact_identifier

_SENSITIVE_FIELDS: frozenset[str] = frozenset({"chat_id", "user_id", "jid", "phone", "sender_id"})

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()) | {
    "message",
    "asctime",
}


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log line. Parseable via json.loads()."""

    default_time_format = "%Y-%m-%dT%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        module_name = getattr(record, "_obs_module", None) or record.name

        payload: dict = {
            "ts": self.formatTime(record, self.default_time_format),
            "level": record.levelname,
            "module": module_name,
            "runId": getattr(record, "run_id", None) or get_run_id(),
            "msg": record.getMessage(),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if key in ("run_id", "module"):
                continue
            if key in _SENSITIVE_FIELDS:
                payload[f"{key}_redacted"] = redact_identifier(
                    value if isinstance(value, str) else str(value)
                )
            else:
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = str(value)

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=True)
