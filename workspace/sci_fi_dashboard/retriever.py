"""
Retriever Module — Queries memory.db using sentence-transformers for vector search.

Uses all-MiniLM-L6-v2 for embedding (matching the PC build) and sqlite-vec
for cosine distance search against both atomic_facts_vec and vec_items tables.

NOTE: The existing DB was built with `nomic-embed-text` via Ollama. This
retriever provides a fallback path using sentence-transformers for when
Ollama is not available. If Ollama IS running, we prefer it for embedding
consistency. Otherwise, we fall back to FTS (full-text search) which works
perfectly without any embedding model at all.
"""

import json
import os
import struct

# Import centralized DB module
try:
    from .db import get_db_connection
except ImportError:
    from db import get_db_connection

# --- Configuration ---
# DB_PATH is now managed by db.py, but we keep a reference if needed for other utils
# or we can just rely entirely on get_db_connection()

# Try to use Ollama embeddings first (same model as DB was built with)
EMBEDDING_MODEL_OLLAMA = "nomic-embed-text"

# Sentence-Transformers fallback
EMBEDDING_MODEL_ST = "all-MiniLM-L6-v2"

# Globals
_embedder = None
_embed_mode = None  # "ollama" or "sentence-transformers" or "fts_only"


def _init_embedder():
    """Initialize the embedding model. Try Ollama first, then sentence-transformers, then FTS-only."""
    global _embedder, _embed_mode

    if _embed_mode is not None:
        return

    # 1. Try Ollama (same model as DB)
    try:
        import ollama

        # Quick test
        result = ollama.embeddings(model=EMBEDDING_MODEL_OLLAMA, prompt="test")
        if result and "embedding" in result:
            _embed_mode = "ollama"
            print(f"✅ Retriever: Using Ollama ({EMBEDDING_MODEL_OLLAMA}) — exact DB match")
            return
    except Exception:
        pass

    # 2. Try sentence-transformers
    try:
        from sentence_transformers import SentenceTransformer

        _embedder = SentenceTransformer(EMBEDDING_MODEL_ST)
        _embed_mode = "sentence-transformers"
        print(f"✅ Retriever: Using sentence-transformers ({EMBEDDING_MODEL_ST})")
        return
    except ImportError:
        pass

    # 3. FTS-only mode (no vector search)
    _embed_mode = "fts_only"
    print("⚠️ Retriever: No embedding model available. Using FTS-only mode.")


def get_embedding(text: str) -> list | None:
    """Generate an embedding vector for the given text."""
    _init_embedder()

    if _embed_mode == "ollama":
        import ollama

        result = ollama.embeddings(model=EMBEDDING_MODEL_OLLAMA, prompt=text)
        return result["embedding"]
    elif _embed_mode == "sentence-transformers":
        vec = _embedder.encode(text).tolist()
        return vec
    else:
        return None


def _serialize_f32(vector: list) -> bytes:
    """Pack a float list into sqlite-vec's expected f32 blob format."""
    return struct.pack(f"{len(vector)}f", *vector)


# _get_connection removed; use get_db_connection() imported from db.py


