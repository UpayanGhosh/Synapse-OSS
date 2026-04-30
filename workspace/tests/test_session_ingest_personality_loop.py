from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _DepsPatch:
    def __init__(self, deps) -> None:
        self.deps = deps
        self.prior_deps = None
        self.prior_pkg_deps = None
        self.had_pkg_deps = False
        self.pkg = None

    def __enter__(self):
        import sci_fi_dashboard as pkg

        self.pkg = pkg
        self.prior_deps = sys.modules.get("sci_fi_dashboard._deps")
        self.had_pkg_deps = hasattr(pkg, "_deps")
        self.prior_pkg_deps = getattr(pkg, "_deps", None)
        sys.modules["sci_fi_dashboard._deps"] = self.deps
        pkg._deps = self.deps
        return self.deps

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.prior_deps is None:
            sys.modules.pop("sci_fi_dashboard._deps", None)
        else:
            sys.modules["sci_fi_dashboard._deps"] = self.prior_deps
        if self.pkg is not None:
            if self.had_pkg_deps:
                self.pkg._deps = self.prior_pkg_deps
            elif hasattr(self.pkg, "_deps"):
                delattr(self.pkg, "_deps")


@pytest.fixture()
def tmp_memory_db() -> Path:
    db_dir = Path(__file__).parent / ".tmp_phase5" / f"kg-timeout-{uuid.uuid4().hex}"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "memory.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ingest_failures (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                session_key     TEXT,
                agent_id        TEXT,
                archived_path   TEXT,
                batch_index     INTEGER,
                total_batches   INTEGER,
                phase           TEXT NOT NULL,
                exception_type  TEXT,
                exception_msg   TEXT,
                traceback       TEXT,
                ingested_vec    INTEGER,
                ingested_kg     INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_ingest_failures_phase
                ON ingest_failures(phase);
            """
        )
        conn.commit()
    finally:
        conn.close()
    try:
        yield db_path
    finally:
        for path in (
            db_path,
            Path(str(db_path) + "-wal"),
            Path(str(db_path) + "-shm"),
        ):
            if path.exists():
                path.unlink()
        try:
            db_dir.rmdir()
        except OSError:
            pass


@pytest.fixture()
def tmp_transcript() -> Path:
    archived = Path(__file__).parent / f".kg-timeout-{uuid.uuid4().hex}.jsonl.deleted.1234567890"
    payloads = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    archived.write_text("\n".join(json.dumps(p) for p in payloads), encoding="utf-8")
    try:
        yield archived
    finally:
        if archived.exists():
            archived.unlink()


@pytest.mark.asyncio
async def test_kg_timeout_records_failure_and_completed(
    tmp_memory_db: Path, tmp_transcript: Path, monkeypatch
) -> None:
    from sci_fi_dashboard import session_ingest

    mock_cfg = MagicMock()
    mock_cfg.db_dir = tmp_memory_db.parent
    mock_cfg.kg_extraction.enabled = True
    mock_cfg.kg_extraction.kg_role = "casual"

    mock_deps = types.SimpleNamespace(
        memory_engine=types.SimpleNamespace(add_memory=lambda **kwargs: {}),
        brain=types.SimpleNamespace(
            add_node=lambda *args, **kwargs: None,
            add_relation=lambda *args, **kwargs: None,
            save_graph=lambda *args, **kwargs: None,
        ),
        synapse_llm_router=object(),
    )

    class _MockExtractor:
        def __init__(self, *args, **kwargs):
            pass

        async def extract(self, text: str) -> dict:
            return {"facts": [], "triples": [], "validated_triples": []}

    async def _fake_load_messages(path: Path) -> list[dict]:  # noqa: ARG001
        return [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

    seen_timeouts: list[float] = []

    async def _fake_wait_for(awaitable, timeout: float):
        seen_timeouts.append(timeout)
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError("kg timeout")

    monkeypatch.setattr(session_ingest.asyncio, "wait_for", _fake_wait_for)

    with (
        _DepsPatch(mock_deps),
        patch("synapse_config.SynapseConfig.load", return_value=mock_cfg),
        patch(
            "sci_fi_dashboard.multiuser.transcript.load_messages",
            new=_fake_load_messages,
        ),
        patch("sci_fi_dashboard.conv_kg_extractor.ConvKGExtractor", _MockExtractor),
    ):
        await session_ingest._ingest_session_background(
            archived_path=tmp_transcript,
            agent_id="the_creator",
            session_key="agent:the_creator:whatsapp:dm:+1234567890",
            hemisphere="safe",
        )

    assert seen_timeouts == [session_ingest.KG_EXTRACT_TIMEOUT_SECONDS]

    conn = sqlite3.connect(str(tmp_memory_db))
    try:
        rows = conn.execute(
            "SELECT phase, exception_type, ingested_vec, ingested_kg "
            "FROM ingest_failures ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    phases = [row[0] for row in rows]
    assert "kg" in phases
    assert "completed" in phases

    kg_rows = [row for row in rows if row[0] == "kg"]
    assert kg_rows, f"Expected a kg failure row, got: {rows}"
    assert any(row[1] == "TimeoutError" for row in kg_rows)

    completed_rows = [row for row in rows if row[0] == "completed"]
    assert completed_rows, f"Expected a completed row, got: {rows}"
    assert completed_rows[-1][2] == 1


@pytest.mark.asyncio
async def test_ingest_distills_response_style_and_codename(
    tmp_memory_db: Path, tmp_transcript: Path
) -> None:
    from sci_fi_dashboard import session_ingest

    mock_cfg = MagicMock()
    mock_cfg.db_dir = tmp_memory_db.parent
    mock_cfg.kg_extraction.enabled = False
    mock_cfg.kg_extraction.kg_role = "casual"

    async def _fake_load_messages(path: Path) -> list[dict]:  # noqa: ARG001
        return [
            {"role": "user", "content": "Keep it short and direct."},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Call me Nova from now on."},
            {"role": "assistant", "content": "Noted, Nova."},
        ]

    session_key = "agent:the_creator:whatsapp:dm:+1234567890"
    mock_deps = types.SimpleNamespace(
        memory_engine=types.SimpleNamespace(add_memory=lambda **kwargs: {"status": "stored", "id": 77}),
        brain=types.SimpleNamespace(
            add_node=lambda *args, **kwargs: None,
            add_relation=lambda *args, **kwargs: None,
            save_graph=lambda *args, **kwargs: None,
        ),
        synapse_llm_router=object(),
    )
    with (
        _DepsPatch(mock_deps),
        patch("synapse_config.SynapseConfig.load", return_value=mock_cfg),
        patch(
            "sci_fi_dashboard.multiuser.transcript.load_messages",
            new=_fake_load_messages,
        ),
    ):
        await session_ingest._ingest_session_background(
            archived_path=tmp_transcript,
            agent_id="the_creator",
            session_key=session_key,
            hemisphere="safe",
        )

    conn = sqlite3.connect(str(tmp_memory_db))
    try:
        rows = conn.execute(
            """
            SELECT key, value, source_doc_id, status
            FROM user_memory_facts
            WHERE user_id = ?
            ORDER BY key
            """,
            (session_key,),
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("codename", "Nova", 77, "active"),
        ("response_style", "direct", 77, "active"),
    ]


@pytest.mark.asyncio
async def test_ingest_distills_even_without_doc_id(
    tmp_memory_db: Path, tmp_transcript: Path
) -> None:
    from sci_fi_dashboard import session_ingest

    mock_cfg = MagicMock()
    mock_cfg.db_dir = tmp_memory_db.parent
    mock_cfg.kg_extraction.enabled = False
    mock_cfg.kg_extraction.kg_role = "casual"

    async def _fake_load_messages(path: Path) -> list[dict]:  # noqa: ARG001
        return [
            {"role": "user", "content": "Keep it short and direct."},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Call me Nova from now on."},
            {"role": "assistant", "content": "Noted, Nova."},
        ]

    session_key = "agent:the_creator:whatsapp:dm:+1234567890"
    mock_deps = types.SimpleNamespace(
        memory_engine=types.SimpleNamespace(add_memory=lambda **kwargs: {"status": "stored"}),
        brain=types.SimpleNamespace(
            add_node=lambda *args, **kwargs: None,
            add_relation=lambda *args, **kwargs: None,
            save_graph=lambda *args, **kwargs: None,
        ),
        synapse_llm_router=object(),
    )
    with (
        _DepsPatch(mock_deps),
        patch("synapse_config.SynapseConfig.load", return_value=mock_cfg),
        patch(
            "sci_fi_dashboard.multiuser.transcript.load_messages",
            new=_fake_load_messages,
        ),
    ):
        await session_ingest._ingest_session_background(
            archived_path=tmp_transcript,
            agent_id="the_creator",
            session_key=session_key,
            hemisphere="safe",
        )

    conn = sqlite3.connect(str(tmp_memory_db))
    try:
        rows = conn.execute(
            """
            SELECT key, value, source_doc_id, status
            FROM user_memory_facts
            WHERE user_id = ?
            ORDER BY key
            """,
            (session_key,),
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("codename", "Nova", None, "active"),
        ("response_style", "direct", None, "active"),
    ]


@pytest.mark.asyncio
async def test_ingest_records_user_memory_failure_and_completes(
    tmp_memory_db: Path, tmp_transcript: Path
) -> None:
    from sci_fi_dashboard import session_ingest

    mock_cfg = MagicMock()
    mock_cfg.db_dir = tmp_memory_db.parent
    mock_cfg.kg_extraction.enabled = False
    mock_cfg.kg_extraction.kg_role = "casual"

    mock_deps = types.SimpleNamespace(
        memory_engine=types.SimpleNamespace(
            add_memory=lambda **kwargs: {"status": "stored", "id": 99}
        ),
        brain=types.SimpleNamespace(
            add_node=lambda *args, **kwargs: None,
            add_relation=lambda *args, **kwargs: None,
            save_graph=lambda *args, **kwargs: None,
        ),
        synapse_llm_router=object(),
    )

    async def _fake_load_messages(path: Path) -> list[dict]:  # noqa: ARG001
        return [
            {"role": "user", "content": "Keep it short and direct."},
            {"role": "assistant", "content": "Done."},
        ]

    def _raise_distill(*args, **kwargs):  # noqa: ANN002, ANN003, ARG001
        raise RuntimeError("distill boom")

    with (
        _DepsPatch(mock_deps),
        patch("synapse_config.SynapseConfig.load", return_value=mock_cfg),
        patch(
            "sci_fi_dashboard.multiuser.transcript.load_messages",
            new=_fake_load_messages,
        ),
        patch(
            "sci_fi_dashboard.user_memory.distill_and_upsert_user_memory_facts",
            new=_raise_distill,
        ),
    ):
        await session_ingest._ingest_session_background(
            archived_path=tmp_transcript,
            agent_id="the_creator",
            session_key="agent:the_creator:whatsapp:dm:+1234567890",
            hemisphere="safe",
        )

    conn = sqlite3.connect(str(tmp_memory_db))
    try:
        rows = conn.execute(
            "SELECT phase, exception_type, ingested_vec, ingested_kg "
            "FROM ingest_failures ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    phases = [row[0] for row in rows]
    assert "user_memory" in phases
    assert "completed" in phases

    user_memory_rows = [row for row in rows if row[0] == "user_memory"]
    assert user_memory_rows, f"Expected user_memory failure row, got: {rows}"
    assert any(row[1] == "RuntimeError" for row in user_memory_rows)

    completed_rows = [row for row in rows if row[0] == "completed"]
    assert completed_rows, f"Expected completed row, got: {rows}"
    assert completed_rows[-1][2] == 1
