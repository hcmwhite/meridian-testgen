#!/usr/bin/env bash
# The CI contract for this repository: exits 0 only if everything passes.
set -euo pipefail

cd "$(dirname "$0")/.."

PY=python3
if [ -x .venv/bin/python ]; then
  PY=.venv/bin/python
fi

"$PY" -m pytest -q
