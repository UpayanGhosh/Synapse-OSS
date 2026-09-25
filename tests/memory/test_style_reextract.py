"""Resumable, owner-scoped classification of legacy relationship rows."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sci_fi_dashboard.personal_memory import PersonalMemoryStore, PersonMemoryContext
from sci_fi_dashboard.personal_memory_service import PersonalMemoryService


def _db_path() -> Path:
    root = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "style-reextract" / uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    return root / "memory.db"


def _legacy_store(db_path: Path) -> PersonalMemoryStore:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE personal_relationship_updates (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               owner_key TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL,
               explicit INTEGER NOT NULL, confidence REAL, source_episode_id TEXT NOT NULL,
               evidence TEXT NOT NULL, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
               UNIQUE(owner_key,field,value,explicit,source_episode_id))"""
        )
    return PersonalMemoryStore(db_path)


def _source(
    store: PersonalMemoryStore, context: PersonMemoryContext,
    key: str, content: str, minute: int,
) -> str:
    source = store.capture_episode(
        context, source_message_id=key, content=content,
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC) + timedelta(minutes=minute),
    )
    assert source
    return source


def test_legacy_owner_row_reextracts_without_replaying_value_or_provenance() -> None:
    db_path = _db_path()
    store = _legacy_store(db_path)
    alice = PersonMemoryContext("person:alice", "dm:alice")
    content = "My default is straightforward and formal."
    source = _source(store, alice, "legacy-tone", content, 0)
    store.apply_relationship_update(
        alice, {"tone": "straightforward and formal"},
        source_episode_id=source, evidence="straightforward and formal",
    )
    with sqlite3.connect(db_path) as conn:
        before = conn.execute(
            "SELECT value,evidence,occurred_at,recorded_at FROM personal_relationship_updates"
        ).fetchone()
    requests = []

    def extractor(observation):
        requests.append(observation)
        return {"style_control": "professional_precise"}

    service = PersonalMemoryService(store, extractor=extractor)
    assert service.queue_missing_style_controls(alice, limit=1) == 1
    assert service.queue_missing_style_controls(alice, limit=1) == 0
    result = asyncio.run(service.process_style_reextract_once(alice, limit=1))

    assert result["classified"] == 1
    assert len(requests) == 1
    assert requests[0]["text"] == content
    assert requests[0]["style_backfill_target"]["field"] == "tone"
    assert store.get_relationship(alice)["runtime_style"] == {"tone": "professional_precise"}
    with sqlite3.connect(db_path) as conn:
        after = conn.execute(
            "SELECT value,evidence,occurred_at,recorded_at FROM personal_relationship_updates"
        ).fetchone()
    assert after == before


def test_seed_is_bounded_and_skips_foreign_superseded_and_nonnull_rows() -> None:
    store = PersonalMemoryStore(_db_path())
    alice = PersonMemoryContext("person:alice", "dm:alice")
    bob = PersonMemoryContext("person:bob", "dm:bob")
    for index in range(7):
        source = _source(store, alice, f"alice-{index}", f"Please keep tone {index} formal.", index)
        store.apply_inferred_relationship_update(
            alice, {"tone": {"value": f"formal {index}", "confidence": 0.8}},
            source_episode_id=source,
            evidence=f"tone {index} formal",
        )
    bob_source = _source(store, bob, "bob-private", "Keep my replies brief.", 0)
    store.apply_relationship_update(
        bob, {"verbosity": "brief"}, source_episode_id=bob_source, evidence="replies brief",
    )
    canonical_source = _source(store, alice, "already-canonical", "Use detailed replies.", 8)
    store.apply_relationship_update(
        alice, {"verbosity": {"value": "detailed", "style_control": "detailed"}},
        source_episode_id=canonical_source, evidence="detailed replies",
    )

    service = PersonalMemoryService(store, extractor=lambda _observation: {"style_control": None})
    assert service.queue_missing_style_controls(alice, limit=2) == 2
    assert service.queue_missing_style_controls(alice, limit=2) == 2
    assert service.queue_missing_style_controls(alice, limit=2) == 2
    assert service.queue_missing_style_controls(alice, limit=2) == 1
    assert service.queue_missing_style_controls(alice, limit=2) == 0
    assert service.style_reextract_status(alice)["pending"] == 7
    assert service.style_reextract_status(bob)["pending"] == 0
    assert service.queue_missing_style_controls(bob, limit=2) == 1


