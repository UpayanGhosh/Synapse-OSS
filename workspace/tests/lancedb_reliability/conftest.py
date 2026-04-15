"""
conftest.py — Shared fixtures and helpers for LanceDB reliability tests.

Data strategy (priority order):
1. AG News dataset (HuggingFace) — 120k real news articles, 4 semantic categories.
   Best for semantic accuracy tests. Requires: pip install datasets
2. 20 Newsgroups (sklearn) — 18k posts, 20 categories. No extra install.
3. WordBank synthetic — pure Python fallback, no downloads, always works.

Vector generation (priority order):
1. FastEmbed via get_provider() — GPU float32 if CUDA, INT8-Q if CPU-only.
2. numpy L2-normalised random — fallback when no provider available (CI/no-GPU).

Fixtures:
- tmp_store           — empty LanceDBVectorStore in a temp dir
- real_dataset        — (texts, labels, label_names) from best available source
- store_1k            — 1k store, real texts + FastEmbed (GPU) or numpy fallback
- store_10k           — 10k store, real texts + FastEmbed (GPU) or numpy fallback
- store_100k          — 100k store, real texts + FastEmbed (GPU). --run-slow
- fastembed_store_10k — 10k store, real texts, FastEmbed required (no numpy fallback)
"""

from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Real Dataset Loader
# ---------------------------------------------------------------------------

_DATASET_CACHE = Path.home() / ".cache" / "synapse_test_data"


