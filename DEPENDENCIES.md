# Dependency Map — Synapse-OSS

## Impact Analysis: "If I edit X, what else might break?"

### TIER 1: HIGH IMPACT (edit carefully, ripple effects)
```
synapse_config.py ──> imported by 50+ files (root config authority)
api_gateway.py ──> central hub, imports ALL subsystems, ~1200 lines
db.py ──> memory_engine, ingest, retriever, scripts/*, purge_trash
memory_engine.py ──> api_gateway (RAG orchestrator, affects search quality)
llm_router.py ──> api_gateway (all LLM calls route through here)
```

### TIER 2: SUBSYSTEM IMPACT (affects own subsystem)
```
sbs/orchestrator.py ──> coordinates: logger, realtime, batch, compiler, feedback, profile
gateway/worker.py ──> imports: queue.py, sender.py, channels/registry.py
channels/registry.py ──> imports all channel implementations
sbs/processing/batch.py ──> imports: profile/manager, selectors/exemplar
retriever.py ──> used by: memory_engine, ingest
```

### TIER 3: ISOLATED (safe to edit independently)
```
dual_cognition.py ──> self-contained, no internal imports
gateway/flood.py ──> self-contained
gateway/dedup.py ──> self-contained
gateway/queue.py ──> self-contained (only dataclasses + asyncio)
narrative.py ──> self-contained (only random)
conflict_resolver.py ──> self-contained (only json, os, time, uuid)
emotional_trajectory.py ──> self-contained (only os, sqlite3, time)
channels/whatsapp.py ──> only imports base.py
channels/telegram.py ──> only imports base.py
channels/discord_channel.py ──> only imports base.py
channels/slack.py ──> only imports base.py
sbs/profile/manager.py ──> standalone JSON CRUD
sbs/sentinel/* ──> internal to sentinel subsystem only
sbs/vacuum.py ──> standalone cleanup utility
```

## Internal Import Graph (simplified)

```
synapse_config.py
    |
    v
utils/env_loader.py <── main.py, config.py, cli/*, do_transcribe.py

synapse_config.py
    |
    +---> db.py ---> memory_engine.py ---> api_gateway.py
    |                    |
    +---> sqlite_graph.py                  api_gateway.py imports:
    |                                        - db, memory_engine, llm_router
    +---> llm_router.py ------------------>  - retriever, dual_cognition
    |                                        - sqlite_graph, sbs/orchestrator
    +---> persona.py                         - channels/registry
    |                                        - gateway/* (flood, dedup, queue, worker)
    +---> ingest.py <-- retriever.py         - conflict_resolver, build_persona

sbs/orchestrator.py
    |
    +---> ingestion/logger.py <-- ingestion/schema.py
    +---> processing/realtime.py <-- ingestion/schema.py, profile/manager.py
    +---> processing/batch.py <-- profile/manager.py, selectors/exemplar.py
    +---> injection/compiler.py <-- profile/manager.py
    +---> feedback/implicit.py <-- profile/manager.py

gateway/worker.py
    |
    +---> gateway/queue.py (MessageTask, TaskQueue)
    +---> gateway/sender.py (WhatsAppSender)
    +---> channels/registry.py (lazy import)

channels/registry.py
    |
    +---> channels/base.py
    +---> channels/stub.py, whatsapp.py, telegram.py, discord_channel.py, slack.py
```

## Circular Import Prevention
- `ChannelRegistry` is lazy-imported in `gateway/worker.py`
- `LanceDBVectorStore` is conditionally imported in `memory_engine.py`
- `SynapseConfig` imported at function level in `db.py`, `sqlite_graph.py`
