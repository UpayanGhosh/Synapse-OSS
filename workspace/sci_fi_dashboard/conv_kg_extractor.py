"""
Conversation-based KG triple extractor — async, LLM-router-based replacement
for the torch-dependent TripleExtractor.

Extracts facts and knowledge-graph triples from recent conversation messages
in background batches.  No torch/transformers dependency.

Usage (from async context)::

    result = await run_batch_extraction(
        persona_id="the_creator",
        sbs_data_dir="/path/to/synapse_data/the_creator",
        llm_router=router,
        graph=sqlite_graph,
        memory_db_path="/path/to/memory.db",
        entities_json_path="/path/to/entities.json",
    )
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import string
from pathlib import Path

from sci_fi_dashboard.llm_router import SynapseLLMRouter
from sci_fi_dashboard.sqlite_graph import SQLiteGraph

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entity normalization
# ---------------------------------------------------------------------------

# Common prefixes/suffixes stripped during normalization.
_STRIP_TOKENS: set[str] = {
    "mr", "mrs", "ms", "dr", "prof", "sir", "the", "a", "an",
}

# Punctuation translation table (remove all punctuation).
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _normalize_entity(raw: str) -> str:
    """Normalize an entity name for consistent KG storage.

    Applies:
      1. Lowercase
      2. Strip leading/trailing whitespace and punctuation
      3. Remove common honorific prefixes (mr, mrs, dr, etc.)
      4. Collapse internal whitespace to single space

    Returns empty string for None/empty input.

    Examples:
        >>> _normalize_entity("  Dr. Upayan Ghosh  ")
        'upayan ghosh'
        >>> _normalize_entity("THE Project")
        'project'
        >>> _normalize_entity("Mr.  John   Doe")
        'john doe'
    """
    if not raw:
        return ""
    text = str(raw).lower().strip()
    # Collapse whitespace first so token splitting works cleanly.
    text = re.sub(r"\s+", " ", text)
    # Strip leading tokens that match honorifics (with or without trailing dot).
    tokens = text.split()
    while tokens and tokens[0].rstrip(".") in _STRIP_TOKENS:
        tokens.pop(0)
    text = " ".join(tokens)
    # Remove stray punctuation at edges (e.g. trailing comma from LLM output).
    text = text.strip(string.punctuation + " ")
    return text

# ---------------------------------------------------------------------------
# Extraction prompt — anti-hallucination variant with standardized relations
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """\
Extract key atomic facts and knowledge graph triples from the following conversation.

RULES — read carefully:
1. Extract ONLY facts that are EXPLICITLY stated or clearly implied in the text.
   Do NOT infer, assume, or hallucinate any information.
2. If a fact is uncertain or hedged ("I think", "maybe", "probably"), prefix the
   content field with "possibly: ".
3. Both the subject and object of every triple MUST appear in the source text.
4. Use ONLY these standardized relation names:
   works_at, lives_in, likes, dislikes, knows, studied_at, born_in, married_to,
   has_child, prefers, plans_to, diagnosed_with, age_is, speaks, member_of,
   interested_in, owns, uses, created, works_on, friends_with, sibling_of,
   employed_as, located_in, part_of, related_to
5. Focus on: personal facts about people, relationships, preferences, plans,
   work details, health details, locations, skills, and affiliations.

Return ONLY valid JSON with this structure:
{{
  "facts": [
    {{"entity": "main subject", "content": "atomic fact", "category": "Work|Relationship|Plan|Preference|Health|Location|Skill|General"}}
  ],
  "triples": [
    ["subject", "relation", "object"]
  ]
}}

