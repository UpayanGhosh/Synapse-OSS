from __future__ import annotations

import asyncio
import inspect

from sci_fi_dashboard.dual_cognition import DualCognitionEngine


class SecretMemory:
    def __init__(self) -> None:
        self.calls = 0

    def query(self, *_args, **_kwargs):
        self.calls += 1
        return {
            "results": [{"content": "Bobs private medical issue: SECRET-BOB-42"}],
            "graph_context": "Private Bob graph edge SECRET-BOB-42",
            "affect_hints": "Bob was anxious about SECRET-BOB-42",
        }


class SecretGraph:
    def __init__(self) -> None:
        self.calls = 0

    def get_entity_neighborhood(self, _name: str) -> str:
        self.calls += 1
        return "Private Bob profile SECRET-BOB-42"


def test_empty_scoped_recall_never_falls_back_to_global_personal_sources() -> None:
    memory = SecretMemory()
    graph = SecretGraph()
    engine = DualCognitionEngine(memory, graph)
    kwargs = {}
    if "allow_legacy_personal_sources" in inspect.signature(engine._recall_memory).parameters:
        kwargs["allow_legacy_personal_sources"] = False

    result = asyncio.run(
        engine._recall_memory(
            "What should I do next?",
            "alice-session",
            "the_creator",
            pre_cached_memory={},
            **kwargs,
        )
    )

    assert memory.calls == 0
    assert graph.calls == 0
    assert result.relevant_facts == []
    assert result.graph_connections == ""
    assert result.affect_hints == ""
    assert "SECRET-BOB-42" not in repr(result)


def test_nonempty_scoped_results_are_used_without_global_fallback() -> None:
    memory = SecretMemory()
    graph = SecretGraph()
    engine = DualCognitionEngine(memory, graph)
    scoped_memory = {
        "results": [{"content": "Alice remembers the tiny red umbrella joke."}],
        "graph_context": "",
        "affect_hints": "",
    }
    kwargs = {}
    if "allow_legacy_personal_sources" in inspect.signature(engine._recall_memory).parameters:
        kwargs["allow_legacy_personal_sources"] = False

    result = asyncio.run(
        engine._recall_memory(
            "tiny red umbrella",
            "alice-session",
            "the_creator",
            pre_cached_memory=scoped_memory,
            **kwargs,
        )
    )

    assert memory.calls == 0
    assert graph.calls == 0
    assert result.relevant_facts == ["Alice remembers the tiny red umbrella joke."]
    assert "SECRET-BOB-42" not in repr(result)
