# Test-generation run — rainbow_keys — RAW codex

- **Date/time:** 2026-08-24 21:47 PDT (2026-08-25T04:47:58+00:00 UTC)
- **System under test:** rainbow_keys (`<REPO_ROOT>/rainbow_keys`)
- **LLM:** RAW (un-orchestrated) `codex`, model `codex CLI default`
- **Validation interpreter:** `<REPO_ROOT>/rainbow_keys/.venv/bin/python`
- **Note:** single naive prompt, no Meridian structure; agent had write access to a fresh copy at `/var/folders/s3/yj7knz911m13_1p7qz17c_km0000gn/T/raw_codex_rainbow_keys_jkwlodfd`

## Results — runtime verdicts

- Tests created (total): **14** in 4 file(s), 245 lines of test code
- **Valid tests: 11** (11 pass; 0 are valid failures)
- Invalid tests: 4
- Files that crashed or hung: 0
- Tokens out: 5916 visible + 1463 reasoning = 7379 billed (extracted from the saved agent_output.json turn.completed event); reported cost: not reported (Codex discloses no dollar figure)

### Valid failures discovered (candidate findings)

- (none)

### Invalid tests

- `test_audio_logic.py::test_note_down_and_up_emit_sounding_state_changes` — TypeError: list.append() takes exactly one argument (2 given)engine = (<audio_logic.NoteEngine object at 0x108de0690>, [])
- `test_audio_logic.py::test_fourth_held_key_waits_then_starts_in_fifo_order` — TypeError: list.append() takes exactly one argument (2 given)engine = (<audio_logic.NoteEngine object at 0x108de07d0>, [])
- `test_audio_logic.py::test_releasing_a_pending_key_prevents_it_from_starting` — TypeError: list.append() takes exactly one argument (2 given)engine = (<audio_logic.NoteEngine object at 0x10968b490>, [])
- `test_audio_logic.py::test_audio_callback_mixes_active_voice_and_removes_finished_release` — TypeError: list.append() takes exactly one argument (2 given)engine = (<audio_logic.NoteEngine object at 0x10977c2b0>, [])

## Reproduce

```sh
scripts/raw_baseline.py --codebase <REPO_ROOT>/rainbow_keys --backend codex --python <REPO_ROOT>/rainbow_keys/.venv/bin/python
```

## Invalid tests caught by Meridian during generation

- (not applicable — RAW runs bypass Meridian entirely)
