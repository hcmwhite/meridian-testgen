# Rainbow Keys

A toy program: a small keyboard synthesizer that plays pentatonic notes and
shows colored key highlights as you hold A S D F G / J K L ; '. It exists in
this repository **as the target application for the Meridian experiment** —
the system under test that Meridian's pipeline parsed, mapped, and generated
test suites for (see the repository README and `../results/`). It is not a
product and is not maintained beyond what the experiment needed.

What matters for the experiment:

- `python/` — the code under test: `audio_logic.py`, `bridge_server.py`,
  `key_mapping.py`, `tui.py` (202 statements total, 11 testable functions).
  All published coverage numbers are measured against these four files.
- `Requirements.md` — the prose requirements document fed to
  `meridian-mapper`; the requirement numbering in the generated tests
  (`results/runs/*/tests/test_req_*.py`) traces back to its sections.
- `Package.swift`, `Sources/` — a Swift menu-bar shell around the Python
  core. Not exercised by the experiment; included because it's part of the
  real app.

To run it directly (text mode, needs `numpy` and `sounddevice`):

```sh
cd python && pip install -r requirements.txt && python tui.py
```

Licensed MIT, same as the rest of the repository — see [LICENSE](LICENSE).
