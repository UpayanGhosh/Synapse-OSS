"""Knowledge graph and memory endpoints."""

import ast
import json
import logging
from contextlib import suppress
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from sci_fi_dashboard import _deps as deps
from sci_fi_dashboard.middleware import validate_api_key
from sci_fi_dashboard.retriever import query_memories
from sci_fi_dashboard.schemas import MemoryItem, QueryItem

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_api_key(request: Request) -> None:
    """FastAPI Depends shim so handlers can declare auth in their signature.

    Mirrors the inline `validate_api_key(request)` pattern used by the rest
    of this module — read-or-delete operations on memory must be gated by
    the same gateway token.
    """
    validate_api_key(request)


@router.post("/ingest")
def ingest_fact(
    subject: str,
    relation: str,
    object_entity: str,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """Ingest a structured fact into the knowledge graph."""
    validate_api_key(request)
    deps.brain.add_node(subject)
    deps.brain.add_node(object_entity)
    deps.brain.add_relation(subject, relation, object_entity)
    background_tasks.add_task(deps.brain.save_graph)
    return {
        "status": "received",
        "fact": f"{subject} --[{relation}]--> {object_entity}",
    }


@router.post("/add")
async def add_memory(item: MemoryItem, background_tasks: BackgroundTasks, request: Request):
    """Unstructured memory -> LLM -> triple extraction -> graph."""
    validate_api_key(request)
    logger.info("Ingesting: %s...", item.content[:60])

    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract the core fact as a triple. JSON format: "
                    '{"s": "Subject", "r": "Relation", "o": "Object"}. No other text.'
                ),
            },
            {"role": "user", "content": item.content},
        ]
        extraction = await deps.synapse_llm_router.call(
            "casual", messages, temperature=0.1, max_tokens=1000
        )
        extraction = extraction.strip()

        data = None
        if "{" in extraction and "}" in extraction:
            start = extraction.find("{")
            end = extraction.rfind("}") + 1
            json_str = extraction[start:end]
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                with suppress(Exception):
                    data = ast.literal_eval(json_str)

        if data:
            s, r, o = data.get("s"), data.get("r"), data.get("o")
            if s and r and o:
                deps.brain.add_node(s)
                deps.brain.add_node(o)
                deps.brain.add_relation(s, r, o)
                background_tasks.add_task(deps.brain.save_graph)
                return {"status": "memorized", "triple": f"{s} -[{r}]-> {o}"}

    except Exception as e:
        logger.warning("Extraction Error: %s", e)

    return {"status": "failed_extraction", "content": item.content}


@router.post("/query")
async def query_memory(item: QueryItem, request: Request):
    """Query knowledge graph + vector memory."""
    validate_api_key(request)
    logger.info("Query: %s", item.text)

    # Graph search
    graph_results = []
    try:
        tokens = item.text.split()
        for token in tokens:
            if deps.brain.graph.has_node(token):
                graph_results.append(token)
                for n in deps.brain.graph.neighbors(token):
                    graph_results.append(f"{token} -> {n}")
    except Exception:
        pass

    # Vector search
    memory_results = {}
    with suppress(Exception):
        memory_results = query_memories(item.text, limit=3)

    return {
        "graph": graph_results,
        "memory": memory_results,
        "graph_count": len(graph_results),
    }


# ---------------------------------------------------------------------------
# Memory inspector — PRODUCT_ISSUES.md §5.3
# ---------------------------------------------------------------------------
@router.get("/memory/list", summary="List stored memory documents (paginated)")
async def list_memory(
    user: str = Query(..., description="user id, e.g. the_creator"),
    hemisphere: str = Query("safe", regex="^(safe|spicy)$"),
    q: Optional[str] = Query(None, description="optional substring filter on doc text"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _auth: None = Depends(_require_api_key),
):
    """Paginated read of stored memory rows.

    The `user` parameter is required for forward-compat — current schema has
    no per-user column, so results are listed across all docs in the chosen
    hemisphere. Auth: gateway token via `x-api-key` (same as other routes
    in this module).
    """
    try:
        return deps.memory_engine.list_documents(
            user=user, hemisphere=hemisphere, search=q, limit=limit, offset=offset
        )
    except Exception as e:
        logger.exception("memory/list failed: %s", e)
        raise HTTPException(status_code=500, detail=f"memory list failed: {e}") from e


@router.delete("/memory/{doc_id}", summary="Delete a single memory document")
async def delete_memory(
    doc_id: str,
    _auth: None = Depends(_require_api_key),
):
    """Delete a doc and cascade to FTS / sqlite-vec / LanceDB / KG triples.

    See `MemoryEngine.delete_document` for the cascade contract and known
    limitations (orphan KG nodes are NOT pruned here).
    """
    try:
        deleted = deps.memory_engine.delete_document(doc_id)
    except Exception as e:
        logger.exception("memory delete failed for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail=f"memory delete failed: {e}") from e
    if not deleted:
        raise HTTPException(status_code=404, detail=f"doc not found: {doc_id}")
    return {"ok": True, "doc_id": doc_id}
