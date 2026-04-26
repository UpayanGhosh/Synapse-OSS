"""manual_ingest_today.py — One-shot ingest of today's session JSONL.

Bypasses the broken `_ingest_session_background` vector-path failure
(see .planning/handover-2026-04-26/EVIDENCE.md E1.7) and the
`atomic_facts` NULL entity/category bug (E1.3).

For each batch of conversation turns:
  1. Extract atomic facts (entity, category, content) via Antigravity Flash
  2. Extract KG triples (subject, relation, object) via Antigravity Flash
  3. INSERT into documents (filename='session', kg_processed=1)
  4. INSERT into atomic_facts with proper entity + category populated
  5. INSERT into entity_links with source_fact_id pointing at the new fact
  6. Add nodes + relations to knowledge_graph.db via SQLiteGraph

Run from project root::

    cd workspace && python scripts/manual_ingest_today.py

Idempotent guard: skips batches whose text hash already exists as a
document row (filename='session') so re-runs don't double-insert.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Path bootstrap so `from synapse_config import ...` works from workspace/
HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from synapse_config import SynapseConfig  # noqa: E402

from sci_fi_dashboard.claude_cli_provider import ClaudeCliClient  # noqa: E402
from sci_fi_dashboard.conv_kg_extractor import (  # noqa: E402
    _ensure_entity_links,
    _write_triple_to_entity_links,
)
from sci_fi_dashboard.sqlite_graph import SQLiteGraph  # noqa: E402

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SESSION_JSONL = (
    Path.home()
    / ".synapse"
    / "state"
    / "agents"
    / "the_creator"
    / "sessions"
    / "cecb9c73-22bc-4cd9-9984-30c167032814.jsonl"
)
BATCH_SIZE = 5  # conversation turns (1 turn = 1 user + 1 assistant)
EXTRACTION_MODEL = "claude_cli/sonnet"  # subscription auth, no RPM cap

COMBINED_EXTRACTION_PROMPT = """Extract structured memory from this conversation segment between the user and Synapse (an AI assistant).

Return TWO things:

1. ATOMIC FACTS — for each non-trivial fact:
   - entity: the primary subject (e.g. "user", "Synapse", "Shreya", "antigravity provider")
   - category: one of [identity, preference, plan, tool, relationship, event, decision, technical, emotional]
   - content: a single concise atomic fact (one declarative sentence, present tense)

2. KG TRIPLES — for each high-confidence relationship:
   - subject and object: entity names (NOT pronouns or full sentences)
   - relation: short verb phrase in snake_case (e.g. "uses", "likes", "knows", "works_on")
   - confidence: 0.0-1.0

Skip greetings, filler, and meta-commentary. Aim for 5-15 facts and 3-10 triples per segment.

Output ONLY a single JSON object with this exact shape, no prose, no code fences:
{{
  "facts": [{{"entity": "...", "category": "...", "content": "..."}}],
  "triples": [["subject", "relation", "object", 0.9]]
}}

