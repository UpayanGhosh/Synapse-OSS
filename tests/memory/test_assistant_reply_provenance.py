from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sci_fi_dashboard.personal_memory import PersonalMemoryStore, PersonMemoryContext

TEST_DATA_ROOT = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "assistant-provenance"


@pytest.fixture
def store_root() -> Path:
    path = TEST_DATA_ROOT / uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def test_assistant_joke_is_not_recalled_until_channel_accepts_it(store_root: Path) -> None:
    store = PersonalMemoryStore(store_root / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    user_episode_id = store.capture_episode(
        context,
        source_message_id="user-joke-request",
        content="I called the tiny red umbrella our official meeting mascot.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    assistant_text = "The haunted toaster budget spreadsheet strikes again."
    assistant_episode_id = store.record_assistant_reply(
        context,
        source_episode_id=user_episode_id,
        source_message_id="reply-task:chunk:0",
        content=assistant_text,
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC),
        delivery_state="pending",
    )

    assert store.recall(context, "haunted toaster budget spreadsheet", limit=3) == []

    store.update_assistant_delivery(
        context,
        source_message_id="reply-task:chunk:0",
        delivery_state="accepted",
    )
    [recalled] = store.recall(context, "haunted toaster budget spreadsheet", limit=3)
    assert recalled.episode_id == assistant_episode_id
    assert recalled.role == "assistant"
    assert recalled.parent_episode_id == user_episode_id
    assert recalled.delivery_state == "accepted"
    assert recalled.content == assistant_text

    with pytest.raises(ValueError):
        store.apply_relationship_update(
            context,
            {"humor": "playful"},
            source_episode_id=assistant_episode_id,
            evidence="haunted toaster budget spreadsheet",
        )


@pytest.mark.parametrize("delivery_state", ["cancelled", "failed"])
def test_unaccepted_assistant_reply_never_becomes_personal_recall(
    store_root: Path,
    delivery_state: str,
) -> None:
    store = PersonalMemoryStore(store_root / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    user_episode_id = store.capture_episode(
        context,
        source_message_id="user-message",
        content="Remember the red umbrella joke.",
        occurred_at=datetime(2026, 9, 23, tzinfo=UTC),
    )
    store.record_assistant_reply(
        context,
        source_episode_id=user_episode_id,
        source_message_id=f"reply-{delivery_state}",
        content="This private response should not be recalled yet.",
        occurred_at=datetime(2026, 9, 25, tzinfo=UTC),
    )
    store.update_assistant_delivery(
        context,
        source_message_id=f"reply-{delivery_state}",
        delivery_state=delivery_state,
    )

    assert store.recall(context, "private response recalled", limit=3) == []


def test_superseded_user_source_hides_assistant_echo_but_preserves_labeled_history(
    store_root: Path,
) -> None:
    store = PersonalMemoryStore(store_root / "memory.db")
    context = PersonMemoryContext("person:alice", "whatsapp:alice", "private")
    old_episode_id = store.capture_episode(
        context,
        source_message_id="style-old",
        content="Keep my work tone formal.",
        occurred_at=datetime(2026, 9, 20, tzinfo=UTC),
    )
    assistant_reply_id = store.record_assistant_reply(
        context,
        source_episode_id=old_episode_id,
        source_message_id="reply-formal-echo",
        content="I will remember your formal work tone.",
        occurred_at=datetime(2026, 9, 20, 0, 1, tzinfo=UTC),
    )
    store.update_assistant_delivery(
        context,
        source_message_id="reply-formal-echo",
        delivery_state="accepted",
    )
    correction_id = store.capture_episode(
        context,
        source_message_id="style-correction",
        content="Correction: use a casual tone at work.",
        occurred_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    store.apply_relationship_update(
        context,
        {"tone": "formal"},
        source_episode_id=old_episode_id,
        evidence="work tone formal",
    )
    store.apply_relationship_update(
        context,
        {"tone": "casual"},
        source_episode_id=correction_id,
        evidence="Correction: use a casual tone",
    )

    active = store.recall(context, "formal work tone", limit=5)
    assert old_episode_id not in {item.episode_id for item in active}
    assert assistant_reply_id not in {item.episode_id for item in active}
    historical = store.recall(
        context,
        "formal work tone",
        limit=5,
        include_history=True,
    )
    [recalled] = [item for item in historical if item.episode_id == assistant_reply_id]
    assert recalled.status == "superseded"
    assert recalled.role == "assistant"
    assert recalled.parent_episode_id == old_episode_id