Text:
{content}"""

# ---------------------------------------------------------------------------
# Grounded triple validation (anti-hallucination)
# ---------------------------------------------------------------------------


def _entity_appears_in_text(entity: str, source_lower: str) -> bool:
    """Check whether *entity* is grounded in *source_lower* (already lowercased).

    Uses progressive matching:
      1. Exact substring match (fast path).
      2. All individual words of the entity appear in the source.

    Designed to be fast — no NLP deps, just string ops.
    """
    if not entity:
        return False
    # Fast path: direct substring.
    if entity in source_lower:
        return True
    # Word-level fallback: every word in the entity must appear somewhere in source.
    words = entity.split()
    if len(words) > 1 and all(w in source_lower for w in words):
        return True
    return False


def _validate_triples(
    triples: list[list[str]],
    source_text: str,
) -> list[tuple[list[str], float]]:
    """Validate extracted triples against the source conversation text.

    For each triple [subject, relation, object]:
      - BOTH entities grounded in source text  -> weight 1.0 (accepted)
      - Only ONE entity grounded               -> weight 0.5 (partial confidence)
      - NEITHER entity grounded                -> REJECTED  (hallucinated)

    Args:
        triples:     List of [subject, relation, object] lists.
        source_text: The raw conversation text that was sent to the LLM.

    Returns:
        List of (triple, confidence_weight) tuples for accepted triples.
        Rejected triples are logged at WARNING level and excluded.
    """
    if not source_text:
        return []

    source_lower = source_text.lower()
    accepted: list[tuple[list[str], float]] = []

    for triple in triples:
        if not isinstance(triple, (list, tuple)) or len(triple) < 3:
            continue

        subj = _normalize_entity(triple[0])
        obj = _normalize_entity(triple[2])
        rel = str(triple[1]).strip().lower()

        if not subj or not rel or not obj:
            continue

        subj_grounded = _entity_appears_in_text(subj, source_lower)
        obj_grounded = _entity_appears_in_text(obj, source_lower)

        if subj_grounded and obj_grounded:
            accepted.append(([subj, rel, obj], 1.0))
        elif subj_grounded or obj_grounded:
            accepted.append(([subj, rel, obj], 0.5))
            logger.debug(
                "[KG] Partial grounding for triple: [%s, %s, %s] — weight 0.5",
                subj, rel, obj,
            )
        else:
            logger.warning(
                "[KG] REJECTED hallucinated triple: [%s, %s, %s] — "
                "neither entity found in source text",
                subj, rel, obj,
            )

    return accepted


# ---------------------------------------------------------------------------
# Provider-aware LLM call kwargs
# ---------------------------------------------------------------------------

# Providers known to support response_format={"type": "json_object"}.
_JSON_FORMAT_PROVIDERS: set[str] = {"openai", "gemini", "groq", "mistral", "together", "together_ai"}


def _get_safe_call_kwargs(model_string: str) -> dict:
    """Build extra kwargs for the LLM call based on provider capabilities.

    Only includes ``response_format={"type": "json_object"}`` for providers
    known to support it.  For all others, the 3-tier parsing fallback in
    ``_parse_llm_output`` handles malformed JSON gracefully.

    Args:
        model_string: Provider-prefixed model string (e.g. "gemini/gemini-2.0-flash").

    Returns:
        Dict of extra kwargs to pass to ``SynapseLLMRouter.call()``.
    """
    if not model_string:
        return {}
    provider = model_string.split("/", 1)[0] if "/" in model_string else ""
    # Normalize ollama_chat -> ollama for prefix matching.
    if provider == "ollama_chat":
        provider = "ollama"
    if provider in _JSON_FORMAT_PROVIDERS:
        return {"response_format": {"type": "json_object"}}
    return {}


# ---------------------------------------------------------------------------
# Contradiction detection — single-valued relations
# ---------------------------------------------------------------------------

# Relations where an entity can only have ONE value at a time.
# If a new extraction contradicts an existing edge with one of these relations,
# the old edge should be UPDATED rather than a second edge appended.
_SINGLE_VALUED_RELATIONS: set[str] = {
    "works_at", "lives_in", "married_to", "born_in", "age_is",
    "employed_as", "located_in", "diagnosed_with",
}


_CHUNK_SIZE = 1500  # chars

# ---------------------------------------------------------------------------
# Per-persona concurrency guard — prevents overlapping extraction runs
# for the same persona while allowing different personas to run in parallel.
# ---------------------------------------------------------------------------

_persona_locks: dict[str, asyncio.Lock] = {}


def _get_persona_lock(persona_id: str) -> asyncio.Lock:
    """Return a per-persona asyncio.Lock, creating it on first access."""
    if persona_id not in _persona_locks:
        _persona_locks[persona_id] = asyncio.Lock()
    return _persona_locks[persona_id]

# ---------------------------------------------------------------------------
# Text chunking — copied verbatim from triple_extractor.py
# ---------------------------------------------------------------------------


def _chunk_text(text: str, max_chars: int = _CHUNK_SIZE) -> list[str]:
    """Split text at sentence boundaries, keeping chunks under max_chars."""
    if len(text) <= max_chars:
        return [text]

    # Split on sentence-ending punctuation including Bengali/Devanagari danda
    sentences = re.split(r"(?<=[.!?।\n])\s+", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        if len(sent) > max_chars:
            if current:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
            chunks.append(sent[:max_chars])
            continue
        if current and current_len + len(sent) > max_chars:
            chunks.append(" ".join(current))
            current = [sent]
            current_len = len(sent)
        else:
            current.append(sent)
            current_len += len(sent)

    if current:
        chunks.append(" ".join(current))

    return chunks if chunks else [text[:max_chars]]


# ---------------------------------------------------------------------------
# JSON parsing (3-tier fallback) — copied verbatim from triple_extractor.py
# ---------------------------------------------------------------------------


def _parse_llm_output(raw: str) -> dict:
    """
    Parse LLM output into {"facts": [...], "triples": [...]}.

    Tier 1: direct json.loads
    Tier 2: extract JSON from markdown code block
    Tier 3: regex-extract triple patterns
    Returns empty result (never raises) if all tiers fail.
    """
    raw = raw.strip()

    # Tier 1
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    # Tier 2
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            pass

    # Tier 3 — extract triple patterns
    triples = re.findall(
        r'\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]', raw
    )
    if triples:
        logger.warning("[KG] LLM output not valid JSON — regex fallback used")
        return {"facts": [], "triples": [[s, r, o] for s, r, o in triples]}

    logger.warning("[KG] Could not parse LLM output — returning empty result")
    return {"facts": [], "triples": []}


# ---------------------------------------------------------------------------
# Result normalisation
# ---------------------------------------------------------------------------


def _normalize_result(result: dict) -> dict:
    """Normalize entities, collapse whitespace, deduplicate facts and triples.

    Uses ``_normalize_entity`` for subject/object in triples and entity names
    in facts — ensures consistent casing and honorific stripping.
    """
    facts: list[dict] = []
    seen_facts: set[str] = set()
    for f in result.get("facts", []):
        entity = _normalize_entity(f.get("entity") or "")
        content = re.sub(r"\s+", " ", (f.get("content") or "").strip())
        if content and content not in seen_facts:
            seen_facts.add(content)
            facts.append({
                "entity": entity,
                "content": content,
                "category": f.get("category", ""),
            })

    triples: list[list[str]] = []
    seen_triples: set[tuple] = set()
    for t in result.get("triples", []):
        if not isinstance(t, (list, tuple)) or len(t) < 3:
            continue
        subj = _normalize_entity(t[0])
        rel = re.sub(r"\s+", " ", str(t[1]).lower().strip())
        obj = _normalize_entity(t[2])
        if subj and rel and obj:
            key = (subj, rel, obj)
            if key not in seen_triples:
                seen_triples.add(key)
                triples.append([subj, rel, obj])

    return {"facts": facts, "triples": triples}


# ---------------------------------------------------------------------------
# entity_links helpers — lifted from scripts/fact_extractor.py
# ---------------------------------------------------------------------------


def _ensure_entity_links(conn: sqlite3.Connection) -> None:
    """Idempotent: create entity_links + archived + confidence columns."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entity_links (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            subject   TEXT NOT NULL,
            relation  TEXT NOT NULL,
            object    TEXT NOT NULL,
            archived  INTEGER DEFAULT 0,
            source_fact_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add missing columns for older schemas (idempotent via PRAGMA check).
    cursor = conn.execute("PRAGMA table_info(entity_links)")
    cols = {row[1] for row in cursor.fetchall()}
    if "archived" not in cols:
        conn.execute("ALTER TABLE entity_links ADD COLUMN archived INTEGER DEFAULT 0")
    if "confidence" not in cols:
        conn.execute("ALTER TABLE entity_links ADD COLUMN confidence REAL DEFAULT 1.0")
    conn.commit()


