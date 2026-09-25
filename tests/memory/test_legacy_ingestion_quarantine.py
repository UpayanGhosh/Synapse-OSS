"""Interactive transcripts must not feed the unowned legacy personal corpus."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

try:
    from sci_fi_dashboard import pipeline_helpers
except ModuleNotFoundError as exc:
    if exc.name != "pyarrow":
        raise
    sys.modules["sci_fi_dashboard._deps"] = ModuleType("sci_fi_dashboard._deps")
    from sci_fi_dashboard import pipeline_helpers


def test_new_archives_interactive_transcript_without_legacy_personal_ingestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "new-quarantine" / uuid4().hex
    root.mkdir(parents=True)
    transcript_file = root / "session.jsonl"
    transcript_file.write_text('{"role":"user","text":"private joke"}\n', encoding="utf-8")
    transcript = sys.modules["sci_fi_dashboard.multiuser.transcript"]
    monkeypatch.setattr(transcript, "transcript_path", lambda *_args: transcript_file)

    async def archive(_path):
        return transcript_file

    monkeypatch.setattr(transcript, "archive_transcript", archive)
    ingested = []

    async def ingest(**kwargs):
        ingested.append(kwargs)

    monkeypatch.setattr(pipeline_helpers, "_ingest_session_background", ingest, raising=False)
    monkeypatch.setattr(
        pipeline_helpers.deps, "conversation_cache",
        SimpleNamespace(invalidate=lambda _key: None), raising=False,
    )
    monkeypatch.setattr(pipeline_helpers.deps, "diary_engine", None, raising=False)

    class Store:
        async def get(self, _key):
            return SimpleNamespace(session_id="old")

        async def delete(self, _key):
            return None

        async def update(self, _key, _value):
            return None

    async def run():
        await pipeline_helpers._handle_new_command("person-scoped", "the_creator", root, Store())
        await asyncio.sleep(0)

    asyncio.run(run())
    assert ingested == []


def test_periodic_interactive_flush_does_not_mine_unowned_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2] / ".tmp" / "synapse-audit" / "flush-quarantine" / uuid4().hex
    root.mkdir(parents=True)
    transcript_file = root / "session.jsonl"
    transcript_file.write_text("turns", encoding="utf-8")
    ingested = []

    async def ingest(**kwargs):
        ingested.append(kwargs)

    async def load_messages(_path):
        return [{"role": "user", "content": "private joke"}] * 51

    async def snapshot(_path, _messages):
        return None

    monkeypatch.setattr(pipeline_helpers, "_ingest_session_background", ingest, raising=False)
    monkeypatch.setattr(pipeline_helpers, "_write_memory_flush_snapshot", snapshot)
    transcript = sys.modules["sci_fi_dashboard.multiuser.transcript"]
    monkeypatch.setattr(transcript, "load_messages", load_messages)

    class Store:
        async def get(self, _key):
            return SimpleNamespace(
                updated_at=0, memory_flush_at=None, memory_flush_message_count=0
            )

        async def update(self, _key, _value):
            return None

    async def run():
        await pipeline_helpers._maybe_schedule_periodic_memory_flush(
            session_key="person-scoped", agent_id="the_creator", data_root=root,
            transcript_file=transcript_file, session_store=Store(),
        )
        await asyncio.sleep(0)

    asyncio.run(run())
    assert ingested == []
