import sqlite3
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sci_fi_dashboard.embedding.migrate import re_embed_documents  # noqa: E402


class StubProvider:
    def info(self):
        return SimpleNamespace(model="new-model", name="stub", dimensions=3)

    def embed_documents(self, texts):
        return [[9.0, 8.0, 7.0] for _ in texts]


class RecordingVectorStore:
    def __init__(self):
        self.facts = []

    def upsert_facts(self, facts):
        self.facts.extend(facts)


class FailingVectorStore:
    def upsert_facts(self, facts):
        raise RuntimeError("vector store unavailable")


def make_database(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                hemisphere_tag TEXT,
                unix_timestamp INTEGER,
                importance INTEGER,
                embedding_model TEXT,
                embedding_version TEXT
            );
            CREATE TABLE vec_items (
                document_id INTEGER PRIMARY KEY,
                embedding BLOB NOT NULL
            );
            INSERT INTO documents
                VALUES (1, 'memory to re-embed', 'safe', 123, 7, 'old-model', 'old-v1');
            """,
        )
        conn.execute(
            "INSERT INTO vec_items VALUES (?, ?)",
            (1, sqlite3.Binary(struct.pack("3f", 1.0, 2.0, 3.0))),
        )


def read_document(path: Path):
    with sqlite3.connect(path) as conn:
        document = conn.execute(
            "SELECT embedding_model, embedding_version FROM documents WHERE id = 1"
        ).fetchone()
        vector = conn.execute("SELECT embedding FROM vec_items WHERE document_id = 1").fetchone()[0]
    return document, struct.unpack("3f", vector)


def test_re_embed_writes_sqlite_and_lancedb_vectors(tmp_path):
    db_path = tmp_path / "memory.db"
    make_database(db_path)
    vector_store = RecordingVectorStore()

    stats = re_embed_documents(db_path, StubProvider(), vector_store=vector_store)

    assert stats == {"processed": 1, "skipped": 0, "errors": 0}
    assert read_document(db_path) == (("new-model", "stub-v1"), (9.0, 8.0, 7.0))
    assert vector_store.facts == [
        {
            "id": 1,
            "vector": [9.0, 8.0, 7.0],
            "metadata": {
                "text": "memory to re-embed",
                "hemisphere_tag": "safe",
                "unix_timestamp": 123,
                "importance": 7,
            },
        }
    ]


def test_re_embed_keeps_rows_retryable_when_vector_store_fails(tmp_path):
    db_path = tmp_path / "memory.db"
    make_database(db_path)

    stats = re_embed_documents(db_path, StubProvider(), vector_store=FailingVectorStore())

    assert stats == {"processed": 0, "skipped": 0, "errors": 1}
    assert read_document(db_path) == (("old-model", "old-v1"), (1.0, 2.0, 3.0))


def test_re_embed_dry_run_does_not_touch_vectors(tmp_path):
    db_path = tmp_path / "memory.db"
    make_database(db_path)

    stats = re_embed_documents(
        db_path,
        StubProvider(),
        dry_run=True,
        vector_store=FailingVectorStore(),
    )

    assert stats == {"processed": 1, "skipped": 0, "errors": 0}
    assert read_document(db_path) == (("old-model", "old-v1"), (1.0, 2.0, 3.0))
