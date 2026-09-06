"""
Re-embedding engine for Synapse-OSS.
Invoked by: synapse re-embed [--dry-run] [--batch-size N] [--db PATH]

Responsibilities:
- Find all documents whose embedding_model differs from the active provider.
- Re-embed them in configurable batch sizes.
- Persist the vectors in sqlite-vec and LanceDB before marking them migrated.
- Update provenance columns (embedding_model, embedding_version) on success.
- Support --dry-run to preview the plan without touching data.
"""

from __future__ import annotations

import logging
import sqlite3
import struct
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sci_fi_dashboard.embedding.base import EmbeddingProvider
    from sci_fi_dashboard.vector_store.base import VectorStore

logger = logging.getLogger(__name__)


def re_embed_documents(
    db_path: Path,
    provider: EmbeddingProvider,
    batch_size: int = 64,
    dry_run: bool = False,
    vector_store: VectorStore | None = None,
) -> dict[str, int]:
    """
    Re-embed all documents that don't have embeddings from the current provider.

    Idempotent: rows where ``embedding_model`` already matches the provider's
    model name are skipped without touching the database.

    Args:
        db_path:    Absolute path to the ``memory.db`` SQLite database.
        provider:   Active :class:`EmbeddingProvider` instance (supplies model
                    name and ``embed_documents()`` implementation).
        batch_size: Number of documents to embed per round-trip to the model.
        dry_run:    When ``True``, count rows that need re-embedding but do not
                    write anything to the database.
        vector_store: Optional vector store used for the re-embedded vectors.
            When omitted, the default :class:`LanceDBVectorStore` is used.

    Returns:
        A dict with keys ``"processed"``, ``"skipped"``, and ``"errors"`` where
        each value is an integer count.
    """
    stats: dict[str, int] = {"processed": 0, "skipped": 0, "errors": 0}
    provider_info = provider.info()

    owns_vector_store = False
    with closing(sqlite3.connect(str(db_path))) as conn:
        # Rows that need re-embedding: model mismatch or no model recorded yet.
        cursor = conn.execute(
            "SELECT id, content, hemisphere_tag, unix_timestamp, importance FROM documents"
            " WHERE embedding_model != ? OR embedding_model IS NULL",
            (provider_info.model,),
        )
        rows = cursor.fetchall()

        if dry_run:
            logger.info("[DryRun] Would re-embed %d documents", len(rows))
            stats["processed"] = len(rows)
            return stats

        try:
            if vector_store is None:
                from sci_fi_dashboard.vector_store import LanceDBVectorStore

                vector_store = LanceDBVectorStore()
                owns_vector_store = True

            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                texts = [r[1] for r in batch]

                try:
                    vectors = provider.embed_documents(texts)
                    if len(vectors) != len(batch):
                        raise ValueError(
                            f"Embedding provider returned {len(vectors)} vectors for "
                            f"{len(batch)} documents"
                        )

                    facts = []
                    for row, vector in zip(batch, vectors, strict=True):
                        row_id, content, hemisphere_tag, unix_timestamp, importance = row
                        vec_blob = struct.pack(f"{len(vector)}f", *vector)
                        conn.execute(
                            "DELETE FROM vec_items WHERE document_id = ?",
                            (row_id,),
                        )
                        conn.execute(
                            "INSERT INTO vec_items(document_id, embedding) VALUES (?, ?)",
                            (row_id, vec_blob),
                        )
                        conn.execute(
                            "UPDATE documents"
                            " SET embedding_model = ?, embedding_version = ?"
                            " WHERE id = ?",
                            (provider_info.model, f"{provider_info.name}-v1", row_id),
                        )
                        facts.append(
                            {
                                "id": row_id,
                                "vector": vector,
                                "metadata": {
                                    "text": content,
                                    "hemisphere_tag": hemisphere_tag or "safe",
                                    "unix_timestamp": unix_timestamp or 0,
                                    "importance": importance if importance is not None else 5,
                                },
                            }
                        )

                    vector_store.upsert_facts(facts)
                    conn.commit()
                    stats["processed"] += len(batch)
                    logger.info(
                        "[ReEmbed] Processed batch %d, %d total",
                        i // batch_size + 1,
                        stats["processed"],
                    )
                except Exception as exc:
                    conn.rollback()
                    logger.error("[ReEmbed] Batch error: %s", exc)
                    stats["errors"] += len(batch)
        except Exception as exc:
            logger.error("[ReEmbed] Vector store initialization error: %s", exc)
            stats["errors"] = len(rows)
        finally:
            if owns_vector_store and vector_store is not None:
                vector_store.close()

    return stats


def re_embed_cli(args: list[str] | None = None) -> None:
    """Entry point for the ``synapse re-embed`` CLI command.

    Example usage::

        synapse re-embed
        synapse re-embed --dry-run
        synapse re-embed --batch-size 32 --db /path/to/memory.db
    """
    import argparse

    from sci_fi_dashboard.embedding.factory import create_provider

    parser = argparse.ArgumentParser(
        prog="synapse re-embed",
        description="Re-embed all documents with the currently configured provider.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be re-embedded without modifying data.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=64,
        help="Number of documents per embedding batch (default: 64).",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Explicit path to memory.db. Defaults to ~/.synapse/workspace/db/memory.db.",
    )
    parsed = parser.parse_args(args)

    db_path = (
        Path(parsed.db)
        if parsed.db
        else Path.home() / ".synapse" / "workspace" / "db" / "memory.db"
    )

    if not db_path.exists():
        print(f"[Error] Database not found at {db_path}")
        return

    provider = create_provider()
    print(f"[ReEmbed] Using provider: {provider.info().name} ({provider.info().model})")

    if parsed.dry_run:
        print("[ReEmbed] Dry run mode — no changes will be made")

    stats = re_embed_documents(
        db_path,
        provider,
        batch_size=parsed.batch_size,
        dry_run=parsed.dry_run,
    )
    print(
        f"[ReEmbed] Done — processed: {stats['processed']},"
        f" skipped: {stats['skipped']}, errors: {stats['errors']}"
    )
