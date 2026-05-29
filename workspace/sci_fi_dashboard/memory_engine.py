import json
import math
import os
import sqlite3
import sys
import threading
import time
from functools import lru_cache, wraps
from pathlib import Path

from flashrank import Ranker, RerankRequest

try:
    from synapse_config import SynapseConfig
except ImportError:
    import os as _os
    import sys as _sys

    _sys.path.insert(0, _os.path.abspath(_os.path.join(_os.path.dirname(__file__), "..")))
    from synapse_config import SynapseConfig

# Import centralized DB module
try:
    from .db import get_db_connection
except ImportError:
    try:
        from db import get_db_connection
    except ImportError:
        # Final fallback if working in workspace/sci_fi_dashboard
        import os
        import sys

        sys.path.append(os.path.dirname(__file__))
        from db import get_db_connection


def with_retry(retries: int = 3, delay: float = 0.5):
    """Simple decorator for retrying SQLite writes on lock contention."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err = None
            for i in range(retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower():
                        last_err = e
                        time.sleep(delay * (2**i))  # Exponential backoff
                        continue
                    raise
            raise last_err

        return wrapper

    return decorator


# Paths
WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(WORKSPACE_ROOT)

import contextlib  # noqa: E402

from sci_fi_dashboard.embedding import get_provider  # noqa: E402
from sci_fi_dashboard.memory_affect import (  # noqa: E402
    extract_affect,
    format_affect_hints,
    load_affect_for_doc_ids,
    score_affect_match,
    tags_to_public_dict,
    upsert_memory_affect,
)
from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter  # noqa: E402
from sci_fi_dashboard.vector_store import LanceDBVectorStore  # noqa: E402

# Configuration
RERANK_MODEL_NAME = "ms-marco-TinyBERT-L-2-v2"


def _coerce_doc_id(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_db_path() -> str:
    from synapse_config import SynapseConfig  # noqa: PLC0415

    return str(SynapseConfig.load().db_dir / "memory.db")


DB_PATH = _get_db_path()


def _resolve_backup_path() -> str:
    """Resolve the persistent backup log path under the user data root.

    Using SynapseConfig.data_root (i.e. ~/.synapse/) rather than the repo
    workspace root avoids Windows path/permission races and survives repo
    clean-ups that remove workspace/_archived_memories/.
    """
    cfg = SynapseConfig.load()
    data_root = getattr(cfg, "data_root", None)
    if data_root:
        return str(Path(data_root) / "workspace" / "_archived_memories" / "persistent_log.jsonl")

    # Test doubles and partial configs may only expose db_dir. Keep memory
    # persistence alive instead of failing during singleton import.
    db_dir = getattr(cfg, "db_dir", None)
    if db_dir:
        return str(Path(db_dir).parent / "_archived_memories" / "persistent_log.jsonl")

    return str(Path.home() / ".synapse" / "workspace" / "_archived_memories" / "persistent_log.jsonl")


class MemoryEngine:
    """
    Single instance that replaces the entire db/server.py process.
    Shared by the gateway -- no duplicate graph, no duplicate FlashText.
    """

    def __init__(self, graph_store=None, keyword_processor=None):
        """
        Accept shared graph_store and keyword_processor from gateway
        to avoid duplication.
        """
        self.vector_store = LanceDBVectorStore()

        # SHARED -- not duplicated
        self.graph_store = graph_store
        self.keyword_processor = keyword_processor

        # Lazy-loaded reranker
        self._ranker = None
        self._ranker_lock = threading.Lock()

        # Embedding provider (via abstraction layer)
        self._embed_provider = get_provider()
        if self._embed_provider is not None:
            print(f"[OK] MemoryEngine initialized (embedding: {self._embed_provider.info().name})")
        else:
            print(
                "[WARN] MemoryEngine: No embedding provider available -- semantic search disabled"
            )
        print("[OK] MemoryEngine initialized (shared graph, no duplication)")

        # Resolve backup path once at init and pre-create the file.
        # Done here (not lazily in add_memory) so any permission error surfaces
        # at startup rather than silently swallowing the first memory write.
        self._backup_file = _resolve_backup_path()
        try:
            os.makedirs(os.path.dirname(self._backup_file), exist_ok=True)
            Path(self._backup_file).touch()
        except OSError as _backup_init_err:
            print(f"[WARN] MemoryEngine: could not pre-create backup log: {_backup_init_err}")

    @lru_cache(maxsize=500)  # noqa: B019
    def get_embedding(self, text: str) -> tuple:
        if self._embed_provider is None:
            return tuple([0.0] * 768)
        try:
            return tuple(self._embed_provider.embed_query(text))
        except Exception as e:
            print(f"[WARN] Embedding generation failed: {e}")
            return tuple([0.0] * self._embed_provider.dimensions)

    def _get_ranker(self) -> Ranker:
        if self._ranker is None:
            with self._ranker_lock:
                if self._ranker is None:
                    self._ranker = Ranker(
                        model_name=RERANK_MODEL_NAME,
                        cache_dir=str(SynapseConfig.load().data_root / "models"),
                    )
        return self._ranker

    def _temporal_score(self, timestamp) -> float:
        if not timestamp:
            return 0.5
        diff_days = (time.time() - timestamp) / 86400
        if diff_days < 0:
            diff_days = 0
        return 1 / (1 + math.log1p(diff_days))

    def query(
        self,
        text: str,
        limit: int = 5,
        with_graph: bool = True,
        hemisphere: str = "safe",
        seed_entities: list[str] | None = None,
    ) -> dict:
        start = time.time()
        with contextlib.suppress(Exception):
            _get_emitter().emit("memory.query_start", {"text": text[:80]})
        _query_start = time.time()

        # First-person pronouns -> include seed_entities in graph lookup even if
        # no entity name appears literally in the query text ("my condition" etc.)
        _FIRST_PERSON = {  # noqa: N806
            "i",
            "my",
            "me",
            "mine",
            "myself",
            "i've",
            "i'm",
            "i'd",
            "i'll",
        }  # noqa: N806
        _is_self_referential = bool(_FIRST_PERSON & set(text.lower().split()))

        try:
            # Entity extraction (shared keyword_processor)
            entities = []
            if self.keyword_processor:
                entities = self.keyword_processor.extract_keywords(text)

            # Inject seed_entities for self-referential queries so the KG is
            # consulted even when the user writes "my X" instead of their name
            if seed_entities and (_is_self_referential or not entities):
                entities = list(dict.fromkeys(entities + seed_entities))

            # Graph context (shared graph_store)
            graph_context = ""
            if with_graph and entities and self.graph_store:
                neighborhoods = []
                for ent in entities:
                    ctx = self.graph_store.get_entity_neighborhood(ent)
                    if ctx:
                        neighborhoods.append(f"Context for {ent}:\n{ctx}")
                graph_context = "\n\n".join(neighborhoods)

            # Temporal routing label
            query_lower = text.lower()
            historical = ["was", "did", "history", "back then", "2024", "2025", "past"]
            current = ["current", "now", "latest", "status", "currently", "today"]

            if any(k in query_lower for k in historical):
                routing = "Historical"
            elif any(k in query_lower for k in current):
                routing = "Current State"
            else:
                routing = "Default (Hybrid)"

            # LanceDB search with hemisphere filtering
            with contextlib.suppress(Exception):
                _get_emitter().emit("memory.embedding_start", {})
            query_vec_tuple = self.get_embedding(text)
            with contextlib.suppress(Exception):
                _get_emitter().emit(
                    "memory.embedding_done",
                    {"dims": len(query_vec_tuple) if hasattr(query_vec_tuple, "__len__") else 768},
                )
            if query_vec_tuple is None:
                return {
                    "results": [],
                    "tier": "error",
                    "entities": entities,
                    "graph_context": graph_context,
                    "error": "Embedding generation failed",
                }
            query_vec = list(query_vec_tuple)

            # Build hemisphere filter (SQL WHERE clause for LanceDB)
            # Spicy sessions see both safe + spicy; safe sessions see only safe
            if hemisphere == "spicy":
                hemisphere_filter = "hemisphere_tag IN ('safe', 'spicy')"
            else:
                hemisphere_filter = "hemisphere_tag = 'safe'"

            with contextlib.suppress(Exception):

                _get_emitter().emit(
                    "memory.lancedb_search_start", {"hemisphere": hemisphere, "limit": limit * 3}
                )
            _search_start = time.time()
            q_results = self.vector_store.search(
                query_vec, limit=limit * 3, query_filter=hemisphere_filter
            )
            query_affect = extract_affect(text)
            affect_by_doc = {}
            doc_ids = [
                doc_id
                for doc_id in (_coerce_doc_id(r.get("id")) for r in q_results)
                if doc_id is not None
            ]
            if doc_ids:
                try:
                    _affect_conn = get_db_connection()
                    try:
                        affect_by_doc = load_affect_for_doc_ids(_affect_conn, doc_ids)
                    finally:
                        _affect_conn.close()
                except Exception as affect_err:
                    print(f"[WARN] memory_affect load failed: {affect_err}")
            with contextlib.suppress(Exception):
                _get_emitter().emit(
                    "memory.lancedb_search_done",
                    {
                        "num_candidates": len(q_results),
                        "latency_ms": round((time.time() - _search_start) * 1000),
                    },
                )

            # Apply 3-factor scoring: relevance + temporal + importance
            for r in q_results:
                ts = r["metadata"].get("unix_timestamp")
                importance = r["metadata"].get("importance", 5)
                doc_id = _coerce_doc_id(r.get("id"))
                affect = affect_by_doc.get(doc_id) if doc_id is not None else None
                affect_score = score_affect_match(query_affect, affect)
                if affect is not None:
                    r["affect"] = tags_to_public_dict(affect, score=affect_score)
                r["combined_score"] = (
                    (r["score"] * 0.35)
                    + (self._temporal_score(ts) * 0.20)
                    + (importance / 10 * 0.20)
                    + (affect_score * 0.25)
                )
                r["affect_score"] = affect_score

            q_results.sort(key=lambda x: x["combined_score"], reverse=True)
            affect_hints = format_affect_hints(
                [
                    r.get("affect", {})
                    for r in q_results[: max(limit, 3)]
                    if r.get("affect", {}).get("score", 0) > 0
                ]
            )
            try:
                _top_scored = q_results[:5]
                _get_emitter().emit(
                    "memory.scoring",
                    {
                        "results": [
                            {
                                "text": r.get("metadata", {}).get("text", "")[:60],
                                "score": round(r.get("combined_score", 0), 3),
                                "semantic": round(r.get("score", 0), 3),
                                "affect": round(r.get("affect_score", 0), 3),
                            }
                            for r in _top_scored
                        ]
                    },
                )
            except Exception:  # noqa: BLE001
                pass

            # Smart gate -- fast path
            high_conf = [
                r
                for r in q_results
                if r["combined_score"] > 0.80
                and (
                    any(e.lower() in r["metadata"]["text"].lower() for e in entities)
                    or not entities
                )
            ]

            if len(high_conf) >= limit:
                with contextlib.suppress(Exception):
                    _get_emitter().emit(
                        "memory.fast_gate_hit",
                        {
                            "threshold": 0.80,
                            "top_score": (
                                round(high_conf[0].get("combined_score", 0), 3) if high_conf else 0
                            ),
                        },
                    )
                return {
                    "results": [
                        {
                            "content": x["metadata"]["text"],
                            "score": x["combined_score"],
                            "source": "lancedb_fast",
                            "affect": x.get("affect"),
                        }
                        for x in high_conf[:limit]
                    ],
                    "tier": "fast_gate",
                    "entities": entities,
                    "graph_context": graph_context,
                    "affect_hints": affect_hints,
                    "routing": routing,
                }

            # Reranker fallback (gracefully degrades to scored results if reranker fails)
            with contextlib.suppress(Exception):
                _get_emitter().emit("memory.reranking_start", {})
            try:
                ranker = self._get_ranker()
                candidates = [
                    {
                        "id": r["id"],
                        "text": r["metadata"]["text"],
                        "meta": {
                            "score": r["combined_score"],
                            "affect": r.get("affect"),
                        },
                    }
                    for r in q_results
                ]
                ranked = ranker.rerank(RerankRequest(query=text, passages=candidates))
                return {
                    "results": [
                        {
                            "content": x["text"],
                            "score": float(x["score"]),
                            "source": "lancedb_reranked",
                            "affect": (x.get("meta") or {}).get("affect"),
                        }
                        for x in ranked[:limit]
                    ],
                    "tier": "reranked",
                    "entities": entities,
                    "graph_context": graph_context,
                    "affect_hints": affect_hints,
                    "elapsed": f"{time.time() - start:.4f}s",
                    "routing": routing,
                }
            except Exception as rerank_err:
                print(f"[WARN] Reranker failed ({rerank_err}) -- falling back to scored results")
                return {
                    "results": [
                        {
                            "content": r["metadata"]["text"],
                            "score": r["combined_score"],
                            "source": "lancedb_scored",
                            "affect": r.get("affect"),
                        }
                        for r in q_results[:limit]
                    ],
                    "tier": "scored_fallback",
                    "entities": entities,
                    "graph_context": graph_context,
                    "affect_hints": affect_hints,
                    "elapsed": f"{time.time() - start:.4f}s",
                    "routing": routing,
                }
        except Exception as e:
            print(f"[WARN] Memory query failed: {e}")
            return {
                "results": [],
                "tier": "error",
                "entities": [],
                "graph_context": "",
                "error": str(e),
            }

    @with_retry(retries=5, delay=0.1)
    def add_memory(
        self, content: str, category: str = "direct_entry", hemisphere: str = "safe"
    ) -> dict:
        backup_error = None
        entry = {"timestamp": time.time(), "category": category, "content": content}
        try:
            # Backup log write is best-effort; storage must still proceed.
            with open(self._backup_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError as backup_err:
            backup_error = str(backup_err)
            print(f"[WARN] Backup log write failed (non-fatal): {backup_err}")

        conn = None
        try:
            # Store - Unified connection path
            conn = get_db_connection()
            cursor = conn.cursor()
            importance = self._score_importance_heuristic(content)
            cursor.execute(
                "INSERT INTO documents"
                " (filename, content, hemisphere_tag, processed, unix_timestamp, importance)"
                " VALUES (?, ?, ?, 0, ?, ?)",
                (category, content, hemisphere, int(time.time()), importance),
            )
            doc_id = cursor.lastrowid
            try:
                upsert_memory_affect(conn, doc_id, extract_affect(content))
            except Exception as affect_err:
                print(f"[WARN] memory_affect upsert failed for doc {doc_id}: {affect_err}")

            # Generate embedding and store in vec_items so doc is visible
            # to semantic search immediately
            embedding = self.get_embedding(content)
            if embedding is not None:
                import struct

                vec_blob = struct.pack(f"{len(embedding)}f", *embedding)
                try:
                    cursor.execute(
                        "INSERT INTO vec_items (document_id, embedding) VALUES (?, ?)",
                        (doc_id, vec_blob),
                    )
                except Exception as vec_err:
                    print(f"[WARN] vec_items insert failed (vector search disabled?): {vec_err}")

                # Also upsert to LanceDB for ANN search
                try:
                    self.vector_store.upsert_facts(
                        [
                            {
                                "id": doc_id,
                                "vector": list(embedding),
                                "metadata": {
                                    "text": content,
                                    "hemisphere_tag": hemisphere,
                                    "unix_timestamp": int(time.time()),
                                    "importance": importance,
                                },
                            }
                        ]
                    )
                except Exception as lancedb_err:
                    print(f"[WARN] LanceDB upsert failed: {lancedb_err}")

                cursor.execute("UPDATE documents SET processed = 1 WHERE id = ?", (doc_id,))
            else:
                print(f"[WARN] Embedding failed for doc {doc_id}; queued for later processing")

            conn.commit()
            return {
                "status": "stored",
                "id": doc_id,
                "embedded": embedding is not None,
                "backup_error": backup_error,
            }
        except Exception as e:
            return {"error": str(e), "backup_error": backup_error}
        finally:
            if conn is not None:
                conn.close()

    def _score_importance_heuristic(self, content: str) -> int:
        """Tier 1: Fast keyword-based importance scoring. Zero tokens."""
        score = 3
        content_lower = content.lower()

        emotional_words = [
            "love",
            "hate",
            "angry",
            "sad",
            "happy",
            "excited",
            "scared",
            "proud",
            "ashamed",
            "miss",
            "breakup",
            "fight",
            "sorry",
            "grateful",
            "cry",
            "depressed",
        ]
        score += sum(1 for w in emotional_words if w in content_lower) * 2

        life_events = [
            "interview",
            "job",
            "exam",
            "result",
            "hospital",
            "birthday",
            "anniversary",
            "moving",
            "travel",
            "married",
            "died",
            "born",
            "graduated",
            "fired",
            "hired",
        ]
        score += sum(1 for w in life_events if w in content_lower) * 2

        if len(content.split()) < 5:
            score -= 2

        return max(1, min(10, score))

    async def _score_importance_llm(self, content: str, llm_fn=None) -> int:
        """Tier 2: LLM-rated importance for ambiguous memories. ~150 tokens."""
        if not llm_fn:
            return 5

        prompt = (
            "Rate the importance of this memory on a scale of 1 to 10.\n"
            '1 = mundane (e.g., "ate lunch", "said hi")\n'
            '5 = moderately notable (e.g., "started a new book")\n'
            '10 = life-altering (e.g., "got into a fight", "received exam results")\n\n'
            f'Memory: "{content}"\n\n'
            "Return ONLY a single integer 1-10:"
        )

        try:
            result = await llm_fn(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=5,
            )
            return max(1, min(10, int(result.strip())))
        except Exception:
            return 5

    async def score_importance(self, content: str, llm_fn=None) -> int:
        """Hybrid: heuristic first, LLM only for grey zone (4-7)."""
        heuristic = self._score_importance_heuristic(content)
        if heuristic <= 3 or heuristic >= 8:
            return heuristic
        return await self._score_importance_llm(content, llm_fn)

    # ------------------------------------------------------------------
    # Memory inspector primitives (PRODUCT_ISSUES.md §5.3)
    # ------------------------------------------------------------------
    # NOTE: The `documents` schema has no per-user column. The `user` filter
    # in list_documents() is accepted by the route layer for forward-compat
    # but ignored at the SQL level — we list across all docs in the chosen
    # hemisphere. delete_document() cascades to FTS, sqlite-vec, LanceDB,
    # memory_affect (FK ON DELETE CASCADE), and entity_links rows whose
    # source_doc_id == doc_id. It does NOT prune orphan KG nodes/edges
    # whose only mention came from the deleted doc — pruning is left to
    # the gentle worker loop's prune_weak_edges pass. This is a known
    # limitation; a stricter cleanup is deferred.
    def list_documents(
        self,
        *,
        user: str | None = None,
        hemisphere: str = "safe",
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Paginated read of stored docs.

        Returns {"items": [...], "total": int, "limit": int, "offset": int,
                 "hemisphere": str}. Each item: id, content, hemisphere,
                 importance, unix_timestamp, created_at, processed.
        """
        if hemisphere not in ("safe", "spicy"):
            hemisphere = "safe"
        # Clamp limits defensively even though the route already validates.
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        where_parts: list[str] = ["hemisphere_tag = ?"]
        params: list = [hemisphere]
        if search:
            where_parts.append("content LIKE ?")
            params.append(f"%{search}%")
        where_sql = " AND ".join(where_parts)

        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            total = cur.execute(
                f"SELECT COUNT(*) FROM documents WHERE {where_sql}",  # noqa: S608
                params,
            ).fetchone()[0]
            rows = cur.execute(
                "SELECT id, content, hemisphere_tag, importance, "
                "unix_timestamp, created_at, processed "
                f"FROM documents WHERE {where_sql} "  # noqa: S608
                "ORDER BY COALESCE(unix_timestamp, 0) DESC, id DESC "
                "LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            items = [
                {
                    "id": r[0],
                    "content": r[1],
                    "hemisphere": r[2],
                    "importance": r[3],
                    "unix_timestamp": r[4],
                    "created_at": r[5],
                    "processed": bool(r[6]) if r[6] is not None else False,
                }
                for r in rows
            ]
            return {
                "items": items,
                "total": int(total),
                "limit": limit,
                "offset": offset,
                "hemisphere": hemisphere,
                "user_filter_applied": False,
                "user": user,
            }
        finally:
            if conn is not None:
                conn.close()

    def delete_document(self, doc_id) -> bool:
        """Delete a doc and propagate to FTS / sqlite-vec / LanceDB / KG.

        Returns True if a row was deleted, False if doc_id wasn't found.
        memory_affect rows are removed via FK ON DELETE CASCADE.
        Orphan KG nodes whose only mention came from this doc are NOT
        pruned here — see class-level NOTE.
        """
        coerced = _coerce_doc_id(doc_id)
        if coerced is None:
            return False

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT 1 FROM documents WHERE id = ? LIMIT 1", (coerced,)
            ).fetchone()
            if row is None:
                return False

            # FTS5 with content=documents does NOT auto-cascade — must mirror
            # the delete on the FTS shadow table to keep the index in sync.
            try:
                cursor.execute("DELETE FROM documents_fts WHERE rowid = ?", (coerced,))
            except Exception as fts_err:
                print(f"[WARN] documents_fts delete failed for {coerced}: {fts_err}")

            # sqlite-vec virtual table
            try:
                cursor.execute("DELETE FROM vec_items WHERE document_id = ?", (coerced,))
            except Exception as vec_err:
                print(f"[WARN] vec_items delete failed for {coerced}: {vec_err}")

            # KG triples linked back to this doc
            try:
                cursor.execute(
                    "DELETE FROM entity_links WHERE source_doc_id = ?", (coerced,)
                )
            except Exception as kg_err:
                print(f"[WARN] entity_links delete failed for {coerced}: {kg_err}")

            # The documents row itself (memory_affect cascades via FK).
            cursor.execute("DELETE FROM documents WHERE id = ?", (coerced,))
            conn.commit()

            # LanceDB delete — separate store, separate failure domain.
            try:
                self.vector_store.delete_by_id(coerced)
            except Exception as ldb_err:
                print(f"[WARN] LanceDB delete failed for {coerced}: {ldb_err}")

            return True
        finally:
            if conn is not None:
                conn.close()

    def think(self, prompt: str, system: str = "You are a helpful, concise assistant.") -> dict:
        """Local LLM call with zero persistence."""
        try:
            # Try cloud router first
            try:
                from sci_fi_dashboard.llm_router import llm

                response_text = llm.generate(prompt, system_prompt=system)
                if response_text and "Error:" not in response_text:
                    return {
                        "response": response_text,
                        "model": getattr(llm, "kimi_model", "cloud"),
                        "source": "llm_router",
                    }
            except ImportError:
                pass

            return {"error": "No LLM backend available (cloud router unavailable)"}
        except Exception as e:
            return {"error": str(e)}
