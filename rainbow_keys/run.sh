#!/bin/bash
# Build and launch Rainbow Keys. Creates the Python venv on first run.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python3 ]; then
    echo "Setting up Python venv..."
    python3 -m venv .venv
    .venv/bin/pip install -q -r python/requirements.txt
fi

swift build

# The app spawns `env python3` for the logic layer, so the venv must be
# on PATH before launch.
source .venv/bin/activate
exec ./.build/debug/RainbowKeys
