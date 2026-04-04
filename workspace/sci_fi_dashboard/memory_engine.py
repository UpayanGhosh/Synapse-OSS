import json
import math
import os
import sqlite3
import sys
import threading
import time
from functools import lru_cache, wraps

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

from sci_fi_dashboard.vector_store import LanceDBVectorStore
from sci_fi_dashboard.embedding import get_provider
from sci_fi_dashboard.pipeline_emitter import get_emitter as _get_emitter

# Configuration
RERANK_MODEL_NAME = "ms-marco-TinyBERT-L-2-v2"


def _get_db_path() -> str:
    from synapse_config import SynapseConfig  # noqa: PLC0415

    return str(SynapseConfig.load().db_dir / "memory.db")


DB_PATH = _get_db_path()
BACKUP_FILE = os.path.join(WORKSPACE_ROOT, "_archived_memories", "persistent_log.jsonl")


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
            print("[WARN] MemoryEngine: No embedding provider available -- semantic search disabled")
        print("[OK] MemoryEngine initialized (shared graph, no duplication)")

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
    ) -> dict:
        start = time.time()
        try: _get_emitter().emit("memory.query_start", {"text": text[:80]})
        except Exception: pass
        _query_start = time.time()

        try:
            # Entity extraction (shared keyword_processor)
            entities = []
            if self.keyword_processor:
                entities = self.keyword_processor.extract_keywords(text)

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
            try: _get_emitter().emit("memory.embedding_start", {})
            except Exception: pass
            query_vec_tuple = self.get_embedding(text)
            try: _get_emitter().emit("memory.embedding_done", {"dims": len(query_vec_tuple) if hasattr(query_vec_tuple, "__len__") else 768})
            except Exception: pass
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

            try: _get_emitter().emit("memory.lancedb_search_start", {"hemisphere": hemisphere, "limit": limit * 3})
            except Exception: pass
            _search_start = time.time()
            q_results = self.vector_store.search(
                query_vec, limit=limit * 3, query_filter=hemisphere_filter
            )
            try: _get_emitter().emit("memory.lancedb_search_done", {
                "num_candidates": len(q_results),
                "latency_ms": round((time.time() - _search_start) * 1000),
            })
            except Exception: pass

            # Apply 3-factor scoring: relevance + temporal + importance
            for r in q_results:
                ts = r["metadata"].get("unix_timestamp")
                importance = r["metadata"].get("importance", 5)
                r["combined_score"] = (
                    (r["score"] * 0.4) + (self._temporal_score(ts) * 0.3) + (importance / 10 * 0.3)
                )

            q_results.sort(key=lambda x: x["combined_score"], reverse=True)
            try:
                _top_scored = q_results[:5]
                _get_emitter().emit("memory.scoring", {
                    "results": [{"text": r.get("metadata", {}).get("text", "")[:60], "score": round(r.get("combined_score", 0), 3), "semantic": round(r.get("score", 0), 3)} for r in _top_scored]
                })
            except Exception: pass

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
                try: _get_emitter().emit("memory.fast_gate_hit", {"threshold": 0.80, "top_score": round(high_conf[0].get("combined_score", 0), 3) if high_conf else 0})
                except Exception: pass
                return {
                    "results": [
                        {
                            "content": x["metadata"]["text"],
                            "score": x["combined_score"],
                            "source": "lancedb_fast",
                        }
                        for x in high_conf[:limit]
                    ],
                    "tier": "fast_gate",
                    "entities": entities,
                    "graph_context": graph_context,
                    "routing": routing,
                }

            # Reranker fallback
            try: _get_emitter().emit("memory.reranking_start", {})
            except Exception: pass
            ranker = self._get_ranker()
            candidates = [
                {
                    "id": r["id"],
                    "text": r["metadata"]["text"],
                    "meta": {"score": r["combined_score"]},
                }
                for r in q_results
            ]
            ranked = ranker.rerank(RerankRequest(query=text, passages=candidates))

            return {
                "results": [
                    {"content": x["text"], "score": float(x["score"]), "source": "lancedb_reranked"}
                    for x in ranked[:limit]
                ],
                "tier": "reranked",
                "entities": entities,
                "graph_context": graph_context,
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
        try:
            # Backup
            os.makedirs(os.path.dirname(BACKUP_FILE), exist_ok=True)
            entry = {"timestamp": time.time(), "category": category, "content": content}
            with open(BACKUP_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

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
                    self.vector_store.upsert_facts([{
                        "id": doc_id,
                        "vector": list(embedding),
                        "metadata": {
                            "text": content,
                            "hemisphere_tag": hemisphere,
                            "unix_timestamp": int(time.time()),
                            "importance": importance,
                        },
                    }])
                except Exception as lancedb_err:
                    print(f"[WARN] LanceDB upsert failed: {lancedb_err}")

                cursor.execute(
                    "UPDATE documents SET processed = 1 WHERE id = ?", (doc_id,)
                )
            else:
                print(f"[WARN] Embedding failed for doc {doc_id}; queued for later processing")

            conn.commit()
            conn.close()
            return {"status": "stored", "id": doc_id, "embedded": embedding is not None}
        except Exception as e:
            return {"error": str(e)}

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

            # Local Ollama fallback (optional import)
            try:
                import ollama

                response = ollama.chat(
                    model="llama3.2:3b",
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    keep_alive="0",
                )
                return {
                    "response": response["message"]["content"],
                    "model": "llama3.2:3b",
                    "source": "local_fallback",
                }
            except ImportError:
                pass

            return {"error": "No LLM backend available (cloud router and local Ollama both unavailable)"}
        except Exception as e:
            return {"error": str(e)}
