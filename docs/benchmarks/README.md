# Benchmarks

Reproducible measurements that back the quantitative claims in the README and the resume.

Each benchmark writes a dated JSON artifact under this directory. Resume claims should cite the **file path of the artifact** (not just the number) so a reviewer can clone the repo and reproduce.

## Running everything

```bash
bash scripts/run_all_benchmarks.sh
```

Combined log lands at `docs/benchmarks/run-{timestamp}.log`. Per-benchmark JSON artifacts land at `docs/benchmarks/{name}-{date}.json`.

## Individual benchmarks

| Script | Measures | Artifact | Prerequisites |
|---|---|---|---|
| `scripts/bench_storage.py` | On-disk size of `~/.synapse/` (per-store breakdown) | `storage-{date}.json` | None beyond Python stdlib |
| `scripts/bench_kg_memory.py` | NetworkX in-memory KG vs SQLite SPO peak memory (`tracemalloc`) | `kg-memory-{date}.json` | `pip install networkx` + populated `knowledge_graph.db` |
| `scripts/bench_retrieval_latency.py` | `MemoryEngine.query()` P50/P95/P99 over N queries | `retrieval-latency-{date}.json` | Synapse deps installed + `~/.synapse/` ingested |
| `pytest -m load --run-slow` (in `workspace/`) | Async pipeline burst delivery rate (500 concurrent senders) | Captured in `run-{date}.log` | Test deps installed |

## Resume citation pattern

Once you have an artifact, cite it like this in interview discussion:

> *"Retrieval P95 = 280 ms over 200 queries against my live corpus — full
> output at `docs/benchmarks/retrieval-latency-2026-05-04.json`,
> regeneration script at `scripts/bench_retrieval_latency.py`."*

This is the strongest answer to *"how do you know that number?"* — the
artifact pins the claim and the script makes it reproducible.

## Adding a benchmark

Conventions:

1. Script lives in `scripts/bench_*.py` (or `bench_*.sh`).
2. Top-of-file docstring states: what it measures, prerequisites, usage, output path.
3. Output is a JSON file with at minimum:
   - `benchmark` (string ID)
   - `ran_at_utc` (ISO 8601)
   - The measured numbers
   - `notes` (string explaining how to reproduce)
4. Default output path is `docs/benchmarks/{name}-{YYYY-MM-DD}.json`.
5. `--out` flag overrides the path.
6. Failures should print to stderr with a clear actionable message and a non-zero exit code.

Once added, hook it into `scripts/run_all_benchmarks.sh` so it runs as part of the sweep.
