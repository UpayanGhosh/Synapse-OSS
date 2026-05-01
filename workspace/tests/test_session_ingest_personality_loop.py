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


@pytest.mark.asyncio
async def test_ingest_writes_atomic_facts_and_links_triples_to_source_doc(
    tmp_memory_db: Path, tmp_transcript: Path
) -> None:
    from sci_fi_dashboard import session_ingest

    mock_cfg = MagicMock()
    mock_cfg.db_dir = tmp_memory_db.parent
    mock_cfg.kg_extraction.enabled = True
    mock_cfg.kg_extraction.kg_role = "casual"

    conn = sqlite3.connect(str(tmp_memory_db))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS atomic_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity TEXT,
                content TEXT NOT NULL,
                category TEXT,
                source_doc_id INTEGER,
                unix_timestamp INTEGER,
                embedding_model TEXT DEFAULT 'nomic-embed-text',
                embedding_version TEXT DEFAULT 'ollama-v1',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS entity_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                relation TEXT NOT NULL,
                object TEXT NOT NULL,
                archived INTEGER DEFAULT 0,
                source_fact_id INTEGER,
                source_doc_id INTEGER,
                confidence REAL DEFAULT 1.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                content TEXT,
                kg_processed INTEGER DEFAULT 0
            );
            INSERT INTO documents (id, filename, content, kg_processed)
            VALUES (321, 'session', 'test', 0);
            """
        )
        conn.commit()
    finally:
        conn.close()

    async def _fake_load_messages(path: Path) -> list[dict]:  # noqa: ARG001
        return [
            {"role": "user", "content": "Baba is my father and he called me today."},
            {"role": "assistant", "content": "That mattered."},
        ]

    class _MockExtractor:
        def __init__(self, *args, **kwargs):
            pass

        async def extract(self, text: str) -> dict:  # noqa: ARG002
            return {
                "facts": [
                    {
                        "entity": "Baba",
                        "content": "Baba is user's father.",
                        "category": "Relationship",
                    }
                ],
                "triples": [["Baba", "related_to", "user"]],
                "validated_triples": [(["Baba", "related_to", "user"], 1.0)],
            }

    mock_deps = types.SimpleNamespace(
        memory_engine=types.SimpleNamespace(
            add_memory=lambda **kwargs: {"status": "stored", "id": 321, "embedded": True}
        ),
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
        patch("sci_fi_dashboard.conv_kg_extractor.ConvKGExtractor", _MockExtractor),
    ):
        await session_ingest._ingest_session_background(
            archived_path=tmp_transcript,
            agent_id="the_creator",
            session_key="agent:the_creator:telegram:dm:123",
            hemisphere="safe",
        )

    conn = sqlite3.connect(str(tmp_memory_db))
    try:
        doc_kg_processed = conn.execute(
            "SELECT kg_processed FROM documents WHERE id = 321"
        ).fetchone()
        fact = conn.execute(
            "SELECT id, entity, content, category, source_doc_id, unix_timestamp, created_at FROM atomic_facts"
        ).fetchone()
        link = conn.execute(
            "SELECT subject, relation, object, source_doc_id, source_fact_id, created_at FROM entity_links"
        ).fetchone()
    finally:
        conn.close()

    assert doc_kg_processed == (1,)
    assert fact is not None
    assert fact[1:5] == ("Baba", "Baba is user's father.", "Relationship", 321)
    assert isinstance(fact[5], int)
    assert fact[6]
    assert link is not None
    assert link[:4] == ("Baba", "related_to", "user", 321)
    assert link[4] == fact[0]
    assert link[5]


def test_kg_entity_links_schema_adds_source_doc_id_for_legacy_tables() -> None:
    from sci_fi_dashboard.conv_kg_extractor import (
        _ensure_entity_links,
        _write_triple_to_entity_links,
    )

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            """
            CREATE TABLE entity_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                relation TEXT NOT NULL,
                object TEXT NOT NULL,
                archived INTEGER DEFAULT 0,
                source_fact_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        _ensure_entity_links(conn)
        _write_triple_to_entity_links(
            conn,
            "Baba",
            "related_to",
            "user",
            fact_id=44,
            confidence=0.9,
            source_doc_id=321,
        )
        conn.commit()

        cols = {row[1] for row in conn.execute("PRAGMA table_info(entity_links)")}
        row = conn.execute(
            "SELECT subject, relation, object, source_doc_id, source_fact_id FROM entity_links"
        ).fetchone()
    finally:
        conn.close()

    assert "source_doc_id" in cols
    assert row == ("Baba", "related_to", "user", 321, 44)