def query_memories(
    user_message: str,
    limit: int = 5,
    use_atomic: bool = True,
    use_docs: bool = True,
    session_type: str = "safe",  # 'safe' or 'spicy'
) -> dict[str, any]:
    """
    Query memory.db for relevant context.

    Returns facts from both atomic_facts (structured knowledge)
    and documents (raw ingested text), plus relationship memories.

    Falls back to FTS if no embedding model is available.
    """
    _init_embedder()
    conn = get_db_connection()
    results = {
        "facts": [],
        "documents": [],
        "relationships": [],
        "method": _embed_mode,
    }

    try:
        cursor = conn.cursor()
        vec = get_embedding(user_message)

        # --- Vector Search (if embeddings available) ---
        if vec is not None:
            vec_blob = _serialize_f32(vec)

            # 1. Search atomic_facts_vec (structured facts)
            # Atomic facts don't currently have tags, so we keep them global/common knowledge
            if use_atomic:
                try:
                    cursor.execute(
                        """
                        SELECT
                            fact_id,
                            distance
                        FROM atomic_facts_vec
                        WHERE embedding MATCH ?
                        AND k = ?
                    """,
                        (vec_blob, limit),
                    )

                    for row in cursor.fetchall():
                        fid, dist = row[0], row[1]
                        # Look up the actual fact
                        cursor.execute(
                            "SELECT entity, content, category FROM atomic_facts WHERE id = ?",
                            (fid,),
                        )
                        fact = cursor.fetchone()
                        if fact:
                            results["facts"].append(
                                {
                                    "entity": fact[0],
                                    "content": fact[1],
                                    "category": fact[2],
                                    "distance": round(dist, 4),
                                }
                            )
                except Exception as e:
                    print(f"⚠️ atomic_facts_vec query failed: {e}")

            # 2. Search vec_items (documents) - WITH HIERARCHICAL ACCESS
            if use_docs:
                try:
                    # HIERARCHY LOGIC:
                    # - 'spicy' sees ALL (safe + spicy)
                    # - 'safe' sees ONLY safe
                    if session_type == "spicy":
                        filter_clause = "d.hemisphere_tag IN ('safe', 'spicy')"
                        params = (vec_blob, limit)
                    else:
                        filter_clause = "d.hemisphere_tag = ?"
                        params = (vec_blob, limit, "safe")

                    # Optimized JOIN query with Session-Aware filtering
                    cursor.execute(
                        f"""
                        SELECT
                            d.filename,
                            d.content,
                            v.distance
                        FROM vec_items v
                        JOIN documents d ON v.document_id = d.id
                        WHERE v.embedding MATCH ?
                          AND k = ?
                          AND {filter_clause}
                    """,
                        params,
                    )

                    for row in cursor.fetchall():
                        filename, content, dist = row[0], row[1], row[2]
                        results["documents"].append(
                            {
                                "source": filename,
                                "content": content[:500],  # Truncate for prompt size
                                "distance": round(dist, 4),
                            }
                        )

                    if session_type == "spicy":
                        results["method"] = "sqlite-vec (spicy-mode)"
                    else:
                        results["method"] = "sqlite-vec (safe-mode)"

                except Exception as e:
                    print(f"⚠️ vec_items query failed: {e}")

        # --- FTS Fallback (always try as supplement) ---
        # Note: FTS filtering by tag would require FTS5 vocabulary update or join, keeping simple for now
        if not results["facts"] and not results["documents"]:
            try:
                import re

                # Sanitize FTS5 query: keep only alphanumeric and spaces
                sanitized = re.sub(r"[^\w\s]", "", user_message)
                # Split into words for OR-style matching
                words = [w for w in sanitized.split() if len(w) > 2]
                if words:
                    fts_query = " OR ".join(words)
                    # For FTS, we do a post-filter join since FTS table doesn't have tags directly usually
                    # But checking schema, documents_fts is context=documents.
                    # We can join on rowid.
                    cursor.execute(
                        """
                        SELECT d.content, fts.rank
                        FROM documents_fts fts
                        JOIN documents d ON fts.rowid = d.id
                        WHERE documents_fts MATCH ?
                        AND d.hemisphere_tag = ?
                        ORDER BY rank
                        LIMIT ?
                    """,
                        (fts_query, session_type, limit),
                    )

                    for row in cursor.fetchall():
                        results["documents"].append(
                            {
                                "source": "fts",
                                "content": row[0][:500],
                                "distance": abs(row[1]),
                            }
                        )
                    results["method"] = "fts_fallback"
            except Exception as e:
                print(f"⚠️ FTS fallback failed: {e}")

        # --- Always check relationship memories ---
        try:
            cursor.execute("""
                SELECT category, content, source_event
                FROM relationship_memories
                ORDER BY created_at DESC
                LIMIT 5
            """)
            for row in cursor.fetchall():
                results["relationships"].append(
                    {
                        "category": row[0],
                        "content": row[1],
                        "source": row[2],
                    }
                )
        except Exception:
            pass

        # --- Entity links for context enrichment ---
        try:
            # Extract potential entities from message
            words = set(user_message.lower().split())
            entity_keywords = {
                "the_creator",
                "the_partner",
                "the_partner_nickname",
                "yourworkplace",
                "synapse",
                "friend_name",
                "sikkim",
                "kolkata",
                "elden",
                "sims",
            }
            matched = words & entity_keywords

            if matched:
                for entity in matched:
                    cursor.execute(
                        """
                        SELECT subject, relation, object
                        FROM entity_links
                        WHERE LOWER(subject) = ? OR LOWER(object) = ?
                        LIMIT 5
                    """,
                        (entity, entity),
                    )
                    for row in cursor.fetchall():
                        results["facts"].append(
                            {
                                "entity": row[0],
                                "content": f"{row[0]} {row[1]} {row[2]}",
                                "category": "entity_link",
                                "distance": 0.0,
                            }
                        )
        except Exception:
            pass

    finally:
        conn.close()

    return results


