"""
Shared helpers and fixtures for FastEmbed reliability tests.
"""

import random
import string
import threading
from dataclasses import dataclass, field

import pytest

try:
    import psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

try:
    import fastembed  # noqa: F401

    _FASTEMBED_AVAILABLE = True
except ImportError:
    _FASTEMBED_AVAILABLE = False

SKIP_NO_FASTEMBED = pytest.mark.skipif(not _FASTEMBED_AVAILABLE, reason="fastembed not installed")


# ---------------------------------------------------------------------------
# Data generator
# ---------------------------------------------------------------------------


class ReliabilityDataGenerator:
    """Generate 100k+ test texts using stdlib only (no HuggingFace/faker deps).

    Distribution:
      70% chat messages  — short, conversational
      15% code snippets  — multi-line, symbols
      10% long docs      — 300-600 word paragraphs
       5% edge cases     — empty-ish, unicode, special chars
    """

    CHAT_TEMPLATES = [
        "hey what's up",
        "can you help me with {}?",
        "I need to {}",
        "what do you think about {}?",
        "thanks for the {}",
        "how do I {}?",
        "is {} available?",
        "please send me {}",
        "remind me to {} tomorrow",
        "did you see the {} today?",
    ]
    TOPICS = [
        "meeting",
        "report",
        "project",
        "deadline",
        "email",
        "code review",
        "deployment",
        "database",
        "API",
        "test",
        "bug fix",
        "PR",
        "sprint",
        "standup",
        "architecture",
        "feature",
        "hotfix",
        "documentation",
    ]
    CODE_TEMPLATES = [
        "def {fn}(x):\n    return x * 2\n",
        "class {fn}:\n    def __init__(self):\n        self.value = 0\n",
        "for i in range({n}):\n    print(i)\n",
        "import {mod}\nresult = {mod}.{fn}()\n",
        "data = {{'key': 'value', 'count': {n}}}\n",
        "if {cond}:\n    raise ValueError('invalid')\n",
        "async def {fn}():\n    await asyncio.sleep(0)\n",
        "SELECT * FROM {tbl} WHERE id = {n};\n",
    ]
    WORDS = [
        "system",
        "process",
        "function",
        "variable",
        "module",
        "interface",
        "service",
        "component",
        "endpoint",
        "handler",
        "middleware",
        "pipeline",
        "queue",
        "worker",
        "cache",
        "index",
        "token",
        "session",
        "config",
    ]

    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)

    def _chat(self) -> str:
        tmpl = self._rng.choice(self.CHAT_TEMPLATES)
        topic = self._rng.choice(self.TOPICS)
        return tmpl.format(topic) if "{}" in tmpl else tmpl

    def _code(self) -> str:
        tmpl = self._rng.choice(self.CODE_TEMPLATES)
        fn = "func_" + "".join(self._rng.choices(string.ascii_lowercase, k=5))
        mod = self._rng.choice(["os", "sys", "json", "math", "time"])
        tbl = self._rng.choice(["users", "messages", "events", "logs"])
        cond = self._rng.choice(["x is None", "not data", "len(items) == 0"])
        n = self._rng.randint(1, 100)
        return tmpl.format(fn=fn, mod=mod, tbl=tbl, cond=cond, n=n)

    def _long_doc(self) -> str:
        sentences = []
        for _ in range(self._rng.randint(8, 20)):
            words = [self._rng.choice(self.WORDS) for _ in range(self._rng.randint(5, 15))]
            sentences.append(" ".join(words) + ".")
        return " ".join(sentences)

    def _edge(self) -> str:
        choices = [
            " ",
            "\t\n",
            "a",
            "None",
            "null",
            "0",
            "\u00e9\u00e0\u00fc",  # accented Latin
            "\u0986\u09ae\u09be\u09b0",  # Bengali
            "\u4e2d\u6587",  # Chinese
            "\U0001f600\U0001f4a5",  # emoji
            "SELECT 1; DROP TABLE users;--",
            '{"key": "val"}',
        ]
        return self._rng.choice(choices)

    def generate(self, n: int) -> list[str]:
        """Generate n texts using the mixed distribution."""
        texts = []
        for _ in range(n):
            r = self._rng.random()
            if r < 0.70:
                texts.append(self._chat())
            elif r < 0.85:
                texts.append(self._code())
            elif r < 0.95:
                texts.append(self._long_doc())
            else:
                texts.append(self._edge())
        return texts

    def generate_long(self, n: int, min_chars: int = 5000) -> list[str]:
        """Generate n texts that are at least min_chars long."""
        texts = []
        for _ in range(n):
            parts = []
            while sum(len(p) for p in parts) < min_chars:
                parts.append(self._long_doc())
            texts.append(" ".join(parts))
        return texts


# ---------------------------------------------------------------------------
# Latency tracker (thread-safe)
# ---------------------------------------------------------------------------


class LatencyTracker:
    """Thread-safe recorder for operation latencies (seconds)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._latencies: list[float] = []

    def record(self, elapsed: float):
        with self._lock:
            self._latencies.append(elapsed)

    def percentile(self, p: float) -> float:
        with self._lock:
            if not self._latencies:
                return 0.0
            sorted_lats = sorted(self._latencies)
            idx = int(len(sorted_lats) * p / 100)
            idx = min(idx, len(sorted_lats) - 1)
            return sorted_lats[idx]

    def window(self, start: int, end: int) -> "LatencyTracker":
        """Return a new tracker with only the slice [start:end]."""
        with self._lock:
            sub = LatencyTracker()
            sub._latencies = self._latencies[start:end]
        return sub

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._latencies)


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------


def get_memory_mb() -> float:
    """Return current process RSS in MB. Returns 0.0 if psutil unavailable."""
    if not _PSUTIL_AVAILABLE:
        return 0.0
    import os

    proc = psutil.Process(os.getpid())
    return proc.memory_info().rss / (1024 * 1024)


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReliabilityReport:
    total_calls: int = 0
    error_count: int = 0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    memory_start_mb: float = 0.0
    memory_end_mb: float = 0.0
    memory_samples: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def error_rate(self) -> float:
        return self.error_count / self.total_calls if self.total_calls else 0.0

    @property
    def memory_drift_mb(self) -> float:
        return self.memory_end_mb - self.memory_start_mb


# ---------------------------------------------------------------------------
# pytest hooks
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line("markers", "reliability: FastEmbed reliability tests")
    config.addinivalue_line("markers", "slow: Tests that take > 1 minute")
    config.addinivalue_line("markers", "performance: Performance / latency tests")
