"""Pending-action store for two-turn calendar confirmations.

A destructive calendar request (delete/update/move/invite) parks here
keyed by ``chat_id``. The next user turn that contains an affirmation
phrase pops the parked action and the assistant executes it. Entries
expire after :data:`DEFAULT_TTL_SECONDS` and the store is bounded so a
chatty caller cannot grow it without limit.

The store is process-local. Calendar chat sessions are single-process
today, and the cost of losing a parked action across a process restart
is one re-prompt. If multi-process becomes real, persist alongside
``auto_flush`` state.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TTL_SECONDS = 600
DEFAULT_MAX_ENTRIES = 100


@dataclass(slots=True)
class PendingAction:
    chat_id: str
    kind: str
    payload: Any
    evidence: str
    expires_at: float
    confirmation_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


class PendingActionStore:
    """Bounded TTL store of pending calendar actions, keyed by chat_id."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: callable = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._clock = clock
        self._entries: OrderedDict[str, PendingAction] = OrderedDict()

    def put(
        self,
        *,
        chat_id: str,
        kind: str,
        payload: Any,
        evidence: str = "",
    ) -> PendingAction:
        if not chat_id:
            raise ValueError("chat_id must not be blank")
        self.prune()
        action = PendingAction(
            chat_id=chat_id,
            kind=kind,
            payload=payload,
            evidence=evidence,
            expires_at=self._clock() + self._ttl,
        )
        self._entries[chat_id] = action
        self._entries.move_to_end(chat_id)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)
        return action

    def peek(self, chat_id: str) -> PendingAction | None:
        action = self._entries.get(chat_id)
        if action is None:
            return None
        if action.expires_at <= self._clock():
            self._entries.pop(chat_id, None)
            return None
        return action

    def get_and_clear(self, chat_id: str) -> PendingAction | None:
        action = self.peek(chat_id)
        if action is None:
            return None
        self._entries.pop(chat_id, None)
        return action

    def discard(self, chat_id: str) -> bool:
        return self._entries.pop(chat_id, None) is not None

    def prune(self) -> int:
        now = self._clock()
        expired = [cid for cid, action in self._entries.items() if action.expires_at <= now]
        for cid in expired:
            self._entries.pop(cid, None)
        return len(expired)

    def __len__(self) -> int:
        return len(self._entries)


_DEFAULT_STORE: PendingActionStore | None = None


def default_store() -> PendingActionStore:
    """Return a process-wide singleton store. Lazy to keep imports cheap."""
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = PendingActionStore()
    return _DEFAULT_STORE


def reset_default_store_for_tests() -> None:
    global _DEFAULT_STORE
    _DEFAULT_STORE = None