def format_context_for_prompt(memory_results: dict) -> str:
    """Format retrieved memories into a clean text block for the LLM prompt."""
    sections = []

    if memory_results.get("facts"):
        facts = memory_results["facts"]
        fact_lines = [f"• {f['content']}" for f in facts[:5]]
        sections.append("**Known Facts:**\n" + "\n".join(fact_lines))

    if memory_results.get("documents"):
        docs = memory_results["documents"]
        doc_lines = [f"• {d['content'][:200]}" for d in docs[:3]]
        sections.append("**Relevant Context:**\n" + "\n".join(doc_lines))

    if memory_results.get("relationships"):
        rels = memory_results["relationships"]
        rel_lines = [f"• [{r['category']}] {r['content']}" for r in rels[:3]]
        sections.append("**Relationship Notes:**\n" + "\n".join(rel_lines))

    if not sections:
        return "(No relevant memories found)"

    return "\n\n".join(sections)


def get_db_stats() -> dict:
    """Get basic stats about the memory database."""
    # DB path check handled by db.py

    conn = get_db_connection()
    cursor = conn.cursor()
    stats = {}

    try:
        cursor.execute("SELECT COUNT(*) FROM atomic_facts")
        stats["atomic_facts"] = cursor.fetchone()[0]
    except Exception:
        stats["atomic_facts"] = 0

    try:
        cursor.execute("SELECT COUNT(*) FROM documents")
        stats["documents"] = cursor.fetchone()[0]
    except Exception:
        stats["documents"] = 0

    try:
        cursor.execute("SELECT COUNT(*) FROM entity_links WHERE archived = 0")
        stats["entity_links"] = cursor.fetchone()[0]
    except Exception:
        stats["entity_links"] = 0

    try:
        cursor.execute("SELECT COUNT(*) FROM relationship_memories")
        stats["relationship_memories"] = cursor.fetchone()[0]
    except Exception:
        stats["relationship_memories"] = 0

    try:
        cursor.execute("SELECT COUNT(*) FROM roast_vault")
        stats["roasts"] = cursor.fetchone()[0]
    except Exception:
        stats["roasts"] = 0

    try:
        cursor.execute("SELECT COUNT(*) FROM gift_date_vault")
        stats["gift_ideas"] = cursor.fetchone()[0]
    except Exception:
        stats["gift_ideas"] = 0

    # Size check redundant with db.py but nice to have in stats
    try:
        from .db import DB_PATH

        stats["db_size_mb"] = round(os.path.getsize(DB_PATH) / (1024 * 1024), 1)
    except Exception:
        from db import DB_PATH

        stats["db_size_mb"] = round(os.path.getsize(DB_PATH) / (1024 * 1024), 1)

    stats["embed_mode"] = _embed_mode or "not_initialized"

    conn.close()
    return stats


if __name__ == "__main__":
    print("🧠 Retriever Self-Test\n")

    # Test 1: DB Stats
    stats = get_db_stats()
    print(f"📊 DB Stats: {json.dumps(stats, indent=2)}\n")

    # Test 2: Query
    test_queries = [
        "What are primary_user's career goals?",
        "partner_user's favorite games",
        "What shoes did primary_user buy?",
    ]

    for q in test_queries:
        print(f'🔍 Query: "{q}"')
        results = query_memories(q, limit=3)
        print(f"   Method: {results['method']}")
        print(f"   Facts: {len(results['facts'])}, Docs: {len(results['documents'])}")
        context = format_context_for_prompt(results)
        print(f"   Context preview: {context[:200]}...\n")
