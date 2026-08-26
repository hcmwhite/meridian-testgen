# Test-generation run — rainbow_keys — codex_cli

- **Date/time:** 2026-08-24 22:19 PDT (2026-08-25T05:19:02+00:00 UTC)
- **System under test:** rainbow_keys (`/private/tmp/rainbow_keys_codex2_comparison`)
- **LLM:** backend `codex_cli`, model `backend default (unrecorded)`
- **Tool:** meridian-testgen 0.1.0
- **Validation interpreter:** `<REPO_ROOT>/rainbow_keys/.venv/bin/python` (resolved from argument)
- **Note:** Second Meridian/Codex leg, run to capture token counts after the accumulator fix; same snapshot mapping artifacts, fresh copy at /private/tmp/rainbow_keys_codex2_comparison, safety profile active. Tokens-out excludes reasoning tokens (accumulator counts visible output only).

## Results — runtime verdicts

- **Valid tests generated: 49** of 64 executed (47 pass; 2 are valid failures)
- Invalid tests that escaped to runtime: 15 (died on a non-assertion exception — defective test, not a finding)
- Files that crashed or hung: 0

*A failure on `AssertionError` means the test ran validly and disagreed with the code — a candidate finding pending human triage. Any other exception means the test itself is wrong.*

### Valid failures discovered (candidate findings)

- `test_req_1.py::test_key_order_returns_playable_keys_left_to_right` — AssertionError: assert ('a', 's', 'd...'g', 'j', ...) == ('a', 's', 'd...'g', 'j', ...)
- `test_req_2.py::test_main_draws_callback_state_and_quits_from_ready_input` — AssertionError: assert [set()] == [set(), {'C'}, set()]

### Invalid tests that escaped to runtime

- `test_req_1.py::test_key_down_starts_a_voice_and_emits_note_on` — TypeError: list.append() takes exactly one argument (2 given)def test_key_down_starts_a_voice_and_emits_note_on():
- `test_req_1.py::test_key_down_starts_first_note_and_emits_active_state` — TypeError: list.append() takes exactly one argument (2 given)def test_key_down_starts_first_note_and_emits_active_state():
- `test_req_1.py::test_key_down_ignores_duplicate_active_key` — TypeError: list.append() takes exactly one argument (2 given)def test_key_down_ignores_duplicate_active_key():
- `test_req_1.py::test_key_down_queues_fourth_note_then_starts_it_when_slot_frees` — TypeError: list.append() takes exactly one argument (2 given)def test_key_down_queues_fourth_note_then_starts_it_when_slot_frees():
- `test_req_1.py::test_key_down_creates_voice_and_emits_note_on_synchronously` — TypeError: list.append() takes exactly one argument (2 given)def test_key_down_creates_voice_and_emits_note_on_synchronously():
- `test_req_1.py::test_frequency_for_key_returns_expected_float_for_representative_key` — KeyError: 'A'def test_frequency_for_key_returns_expected_float_for_representative_key():
- `test_req_1.py::test_frequency_for_key_maps_playable_keys_in_ascending_pentatonic_order` — KeyError: 'A'def test_frequency_for_key_maps_playable_keys_in_ascending_pentatonic_order():
- `test_req_2.py::test_key_down_starts_once_emits_highlight_and_returns_none` — TypeError: list.append() takes exactly one argument (2 given)def test_key_down_starts_once_emits_highlight_and_returns_none():
- `test_req_2.py::test_key_down_waiting_for_polyphony_does_not_emit_highlight_until_started` — TypeError: list.append() takes exactly one argument (2 given)def test_key_down_waiting_for_polyphony_does_not_emit_highlight_until_started()
- `test_req_2.py::test_key_up_active_key_stops_and_promotes_pending_key_with_highlight_events` — TypeError: NoteEngine.__init__() got an unexpected keyword argument 'polyphony'def test_key_up_active_key_stops_and_promotes_pending_key_wit
- `test_req_2.py::test_key_up_pending_key_removes_it_without_emitting_highlight_event` — TypeError: NoteEngine.__init__() got an unexpected keyword argument 'polyphony'def test_key_up_pending_key_removes_it_without_emitting_highl
- `test_req_2.py::test_key_up_empty_state_is_a_noop_and_many_pending_keys_promote_in_order` — TypeError: NoteEngine.__init__() got an unexpected keyword argument 'polyphony'def test_key_up_empty_state_is_a_noop_and_many_pending_keys_p
- `test_req_2.py::test_main_draws_initial_key_display_and_releases_timed_out_key` — StopIterationmonkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x109204770>
- `test_req_3.py::test_req_3` — collection failureImportError while importing test module '/private/tmp/rainbow_keys_codex2_comparison/test/test_req_3.py'.
- `test_req_4.py::test_key_down_maps_a_raw_key_to_a_voice_and_ignores_duplicates` — TypeError: list.append() takes exactly one argument (2 given)def test_key_down_maps_a_raw_key_to_a_voice_and_ignores_duplicates():

