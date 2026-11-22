#!/usr/bin/env bash
# Run only local B8.3 tests against an immutable Qwen 2.1.0 checkout copy.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${1:?Usage: test.sh /path/to/qwen-audio-agent-v2.1.0}"
REVISION=a9f4478da8df400d04facbb099ac2933ce8b11bc
SCRATCH="$(mktemp -d -t tivoo-qwen-b83-XXXXXXXX)"
trap 'rm -rf "$SCRATCH"' EXIT
mkdir -p "$SCRATCH/upstream" "$SCRATCH/deps"
git -C "$SOURCE" archive "$REVISION" | tar -x -C "$SCRATCH/upstream"
cd "$SCRATCH/upstream"
printf '%s  %s\n' 361c6bd6afbd73aeb3519991227e7b2688b65004465788095545d3635d0965da server/src/frontend/tools/mcp/frontend-mcp-config.mjs | sha256sum --check --status
if [[ -n "${QWEN_B83_NODE_MODULES:-}" ]]; then
  ln -s "$(realpath "$QWEN_B83_NODE_MODULES")" node_modules
else
  cp "$HERE/test-runtime/package.json" "$HERE/test-runtime/package-lock.json" "$SCRATCH/deps/"
  npm ci --prefix "$SCRATCH/deps" --ignore-scripts --no-audit --no-fund
  ln -s "$SCRATCH/deps/node_modules" node_modules
fi
# Prove the new behavior is missing before applying the patch. No source checkout
# or installed NAS package is changed by either run.
if QWEN_B83_SOURCE="$PWD" node --test "$HERE/tests/private-http.test.mjs" > "$SCRATCH/red.log" 2>&1; then
  cat "$SCRATCH/red.log"
  echo 'Expected the unpatched RFC1918 policy tests to fail.' >&2
  exit 1
fi
cat "$SCRATCH/red.log"
patch --batch --fuzz=0 -p1 < "$HERE/0001-frontend-mcp-private-http.patch"
export QWEN_B83_SOURCE="$PWD"
node --test "$HERE/tests/private-http.test.mjs" \
  "$HERE/tests/mcp-integration.test.mjs" \
  server/test/frontend-mcp-config.test.mjs \
  server/test/frontend-mcp-client.test.mjs \
  server/test/tool-call-handler.test.mjs \
  server/test/realtime-presentation-runtime.test.mjs