def test_capture_autoqueues_and_pump_repairs_after_restart() -> None:
    store = PersonalMemoryStore(_db_path())
    alice = PersonMemoryContext("person:alice", "dm:alice")
    old = _source(store, alice, "old-style", "I like concise replies.", 0)
    store.apply_relationship_update(
        alice, {"verbosity": "concise replies"},
        source_episode_id=old, evidence="concise replies",
    )

    async def extractor(observation):
        if observation.get("style_backfill_target"):
            return {"style_control": "concise"}
        return {"relationship_updates": []}

    first = PersonalMemoryService(store, extractor=extractor, poll_seconds=0.01)
    first.capture_user_turn(
        alice, source_message_id="new-inbound", content="Hello again.",
        occurred_at=datetime(2026, 9, 25, 1, tzinfo=UTC),
    )
    assert first.style_reextract_status(alice)["pending"] == 1

    restarted = PersonalMemoryService(PersonalMemoryStore(store.db_path), extractor=extractor, poll_seconds=0.01)

    async def run_pump() -> None:
        await restarted.start()
        try:
            for _ in range(100):
                if restarted.store.get_relationship(alice)["runtime_style"].get("verbosity") == "concise":
                    break
                await asyncio.sleep(0.02)
        finally:
            await restarted.stop()

    asyncio.run(run_pump())
    assert restarted.store.get_relationship(alice)["runtime_style"] == {"verbosity": "concise"}


def test_source_corrected_during_model_call_cannot_be_reclassified() -> None:
    store = PersonalMemoryStore(_db_path())
    alice = PersonMemoryContext("person:alice", "dm:alice")
    old = _source(store, alice, "old", "Please use formal tone.", 0)
    store.apply_relationship_update(
        alice, {"tone": "formal"}, source_episode_id=old, evidence="formal tone",
    )

    def extractor(_observation):
        newer = _source(store, alice, "new", "Actually use casual tone.", 1)
        store.apply_relationship_update(
            alice, {"tone": {"value": "casual", "style_control": "casual_witty"}},
            source_episode_id=newer, evidence="casual tone",
        )
        return {"style_control": "professional_precise"}

    service = PersonalMemoryService(store, extractor=extractor)
    assert service.queue_missing_style_controls(alice) == 1
    result = asyncio.run(service.process_style_reextract_once(alice))

    assert result["classified"] == 0
    assert store.get_relationship(alice)["runtime_style"] == {"tone": "casual_witty"}
    with store._connect() as conn:
        [control] = conn.execute(
            "SELECT style_control FROM personal_relationship_updates WHERE source_episode_id=?", (old,)
        ).fetchone()
    assert control is None


def test_explicit_abstention_is_terminal_and_does_not_reseed() -> None:
    store = PersonalMemoryStore(_db_path())
    alice = PersonMemoryContext("person:alice", "dm:alice")
    source = _source(store, alice, "uncertain", "I guess my voice changes a lot.", 0)
    store.apply_relationship_update(
        alice, {"tone": "changes a lot"}, source_episode_id=source,
        evidence="voice changes a lot",
    )
    service = PersonalMemoryService(store, extractor=lambda _observation: {"style_control": None})

    assert service.queue_missing_style_controls(alice) == 1
    assert asyncio.run(service.process_style_reextract_once(alice))["unclassified"] == 1
    assert store.get_relationship(alice)["runtime_style"] == {}
    assert service.queue_missing_style_controls(alice) == 0
    assert service.style_reextract_status(alice)["unclassified"] == 1