class RealDatasetLoader:
    """Downloads and caches a real text dataset for testing.

    Priority:
    1. AG News (HuggingFace `datasets`) — 120k news articles, 4 categories.
       Categories: 0=World, 1=Sports, 2=Business, 3=Sci/Tech
    2. 20 Newsgroups (sklearn) — 18k posts, 20 categories. No install needed.
    3. Returns None — caller falls back to synthetic wordbank.

    Dataset is cached to ~/.cache/synapse_test_data/ after first download.
    Subsequent runs are instant (disk read only, no network).
    """

    AG_NEWS_CACHE = _DATASET_CACHE / "ag_news.npz"
    LABEL_NAMES_AG = ["World", "Sports", "Business", "Sci/Tech"]
    LABEL_NAMES_20NG = None  # filled at load time

    def load(self, n: int | None = None) -> tuple[list[str], list[int], list[str]] | None:
        """Return (texts, labels, label_names) or None if all sources fail.

        Args:
            n: Max number of samples to return. None = all available.
        """
        result = self._load_ag_news(n) or self._load_20newsgroups(n)
        return result

    def _load_ag_news(self, n: int | None) -> tuple[list[str], list[int], list[str]] | None:
        """Try HuggingFace datasets — AG News."""
        # Check disk cache first (no network needed)
        if self.AG_NEWS_CACHE.exists():
            try:
                data = np.load(str(self.AG_NEWS_CACHE), allow_pickle=True)
                texts = data["texts"].tolist()
                labels = data["labels"].tolist()
                if n:
                    texts, labels = texts[:n], labels[:n]
                return texts, labels, self.LABEL_NAMES_AG
            except Exception:
                pass  # corrupt cache — re-download below

        try:
            from datasets import load_dataset  # pip install datasets
        except ImportError:
            return None

        try:
            print("\n[dataset] Downloading AG News from HuggingFace (120k articles)...")
            ds = load_dataset("ag_news", split="train", trust_remote_code=False)
            # Combine title + description for richer text
            texts = [f"{row['text']}" for row in ds]
            labels = [int(row["label"]) for row in ds]

            # Cache to disk
            _DATASET_CACHE.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                str(self.AG_NEWS_CACHE),
                texts=np.array(texts, dtype=object),
                labels=np.array(labels, dtype=np.int32),
            )
            print(f"[dataset] AG News cached to {self.AG_NEWS_CACHE} ({len(texts)} records)")

            if n:
                texts, labels = texts[:n], labels[:n]
            return texts, labels, self.LABEL_NAMES_AG
        except Exception as e:
            print(f"[dataset] AG News download failed: {e}")
            return None

    def _load_20newsgroups(self, n: int | None) -> tuple[list[str], list[int], list[str]] | None:
        """Try sklearn 20 Newsgroups — no extra install needed."""
        try:
            from sklearn.datasets import fetch_20newsgroups

            data = fetch_20newsgroups(subset="all", remove=("headers", "footers", "quotes"))
            texts = data.data
            labels = data.target.tolist()
            label_names = list(data.target_names)
            if n:
                texts, labels = texts[:n], labels[:n]
            print(f"[dataset] Using 20 Newsgroups ({len(texts)} posts, 20 categories)")
            return list(texts), labels, label_names
        except Exception as e:
            print(f"[dataset] 20 Newsgroups unavailable: {e}")
            return None

    # ------------------------------------------------------------------
    # Chat simulation — PersonaChat
    # ------------------------------------------------------------------

    PERSONA_CACHE = _DATASET_CACHE / "persona_chat.npz"

    def load_chat(self, n_facts: int | None = None) -> ChatDataset | None:
        """Load PersonaChat for memory/chat simulation tests.

        Returns a ChatDataset with:
          - facts        : list[str]  — persona facts ("I love hiking on weekends")
          - persona_ids  : list[int]  — which persona each fact belongs to
          - queries      : list[str]  — conversation utterances used as queries
          - query_pids   : list[int]  — persona_id the query came from
          - label_names  : list[str]  — ["persona_0", "persona_1", ...]

        Dataset is downloaded once and cached to disk.
        Requires: pip install datasets
        """
        return self._load_persona_chat(n_facts)

    def _load_persona_chat(self, n_facts: int | None) -> ChatDataset | None:
        """Download / load from cache PersonaChat (AlekseyKorshuk/persona-chat)."""
        # Try disk cache first
        if self.PERSONA_CACHE.exists():
            try:
                data = np.load(str(self.PERSONA_CACHE), allow_pickle=True)
                facts = data["facts"].tolist()
                persona_ids = data["persona_ids"].tolist()
                queries = data["queries"].tolist()
                query_pids = data["query_pids"].tolist()
                n_personas = int(data["n_personas"])
                label_names = [f"persona_{i}" for i in range(n_personas)]
                if n_facts:
                    facts, persona_ids = facts[:n_facts], persona_ids[:n_facts]
                print(
                    f"[dataset] PersonaChat loaded from cache ({len(facts)} facts, {len(queries)} queries)"
                )
                return ChatDataset(facts, persona_ids, queries, query_pids, label_names)
            except Exception:
                pass  # corrupt cache — re-download

        try:
            from datasets import load_dataset
        except ImportError:
            print("[dataset] PersonaChat unavailable: pip install datasets")
            return None

        try:
            print("\n[dataset] Downloading PersonaChat from HuggingFace...")
            ds = load_dataset("AlekseyKorshuk/persona-chat", split="train", trust_remote_code=False)
        except Exception as e:
            print(f"[dataset] PersonaChat download failed: {e}")
            return None

        facts, persona_ids, queries, query_pids = [], [], [], []
        persona_counter = 0

        for item in ds:
            pid = persona_counter
            persona_counter += 1
            # Each item has a 'personality' list of facts
            for fact in item.get("personality", []):
                fact = fact.strip()
                if fact:
                    facts.append(fact)
                    persona_ids.append(pid)
            # Utterances: flatten history turns as conversation queries
            for utt in item.get("utterances", []):
                for turn in utt.get("history", []):
                    turn = turn.strip()
                    if turn and len(turn) > 5:
                        queries.append(turn)
                        query_pids.append(pid)

        label_names = [f"persona_{i}" for i in range(persona_counter)]

        # Cache to disk
        _DATASET_CACHE.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            str(self.PERSONA_CACHE),
            facts=np.array(facts, dtype=object),
            persona_ids=np.array(persona_ids, dtype=np.int32),
            queries=np.array(queries, dtype=object),
            query_pids=np.array(query_pids, dtype=np.int32),
            n_personas=np.array(persona_counter, dtype=np.int32),
        )
        print(
            f"[dataset] PersonaChat cached: {len(facts)} facts across "
            f"{persona_counter} personas, {len(queries)} query turns"
        )

        if n_facts:
            facts, persona_ids = facts[:n_facts], persona_ids[:n_facts]
        return ChatDataset(facts, persona_ids, queries, query_pids, label_names)


