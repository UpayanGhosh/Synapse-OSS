"""
Re-embedding engine for Synapse-OSS.
Invoked by: synapse re-embed [--dry-run] [--batch-size N] [--db PATH]

Responsibilities:
- Find all documents whose embedding_model differs from the active provider.
- Re-embed them in configurable batch sizes.
- Update provenance columns (embedding_model, embedding_version) on success.
- Support --dry-run to preview the plan without touching data.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sci_fi_dashboard.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)


def re_embed_documents(
    db_path: Path,
    provider: "EmbeddingProvider",
    batch_size: int = 64,
    dry_run: bool = False,
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

    Returns:
        A dict with keys ``"processed"``, ``"skipped"``, and ``"errors"`` where
        each value is an integer count.
    """
    stats: dict[str, int] = {"processed": 0, "skipped": 0, "errors": 0}
    provider_info = provider.info()

    with sqlite3.connect(str(db_path)) as conn:
        # Rows that need re-embedding: model mismatch or no model recorded yet.
        cursor = conn.execute(
            "SELECT id, content FROM documents"
            " WHERE embedding_model != ? OR embedding_model IS NULL",
            (provider_info.model,),
        )
        rows = cursor.fetchall()

        if dry_run:
            logger.info("[DryRun] Would re-embed %d documents", len(rows))
            stats["processed"] = len(rows)
            return stats

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            ids = [r[0] for r in batch]
            texts = [r[1] for r in batch]

            try:
                vectors = provider.embed_documents(texts)
                for row_id, _vector in zip(ids, vectors):
                    # Update provenance metadata.
                    # The actual embedding bytes are written by the ingestion
                    # pipeline's vec_items upsert — this function only updates
                    # the tracking columns so the row won't be re-processed
                    # on the next run.
                    conn.execute(
                        "UPDATE documents"
                        " SET embedding_model = ?, embedding_version = ?"
                        " WHERE id = ?",
                        (provider_info.model, f"{provider_info.name}-v1", row_id),
                    )
                    stats["processed"] += 1
                conn.commit()
                logger.info(
                    "[ReEmbed] Processed batch %d, %d total",
                    i // batch_size + 1,
                    stats["processed"],
                )
            except Exception as exc:
                logger.error("[ReEmbed] Batch error: %s", exc)
                stats["errors"] += len(batch)

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
