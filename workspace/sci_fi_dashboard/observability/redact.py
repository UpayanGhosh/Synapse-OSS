"""OBS-02: redact_identifier() — HMAC-SHA256 salted redaction of phone numbers and JIDs.

Design notes:
  - Salt is 32 CSPRNG bytes at ~/.synapse/state/logging_salt, chmod 0o600.
  - Salt generated once on first import; persists across process restarts.
  - HMAC-SHA256 prevents reversal even if output lands on disk.
  - Output shape id_<8hex> contains no structural info about input.
  - Idempotent: redact(redact(x)) == redact(x).
  - Bracketed-placeholder passthrough: any input matching len(s) >= 2 and
    s.startswith("<") and s.endswith(">") passes through unchanged.
    These are system sentinels (<none>, <empty>, <no-run>, <unknown>) --
    NOT user-supplied identifiers. Re-hashing them would produce meaningless
    id_XXXX and break log filters. Check is BEFORE the HMAC step.
  - Never imports SynapseConfig (would create circular dep at module load).
    Salt path derived directly from Path.home() / ".synapse" / "state" / "logging_salt".
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

# ---------------------------------------------------------------------------
# Salt bootstrap — runs at module import time
# ---------------------------------------------------------------------------

_SYNAPSE_HOME = Path(os.environ.get("SYNAPSE_HOME", "")).expanduser() or (Path.home() / ".synapse")
_SALT_PATH = _SYNAPSE_HOME / "state" / "logging_salt"

# Shape of an already-redacted value. Idempotency check uses this.
_REDACTED_SHAPE = re.compile(r"^id_[0-9a-f]{8}$")


def _load_or_mint_salt() -> bytes:
    if _SALT_PATH.exists():
        raw = _SALT_PATH.read_bytes()
        if len(raw) >= 16:
            return raw
    _SALT_PATH.parent.mkdir(parents=True, exist_ok=True)
    salt = secrets.token_bytes(32)
    _SALT_PATH.write_bytes(salt)
    with contextlib.suppress(NotImplementedError, OSError):
        _SALT_PATH.chmod(0o600)
    return salt


_SALT: bytes = _load_or_mint_salt()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact_identifier(value: str | None) -> str:
    """Return a stable PII-free representation of `value`.

    Returns:
      "<none>" for falsy input; value unchanged if it already matches
      id_<8hex> shape (idempotency); value unchanged if it is a bracketed
      placeholder sentinel like <none>, <empty>, <no-run>;
      otherwise "id_<first 8 hex chars of HMAC-SHA256(salt, value)>".
    """
    if not value:
        return "<none>"
    s = value if isinstance(value, str) else str(value)
    if _REDACTED_SHAPE.match(s):
        return s
    # Bracketed-placeholder passthrough: system sentinels are NOT PII.
    # Passing through keeps log grep/dashboard filters stable (T-13-PLACEHOLDER-01).
    if len(s) >= 2 and s.startswith("<") and s.endswith(">"):
        return s
    digest = hmac.new(_SALT, s.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"id_{digest[:8]}"