### Quarantined

14 wholly-invalid test function(s) were marked `@pytest.mark.skip` in place, each with its failure as the reason — the delivered suite executes only valid tests. Remove a decorator to reinstate one:

- `test_req_1.py::test_key_down_starts_a_voice_and_emits_note_on`
- `test_req_1.py::test_key_down_starts_first_note_and_emits_active_state`
- `test_req_1.py::test_key_down_ignores_duplicate_active_key`
- `test_req_1.py::test_key_down_queues_fourth_note_then_starts_it_when_slot_frees`
- `test_req_1.py::test_key_down_creates_voice_and_emits_note_on_synchronously`
- `test_req_1.py::test_frequency_for_key_returns_expected_float_for_representative_key`
- `test_req_1.py::test_frequency_for_key_maps_playable_keys_in_ascending_pentatonic_order`
- `test_req_2.py::test_key_down_starts_once_emits_highlight_and_returns_none`
- `test_req_2.py::test_key_down_waiting_for_polyphony_does_not_emit_highlight_until_started`
- `test_req_2.py::test_key_up_active_key_stops_and_promotes_pending_key_with_highlight_events`
- `test_req_2.py::test_key_up_pending_key_removes_it_without_emitting_highlight_event`
- `test_req_2.py::test_key_up_empty_state_is_a_noop_and_many_pending_keys_promote_in_order`
- `test_req_2.py::test_main_draws_initial_key_display_and_releases_timed_out_key`
- `test_req_4.py::test_key_down_maps_a_raw_key_to_a_voice_and_ignores_duplicates`

## Invalid tests caught by Meridian during generation

- **0 rejected attempt(s)**, each retried with the reason in the prompt — every attempt validated first time

## Generation counts

- Items (function–requirement pairs + structural): 26
- Items that produced a mechanically valid test: 26
- **Test functions generated: 58** across 5 files
- Retries used: 0; exhausted: 0; skipped as category_leak: 0
- LLM calls: 26; reported cost: $0.0000 (920971 in / 32929 out tokens; zeros mean the backend reports no usage)

## Reproduce

```sh
meridian-parser <REPO_ROOT>/rainbow_keys --out results/rainbow_keys/ast.json   # meridian-parser 0.2.0, codebase commit 44e622551ef8f0a9c031707faf111a6a98d7263c
meridian-mapper results/rainbow_keys/ast.json <REPO_ROOT>/rainbow_keys/SampleRequirements.md <REPO_ROOT>/rainbow_keys --out results/rainbow_keys_snapshot_20260824_pre_safety/mapping_ast.json   # meridian-mapper 0.1.0
meridian-testgen results/rainbow_keys_snapshot_20260824_pre_safety/mapping_ast.json results/rainbow_keys_snapshot_20260824_pre_safety/mapping_requirements.json /private/tmp/rainbow_keys_codex2_comparison --python <REPO_ROOT>/rainbow_keys/.venv/bin/python --out-dir results/rainbow_keys_codex2_safety_comparison --backend codex_cli --llm-timeout 600 --prompt-debug
```

## Snapshot

Generated test files copied into `tests/` beside this report:

- `test_req_1.py`
- `test_req_2.py`
- `test_req_3.py`
- `test_req_4.py`
- `test_structural.py`
- `conftest.py`
