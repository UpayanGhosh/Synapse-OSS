import json
import math
import os
import sqlite3
import sys
import threading
import time
from functools import lru_cache, wraps

from flashrank import Ranker, RerankRequest

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
# Note: scripts/v2_migration might not exist yet or might be elsewhere,
# but I will keep it as per user's provision.
sys.path.append(os.path.join(WORKSPACE_ROOT, "scripts", "v2_migration"))

try:
    from scripts.v2_migration.qdrant_handler import QdrantVectorStore
except ImportError:
    # Fallback to absolute import if package structure is tricky
    sys.path.append(os.path.join(WORKSPACE_ROOT, "sci_fi_dashboard"))
    from retriever import QdrantVectorStore  # noqa: E402

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    ollama = None
    OLLAMA_AVAILABLE = False

# Configuration
EMBEDDING_MODEL = "nomic-embed-text"
OLLAMA_KEEP_ALIVE = "0"  # CRITICAL: zero persistence
RERANK_MODEL_NAME = "ms-marco-TinyBERT-L-2-v2"
DB_PATH = os.path.join(WORKSPACE_ROOT, "db", "memory.db")
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
        self.qdrant_store = QdrantVectorStore()

        # SHARED -- not duplicated
        self.graph_store = graph_store
        self.keyword_processor = keyword_processor

        # Lazy-loaded reranker
        self._ranker = None
        self._ranker_lock = threading.Lock()
        self._st_model = None  # lazy-loaded sentence-transformers fallback

        if OLLAMA_AVAILABLE:
            print("[OK] MemoryEngine initialized (Ollama available -- nomic-embed-text)")
        else:
            print("[WARN] Ollama not found -- local embedding and The Vault disabled")
            print("[WARN] Embedding fallback: sentence-transformers all-MiniLM-L6-v2 (384-dim)")
            print("[WARN] If DB has existing 768-dim vectors, re-ingest to restore semantic search")
        print("[OK] MemoryEngine initialized (shared graph, no duplication)")

    def _sentence_transformer_embed(self, text: str) -> tuple:
        """Fallback embedding using all-MiniLM-L6-v2 (384-dim). Lazy-loaded."""
        if self._st_model is None:
            from sentence_transformers import SentenceTransformer
            self._st_model = SentenceTransformer("all-MiniLM-L6-v2")
        return tuple(self._st_model.encode(text).tolist())

    @lru_cache(maxsize=500)  # noqa: B019
    def get_embedding(self, text: str) -> tuple:
        if not OLLAMA_AVAILABLE:
            return self._sentence_transformer_embed(text)
        try:
            response = ollama.embeddings(
                model=EMBEDDING_MODEL,
                prompt=text,
                keep_alive=OLLAMA_KEEP_ALIVE,
            )
            return tuple(response["embedding"])
        except Exception as e:
            print(f"[WARN] Embedding generation failed: {e}")
            return tuple([0.0] * 768)

    def _get_ranker(self) -> Ranker:
        if self._ranker is None:
            with self._ranker_lock:
                if self._ranker is None:
                    self._ranker = Ranker(
                        model_name=RERANK_MODEL_NAME,
                        cache_dir=os.path.join(os.path.expanduser("~/.openclaw"), "models"),
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
    ) -> dict:
        start = time.time()

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

            # Qdrant search
            query_vec = list(self.get_embedding(text))
            q_results = self.qdrant_store.search(query_vec, limit=limit * 3)

            # Apply 3-factor scoring: relevance + temporal + importance
            for r in q_results:
                ts = r["metadata"].get("unix_timestamp")
                importance = r["metadata"].get("importance", 5)
                r["combined_score"] = (
                    (r["score"] * 0.4) + (self._temporal_score(ts) * 0.3) + (importance / 10 * 0.3)
                )

            q_results.sort(key=lambda x: x["combined_score"], reverse=True)

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
                return {
                    "results": [
                        {
                            "content": x["metadata"]["text"],
                            "score": x["combined_score"],
                            "source": "qdrant_fast",
                        }
                        for x in high_conf[:limit]
                    ],
                    "tier": "fast_gate",
                    "entities": entities,
                    "graph_context": graph_context,
                    "routing": routing,
                }

            # Reranker fallback
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
                    {"content": x["text"], "score": float(x["score"]), "source": "qdrant_reranked"}
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
    def add_memory(self, content: str, category: str = "direct_entry") -> dict:
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
                "INSERT INTO documents (filename, content, processed, unix_timestamp, importance)"
                " VALUES (?, ?, 0, ?, ?)",
                (category, content, int(time.time()), importance),
            )
            doc_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return {"status": "queued", "id": doc_id}
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

            # Local fallback
            if OLLAMA_AVAILABLE:
                response = ollama.chat(
                    model="llama3.2:3b",
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    keep_alive=OLLAMA_KEEP_ALIVE,
                )
                return {
                    "response": response["message"]["content"],
                    "model": "llama3.2:3b",
                    "source": "local_fallback",
                }
            else:
                return {"error": "Ollama not available and cloud LLM router unavailable"}
        except Exception as e:
            return {"error": str(e)}
