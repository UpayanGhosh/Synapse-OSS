"""A captured user source can be distilled by two valid extractors without false conflict."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard.personal_memory import PersonalMemoryStore, PersonMemoryContext
from sci_fi_dashboard.user_memory import UserMemoryFact, upsert_user_memory_facts


def test_same_source_equal_fact_accepts_alternate_grounded_evidence() -> None:
    root = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "fact-support" / uuid4().hex
    root.mkdir(parents=True)
    store = PersonalMemoryStore(root / "memory.db")
    context = PersonMemoryContext("person:alice", "alice:chat")
    source_id = store.capture_episode(
        context,
        source_message_id="one-source",
        content="Please keep replies concise. I prefer brief answers.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )

    def fact(value: str, evidence: str) -> UserMemoryFact:
        return UserMemoryFact(
            user_id="person:alice", kind="preference", key="reply_style",
            value=value, summary="Alice prefers concise replies.", confidence=0.9,
            source_doc_id=None, evidence=evidence, source_episode_id=source_id,
        )

    with sqlite3.connect(root / "memory.db") as conn:
        upsert_user_memory_facts(conn, [fact("concise", "Please keep replies concise.")])
        upsert_user_memory_facts(conn, [fact("Concise", "I prefer brief answers.")])
        [(support,)] = conn.execute(
            "SELECT evidence FROM personal_fact_support WHERE source_episode_id=?",
            (source_id,),
        ).fetchall()
        assert support == "Please keep replies concise."
        with pytest.raises(ValueError):
            upsert_user_memory_facts(conn, [fact("concise", "Bob said this privately.")])
        with pytest.raises(ValueError):
            upsert_user_memory_facts(conn, [fact("detailed", "I prefer brief answers.")])
