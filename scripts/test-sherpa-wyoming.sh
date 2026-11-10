#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT_DIR/.venv-sherpa/bin/python}"

if [[ ! -x "$PYTHON" ]]; then
  echo "Python 3.11 test environment not found: $PYTHON" >&2
  echo "Create it with uv using Python 3.11 and install services/sherpa_wyoming/requirements-dev.txt." >&2
  exit 1
fi

"$PYTHON" -c 'import sys; assert sys.version_info[:2] == (3, 11), sys.version'
cd "$ROOT_DIR"
if [[ $# -eq 0 || "$1" == -* ]]; then
  set -- tests/services/sherpa_wyoming "$@"
fi
exec "$PYTHON" -m pytest -c /dev/null -p no:cacheprovider "$@"
