"""Written by meridian-testgen so its generated tests can import the
code under test. Yours to edit; recreated only if absent."""
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
for _extra in [_root] + [_root / d for d in ['python']]:
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))