@pytest.mark.asyncio
async def test_ingest_normalizes_first_person_and_skips_vague_pronoun_kg_entities(
    tmp_memory_db: Path, tmp_transcript: Path
) -> None:
    from sci_fi_dashboard import session_ingest

    mock_cfg = MagicMock()
    mock_cfg.db_dir = tmp_memory_db.parent
    mock_cfg.kg_extraction.enabled = True
    mock_cfg.kg_extraction.kg_role = "casual"

    conn = sqlite3.connect(str(tmp_memory_db))
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT,
                content TEXT,
                kg_processed INTEGER DEFAULT 0
            );
            INSERT INTO documents (id, filename, content, kg_processed)
            VALUES (654, 'session', 'test', 0);
            """
        )
        conn.commit()
    finally:
        conn.close()

    async def _fake_load_messages(path: Path) -> list[dict]:  # noqa: ARG001
        return [
            {"role": "user", "content": "I like Mira, but she owes me nothing."},
            {"role": "assistant", "content": "Fair."},
        ]

    class _MockExtractor:
        def __init__(self, *args, **kwargs):
            pass

        async def extract(self, text: str) -> dict:  # noqa: ARG002
            return {
                "facts": [
                    {"entity": "I", "content": "I like Mira.", "category": "Relationship"},
                    {
                        "entity": "I",
                        "content": "likes the person I like.",
                        "category": "Relationship",
                    },
                    {
                        "entity": "I",
                        "content": "likes the person",
                        "category": "Relationship",
                    },
                    {
                        "entity": "I",
                        "content": 'likes "someone the user likes"',
                        "category": "Relationship",
                    },
                    {
                        "entity": "I",
                        "content": (
                            'Seeing "the person I like" get comfortable with "someone else" '
                            "made User feel small."
                        ),
                        "category": "Relationship",
                    },
                    {"entity": "she", "content": "She owes me nothing.", "category": "Relationship"},
                ],
                "triples": [
                    ["I", "interested_in", "Mira"],
                    ["user", "likes", "person I like"],
                    ["someone", "related_to", "attention"],
                ],
                "validated_triples": [
                    (["I", "interested_in", "Mira"], 1.0),
                    (["user", "likes", "person I like"], 1.0),
                    (["someone", "related_to", "attention"], 1.0),
                ],
            }

    mock_deps = types.SimpleNamespace(
        memory_engine=types.SimpleNamespace(
            add_memory=lambda **kwargs: {"status": "stored", "id": 654, "embedded": True}
        ),
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
        patch("sci_fi_dashboard.conv_kg_extractor.ConvKGExtractor", _MockExtractor),
    ):
        await session_ingest._ingest_session_background(
            archived_path=tmp_transcript,
            agent_id="the_creator",
            session_key="agent:the_creator:telegram:dm:123",
            hemisphere="safe",
        )

    conn = sqlite3.connect(str(tmp_memory_db))
    try:
        fact_entities = [
            row[0] for row in conn.execute("SELECT entity FROM atomic_facts ORDER BY id")
        ]
        fact_contents = [
            row[0] for row in conn.execute("SELECT content FROM atomic_facts ORDER BY id")
        ]
        links = conn.execute(
            "SELECT subject, relation, object FROM entity_links ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    assert fact_entities == ["user", "user", "user", "user", "user"]
    assert fact_contents == [
        "User likes Mira.",
        "User likes someone.",
        "User likes someone.",
        "User likes someone.",
        "Seeing someone the user likes get comfortable with someone else made the user feel small.",
    ]
    assert links == [("user", "interested_in", "Mira")]
