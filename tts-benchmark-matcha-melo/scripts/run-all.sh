#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export HTTP_PROXY=http://127.0.0.1:7897
export HTTPS_PROXY=http://127.0.0.1:7897
export ALL_PROXY=http://127.0.0.1:7897
PYTHON="${PYTHON:-python3}"
for engine in matcha melo; do
  for threads in 1 2 4; do
    OMP_NUM_THREADS="$threads" OPENBLAS_NUM_THREADS="$threads" MKL_NUM_THREADS="$threads" \
      "$PYTHON" "$ROOT/scripts/benchmark.py" \
      --engine "$engine" --threads "$threads" \
      --model-root "$ROOT/models" --output-dir "$ROOT/results"
  done
done
