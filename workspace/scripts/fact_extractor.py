"""
Conversation-based KG extractor CLI — thin wrapper around conv_kg_extractor.

Replaces the old torch-based document extraction pipeline.  Now processes
recent conversation messages (not documents) via the configured LLM router.

Usage
-----
    python scripts/fact_extractor.py                 # process new messages
    python scripts/fact_extractor.py --force         # ignore min_messages threshold
    python scripts/fact_extractor.py --limit 100     # cap at 100 messages
    python scripts/fact_extractor.py --dry-run       # extract but don't write
"""

import argparse
import asyncio
import os
import sys

_sys_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _sys_path not in sys.path:
    sys.path.insert(0, _sys_path)

from synapse_config import SynapseConfig  # noqa: E402
from sci_fi_dashboard.conv_kg_extractor import (  # noqa: E402
    ConvKGExtractor,
    fetch_messages_since,
    run_batch_extraction,
    _get_last_kg_timestamp,
)
from sci_fi_dashboard.llm_router import SynapseLLMRouter  # noqa: E402
from sci_fi_dashboard.sqlite_graph import SQLiteGraph  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_cfg = SynapseConfig.load()
ENTITIES_JSON = os.path.join(
    os.path.dirname(__file__), "..", "sci_fi_dashboard", "entities.json"
)
ENTITIES_JSON = os.path.normpath(ENTITIES_JSON)


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


async def _run_extraction(
    force: bool = False,
    limit: int = 200,
    dry_run: bool = False,
) -> None:
    """Run conversation-based KG extraction for all personas."""
    cfg = SynapseConfig.load()
    router = SynapseLLMRouter(cfg)
    graph = SQLiteGraph()

    personas = ["the_creator", "the_partner"]

    for persona_id in personas:
        sbs_data_dir = str(cfg.sbs_dir / persona_id)
        memory_db_path = str(cfg.db_dir / "memory.db")

        if dry_run:
            # Dry-run: extract only, print results, skip writes
            last_ts = _get_last_kg_timestamp(sbs_data_dir)
            db_path = os.path.join(sbs_data_dir, "indices", "messages.db")

            try:
                msgs = await fetch_messages_since(db_path, last_ts, limit=limit)
            except Exception as e:
                print(f"[{persona_id}] Could not read messages: {e}")
                continue

            if not msgs:
                print(f"[{persona_id}] No new messages since {last_ts}")
                continue

            print(f"[{persona_id}] {len(msgs)} message(s) since {last_ts}")
            text = "\n".join(f"[{m['role']}]: {m['content']}" for m in msgs)

            extractor = ConvKGExtractor(router)
            result = await extractor.extract(text)
            facts = result.get("facts", [])
            triples = result.get("triples", [])

            print(f"  [dry] {len(facts)} fact(s), {len(triples)} triple(s)")
            for f in facts[:5]:
                print(f"    fact: [{f['entity']}] {f['content']}")
            for t in triples[:5]:
                print(f"    triple: {t}")
        else:
            # Normal run: full batch extraction with writes
            effective_min = 0 if force else cfg.kg_extraction.min_messages
            result = await run_batch_extraction(
                persona_id=persona_id,
                sbs_data_dir=sbs_data_dir,
                llm_router=router,
                graph=graph,
                memory_db_path=memory_db_path,
                entities_json_path=ENTITIES_JSON,
                min_messages=effective_min,
                max_messages=limit if limit > 0 else 200,
                force=force,
            )
            if result.get("skipped"):
                print(
                    f"[{persona_id}] Skipped"
                    f" (pending: {result.get('pending', '?')},"
                    f" reason: {result.get('reason', 'threshold')})"
                )
            elif result.get("error"):
                print(f"[{persona_id}] Error: {result['error']}")
            else:
                print(
                    f"[{persona_id}] Extracted"
                    f" {result.get('extracted', 0)} triples,"
                    f" {result.get('facts', 0)} facts"
                )

    graph.close()


def process_documents(
    force: bool = False, limit: int = 200, dry_run: bool = False
) -> None:
    """Backward-compatible entry point (wraps the async extraction)."""
    asyncio.run(_run_extraction(force=force, limit=limit, dry_run=dry_run))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Conversation-based KG extractor — uses configured LLM router"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore min_messages threshold (process all pending messages)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        metavar="N",
        help="Cap at N messages (default: 200)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract but do not write to any DB or JSON",
    )
    args = parser.parse_args()
    process_documents(force=args.force, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
