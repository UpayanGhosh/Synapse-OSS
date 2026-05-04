#!/usr/bin/env bash
# Run all resume-grade benchmarks in sequence.
#
# Each script writes a dated JSON artifact under docs/benchmarks/.
# Resume claims should cite these artifacts (file paths) so an interviewer
# can clone and reproduce.
#
# Run from the repo root:
#     bash scripts/run_all_benchmarks.sh
#
# To run individual benchmarks see the headers of:
#     scripts/bench_retrieval_latency.py
#     scripts/bench_kg_memory.py
#     scripts/bench_storage.py

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p docs/benchmarks

DATE="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
LOG="docs/benchmarks/run-${DATE}.log"

echo "[run] Logging combined output to $LOG"
echo "[run] $(date -u +%FT%TZ) starting all benchmarks" | tee "$LOG"

step() {
  local name="$1"; shift
  echo "" | tee -a "$LOG"
  echo "===== $name =====" | tee -a "$LOG"
  if "$@" 2>&1 | tee -a "$LOG"; then
    echo "[run] $name: OK" | tee -a "$LOG"
  else
    echo "[run] $name: FAILED (continuing)" | tee -a "$LOG"
  fi
}

# 1. Storage footprint — fastest, no extra deps.
step "Storage footprint" python scripts/bench_storage.py

# 2. KG memory comparison — needs `pip install networkx`.
step "KG memory (NetworkX vs SQLite)" python scripts/bench_kg_memory.py

# 3. Retrieval latency — needs Synapse deps + populated DBs.
step "Retrieval latency (P50/P95/P99)" python scripts/bench_retrieval_latency.py

# 4. Burst load test — already in the test suite.
step "Burst load suite" bash -c "cd workspace && pytest -m load --run-slow -v --durations=10"

echo "" | tee -a "$LOG"
echo "[run] $(date -u +%FT%TZ) all benchmarks finished" | tee -a "$LOG"
echo "[run] Outputs in docs/benchmarks/" | tee -a "$LOG"
ls -la docs/benchmarks/ | tee -a "$LOG"
