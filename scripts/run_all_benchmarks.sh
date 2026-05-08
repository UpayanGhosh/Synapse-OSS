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

if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="$PYTHON"
elif [[ -x "$REPO_ROOT/.venv/Scripts/python.exe" ]]; then
  PYTHON_BIN="$REPO_ROOT/.venv/Scripts/python.exe"
elif [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "[run] ERROR: Python not found. Create a venv at .venv or set PYTHON=/path/to/python." >&2
  exit 127
fi

echo "[run] Logging combined output to $LOG"
echo "[run] $(date -u +%FT%TZ) starting all benchmarks" | tee "$LOG"
echo "[run] Python: $PYTHON_BIN" | tee -a "$LOG"

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
step "Storage footprint" "$PYTHON_BIN" scripts/bench_storage.py

# 2. KG memory comparison — needs `pip install networkx`.
step "KG memory (NetworkX vs SQLite)" "$PYTHON_BIN" scripts/bench_kg_memory.py

# 3. Retrieval latency — needs Synapse deps + populated DBs.
step "Retrieval latency (P50/P95/P99)" "$PYTHON_BIN" scripts/bench_retrieval_latency.py

# 4. Retrieval quality: labeled sentinel memories with Hit@K/MRR.
step "Retrieval quality (Hit@K/MRR)" "$PYTHON_BIN" scripts/bench_retrieval_quality.py

# 5. Memory write durability: documents + timestamps + vectors + affect rows.
step "Memory write persistence" "$PYTHON_BIN" scripts/bench_memory_write_persistence.py

# 6. KG query/integrity: indexed lookup latency + hygiene counters.
step "KG query integrity" "$PYTHON_BIN" scripts/bench_kg_query_integrity.py

# 7. Embedding throughput: provider docs/sec + vector health.
step "Embedding throughput" "$PYTHON_BIN" scripts/bench_embedding_throughput.py

# 8. Burst load test: already in the test suite.
if [[ "$PYTHON_BIN" == *.exe && -d /mnt/c/tmp ]]; then
  BENCH_PYTEST_TMP="${BENCH_PYTEST_TMP:-/mnt/c/tmp/synapse-bench-pytest-$DATE}"
  BENCH_PYCACHE="${BENCH_PYCACHE:-/mnt/c/tmp/synapse-bench-pycache-$DATE}"
else
  BENCH_PYTEST_TMP="${BENCH_PYTEST_TMP:-$REPO_ROOT/.codex-bench-pytest-$DATE}"
  BENCH_PYCACHE="${BENCH_PYCACHE:-$REPO_ROOT/.codex-bench-pycache-$DATE}"
fi
mkdir -p "$BENCH_PYTEST_TMP" "$BENCH_PYCACHE"
PY_REPO_ROOT="$REPO_ROOT"
PY_BENCH_PYTEST_TMP="$BENCH_PYTEST_TMP"
PY_BENCH_PYCACHE="$BENCH_PYCACHE"
if [[ "$PYTHON_BIN" == *.exe && -n "$(command -v wslpath || true)" ]]; then
  PY_REPO_ROOT="$(wslpath -w "$REPO_ROOT")"
  PY_BENCH_PYTEST_TMP="$(wslpath -w "$BENCH_PYTEST_TMP")"
  PY_BENCH_PYCACHE="$(wslpath -w "$BENCH_PYCACHE")"
fi
step "Burst load suite" env \
  TEMP="$PY_BENCH_PYTEST_TMP" \
  TMP="$PY_BENCH_PYTEST_TMP" \
  PYTHONPYCACHEPREFIX="$PY_BENCH_PYCACHE" \
  PYTHONUTF8=1 \
  PYTHONIOENCODING=utf-8 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PY_REPO_ROOT/workspace" \
  "$PYTHON_BIN" -m pytest "$PY_REPO_ROOT/workspace/tests/load" -m load --run-slow -v --durations=10 \
    --basetemp "$PY_BENCH_PYTEST_TMP/base" \
    -o "cache_dir=$PY_BENCH_PYTEST_TMP/cache"

echo "" | tee -a "$LOG"
echo "[run] $(date -u +%FT%TZ) all benchmarks finished" | tee -a "$LOG"
echo "[run] Outputs in docs/benchmarks/" | tee -a "$LOG"
ls -la docs/benchmarks/ | tee -a "$LOG"
