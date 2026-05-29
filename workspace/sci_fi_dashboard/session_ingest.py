"""session_ingest.py — Full memory loop background ingestion after /new.

Runs as asyncio.create_task() from pipeline_helpers._handle_new_command().

Per batch of conversation turns:
  1. Vector ingestion: MemoryEngine.add_memory() → LanceDB + sqlite-vec
  2. KG extraction:    ConvKGExtractor.extract() via LLM router → validated triples
  3. Triple writes:    SQLiteGraph.add_relation() + entity_links table in memory.db

Batched with BATCH_SLEEP_S between batches to avoid rate limits.
Never blocks the chat pipeline.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import re
import sqlite3
import sys
import time
import traceback as _traceback_mod
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

BATCH_SIZE = 5  # conversation turns per batch (1 turn = 1 user + 1 assistant)
BATCH_SLEEP_S = 1.0  # seconds between batches (rate-limit safety)
KG_EXTRACT_TIMEOUT_SECONDS = 45.0
_TRACEBACK_MAX_BYTES = 4096  # truncate stored tracebacks to 4 KB
_FIRST_PERSON_ENTITIES = {"i", "me", "my", "mine", "myself"}
_VAGUE_KG_ENTITIES = {
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "they",
    "them",
    "their",
    "theirs",
    "someone",
    "somebody",
    "person",
    "people",
    "person i like",
    "the person i like",
    "someone i like",
    "someone the user likes",
}


def _ensure_atomic_facts_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS atomic_facts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            entity          TEXT,
            content         TEXT NOT NULL,
            category        TEXT,
            source_doc_id   INTEGER,
            unix_timestamp  INTEGER,
            embedding_model TEXT DEFAULT 'nomic-embed-text',
            embedding_version TEXT DEFAULT 'ollama-v1',
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cols = {row[1] for row in conn.execute("PRAGMA table_info(atomic_facts)").fetchall()}
    migrations = {
        "entity": "TEXT",
        "category": "TEXT",
        "source_doc_id": "INTEGER",
        "unix_timestamp": "INTEGER",
        "embedding_model": "TEXT DEFAULT 'nomic-embed-text'",
        "embedding_version": "TEXT DEFAULT 'ollama-v1'",
    }
    for column, ddl in migrations.items():
        if column not in cols:
            conn.execute(f"ALTER TABLE atomic_facts ADD COLUMN {column} {ddl}")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_atomic_facts_source_doc_id ON atomic_facts(source_doc_id)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_atomic_facts_entity ON atomic_facts(entity)")


def _write_atomic_facts(
    conn: sqlite3.Connection,
    facts: list[dict],
    *,
    source_doc_id: int | None,
) -> list[int]:
    _ensure_atomic_facts_table(conn)
    fact_ids: list[int] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        content = _normalize_atomic_fact_content(fact.get("content"))
        if not content:
            continue
        entity = _normalize_kg_entity_for_storage(fact.get("entity"))
        if entity is None:
            continue
        category = str(fact.get("category") or "").strip() or None
        conn.execute(
            """
            INSERT INTO atomic_facts
                (entity, content, category, source_doc_id, unix_timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entity, content, category, source_doc_id, int(time.time())),
        )
        fact_ids.append(int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
    return fact_ids


def _fact_id_for_triple(
    facts: list[dict],
    fact_ids: list[int],
    *,
    subject: str,
) -> int:
    if not fact_ids:
        return 0
    subject_lower = str(subject or "").strip().lower()
    for idx, fact in enumerate(facts[: len(fact_ids)]):
        if not isinstance(fact, dict):
            continue
        entity = str(fact.get("entity") or "").strip().lower()
        if entity and entity == subject_lower:
            return fact_ids[idx]
    return fact_ids[0]


def _normalize_kg_entity_for_storage(raw: object) -> str | None:
    entity = str(raw or "").strip()
    if not entity:
        return None
    lowered = entity.lower()
    if lowered in _FIRST_PERSON_ENTITIES:
        return "user"
    if lowered in _VAGUE_KG_ENTITIES:
        return None
    return entity


def _normalize_atomic_fact_content(raw: object) -> str:
    """Clean first-person artifacts from LLM-extracted atomic facts."""
    content = " ".join(str(raw or "").strip().split())
    if not content:
        return ""
    content = re.sub(r"[\"“”]", "", content)
    if re.fullmatch(
        r"(?:User )?likes (?:(?:the )?person I like|the person|the person they like|someone the user likes)\.?",
        content,
        flags=re.IGNORECASE,
    ):
        return "User likes someone."
    content = re.sub(
        r"^I like ([^.!?]+)\.?$",
        r"User likes \1.",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"\bUser likes (?:the )?person I like\b\.?",
        "User likes someone.",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"\bthe person I like\b|\bperson I like\b",
        "someone the user likes",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(
        r"\bmade User feel\b",
        "made the user feel",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"\bUser's\b", "the user's", content)
    return content


def _mark_document_kg_processed(conn: sqlite3.Connection, doc_id: int | None) -> None:
    if doc_id is None:
        return
    cols = {row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()}
    if "kg_processed" not in cols:
        return
    conn.execute("UPDATE documents SET kg_processed = 1 WHERE id = ?", (doc_id,))


def _record_ingest_failure(
    memory_db_path: str,
    *,
    phase: str,
    session_key: str,
    agent_id: str,
    archived_path: Path | str,
    batch_index: int | None = None,
    total_batches: int | None = None,
    exc: Exception | None = None,
    ingested_vec: int | None = None,
    ingested_kg: int | None = None,
) -> None:
    """Insert one row into ingest_failures. Never raises — degrades to log.warning."""
    exc_type = type(exc).__name__ if exc is not None else None
    exc_msg = str(exc) if exc is not None else None
    tb_text: str | None = None
    if exc is not None:
        tb_text = _traceback_mod.format_exc()
        if len(tb_text) > _TRACEBACK_MAX_BYTES:
            tb_text = tb_text[-_TRACEBACK_MAX_BYTES:]

    try:
        conn = sqlite3.connect(memory_db_path)
        try:
            conn.execute(
                """
                INSERT INTO ingest_failures
                    (session_key, agent_id, archived_path, batch_index, total_batches,
                     phase, exception_type, exception_msg, traceback,
                     ingested_vec, ingested_kg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_key,
                    agent_id,
                    str(archived_path),
                    batch_index,
                    total_batches,
                    phase,
                    exc_type,
                    exc_msg,
                    tb_text,
                    ingested_vec,
                    ingested_kg,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as insert_err:
        log.warning("[session_ingest] failed to record ingest_failure row: %s", insert_err)


def _session_channel_label(session_key: str | None) -> str:
    parts = str(session_key or "").split(":")
    channel = parts[2].strip().lower() if len(parts) >= 3 else ""
    labels = {
        "telegram": "Telegram",
        "whatsapp": "WhatsApp",
        "discord": "Discord",
        "slack": "Slack",
        "cli": "CLI",
        "api": "API",
    }
    return labels.get(channel, "Chat")


def _format_batch(messages: list[dict], date_str: str, channel_label: str = "Chat") -> str:
    """Format a list of messages into a readable text block for embedding + KG extraction.

    Example:
        [WhatsApp session — 2026-04-07]
        User: hey what book did you mention?
        Me: The Feynman one — Surely You're Joking
    """
    clean_channel = re.sub(r"[^A-Za-z0-9 _-]+", "", str(channel_label or "Chat")).strip()
    if not clean_channel:
        clean_channel = "Chat"
    lines = [f"[{clean_channel} session — {date_str}]"]
    for msg in messages:
        role = msg.get("role", "user")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        label = "User" if role == "user" else "Me"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


async def _ingest_session_background(
    archived_path: Path,
    agent_id: str,
    session_key: str,
    hemisphere: str = "safe",
) -> None:
    """Background coroutine: run full memory loop on an archived session transcript.

    Reads the archived JSONL, groups messages into batches, then for each batch:
      - Ingests into vector memory (MemoryEngine.add_memory)
      - Extracts KG triples (ConvKGExtractor.extract via LLM router)
      - Writes triples to SQLiteGraph (deps.brain) and entity_links table

    Args:
        archived_path: Path to the archived JSONL (e.g. abc123.jsonl.deleted.1234567890)
        agent_id:       Resolved agent ID (e.g. "the_creator")
        session_key:    Used for logging context
        hemisphere:     "safe" or "spicy" — controls memory hemisphere
    """
    # Late imports to avoid circular deps at module load time
    from synapse_config import SynapseConfig

    deps = sys.modules.get("sci_fi_dashboard._deps")
    if deps is None:
        deps = importlib.import_module("sci_fi_dashboard._deps")
    from sci_fi_dashboard.conv_kg_extractor import (
        ConvKGExtractor,
        _ensure_entity_links,
        _write_triple_to_entity_links,
    )
    from sci_fi_dashboard.multiuser.transcript import load_messages
    from sci_fi_dashboard.user_memory_distiller_v2 import (
        distill_and_upsert_user_memory_facts_v2,
    )

    cfg = SynapseConfig.load()
    memory_db_path = str(cfg.db_dir / "memory.db")

    # Find the archived file — glob in case timestamp differs by a few ms
    if not archived_path.exists():
        stem = archived_path.name.split(".jsonl.deleted.")[0]
        candidates = list(archived_path.parent.glob(f"{stem}.jsonl.deleted.*"))
        if not candidates:
            log.warning("[session_ingest] no archived file found for %s", archived_path.name)
            return
        archived_path = max(candidates, key=lambda p: p.stat().st_mtime)

    try:
        messages = await load_messages(archived_path)
    except Exception as exc:
        log.error("[session_ingest] failed to load %s: %s", archived_path, exc)
        _record_ingest_failure(
            memory_db_path,
            phase="load",
            session_key=session_key,
            agent_id=agent_id,
            archived_path=archived_path,
            exc=exc,
        )
        return

    if not messages:
        log.info("[session_ingest] empty transcript %s — nothing to ingest", archived_path.name)
        return

    # Group into batches of BATCH_SIZE turns (1 turn = user msg + assistant reply)
    date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    batches: list[list[dict]] = []
    current: list[dict] = []
    turn_count = 0

    for msg in messages:
        current.append(msg)
        if msg.get("role") == "assistant":
            turn_count += 1
            if turn_count >= BATCH_SIZE:
                batches.append(current)
                current = []
                turn_count = 0
    if current:
        batches.append(current)

    if not batches:
        return

    # KG extraction setup — same role as periodic pipeline
    kg_enabled = cfg.kg_extraction.enabled
    kg_role = cfg.kg_extraction.kg_role if kg_enabled else None
    extractor = (
        ConvKGExtractor(deps.synapse_llm_router, role=kg_role or "casual") if kg_enabled else None
    )

    log.info(
        "[session_ingest] starting: %d batches, kg=%s, session=%s",
        len(batches),
        kg_enabled,
        session_key,
    )

    ingested_vec = 0
    ingested_kg = 0

    for i, batch in enumerate(batches):
        text = _format_batch(batch, date_str, _session_channel_label(session_key))

        # ── 1. Vector ingestion ──
        try:
            result = deps.memory_engine.add_memory(
                content=text,
                category="session",
                hemisphere=hemisphere,
            )
        except Exception as exc:
            _record_ingest_failure(
                memory_db_path,
                phase="vector",
                session_key=session_key,
                agent_id=agent_id,
                archived_path=archived_path,
                batch_index=i + 1,
                total_batches=len(batches),
                exc=exc,
            )
            log.error("[session_ingest] vector batch %d/%d raised: %s", i + 1, len(batches), exc)
            continue
        if isinstance(result, dict) and "error" in result:
            _record_ingest_failure(
                memory_db_path,
                phase="vector",
                session_key=session_key,
                agent_id=agent_id,
                archived_path=archived_path,
                batch_index=i + 1,
                total_batches=len(batches),
                exc=RuntimeError(result["error"]),
            )
            log.error(
                "[session_ingest] vector batch %d/%d returned error: %s",
                i + 1,
                len(batches),
                result["error"],
            )
            continue
        ingested_vec += 1

        doc_id: int | None = None
        if isinstance(result, dict):
            raw_doc_id = result.get("id")
            if raw_doc_id is not None:
                try:
                    doc_id = int(raw_doc_id)
                except (TypeError, ValueError):
                    doc_id = None

        try:
            conn = sqlite3.connect(memory_db_path, timeout=5.0)
            conn.execute("PRAGMA busy_timeout = 5000")
            try:
                facts = await distill_and_upsert_user_memory_facts_v2(
                    conn,
                    text=text,
                    user_id=session_key,
                    source_doc_id=doc_id,
                )
                conn.commit()
            finally:
                conn.close()
            if facts:
                log.info(
                    "[session_ingest] distilled %d user facts from doc %s",
                    len(facts),
                    doc_id,
                )
        except Exception as distill_err:
            _record_ingest_failure(
                memory_db_path,
                phase="user_memory",
                session_key=session_key,
                agent_id=agent_id,
                archived_path=archived_path,
                batch_index=i + 1,
                total_batches=len(batches),
                exc=distill_err,
                ingested_vec=ingested_vec,
                ingested_kg=ingested_kg,
            )
            log.warning(
                "[session_ingest] user memory distill failed for doc %s: %s",
                doc_id,
                distill_err,
            )

        # ── 2. KG extraction + triple writes ──
        if extractor is not None:
            try:
                result = await asyncio.wait_for(
                    extractor.extract(text),
                    timeout=KG_EXTRACT_TIMEOUT_SECONDS,
                )
                validated = result.get("validated_triples", [])

                conn = None
                if validated:
                    conn = sqlite3.connect(memory_db_path, timeout=5.0)
                    conn.execute("PRAGMA busy_timeout = 5000")
                    try:
                        _ensure_entity_links(conn)
                        extracted_facts = result.get("facts", [])
                        fact_ids = _write_atomic_facts(
                            conn,
                            extracted_facts if isinstance(extracted_facts, list) else [],
                            source_doc_id=doc_id,
                        )
                        for triple, confidence in validated:
                            if len(triple) < 3:
                                continue
                            subj = _normalize_kg_entity_for_storage(triple[0])
                            rel = str(triple[1])
                            obj = _normalize_kg_entity_for_storage(triple[2])
                            if subj is None or obj is None:
                                continue
                            if not subj.strip() or not rel.strip() or not obj.strip():
                                continue
                            fact_id = _fact_id_for_triple(
                                extracted_facts if isinstance(extracted_facts, list) else [],
                                fact_ids,
                                subject=subj,
                            )
                            # Write to SQLiteGraph (in-memory + persisted on save_graph)
                            deps.brain.add_node(subj)
                            deps.brain.add_node(obj)
                            deps.brain.add_relation(subj, rel, obj, weight=confidence)
                            # Write to entity_links table in memory.db
                            _write_triple_to_entity_links(
                                conn,
                                subj,
                                rel,
                                obj,
                                fact_id=fact_id,
                                confidence=confidence,
                                source_doc_id=doc_id,
                            )
                        _mark_document_kg_processed(conn, doc_id)
                        conn.commit()
                    finally:
                        conn.close()

                    ingested_kg += len(validated)
                else:
                    conn = sqlite3.connect(memory_db_path, timeout=5.0)
                    conn.execute("PRAGMA busy_timeout = 5000")
                    try:
                        _mark_document_kg_processed(conn, doc_id)
                        conn.commit()
                    finally:
                        conn.close()
            except asyncio.TimeoutError as exc:
                log.error(
                    "[session_ingest] KG batch %d/%d timed out after %.1fs",
                    i + 1,
                    len(batches),
                    KG_EXTRACT_TIMEOUT_SECONDS,
                )
                _record_ingest_failure(
                    memory_db_path,
                    phase="kg",
                    session_key=session_key,
                    agent_id=agent_id,
                    archived_path=archived_path,
                    batch_index=i + 1,
                    total_batches=len(batches),
                    exc=exc,
                )
            except Exception as exc:
                log.error("[session_ingest] KG batch %d/%d failed: %s", i + 1, len(batches), exc)
                _record_ingest_failure(
                    memory_db_path,
                    phase="kg",
                    session_key=session_key,
                    agent_id=agent_id,
                    archived_path=archived_path,
                    batch_index=i + 1,
                    total_batches=len(batches),
                    exc=exc,
                )

        if i < len(batches) - 1:
            await asyncio.sleep(BATCH_SLEEP_S)

    # Persist SQLiteGraph to disk after all batches
    if kg_enabled and ingested_kg > 0:
        try:
            deps.brain.save_graph()
        except Exception as exc:
            log.warning("[session_ingest] save_graph failed: %s", exc)

    log.info(
        "[session_ingest] done: %d/%d vec batches, %d KG triples — session %s",
        ingested_vec,
        len(batches),
        ingested_kg,
        session_key,
    )
    _record_ingest_failure(
        memory_db_path,
        phase="completed",
        session_key=session_key,
        agent_id=agent_id,
        archived_path=archived_path,
        total_batches=len(batches),
        ingested_vec=ingested_vec,
        ingested_kg=ingested_kg,
    )
