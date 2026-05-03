# Local-only benchmark (placeholder — needs a real run)

This file documents the *target* benchmark methodology for the no-cloud profile
(`synapse.local-only.json`). The numbers below are placeholders until a real
benchmark run is executed; see Issue 6.1 in PRODUCT_ISSUES.md for the related
reranker eval.

## Setup
- Profile: `cp synapse.local-only.json ~/.synapse/synapse.json`
- Required local services: Ollama (port 11434), models pulled per `model_mappings`.
- Embedding: FastEmbed local ONNX (no external service).
- No internet egress should occur during the chat path.

## Methodology
1. Held-out conversation set: 50 turns from a synthetic personal-AI transcript
   (no real user data). Categories: casual, code, analysis, sensitive (vault).
2. Metrics:
   - Cold-start chat latency P50/P95
   - Memory retrieval P50/P95 (`MemoryEngine.query()`)
   - Response quality scored 1-5 by an LLM judge (Claude Sonnet) AND a
     human reviewer; report both.
   - Egress check: assert `tcpdump` or equivalent shows zero outbound
     packets to non-localhost during the run.
3. Compare against the cloud-default profile on the same transcript.

## Results
*Pending — run `python scripts/eval_local_only.py` (TODO: not yet built).*

| Metric | Cloud default | Local-only | Delta |
|---|---|---|---|
| Chat latency P50 | TBD | TBD | TBD |
| Chat latency P95 | TBD | TBD | TBD |
| Retrieval P95    | TBD | TBD | TBD |
| Quality (LLM judge) | TBD | TBD | TBD |

## Known regressions
- Long-context queries (>3k tokens) likely degrade more on llama3.2:3b than on Gemini Pro.
- Code-focused turns will be weaker without claude-sonnet — qwen2.5-coder:7b is the local stand-in.

## Done when
This page lists actual P50/P95 numbers from a recorded run, and the egress check
result is reproducible.
