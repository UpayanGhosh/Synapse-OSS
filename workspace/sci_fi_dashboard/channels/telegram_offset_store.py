"""
Persisted Telegram update offset store.

Saves the last processed ``update_id`` to a JSON file so that on restart the
bot resumes from where it left off instead of re-processing old updates or
dropping pending ones.

File format (version 2)::

    {
        "version": 2,
        "bot_id": "123456",
        "update_id": 987654
    }

Safety:
  - Atomic write via ``tempfile`` + ``os.replace()`` — no partial writes.
  - Bot-ID check on load — if the token changed, the old offset is ignored
    (returns 0) so the bot doesn't skip updates belonging to a different bot.
  - Corrupt / missing file → returns 0 gracefully.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

STORE_VERSION = 2


class TelegramOffsetStore:
    """Persist and retrieve the last Telegram ``update_id``."""

    def __init__(self, state_dir: Path, account_id: str) -> None:
        self._path = state_dir / "telegram" / f"update-offset-{account_id}.json"

    @staticmethod
    def extract_bot_id(token: str) -> str:
        """Extract the digits before ``':'`` from a bot token.

        Args:
            token: A Telegram bot token like ``"123456:ABC-DEF"``.

        Returns:
            The bot ID portion, e.g. ``"123456"``.  Returns the full token
            if no colon is present (defensive).
        """
        if ":" in token:
            return token.split(":")[0]
        return token

    def load(self, current_bot_id: str) -> int:
        """Load the last saved ``update_id``.

        Returns 0 when:
          - The file does not exist.
          - The file is corrupt or not valid JSON.
          - The stored ``bot_id`` does not match *current_bot_id* (token rotation).
          - The stored ``update_id`` is not a positive integer.

        Args:
            current_bot_id: The bot ID extracted from the current token.

        Returns:
            The last saved ``update_id``, or ``0``.
        """
        if not self._path.exists():
            logger.debug("[TEL-OFFSET] No offset file at %s — starting from 0", self._path)
            return 0

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "[TEL-OFFSET] Corrupt offset file %s: %s — starting from 0", self._path, exc
            )
            return 0

        if not isinstance(data, dict):
            logger.warning("[TEL-OFFSET] Unexpected format in %s — starting from 0", self._path)
            return 0

        stored_bot_id = data.get("bot_id", "")
        if stored_bot_id != current_bot_id:
            logger.info(
                "[TEL-OFFSET] Bot-ID mismatch (stored=%s, current=%s) — resetting to 0",
                stored_bot_id,
                current_bot_id,
            )
            return 0

        update_id = data.get("update_id", 0)
        if not isinstance(update_id, int) or update_id < 0:
            logger.warning(
                "[TEL-OFFSET] Invalid update_id=%r in %s — starting from 0",
                update_id,
                self._path,
            )
            return 0

        logger.info("[TEL-OFFSET] Resuming from update_id=%d", update_id)
        return update_id

    def save(self, update_id: int, bot_id: str) -> None:
        """Atomically persist the latest ``update_id``.

        Uses a tempfile in the same directory + ``os.replace()`` for crash safety.

        Args:
            update_id: The ``update_id`` of the last successfully processed update.
            bot_id:    The bot ID (digits before ``':'``).

        Raises:
            ValueError: If *update_id* is negative.
        """
        if update_id < 0:
            raise ValueError(f"update_id must be non-negative, got {update_id}")

        self._path.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(
            {"version": STORE_VERSION, "bot_id": bot_id, "update_id": update_id},
            indent=2,
        )

        # Write to temp file in the same directory, then atomic replace
        fd, tmp_path = tempfile.mkstemp(dir=str(self._path.parent), suffix=".tmp", prefix="offset-")
        closed = False
        try:
            os.write(fd, payload.encode("utf-8"))
            os.close(fd)
            closed = True
            os.replace(tmp_path, str(self._path))
        except Exception:
            if not closed:
                with contextlib.suppress(OSError):
                    os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

        logger.debug("[TEL-OFFSET] Saved update_id=%d for bot_id=%s", update_id, bot_id)
