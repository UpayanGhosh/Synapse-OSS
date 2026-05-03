#!/usr/bin/env bash
# Collect repo metrics for README auto-generation.
# Counts test functions, test files, and total Python files, then writes
# the result to docs/_generated/metrics.json with a UTC timestamp.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p docs/_generated

tests=$(grep -rh "^def test_\|^async def test_" workspace/tests/ | wc -l | tr -d ' ')
test_files=$(find workspace/tests -name "test_*.py" | wc -l | tr -d ' ')
py_files=$(find workspace -name "*.py" | wc -l | tr -d ' ')
generated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

cat > docs/_generated/metrics.json <<EOF
{"tests": ${tests}, "test_files": ${test_files}, "py_files": ${py_files}, "generated_at": "${generated_at}"}
EOF

echo "Wrote docs/_generated/metrics.json: tests=${tests} test_files=${test_files} py_files=${py_files} generated_at=${generated_at}"
