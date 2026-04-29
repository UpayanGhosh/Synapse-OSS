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
import logging
import sqlite3
import traceback as _traceback_mod
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)

BATCH_SIZE = 5  # conversation turns per batch (1 turn = 1 user + 1 assistant)
BATCH_SLEEP_S = 1.0  # seconds between batches (rate-limit safety)
KG_EXTRACT_TIMEOUT_SECONDS = 45.0
_TRACEBACK_MAX_BYTES = 4096  # truncate stored tracebacks to 4 KB


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


def _format_batch(messages: list[dict], date_str: str) -> str:
    """Format a list of messages into a readable text block for embedding + KG extraction.

    Example:
        [WhatsApp session — 2026-04-07]
        User: hey what book did you mention?
        Me: The Feynman one — Surely You're Joking
    """
    lines = [f"[WhatsApp session — {date_str}]"]
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

    from sci_fi_dashboard import _deps as deps
    from sci_fi_dashboard.conv_kg_extractor import (
        ConvKGExtractor,
        _ensure_entity_links,
        _write_triple_to_entity_links,
    )
    from sci_fi_dashboard.multiuser.transcript import load_messages

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
        text = _format_batch(batch, date_str)

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

        # ── 2. KG extraction + triple writes ──
        if extractor is not None:
            try:
                result = await asyncio.wait_for(
                    extractor.extract(text),
                    timeout=KG_EXTRACT_TIMEOUT_SECONDS,
                )
                validated = result.get("validated_triples", [])

                if validated:
                    conn = sqlite3.connect(memory_db_path)
                    try:
                        _ensure_entity_links(conn)
                        for triple, confidence in validated:
                            if len(triple) < 3:
                                continue
                            subj, rel, obj = str(triple[0]), str(triple[1]), str(triple[2])
                            if not subj.strip() or not rel.strip() or not obj.strip():
                                continue
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
                                fact_id=0,
                                confidence=confidence,
                            )
                        conn.commit()
                    finally:
                        conn.close()

                    ingested_kg += len(validated)
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
