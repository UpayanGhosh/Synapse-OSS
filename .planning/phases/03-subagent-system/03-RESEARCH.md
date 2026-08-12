# Phase 03: Subagent System — Research

**Researched:** 2026-04-07
**Status:** RESEARCH COMPLETE
**Confidence:** HIGH

---

## Key Findings

- **No new dependencies needed.** The entire subagent system is built from stdlib asyncio + existing FastAPI/ChannelRegistry patterns already in the codebase. `SubagentRegistry` mirrors `ChannelRegistry`; `_run_agent()` mirrors `gateway/worker.py _handle_task()`.

- **`asyncio.TaskGroup` is the wrong primitive for AGENT-02.** TaskGroup cancels all sibling tasks when one fails — exactly the opposite of the isolation requirement. Use independent `asyncio.create_task()` calls per agent, each with their own `try/except` boundary inside `_run_agent()`.

- **GC anchor is mandatory.** `asyncio.create_task()` without storing the returned Task in a `set` risks silent task destruction mid-run. The `_background_tasks: set` pattern in `pipeline_helpers.py` (lines 232-235) must be replicated in `SubagentRegistry._task_refs`.

- **Read-only memory isolation via snapshot, not enforcement.** Sub-agents get `context_snapshot: list[dict]` (a frozen copy of recent history) and `memory_snapshot: list[dict]` (pre-queried results). They never receive the live `MemoryEngine` singleton reference — this prevents accidental writes at the API contract level.

- **asyncio.shield() in `finally:` protects SQLite WAL cleanup.** When a sub-agent times out or is cancelled, the `finally:` block must call `registry.archive(record)` — which is sync-only (no await, just dict manipulation). No `asyncio.shield()` is needed for the archive itself, but if any future cleanup requires `await` (e.g., writing a result summary to memory), shield it.

- **Result delivery reuses existing `channel_registry.get(channel_id).send()` path.** No new message bus needed — the sub-agent simply calls the same channel adapter the parent conversation used.

---

## Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Standard Stack | HIGH | All stdlib; patterns verified in codebase |
| Architecture | HIGH | Direct mirror of existing registry + worker patterns |
| Pitfalls | HIGH | asyncio docs + SQLAlchemy GitHub issues + codebase verification |
| Integration Points | HIGH | Exact file locations confirmed by reading codebase |

---

## Open Questions

1. **Spawn intent detection depth** — keyword gate vs. LLM classifier. Recommendation: keyword gate for Phase 3.
2. **Sub-agent LLM call depth** — full `persona_chat()` vs. direct `SynapseLLMRouter.call()`. Recommendation: planner discretion.
3. **Sub-agent memory write permission** — Phase 3 default: read-only snapshots. Write permission deferred to enhancement.

---

## Validation Architecture

### Test Strategy
- **Unit:** SubAgent dataclass creation, AgentRegistry CRUD, state transitions
- **Integration:** Spawn → execute → deliver result via channel send path
- **Timing:** Two parallel agents must complete in ~max(t1, t2) not sum
- **Crash isolation:** Agent exception must not propagate to parent conversation
- **Progress:** Agent running >30s must emit progress callback at configured interval
- **API:** `GET /agents` returns correct status, timing, and description fields

### Key Invariants
- Sub-agent never holds a reference to live MemoryEngine
- `_task_refs` set always contains all running agent Tasks (GC anchor)
- Archive record written in `finally:` block regardless of success/failure/timeout
- Channel send path is the same adapter the parent used (no new bus)

---

*Phase: 03-subagent-system*
*Research completed: 2026-04-07*