class ChatDataset:
    """Holds PersonaChat data split into facts (memories) and queries (conversation turns).

    facts       — persona statements like "I love hiking on weekends".
                  These are stored in LanceDB as memories.
    persona_ids — which persona each fact belongs to (int).
    queries     — conversation utterances like "do you enjoy outdoor activities?".
                  These are used as search queries against the fact store.
    query_pids  — persona_id the query came from (so we know which facts are 'correct').
    label_names — ["persona_0", "persona_1", ...]
    """

    def __init__(
        self,
        facts: list[str],
        persona_ids: list[int],
        queries: list[str],
        query_pids: list[int],
        label_names: list[str],
    ) -> None:
        self.facts = facts
        self.persona_ids = persona_ids
        self.queries = queries
        self.query_pids = query_pids
        self.label_names = label_names

    def __repr__(self) -> str:
        return (
            f"ChatDataset({len(self.facts)} facts, "
            f"{len(set(self.persona_ids))} personas, "
            f"{len(self.queries)} query turns)"
        )


# Singleton loader — download happens once per Python session
_dataset_loader = RealDatasetLoader()


# ---------------------------------------------------------------------------
# Wordbank — fallback when no real dataset available
# ---------------------------------------------------------------------------

_ADJ = [
    "bright",
    "dark",
    "happy",
    "tired",
    "fast",
    "slow",
    "warm",
    "cold",
    "clear",
    "fuzzy",
    "sharp",
    "quiet",
    "loud",
    "calm",
    "busy",
    "free",
    "deep",
    "light",
    "heavy",
    "smooth",
    "rough",
    "soft",
    "hard",
    "old",
    "new",
    "long",
    "short",
    "wide",
    "narrow",
    "strong",
]
_NOUNS = [
    "morning",
    "project",
    "memory",
    "code",
    "feeling",
    "idea",
    "plan",
    "meeting",
    "note",
    "problem",
    "solution",
    "moment",
    "day",
    "night",
    "coffee",
    "task",
    "goal",
    "habit",
    "thought",
    "routine",
    "session",
    "focus",
    "question",
    "answer",
    "detail",
    "change",
    "step",
    "result",
    "pattern",
    "system",
]
_VERBS = [
    "enjoy",
    "remember",
    "build",
    "explore",
    "fix",
    "learn",
    "create",
    "share",
    "review",
    "improve",
    "start",
    "finish",
    "track",
    "handle",
    "check",
    "update",
    "debug",
    "deploy",
    "test",
    "run",
]
_PLACES = [
    "office",
    "home",
    "terminal",
    "notebook",
    "dashboard",
    "workspace",
    "garden",
    "library",
    "studio",
    "lab",
]
_TIMES = [
    "morning",
    "afternoon",
    "evening",
    "weekend",
    "sprint",
    "deadline",
    "session",
    "standup",
    "review",
    "release",
]
_TEMPLATES = [
    "I {verb} the {adj} {noun} during {time}",
    "the {noun} feels {adj} today in the {place}",
    "need to {verb} a {adj} {noun} for the {time}",
    "that {adj} {noun} is hard to {verb} at {place}",
    "feeling {adj} while trying to {verb} the {noun}",
    "the {place} has a {adj} {noun} that I always {verb}",
    "during {time} I usually {verb} my {adj} {noun}",
    "this {adj} {noun} from {place} will {verb} soon",
    "{verb} the {noun} until it is {adj} enough",
    "a {adj} {noun} helped me {verb} at {place}",
    "every {time} I try to {verb} something {adj}",
    "the {adj} {noun} at {place} makes me want to {verb}",
]

# Categories and entities for metadata variety
_CATEGORIES = [
    "memory",
    "fact",
    "preference",
    "event",
    "skill",
    "routine",
    "observation",
    "goal",
    "task",
    "reflection",
]
_ENTITIES = [
    "user",
    "friend",
    "colleague",
    "project",
    "tool",
    "location",
    "habit",
    "emotion",
    "idea",
    "system",
]
_HEMISPHERES = ["safe", "safe", "safe", "safe", "spicy"]  # 80% safe


