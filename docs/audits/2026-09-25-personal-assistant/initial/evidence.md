# Synapse memory/personality evidence audit

Date: 2026-09-25

Checkout: `main`, clean at start (`main...origin/main`).

Audit scope: user identity, dynamic recall, prompt/personality behavior, and acceptance evidence.

## Verification run

Python 3.13 and global pytest 9.0.2 are available; no repository `.venv` exists. `pyproject.toml` declares pytest only in the `dev` extra. `git ls-files` found no conventional pytest test modules; tracked candidates are the three eval scripts below, `workspace/scripts/memory_test.py`, and `workspace/sci_fi_dashboard/model_parity/test_runner.py`.

Executed the three deterministic eval functions using isolated DB/profile roots below ignored `.tmp/synapse-audit` (no live provider, default home DB, or private corpus):

- `eval_personality_differentiation.run_eval`: PASS — distinct compiled prompts; both configured response styles appear.
- `eval_longitudinal_personality.run_eval`: PASS — all 3 compiled profiles differ; each has only its expected style marker.
- `eval_proactive_memory_canary.run_canary`: PASS — 20 scripted docs and 20 affect rows; 11 facts distilled; project/codename found; style/routine survives simulated restart; proactive decision true with memory evidence.

The fixture scripts are [eval_personality_differentiation.py](../../workspace/scripts/eval_personality_differentiation.py:53), [eval_longitudinal_personality.py](../../workspace/scripts/eval_longitudinal_personality.py:21), and [eval_proactive_memory_canary.py](../../workspace/scripts/eval_proactive_memory_canary.py:23). Their checks compile prompts or score a policy; they do not generate conversational responses, exercise channel turns, measure retrieval quality, compare against a baseline, or test user isolation.

Two focused, synthetic source-method probes also passed:

- A provider exception in `MemoryEngine.get_embedding` returns `(0.0, 0.0, 0.0)` rather than signaling failure. The caller then checks for `None` before querying the vector store. The deterministic probe printed `[WARN] Embedding generation failed: synthetic provider outage` and returned the zero vector. Source: [memory_engine.py](../../workspace/sci_fi_dashboard/memory_engine.py:161) and query handling at [memory_engine.py](../../workspace/sci_fi_dashboard/memory_engine.py:252).
- The `casual_light` prompt policy sets `memory_limit=0` and disables graph context. Formatting kept the permanent profile and affect hint, while dropping the fixture's dynamic episodic result and graph relation. Source: [chat_pipeline.py](../../workspace/sci_fi_dashboard/chat_pipeline.py:844) and [chat_pipeline.py](../../workspace/sci_fi_dashboard/chat_pipeline.py:265).

The isolated probes extract the checked-in pure methods because importing the full memory engine fails in this environment: `ModuleNotFoundError: No module named 'pyarrow'`. No packages were installed.

## Acceptance gaps supported by checked-in evidence

- The affect-memory design calls for real conversational evaluation, including factual, emotional, and mixed prompts with specificity/tone/hallucination/continuity comparisons, but explicitly lists this as follow-up work: [affect-aware-memory-design.md](../../docs/superpowers/specs/2026-04-27-affect-aware-memory-design.md:298) and [affect-aware-memory-design.md](../../docs/superpowers/specs/2026-04-27-affect-aware-memory-design.md:323).
- Existing personality evals assert prompt markers and prompt inequality. They do not assert that a same prompt produces short, socially appropriate responses; the compiled communication block defaults average message length to 15 words at [compiler.py](../../workspace/sci_fi_dashboard/sbs/injection/compiler.py:200).
- The chat pipeline's permanent profile SQL selects relationship and distillation documents by filename with no user predicate: [chat_pipeline.py](../../workspace/sci_fi_dashboard/chat_pipeline.py:2050). This is a cross-user isolation risk if the configured DB contains multiple users; this audit did not run a live or private-data cross-user test.
- The vector retrieval API takes query text, limits, hemisphere, and seed entities, but no user/session ID; vector filtering shown in [memory_engine.py](../../workspace/sci_fi_dashboard/memory_engine.py:188) and [memory_engine.py](../../workspace/sci_fi_dashboard/memory_engine.py:268) is hemisphere-only. A cross-user leak is conditional on shared vector-store contents/configuration; no private corpus was queried.
- Current data can carry timestamps at channel boundaries (for example [whatsapp.py](../../workspace/sci_fi_dashboard/channels/whatsapp.py:660) and [telegram.py](../../workspace/sci_fi_dashboard/channels/telegram.py:600)), while `/new` ingestion creates a current batch date at [session_ingest.py](../../workspace/sci_fi_dashboard/session_ingest.py:355). Acceptance tests do not verify preserving per-turn emotional state or original timing across ingestion/retrieval.

## Tooling and repo notes

- Graph MCP tools were not available. The offline CLI fallback could not find cached `code-review-graph`; no installation or rebuild attempted.
- MemPalace search CLI was unavailable (`The system cannot find the path specified`).
- Root and workspace `tasks/lessons.md` files are absent.
- `.tmp/synapse-audit` is ignored by Git; all temporary eval DBs self-cleaned and no source files were edited.
