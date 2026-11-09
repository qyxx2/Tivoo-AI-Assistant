#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
MODEL="$ROOT/sherpa-onnx-paraformer-zh-small-2024-03-09"
VENV="${TIVOO_STT_VENV:-/tmp/tivoo-stt-venv}"

# ARM Ubuntu device's local proxy; downloads must use this endpoint.
export HTTP_PROXY=http://127.0.0.1:7897
export HTTPS_PROXY=http://127.0.0.1:7897
export ALL_PROXY=http://127.0.0.1:7897

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --disable-pip-version-check sherpa-onnx==2.0.1 numpy

mkdir -p "$ROOT/arm-ubuntu/logs"
: > "$ROOT/arm-ubuntu/results.jsonl"
for threads in 1 2 4; do
  OMP_NUM_THREADS="$threads" OPENBLAS_NUM_THREADS="$threads" MKL_NUM_THREADS="$threads" \
    "$VENV/bin/python" "$ROOT/benchmark.py" \
      --model-dir "$MODEL" --threads "$threads" --repeat 5 \
      --output "$ROOT/arm-ubuntu/results.jsonl" \
      2>&1 | tee "$ROOT/arm-ubuntu/logs/threads_${threads}.log"
done