# ---------------------------------------------------------------------------
# Data Generator
# ---------------------------------------------------------------------------


class LanceDBDataGenerator:
    """Generates test records programmatically — no LLM required.

    Texts are assembled from the wordbank above. Vectors are either:
    - Random L2-normalized float32 (reproducible, fast, for DB-layer tests)
    - Real FastEmbed output (for semantic/accuracy tests)

    Usage::

        gen = LanceDBDataGenerator(seed=42)
        texts = gen.texts(10_000)
        vectors = gen.vectors_random(10_000, dims=768)
        facts = gen.facts(10_000, vectors=vectors)
    """

    def __init__(self, seed: int = 42) -> None:
        self._seed = seed
        self._rng = random.Random(seed)
        self._np_rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------
    # Text generation
    # ------------------------------------------------------------------

    def texts(self, n: int) -> list[str]:
        """Generate n diverse text strings from wordbank templates."""
        rng = random.Random(self._seed)
        out = []
        for i in range(n):
            tpl = rng.choice(_TEMPLATES)
            text = tpl.format(
                adj=rng.choice(_ADJ),
                noun=rng.choice(_NOUNS),
                verb=rng.choice(_VERBS),
                place=rng.choice(_PLACES),
                time=rng.choice(_TIMES),
            )
            # Occasionally add a numeric suffix to ensure uniqueness at scale
            if i % 5 == 0:
                text += f" ({i})"
            out.append(text)
        return out

    def texts_with_known_cluster(
        self, n: int, cluster_size: int = 10
    ) -> tuple[list[str], list[str]]:
        """Return (corpus, queries) where each query is a paraphrase of a corpus item.

        Useful for accuracy tests: corpus[i*k] ≈ queries[i] semantically.
        """
        base_phrases = [
            "I enjoy writing clean code every morning",
            "the project deadline is approaching fast",
            "feeling tired after a long debugging session",
            "coffee helps me focus during long meetings",
            "need to review the pull request before release",
        ]
        corpus = self.texts(n)
        queries = []
        for phrase in base_phrases[:cluster_size]:
            # Light paraphrase: word swap
            queries.append(phrase.replace("I ", "we ").replace("enjoy", "like"))
        return corpus, queries

    # ------------------------------------------------------------------
    # Vector generation
    # ------------------------------------------------------------------

    def vectors_random(self, n: int, dims: int = 768) -> np.ndarray:
        """Generate n L2-normalized float32 vectors (fast, reproducible)."""
        rng = np.random.default_rng(self._seed)
        vecs = rng.standard_normal((n, dims)).astype(np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        return vecs / np.maximum(norms, 1e-8)

    def vectors_fastembed(self, texts: list[str], batch_size: int = 256) -> np.ndarray:
        """Embed texts using the project's FastEmbedProvider (auto GPU/CPU selection).

        Uses get_provider() from the project factory which:
        - CUDA available  → float32 model on GPU (~150+ text/s single, faster batched)
        - CPU-only        → INT8-Q model on CPU (~64 text/s)
        Never directly instantiates fastembed to ensure GPU detection is respected.
        Falls back to pytest.skip if no provider is available.
        """
        try:
            from sci_fi_dashboard.embedding.factory import get_provider

            provider = get_provider()
        except Exception as e:
            pytest.skip(f"Embedding provider unavailable: {e}")

        if provider is None:
            pytest.skip("No embedding provider configured")

        # Truncate to avoid GPU OOM — AG News articles can be 10k+ chars (~3500 tokens).
        # 2000 chars ≈ 500 tokens, keeps BiasSoftmax arena well under 200 MB per batch.
        _MAX_CHARS = 2000  # noqa: N806
        all_vecs = []
        for i in range(0, len(texts), batch_size):
            batch = [t[:_MAX_CHARS] for t in texts[i : i + batch_size]]
            vecs = provider.embed_documents(batch)
            all_vecs.extend(vecs)

        arr = np.array(all_vecs, dtype=np.float32)
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        return arr / np.maximum(norms, 1e-8)

    # ------------------------------------------------------------------
    # Fact dict generation
    # ------------------------------------------------------------------

    def facts(
        self,
        n: int,
        vectors: np.ndarray | None = None,
        texts: list[str] | None = None,
        id_offset: int = 0,
        dims: int = 768,
    ) -> list[dict]:
        """Build list of fact dicts ready for LanceDBVectorStore.upsert_facts()."""
        rng = random.Random(self._seed + id_offset)
        if vectors is None:
            vectors = self.vectors_random(n, dims=dims)
        if texts is None:
            texts = self.texts(n)

        facts = []
        for i in range(n):
            facts.append(
                {
                    "id": id_offset + i,
                    "vector": vectors[i].tolist(),
                    "metadata": {
                        "text": texts[i],
                        "hemisphere_tag": rng.choice(_HEMISPHERES),
                        "unix_timestamp": 1_700_000_000 + i * 60,
                        "importance": rng.randint(1, 10),
                        "source_id": rng.randint(1, 1000),
                        "entity": rng.choice(_ENTITIES),
                        "category": rng.choice(_CATEGORIES),
                    },
                }
            )
        return facts


# ---------------------------------------------------------------------------
# Latency Tracker (thread-safe)
# ---------------------------------------------------------------------------


class LatencyTracker:
    """Thread-safe wall-clock latency recorder with percentile computation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: list[float] = []

    def record(self, ms: float) -> None:
        with self._lock:
            self._samples.append(ms)

    def percentile(self, p: float) -> float:
        with self._lock:
            if not self._samples:
                return 0.0
            arr = sorted(self._samples)
            idx = max(0, int(len(arr) * p / 100) - 1)
            return arr[idx]

    def mean(self) -> float:
        with self._lock:
            return sum(self._samples) / len(self._samples) if self._samples else 0.0

    def count(self) -> int:
        with self._lock:
            return len(self._samples)

    def errors(self) -> int:
        """Samples recorded as -1 indicate an error."""
        with self._lock:
            return sum(1 for s in self._samples if s < 0)


# ---------------------------------------------------------------------------
# Memory helper
# ---------------------------------------------------------------------------


def get_memory_mb() -> float:
    """Current process RSS in MB. Falls back to 0 if psutil unavailable."""
    try:
        import os

        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class LanceDBReport:
    phase: str
    ingest_rows: int = 0
    ingest_wall_s: float = 0.0
    ingest_rows_per_s: float = 0.0
    ingest_errors: int = 0
    search_calls: int = 0
    search_p50_ms: float = 0.0
    search_p95_ms: float = 0.0
    search_p99_ms: float = 0.0
    memory_delta_mb: float = 0.0
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pytest markers
# (--run-slow option and slow marker skip logic are already registered in
#  the parent tests/conftest.py — do NOT re-register them here)
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line("markers", "fastembed: requires fastembed package")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def generator() -> LanceDBDataGenerator:
    return LanceDBDataGenerator(seed=42)


@pytest.fixture(scope="session")
def real_dataset() -> tuple[list[str], list[int], list[str]] | None:
    """Best available real text dataset: AG News > 20 Newsgroups > None.

    Returns (texts, labels, label_names) or None if all sources fail.
    Downloaded once per session, cached to disk for subsequent runs.

    AG News label_names: ['World', 'Sports', 'Business', 'Sci/Tech']
    """
    return _dataset_loader.load(n=None)  # full dataset, no truncation


@pytest.fixture
def tmp_store(tmp_path):
    """Empty LanceDBVectorStore in a fresh temp dir."""
    pytest.importorskip("lancedb")
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

    store = LanceDBVectorStore(db_path=tmp_path / "db", embedding_dimensions=768)
    yield store
    store.close()


def _embed_or_random(
    generator,
    n: int,
    batch_size: int = 256,
    real_texts: list[str] | None = None,
) -> tuple[np.ndarray, list[str]]:
    """Embed n texts with FastEmbed (GPU if available), fall back to numpy.

    Text priority:
      1. real_texts slice (AG News / 20 Newsgroups — real-world distribution)
      2. Synthetic wordbank texts (always works, no downloads)

    Vector priority:
      1. FastEmbed via get_provider() — GPU float32 (CUDA) or INT8-Q (CPU)
      2. numpy L2-normalised random   — fallback for CI / no provider

    GPU float32 is selected automatically by FastEmbedProvider._detect_accelerator().
    """
    # Pick texts: real dataset (trimmed/padded to n) or synthetic
    if real_texts and len(real_texts) >= n:
        texts = real_texts[:n]
    elif real_texts:
        # Dataset smaller than n — tile it to reach n
        reps = (n // len(real_texts)) + 1
        texts = (real_texts * reps)[:n]
    else:
        texts = generator.texts(n)

    try:
        from sci_fi_dashboard.embedding.factory import get_provider

        provider = get_provider()
        if provider is not None:
            _MAX_CHARS = 2000  # noqa: N806
            all_vecs = []
            for i in range(0, n, batch_size):
                batch = [t[:_MAX_CHARS] for t in texts[i : i + batch_size]]
                all_vecs.extend(provider.embed_documents(batch))
            arr = np.array(all_vecs, dtype=np.float32)
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            return arr / np.maximum(norms, 1e-8), texts
    except Exception:
        pass  # provider unavailable — fall through to numpy

    # Numpy fallback (deterministic, for CI / no-GPU environments)
    return generator.vectors_random(n), texts


@pytest.fixture(scope="session")
def store_1k(tmp_path_factory, generator, real_dataset):
    """1k store. Real AG News / 20NG texts + FastEmbed (GPU) or numpy fallback."""
    pytest.importorskip("lancedb")
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

    db_path = tmp_path_factory.mktemp("store_1k")
    store = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)
    rt = real_dataset[0] if real_dataset else None
    vectors, texts = _embed_or_random(generator, 1_000, real_texts=rt)
    facts = generator.facts(1_000, vectors=vectors, texts=texts)
    store.upsert_facts(facts)
    yield store, facts
    store.close()


@pytest.fixture(scope="session")
def store_10k(tmp_path_factory, generator, real_dataset):
    """10k store. Real AG News / 20NG texts + FastEmbed (GPU) or numpy fallback."""
    pytest.importorskip("lancedb")
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

    db_path = tmp_path_factory.mktemp("store_10k")
    store = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)
    rt = real_dataset[0] if real_dataset else None
    vectors, texts = _embed_or_random(generator, 10_000, real_texts=rt)
    facts = generator.facts(10_000, vectors=vectors, texts=texts)
    store.upsert_facts(facts)
    yield store, facts
    store.close()


@pytest.fixture(scope="session")
def store_100k(tmp_path_factory, generator, real_dataset):
    """100k store. Real AG News texts (120k available) + FastEmbed GPU. --run-slow."""
    pytest.importorskip("lancedb")
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

    db_path = tmp_path_factory.mktemp("store_100k")
    store = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)
    rt = real_dataset[0] if real_dataset else None
    vectors, texts = _embed_or_random(generator, 100_000, real_texts=rt)
    facts = generator.facts(100_000, vectors=vectors, texts=texts)
    for i in range(0, 100_000, 1_000):
        store.upsert_facts(facts[i : i + 1_000])
    yield store, facts
    store.close()


@pytest.fixture(scope="session")
def fastembed_store_10k(tmp_path_factory, generator, real_dataset):
    """10k store. Real texts + FastEmbed required (no numpy fallback — semantic tests)."""
    pytest.importorskip("lancedb")
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

    db_path = tmp_path_factory.mktemp("fastembed_10k")
    store = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)
    # Use real dataset texts if available, else synthetic
    texts = real_dataset[0][:10000] if real_dataset else generator.texts(10000)
    vectors = generator.vectors_fastembed(texts, batch_size=256)
    facts = generator.facts(10_000, vectors=vectors, texts=texts)
    store.upsert_facts(facts)
    yield store, facts, texts, vectors
    store.close()


@pytest.fixture(scope="session")
def persona_dataset() -> ChatDataset | None:
    """PersonaChat dataset for chat/memory simulation tests.

    Returns a ChatDataset or None if download fails.
    Downloaded once, cached to ~/.cache/synapse_test_data/persona_chat.npz.

    Structure:
      .facts        — persona facts: "I love hiking on weekends"
      .persona_ids  — which persona each fact belongs to
      .queries      — conversation turns: "do you like outdoor activities?"
      .query_pids   — persona_id the query came from
      .label_names  — ["persona_0", "persona_1", ...]
    """
    return _dataset_loader.load_chat()


@pytest.fixture(scope="session")
def persona_store(tmp_path_factory, generator, persona_dataset):
    """LanceDB store loaded with PersonaChat persona facts as memories.

    Each fact is stored with:
      text          = the persona fact string
      category      = persona label ("persona_42")
      hemisphere_tag = "safe"

    Queries (.queries) from the same persona should retrieve that persona's facts.
    Requires FastEmbed (GPU/CPU) — skips if no provider available.
    Skips if PersonaChat download failed.
    """
    if persona_dataset is None:
        pytest.skip("PersonaChat dataset unavailable — pip install datasets")
    pytest.importorskip("lancedb")
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

    facts_texts = persona_dataset.facts
    persona_ids = persona_dataset.persona_ids
    label_names = persona_dataset.label_names

    # Embed all facts via FastEmbed (GPU if available)
    vectors = generator.vectors_fastembed(facts_texts, batch_size=256)

    db_path = tmp_path_factory.mktemp("persona_store")
    store = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)

    facts = []
    for i, (text, pid, vec) in enumerate(zip(facts_texts, persona_ids, vectors, strict=False)):
        facts.append(
            {
                "id": i,
                "vector": vec.tolist(),
                "metadata": {
                    "text": text,
                    "hemisphere_tag": "safe",
                    "category": label_names[pid] if pid < len(label_names) else "unknown",
                    "importance": 7,
                    "source_id": pid,
                },
            }
        )

    # Upsert in batches
    for i in range(0, len(facts), 1_000):
        store.upsert_facts(facts[i : i + 1_000])

    print(f"\n[persona_store] {len(facts)} facts loaded from {len(set(persona_ids))} personas")
    yield store, persona_dataset
    store.close()


@pytest.fixture(scope="session")
def categorised_store(tmp_path_factory, generator, real_dataset):
    """Store with per-category labels for semantic clustering tests.

    Uses AG News (World/Sports/Business/Sci-Tech) or 20 Newsgroups.
    Each fact's metadata carries a 'category' from the real dataset label.
    Requires FastEmbed — skips if unavailable.
    Requires real_dataset — skips if dataset download failed.
    """
    if real_dataset is None:
        pytest.skip("No real dataset available — install datasets or sklearn")
    pytest.importorskip("lancedb")
    from sci_fi_dashboard.vector_store.lancedb_store import LanceDBVectorStore

    texts, labels, label_names = real_dataset
    # Use up to 20k samples (balanced across categories)
    n_per_cat = 2_000
    selected_texts, selected_labels = [], []
    from collections import Counter

    counts: Counter = Counter()
    for t, label in zip(texts, labels, strict=False):
        if counts[label] < n_per_cat:
            selected_texts.append(t)
            selected_labels.append(label)
            counts[label] += 1
        if len(selected_texts) >= n_per_cat * len(label_names):
            break

    vectors = generator.vectors_fastembed(selected_texts, batch_size=256)

    db_path = tmp_path_factory.mktemp("categorised")
    store = LanceDBVectorStore(db_path=db_path, embedding_dimensions=768)
    facts = []
    for i, (text, label, vec) in enumerate(
        zip(selected_texts, selected_labels, vectors, strict=False)
    ):
        facts.append(
            {
                "id": i,
                "vector": vec.tolist(),
                "metadata": {
                    "text": text,
                    "hemisphere_tag": "safe",
                    "category": label_names[label],
                    "importance": label + 1,
                },
            }
        )
    store.upsert_facts(facts)
    yield store, selected_texts, selected_labels, label_names
    store.close()
