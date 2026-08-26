#!/bin/bash
# CI contract: exits 0 only if the Swift package builds and the Python
# logic layer compiles and passes its mapping invariants.
set -euo pipefail
cd "$(dirname "$0")/.."

swift build

PY=python3
[ -x "$PWD/.venv/bin/python3" ] && PY="$PWD/.venv/bin/python3"
"$PY" -m py_compile python/key_mapping.py python/audio_logic.py python/bridge_server.py

cd python
"$PY" -c "
import key_mapping as km
keys = km.key_order()
assert len(keys) == 10
freqs = [km.frequency_for_key(k) for k in keys]
assert freqs == sorted(freqs)
assert all(freqs[i+5] == freqs[i]*2 for i in range(5))
assert len(km.all_colors()) == 10
"
