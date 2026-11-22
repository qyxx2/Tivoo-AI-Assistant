#!/usr/bin/env bash
# Isolated B8.5 RED/GREEN verification; never modifies the source checkout or NAS.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${1:?Usage: test-terminal.sh /path/to/qwen-audio-agent-v2.1.0}"
REVISION=a9f4478da8df400d04facbb099ac2933ce8b11bc
SCRATCH="$(mktemp -d -t tivoo-qwen-b85-XXXXXXXX)"
trap 'rm -rf "$SCRATCH"' EXIT
mkdir -p "$SCRATCH/upstream" "$SCRATCH/deps"
git -C "$SOURCE" archive "$REVISION" | tar -x -C "$SCRATCH/upstream"
cd "$SCRATCH/upstream"
sha256sum --check --status "$HERE/terminal-source.sha256"
if [[ -n "${QWEN_B85_NODE_MODULES:-}" ]]; then
  ln -s "$(realpath "$QWEN_B85_NODE_MODULES")" node_modules
else
  cp "$HERE/test-runtime/package.json" "$HERE/test-runtime/package-lock.json" "$SCRATCH/deps/"
  npm ci --prefix "$SCRATCH/deps" --ignore-scripts --no-audit --no-fund
  ln -s "$SCRATCH/deps/node_modules" node_modules
fi
export QWEN_B85_SOURCE="$PWD"
if node --test "$HERE/tests/terminal-status.test.mjs" > "$SCRATCH/red.log" 2>&1; then
  cat "$SCRATCH/red.log"
  echo 'Expected unpatched terminal observability tests to fail.' >&2
  exit 1
fi
cat "$SCRATCH/red.log"
# Require assertion failures for missing semantics; setup/import failures are not RED.
if ! rg -q 'ERR_ASSERTION' "$SCRATCH/red.log" || rg -q 'ERR_MODULE_NOT_FOUND|SyntaxError' "$SCRATCH/red.log"; then
  echo 'RED failed for an unexpected setup reason.' >&2
  exit 1
fi
patch --batch --fuzz=0 -p1 < "$HERE/0002-response-terminal-status.patch"
node --test "$HERE/tests/terminal-status.test.mjs" \
  test/gateway-client-protocol.test.mjs \
  server/test/gateway-client-protocol-session.test.mjs \
  server/test/realtime-presentation-runtime.test.mjs \
  server/test/realtime-session-runtime.test.mjs
