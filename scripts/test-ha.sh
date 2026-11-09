#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON:-${ROOT}/.venv/bin/python}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python environment not found: ${PYTHON_BIN}" >&2
  echo "Create .venv and install requirements_test.txt first." >&2
  exit 1
fi

cd "${ROOT}"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH="${ROOT}/homeassistant${PYTHONPATH:+:${PYTHONPATH}}"

if [[ "$#" -eq 0 ]]; then
  set -- tests
fi

exec "${PYTHON_BIN}" -m pytest -p pytest_homeassistant.bootstrap -p pytest_asyncio.plugin -p pytest_socket "$@"