Conversation:
{text}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_code_fence(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        # remove leading fence (```json or ```)
        m = re.match(r"^```(?:json)?\s*\n?", raw)
        if m:
            raw = raw[m.end() :]
        raw = raw.rsplit("```", 1)[0]
    return raw.strip()


def _parse_json_array(raw: str) -> list:
    raw = _strip_code_fence(raw)
    if not raw:
        return []
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
        return []
    except json.JSONDecodeError as exc:
        print(f"  ! JSON parse failed: {exc}", file=sys.stderr)
        print(f"    raw head: {raw[:200]!r}", file=sys.stderr)
        return []


def _parse_json_object(raw: str) -> dict:
    raw = _strip_code_fence(raw)
    if not raw:
        return {}
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
        return {}
    except json.JSONDecodeError as exc:
        print(f"  ! JSON parse failed: {exc}", file=sys.stderr)
        print(f"    raw head: {raw[:200]!r}", file=sys.stderr)
        return {}


async def _call_with_retry(client, *, messages, model, max_attempts=3):
    """Call extraction model with one retry on transient subprocess error.

    Claude CLI has no RPM cap (subscription auth), so the only failure mode here
    is the subprocess hanging or non-zero-exiting. We retry once after a short
    pause."""
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return await client.chat_completion(
                messages=messages,
                model=model,
                temperature=0.0,
                max_tokens=4096,  # avoid truncation on dense batches
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt == max_attempts - 1:
                raise
            print(
                f"  ! call failed ({type(exc).__name__}: {str(exc)[:120]}), "
                f"retrying after 5s (attempt {attempt + 1}/{max_attempts})"
            )
            await asyncio.sleep(5)
    raise last_exc  # type: ignore[misc]


def _format_batch(messages: list[dict], date_str: str) -> str:
    lines = [f"[Synapse session - {date_str}]"]
    for msg in messages:
        role = msg.get("role", "user")
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        # strip Synapse's appended Context-Usage footer to keep the model focused
        content = re.split(r"\n+\*\*Context Usage:", content)[0].strip()
        label = "User" if role == "user" else "Synapse"
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _document_already_exists(conn: sqlite3.Connection, content_hash: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM documents WHERE filename = 'session' AND content LIKE ? LIMIT 1",
        (f"%[ingest_marker:{content_hash}]%",),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Core ingestion
# ---------------------------------------------------------------------------


async def ingest_batch(
    client: AntigravityClient,
    conn: sqlite3.Connection,
    graph: SQLiteGraph,
    batch_idx: int,
    total_batches: int,
    text: str,
    date_str: str,
) -> dict:
    content_hash = _content_hash(text)
    if _document_already_exists(conn, content_hash):
        print(f"  [batch {batch_idx + 1}/{total_batches}] already ingested (hash={content_hash}), skip")
        return {"facts": 0, "triples": 0, "skipped": True}

    print(f"  [batch {batch_idx + 1}/{total_batches}] extracting facts + triples (combined)…")
    resp = await _call_with_retry(
        client,
        messages=[
            {"role": "user", "content": COMBINED_EXTRACTION_PROMPT.format(text=text)}
        ],
        model=EXTRACTION_MODEL,
    )
    payload = _parse_json_object(resp.text)
    facts = payload.get("facts", []) if isinstance(payload, dict) else []
    raw_triples = payload.get("triples", []) if isinstance(payload, dict) else []

    # 1. Insert document with kg_processed=1 + a hash marker
    marker = f"\n\n[ingest_marker:{content_hash}]"
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO documents (filename, content, hemisphere_tag, processed,"
        " unix_timestamp, importance, kg_processed) VALUES (?, ?, ?, 1, ?, ?, 1)",
        ("session", text + marker, "safe", int(time.time()), 5),
    )
    doc_id = cur.lastrowid

    # 2. Insert atomic_facts (entity + category populated, this is the bug fix)
    fact_id_map: list[int] = []
    written_facts = 0
    for f in facts:
        if not isinstance(f, dict):
            continue
        entity = str(f.get("entity") or "").strip()
        category = str(f.get("category") or "").strip()
        content = str(f.get("content") or "").strip()
        if not content:
            continue
        cur.execute(
            "INSERT INTO atomic_facts (entity, content, category, source_doc_id,"
            " embedding_model, embedding_version) VALUES (?, ?, ?, ?, ?, ?)",
            (entity or None, content, category or None, doc_id, "manual_ingest", "v1"),
        )
        fact_id_map.append(cur.lastrowid)
        written_facts += 1

    # 3. Insert entity_links (with source_fact_id pointing at a real atomic_fact when possible)
    written_triples = 0
    fact_id_for_triples = fact_id_map[0] if fact_id_map else 0
    for t in raw_triples:
        if not isinstance(t, list) or len(t) < 3:
            continue
        subj = str(t[0]).strip()
        rel = str(t[1]).strip()
        obj = str(t[2]).strip()
        if not (subj and rel and obj):
            continue
        confidence = float(t[3]) if len(t) > 3 and isinstance(t[3], (int, float)) else 1.0

        # Try to bind triple to a fact whose entity matches the subject
        bound_fact_id = fact_id_for_triples
        for idx, f in enumerate(facts[: len(fact_id_map)]):
            if isinstance(f, dict) and (f.get("entity") or "").lower() == subj.lower():
                bound_fact_id = fact_id_map[idx]
                break

        _write_triple_to_entity_links(conn, subj, rel, obj, bound_fact_id, confidence)
        written_triples += 1

        # Also write to knowledge_graph.db
        try:
            graph.add_node(subj)
            graph.add_node(obj)
            graph.add_relation(subj, rel, obj, weight=confidence)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! graph write failed for ({subj}, {rel}, {obj}): {exc}", file=sys.stderr)

    conn.commit()
    print(
        f"  [batch {batch_idx + 1}/{total_batches}] [OK] doc_id={doc_id}"
        f" facts={written_facts} triples={written_triples}"
    )
    return {"facts": written_facts, "triples": written_triples, "doc_id": doc_id}


async def main() -> None:
    if not SESSION_JSONL.exists():
        print(f"ERROR: session JSONL not found at {SESSION_JSONL}", file=sys.stderr)
        sys.exit(1)

    cfg = SynapseConfig.load()
    memory_db = str(cfg.db_dir / "memory.db")
    print(f"DB: {memory_db}")
    print(f"Source: {SESSION_JSONL}")

    # Load messages
    raw_messages: list[dict] = []
    with open(SESSION_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                raw_messages.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    print(f"Messages loaded: {len(raw_messages)}")

    # Batch by 5 turns (assistant marks end-of-turn)
    batches: list[list[dict]] = []
    current: list[dict] = []
    turn_count = 0
    for msg in raw_messages:
        current.append(msg)
        if msg.get("role") == "assistant":
            turn_count += 1
            if turn_count >= BATCH_SIZE:
                batches.append(current)
                current = []
                turn_count = 0
    if current:
        batches.append(current)

    print(f"Batches: {len(batches)}")
    if not batches:
        print("Nothing to ingest.")
        return

    # Open DB + ensure schema for entity_links
    conn = sqlite3.connect(memory_db)
    _ensure_entity_links(conn)
    graph = SQLiteGraph()  # uses default ~/.synapse/workspace/db/knowledge_graph.db

    client = ClaudeCliClient(timeout=180.0)
    date_str = datetime.now(tz=UTC).strftime("%Y-%m-%d")

    total_facts = 0
    total_triples = 0
    skipped = 0

    for i, batch in enumerate(batches):
        text = _format_batch(batch, date_str)
        try:
            result = await ingest_batch(client, conn, graph, i, len(batches), text, date_str)
            if result.get("skipped"):
                skipped += 1
            else:
                total_facts += result["facts"]
                total_triples += result["triples"]
        except Exception as exc:  # noqa: BLE001
            print(f"  ! batch {i + 1} failed: {exc}", file=sys.stderr)
            import traceback

            traceback.print_exc()

        # claude_cli has no RPM cap; tiny pause just to be polite to the subprocess
        await asyncio.sleep(0.5)

    # Persist graph
    try:
        graph.save_graph()
    except Exception as exc:  # noqa: BLE001
        print(f"! graph.save_graph failed: {exc}", file=sys.stderr)

    # Final counts
    cur = conn.cursor()
    print()
    print("--- AFTER ---")
    print(f"  documents total: {cur.execute('SELECT COUNT(*) FROM documents').fetchone()[0]}")
    print(
        "  documents (session, today): "
        + str(
            cur.execute(
                "SELECT COUNT(*) FROM documents WHERE filename='session' "
                "AND created_at > datetime('now', '-1 day')"
            ).fetchone()[0]
        )
    )
    print(f"  atomic_facts: {cur.execute('SELECT COUNT(*) FROM atomic_facts').fetchone()[0]}")
    print(f"  entity_links: {cur.execute('SELECT COUNT(*) FROM entity_links').fetchone()[0]}")
    print(
        f"  kg_processed=1: {cur.execute('SELECT COUNT(*) FROM documents WHERE kg_processed=1').fetchone()[0]}"
    )
    print()
    print(f"This run: facts={total_facts} triples={total_triples} batches_skipped={skipped}")
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