def test_malformed_model_output_retries_then_fails_without_changing_source() -> None:
    store = PersonalMemoryStore(_db_path())
    alice = PersonMemoryContext("person:alice", "dm:alice")
    source = _source(store, alice, "bad-output", "Please use a formal voice.", 0)
    store.apply_relationship_update(
        alice, {"tone": "formal voice"}, source_episode_id=source,
        evidence="formal voice",
    )
    service = PersonalMemoryService(
        store, extractor=lambda _observation: {
            "style_control": "professional_precise", "relationship_update_id": 999999,
        }
    )
    assert service.queue_missing_style_controls(alice) == 1
    for attempt in range(3):
        asyncio.run(service.process_style_reextract_once(alice))
        assert store.get_relationship(alice)["runtime_style"] == {}
        if attempt < 2:
            with store._connect() as conn:
                conn.execute(
                    "UPDATE personal_style_reextract_jobs SET next_attempt_at=?",
                    ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
                )
    assert service.style_reextract_status(alice)["failed"] == 1


def test_expired_lease_is_reclaimed_and_stale_result_cannot_overwrite() -> None:
    store = PersonalMemoryStore(_db_path())
    alice = PersonMemoryContext("person:alice", "dm:alice")
    source = _source(store, alice, "lease", "Please keep my replies brief.", 0)
    store.apply_relationship_update(
        alice, {"verbosity": "brief"}, source_episode_id=source,
        evidence="replies brief",
    )
    service = PersonalMemoryService(store, extractor=lambda _observation: {"style_control": "concise"})
    assert service.queue_missing_style_controls(alice) == 1
    old_claim = service._claim_style_reextract("person:person:alice")
    assert old_claim is not None
    with store._connect() as conn:
        conn.execute(
            "UPDATE personal_style_reextract_jobs SET lease_until=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )

    assert asyncio.run(service.process_style_reextract_once(alice))["classified"] == 1
    assert service._finish_style_reextract(old_claim, "detailed") == "stale"
    assert store.get_relationship(alice)["runtime_style"] == {"verbosity": "concise"}


def test_owner_mismatch_after_enqueue_never_reaches_extractor() -> None:
    store = PersonalMemoryStore(_db_path())
    alice = PersonMemoryContext("person:alice", "dm:alice")
    source = _source(store, alice, "owner-row", "My private style is formal.", 0)
    store.apply_relationship_update(
        alice, {"tone": "formal"}, source_episode_id=source, evidence="style is formal",
    )
    seen = []
    service = PersonalMemoryService(
        store, extractor=lambda observation: seen.append(observation) or {
            "style_control": "professional_precise"
        }
    )
    assert service.queue_missing_style_controls(alice) == 1
    with store._connect() as conn:
        conn.execute(
            "UPDATE personal_episodes SET owner_key=? WHERE episode_id=?",
            ("person:other", source),
        )

    assert asyncio.run(service.process_style_reextract_once(alice))["skipped"] == 1
    assert seen == []


def test_sync_extractor_is_bounded_by_lease_safe_timeout() -> None:
    store = PersonalMemoryStore(_db_path())
    alice = PersonMemoryContext("person:alice", "dm:alice")
    source = _source(store, alice, "slow", "Please use formal replies.", 0)
    store.apply_relationship_update(
        alice, {"tone": "formal replies"}, source_episode_id=source,
        evidence="formal replies",
    )

    def slow_extractor(_observation):
        time.sleep(0.06)
        return {"style_control": "professional_precise"}

    service = PersonalMemoryService(
        store, extractor=slow_extractor,
        style_extract_timeout=0.01, style_lease_seconds=6,
    )
    assert service.queue_missing_style_controls(alice) == 1

    assert asyncio.run(service.process_style_reextract_once(alice))["classified"] == 0
    assert service.style_reextract_status(alice)["pending"] == 1
    assert store.get_relationship(alice)["runtime_style"] == {}