def _write_triple_to_entity_links(
    conn: sqlite3.Connection,
    subj: str,
    rel: str,
    obj: str,
    fact_id: int,
    confidence: float = 1.0,
) -> None:
    """Archival-write: for single-valued relations, mark old (subj, rel) as
    archived before inserting the new row.  Multi-valued relations (likes,
    knows, etc.) are appended without archiving prior values."""
    if rel in _SINGLE_VALUED_RELATIONS:
        conn.execute(
            "UPDATE entity_links SET archived = 1"
            " WHERE subject = ? AND relation = ? AND archived = 0",
            (subj, rel),
        )
    conn.execute(
        "INSERT INTO entity_links (subject, relation, object, archived, source_fact_id, confidence)"
        " VALUES (?, ?, ?, 0, ?, ?)",
        (subj, rel, obj, fact_id, confidence),
    )


def _update_entities_json(entities_json_path: str, new_entities: set[str]) -> None:
    """Merge new entity names into entities.json (dict of name -> 1).

    Entity names are normalized via ``_normalize_entity`` before insertion
    to prevent fragmented entries for the same real-world entity.
    """
    try:
        with open(entities_json_path, encoding="utf-8") as f:
            current: dict = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        current = {}

    before = len(current)
    for name in new_entities:
        normalized = _normalize_entity(name)
        if normalized:
            current[normalized] = 1

    with open(entities_json_path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

    added = len(current) - before
    if added:
        logger.info("[KG] entities.json updated (+%d new entities, %d total)", added, len(current))


# ---------------------------------------------------------------------------
# Contradiction-aware graph write
# ---------------------------------------------------------------------------


def _write_triple_to_graph(
    graph: SQLiteGraph,
    subj: str,
    rel: str,
    obj: str,
    weight: float = 1.0,
) -> None:
    """Write a triple to SQLiteGraph with contradiction detection.

    For single-valued relations (works_at, lives_in, etc.), if an existing
    edge with the same (subject, relation) but a DIFFERENT object exists,
    the old edge is removed and replaced.  For multi-valued relations
    (likes, knows, etc.), the new edge is appended as usual.

    Args:
        graph:  The SQLiteGraph instance.
        subj:   Normalized subject entity.
        rel:    Relation string (lowercase).
        obj:    Normalized object entity.
        weight: Confidence weight for the edge.
    """
    import time as _time  # noqa: PLC0415

    if rel in _SINGLE_VALUED_RELATIONS:
        conn = graph._conn()
        existing = conn.execute(
            "SELECT target FROM edges WHERE source = ? AND relation = ?",
            (subj, rel),
        ).fetchone()
        if existing and existing["target"] != obj:
            old_obj = existing["target"]
            logger.info(
                "[KG] Contradiction: updating '%s %s' from '%s' to '%s'",
                subj, rel, old_obj, obj,
            )
            # Atomic DELETE + INSERT in one transaction on the same connection.
            # Bypasses add_edge to guarantee both ops share a single commit.
            now = _time.time()
            conn.execute(
                "DELETE FROM edges WHERE source = ? AND relation = ?",
                (subj, rel),
            )
            for node in (subj, obj):
                conn.execute(
                    "INSERT OR IGNORE INTO nodes (name, created_at, updated_at)"
                    " VALUES (?, ?, ?)",
                    (node, now, now),
                )
            conn.execute(
                "INSERT INTO edges (source, target, relation, weight, evidence, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(source, target, relation) DO UPDATE SET"
                "   weight = ?, evidence = evidence || ' | ' || ?",
                (subj, obj, rel, weight, "conv_kg", now, weight, "conv_kg"),
            )
            conn.commit()
            return
    # Non-contradictory or multi-valued: standard add_edge (UPSERT).
    graph.add_edge(subj, obj, relation=rel, weight=weight, evidence="conv_kg")


# ---------------------------------------------------------------------------
# State tracking helpers (Subtask 2)
# ---------------------------------------------------------------------------


def _get_last_kg_timestamp(sbs_data_dir: str) -> str:
    """Read the last KG extraction timestamp from kg_state.json.

    Returns ISO timestamp string, or '2000-01-01T00:00:00' if the file
    is missing or corrupt.
    """
    state_file = Path(sbs_data_dir) / "kg_state.json"
    try:
        if state_file.exists():
            with open(state_file, encoding="utf-8") as f:
                state = json.load(f)
            return state.get("kg_last_extracted_at", "2000-01-01T00:00:00")
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[KG] Could not read kg_state.json: %s", exc)
    return "2000-01-01T00:00:00"


def _set_last_kg_timestamp(sbs_data_dir: str, ts: str) -> None:
    """Write the last KG extraction timestamp to kg_state.json."""
    state_dir = Path(sbs_data_dir)
    os.makedirs(str(state_dir), exist_ok=True)
    state_file = state_dir / "kg_state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump({"kg_last_extracted_at": ts}, f)


async def fetch_messages_since(
    db_path: str, since_iso: str, limit: int = 200
) -> list[dict]:
    """Fetch conversation messages newer than *since_iso* from messages.db.

    Uses asyncio.to_thread with a thread-local connection (justified: read
    query may scan many rows).  The connection is opened and closed within
    the callable — no shared-connection issue.
    """

    def _query() -> list[dict]:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT msg_id, timestamp, role, content"
                " FROM messages"
                " WHERE timestamp > ?"
                " ORDER BY timestamp ASC"
                " LIMIT ?",
                (since_iso, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    return await asyncio.to_thread(_query)


# ---------------------------------------------------------------------------
# ConvKGExtractor (Subtask 3)
# ---------------------------------------------------------------------------


class ConvKGExtractor:
    """Async KG extractor that calls the configured LLM via SynapseLLMRouter.

    No torch/transformers dependency.  Processes text in chunks sequentially.

    Supports a dedicated ``"kg"`` role in model_mappings with automatic
    fallback to ``"casual"`` when ``"kg"`` is not configured.
    """

    def __init__(self, llm_router: SynapseLLMRouter, role: str = "kg") -> None:
        self._router = llm_router
        # Role resolution: try the requested role, fall back to "casual".
        if role not in llm_router._config.model_mappings:
            fallback = "casual"
            logger.debug(
                "[KG] Role '%s' not in model_mappings — falling back to '%s'",
                role, fallback,
            )
            role = fallback
        self._role = role
        # Determine provider-safe kwargs once (avoids per-chunk lookups).
        model_str = (
            llm_router._config.model_mappings.get(role, {}).get("model", "")
        )
        self._extra_kwargs = _get_safe_call_kwargs(model_str)

    async def extract(self, text: str) -> dict:
        """Extract facts and triples from *text*.

        Long text is chunked at ~1500 chars; results are merged and
        deduplicated across chunks.  Triples are validated against the
        source text to reject hallucinated entities.

        Returns::

            {
                "facts": [{"entity": str, "content": str, "category": str}, ...],
                "triples": [["subject", "relation", "object"], ...],
                "validated_triples": [([subj, rel, obj], confidence), ...],
            }
        """
        if not text or not text.strip():
            return {"facts": [], "triples": [], "validated_triples": []}

        chunks = _chunk_text(text)
        merged_facts: list[dict] = []
        merged_triples: list[list[str]] = []
        seen_facts: set[str] = set()
        seen_triples: set[tuple] = set()

        for chunk in chunks:
            try:
                prompt = _EXTRACTION_PROMPT.format(content=chunk)
                messages = [{"role": "user", "content": prompt}]
                raw_text = await self._router.call(
                    self._role,
                    messages,
                    temperature=0.3,
                    max_tokens=1500,
                    **self._extra_kwargs,
                )
                result = _normalize_result(_parse_llm_output(raw_text))

                for f in result["facts"]:
                    if f["content"] not in seen_facts:
                        seen_facts.add(f["content"])
                        merged_facts.append(f)

                for t in result["triples"]:
                    key = tuple(t)
                    if key not in seen_triples:
                        seen_triples.add(key)
                        merged_triples.append(t)

            except Exception as e:
                logger.warning("[KG] Chunk extraction failed (%s): %s", type(e).__name__, e)

        # Validate all merged triples against the FULL source text.
        validated = _validate_triples(merged_triples, text)
        logger.info(
            "[KG] Validation: %d raw triples -> %d accepted (%d rejected)",
            len(merged_triples),
            len(validated),
            len(merged_triples) - len(validated),
        )

        return {
            "facts": merged_facts,
            "triples": merged_triples,
            "validated_triples": validated,
        }


# ---------------------------------------------------------------------------
# run_batch_extraction orchestrator (Subtask 4)
# ---------------------------------------------------------------------------


async def run_batch_extraction(
    persona_id: str,
    sbs_data_dir: str,
    llm_router: SynapseLLMRouter,
    graph: SQLiteGraph,
    memory_db_path: str,
    entities_json_path: str,
    min_messages: int = 15,
    max_messages: int = 200,
    force: bool = False,
    kg_role: str = "kg",
) -> dict:
    """Run a single batch of conversation-based KG extraction for one persona.

    Acquires a module-level lock to prevent overlapping runs.

    Pipeline improvements over the original:
      - Uses a dedicated ``"kg"`` LLM role (falls back to ``"casual"``).
      - Provider-aware ``response_format`` (only for providers that support it).
      - Validates every triple against source text (anti-hallucination).
      - Confidence-weighted writes (1.0 for fully grounded, 0.5 for partial).
      - Contradiction detection for single-valued relations in SQLiteGraph.
      - Entity normalization before all writes.

    Returns:
        {"extracted": int, "facts": int, "rejected": int} on success.
        {"skipped": True, ...} when skipped (disabled or below threshold).
        {"error": str, "extracted": 0} on write failure.
    """
    from synapse_config import SynapseConfig

    async with _get_persona_lock(persona_id):
        # (a) Guard — check config
        cfg = SynapseConfig.load()
        if not cfg.kg_extraction.enabled:
            return {"skipped": True, "reason": "disabled"}

        # (b) Read watermark
        last_ts = _get_last_kg_timestamp(sbs_data_dir)

        # (c) Resolve messages DB path
        db_path = str(Path(sbs_data_dir) / "indices" / "messages.db")

        # (d) Fetch messages
        msgs = await fetch_messages_since(db_path, last_ts, limit=max_messages)

        # (e) Threshold check
        effective_min = 0 if force else min_messages
        if len(msgs) < effective_min:
            return {"skipped": True, "pending": len(msgs)}

        if not msgs:
            return {"skipped": True, "pending": 0}

        # (f) Build text
        text = "\n".join(
            f"[{m['role']}]: {m['content']}" for m in msgs
        )

        # (g) LLM extraction with KG role (falls back to casual internally)
        extractor = ConvKGExtractor(llm_router, role=kg_role)
        result = await extractor.extract(text)

        validated_triples = result.get("validated_triples", [])
        facts = result.get("facts", [])
        raw_triple_count = len(result.get("triples", []))
        rejected_count = raw_triple_count - len(validated_triples)

        if not validated_triples and not facts:
            logger.info("[KG] No validated triples/facts extracted for %s", persona_id)
            # Still advance watermark — the messages were processed, just empty
            try:
                _set_last_kg_timestamp(sbs_data_dir, msgs[-1]["timestamp"])
            except Exception as e:
                logger.warning("[KG] Failed to advance watermark on empty result: %s", e)
            return {"extracted": 0, "facts": 0, "rejected": rejected_count}

        # (h) through (k): Write sequence with watermark-last ordering
        try:
            # (h) Write validated triples to SQLiteGraph with contradiction detection
            for triple, confidence in validated_triples:
                if len(triple) < 3:
                    continue
                subj, rel, obj = triple[0], triple[1], triple[2]
                _write_triple_to_graph(graph, subj, rel, obj, weight=confidence)

            # (i) Write entity_links to memory.db with confidence
            conn = sqlite3.connect(memory_db_path)
            try:
                _ensure_entity_links(conn)
                for triple, confidence in validated_triples:
                    if len(triple) < 3:
                        continue
                    subj, rel, obj = triple[0], triple[1], triple[2]
                    _write_triple_to_entity_links(
                        conn, subj, rel, obj, fact_id=0, confidence=confidence,
                    )
                conn.commit()
            finally:
                conn.close()

            # (j) Update entities.json (normalized entity names)
            all_entities: set[str] = set()
            for triple, _ in validated_triples:
                if len(triple) >= 3:
                    all_entities.add(triple[0])
                    all_entities.add(triple[2])
            _update_entities_json(entities_json_path, all_entities)

            # (k) Advance watermark — ONLY on full success (ABSOLUTE LAST)
            _set_last_kg_timestamp(sbs_data_dir, msgs[-1]["timestamp"])

        except Exception as write_err:
            logger.error(
                "KG write failed for %s, watermark NOT advanced: %s",
                persona_id, write_err,
            )
            return {"error": str(write_err), "extracted": 0}

        logger.info(
            "[KG] Extracted %d validated triples (%d rejected), %d facts for %s",
            len(validated_triples), rejected_count, len(facts), persona_id,
        )
        return {
            "extracted": len(validated_triples),
            "facts": len(facts),
            "rejected": rejected_count,
        }
