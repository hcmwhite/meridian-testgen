# Test-generation run — rainbow_keys — claude_cli

- **Date/time:** 2026-08-24 19:55 PDT (2026-08-25T02:55:36+00:00 UTC)
- **System under test:** rainbow_keys (`/private/tmp/rainbow_keys_claude_comparison`)
- **LLM:** backend `claude_cli`, model `claude-sonnet-4-5`
- **Tool:** meridian-testgen 0.1.0
- **Validation interpreter:** `<REPO_ROOT>/rainbow_keys/.venv/bin/python` (resolved from argument)
- **Note:** Claude-mode twin of the Codex comparison run: same snapshot mapping artifacts, fresh copy of the codebase at /private/tmp/rainbow_keys_claude_comparison, safety profile active (built-in default).

## Results — runtime verdicts

- **Valid tests generated: 88** of 155 executed (76 pass; 12 are valid failures)
- Invalid tests that escaped to runtime: 67 (died on a non-assertion exception — defective test, not a finding)
- Files that crashed or hung: 0

*A failure on `AssertionError` means the test ran validly and disagreed with the code — a candidate finding pending human triage. Any other exception means the test itself is wrong.*

### Valid failures discovered (candidate findings)

- `test_req_1.py::test_render_attack_envelope_ramps_up` — assert np.float32(0.0) > np.float32(0.0)def test_render_attack_envelope_ramps_up():
- `test_req_1.py::test_render_release_envelope_ramps_down` — assert np.float32(0.0) > np.float32(0.0)def test_render_release_envelope_ramps_down():
- `test_req_1.py::test_key_order_returns_expected_keys_in_left_to_right_order` — AssertionError: assert ('a', 's', 'd...'g', 'j', ...) == ('A', 'S', 'D...'G', 'J', ...)
- `test_req_2.py::test_main_timeout_loop_and_branch` — AssertionError: assert 0 >= 1
- `test_req_2.py::test_main_handles_key_press_and_highlights` — AssertionError: expected call not found.
- `test_req_2.py::test_main_does_not_trigger_key_down_if_already_pressed` — AssertionError: expected call not found.
- `test_req_3.py::test_main_releases_key_after_timeout` — AssertionError: Expected 'key_up' to have been called.def test_main_releases_key_after_timeout():
- `test_req_3.py::test_main_does_not_repeat_key_down_for_held_key` — AssertionError: expected call not found.
- `test_req_3.py::test_main_key_release_on_timeout` — AssertionError: assert call('KEY_A') in []
- `test_req_3.py::test_main_exits_on_q_restores_terminal_and_closes_engine` — AssertionError: expected call not found.
- `test_req_3.py::test_main_handles_valid_key_press` — AssertionError: expected call not found.
- `test_req_3.py::test_main_releases_key_on_timeout` — AssertionError: expected call not found.

### Invalid tests that escaped to runtime

- `test_req_1.py::test_note_off_returns_none` — TypeError: _Voice.__init__() missing 2 required positional arguments: 'key' and 'frequency_hz'def test_note_off_returns_none():
- `test_req_1.py::test_note_off_sets_releasing_since_to_current_sample_position` — TypeError: _Voice.__init__() missing 2 required positional arguments: 'key' and 'frequency_hz'def test_note_off_sets_releasing_since_to_curr
- `test_req_1.py::test_note_off_marks_release_phase_immediately` — TypeError: _Voice.__init__() missing 2 required positional arguments: 'key' and 'frequency_hz'def test_note_off_marks_release_phase_immediat
- `test_req_1.py::test_note_off_at_different_sample_positions` — TypeError: _Voice.__init__() missing 2 required positional arguments: 'key' and 'frequency_hz'def test_note_off_at_different_sample_position
- `test_req_1.py::test_key_down_creates_voice_and_emits_event` — KeyError: 'C4'def test_key_down_creates_voice_and_emits_event():
- `test_req_1.py::test_key_down_ignores_duplicate_when_pending` — KeyError: 'key0'def test_key_down_ignores_duplicate_when_pending():
- `test_req_1.py::test_key_down_adds_to_pending_when_at_voice_limit` — KeyError: 'key_0'def test_key_down_adds_to_pending_when_at_voice_limit():
- `test_req_1.py::test_key_down_with_empty_string` — KeyError: ''def test_key_down_with_empty_string():
- `test_req_1.py::test_key_down_with_single_char` — KeyError: 'x'def test_key_down_with_single_char():
- `test_req_1.py::test_key_down_with_multi_char_key` — KeyError: 'shift+c'def test_key_down_with_multi_char_key():
- `test_req_1.py::test_key_down_activates_note_when_under_limit` — KeyError: 'A'def test_key_down_activates_note_when_under_limit():
- `test_req_1.py::test_key_down_queues_when_at_max_simultaneous_notes` — KeyError: 'A'def test_key_down_queues_when_at_max_simultaneous_notes():
- `test_req_1.py::test_key_down_ignores_duplicate_when_already_active` — KeyError: 'A'def test_key_down_ignores_duplicate_when_already_active():
- `test_req_1.py::test_key_down_ignores_duplicate_when_already_pending` — KeyError: 'A'def test_key_down_ignores_duplicate_when_already_pending():
- `test_req_1.py::test_key_down_with_empty_string_key` — KeyError: ''def test_key_down_with_empty_string_key():
- `test_req_1.py::test_key_down_with_single_character_key` — KeyError: 'E'def test_key_down_with_single_character_key():
- `test_req_1.py::test_key_down_with_multiple_character_key` — KeyError: 'C#'def test_key_down_with_multiple_character_key():
- `test_req_1.py::test_key_down_ignores_duplicate_active_key` — KeyError: 'C4'def test_key_down_ignores_duplicate_active_key():
- `test_req_1.py::test_key_down_ignores_duplicate_pending_key` — KeyError: 'key_0'def test_key_down_ignores_duplicate_pending_key():
- `test_req_1.py::test_key_down_with_empty_sequence` — KeyError: 'A4'def test_key_down_with_empty_sequence():
- `test_req_1.py::test_key_down_with_one_element_sequence` — KeyError: 'C4'def test_key_down_with_one_element_sequence():
- `test_req_1.py::test_key_down_with_many_elements_sequence` — KeyError: 'key_0'def test_key_down_with_many_elements_sequence():
- `test_req_1.py::test_key_up_activates_pending_note` — KeyError: 'key_0'def test_key_up_activates_pending_note():
- `test_req_1.py::test_key_up_single_element_sequence` — KeyError: 'single'def test_key_up_single_element_sequence():
- `test_req_1.py::test_key_up_many_elements_sequence` — KeyError: 'b'def test_key_up_many_elements_sequence():
- `test_req_1.py::test_key_up_emit_loop_executed` — KeyError: 'key_0'def test_key_up_emit_loop_executed():
- `test_req_1.py::test_key_up_active_no_pending_empty_sequence` — KeyError: 'A'def test_key_up_active_no_pending_empty_sequence():
- `test_req_1.py::test_key_up_active_with_one_pending_one_element` — KeyError: 'A'def test_key_up_active_with_one_pending_one_element():
- `test_req_1.py::test_key_up_active_with_many_pending_many_elements` — KeyError: 'A'def test_key_up_active_with_many_pending_many_elements():
- `test_req_1.py::test_key_up_pending_key_removed_without_sounding` — KeyError: 'A'def test_key_up_pending_key_removed_without_sounding():
- `test_req_1.py::test_key_up_representative_key_value` — KeyError: 'C4'def test_key_up_representative_key_value():
- `test_req_1.py::test_key_up_active_note_calls_note_off` — KeyError: 'C4'def test_key_up_active_note_calls_note_off():
- `test_req_1.py::test_key_up_active_with_pending_activates_next` — KeyError: 'C4'def test_key_up_active_with_pending_activates_next():
- `test_req_1.py::test_key_up_pending_note_removes_without_sounding` — KeyError: 'C4'def test_key_up_pending_note_removes_without_sounding():
- `test_req_1.py::test_key_up_single_active_note` — KeyError: 'A4'def test_key_up_single_active_note():
- `test_req_1.py::test_key_up_multiple_active_notes` — KeyError: 'C4'def test_key_up_multiple_active_notes():
- `test_req_1.py::test_key_up_unknown_key_does_nothing` — KeyError: 'C4'def test_key_up_unknown_key_does_nothing():
- `test_req_1.py::test_frequency_for_key_representative_valid_key` — KeyError: 'A'def test_frequency_for_key_representative_valid_key():
- `test_req_1.py::test_frequency_for_key_all_valid_keys_return_floats` — KeyError: 'A'def test_frequency_for_key_all_valid_keys_return_floats():
- `test_req_1.py::test_frequency_for_key_ascending_order_lower_octave` — KeyError: 'A'def test_frequency_for_key_ascending_order_lower_octave():
- `test_req_1.py::test_frequency_for_key_ascending_order_upper_octave` — KeyError: 'J'def test_frequency_for_key_ascending_order_upper_octave():
- `test_req_1.py::test_frequency_for_key_octave_relationship` — KeyError: 'A'def test_frequency_for_key_octave_relationship():
- `test_req_2.py::test_key_down_emits_event_when_active_empty` — KeyError: 'A'def test_key_down_emits_event_when_active_empty():
- `test_req_2.py::test_key_down_emits_event_when_active_has_one` — KeyError: 'A'def test_key_down_emits_event_when_active_has_one():
- `test_req_2.py::test_key_down_emits_event_when_active_has_many` — KeyError: 'KEY0'def test_key_down_emits_event_when_active_has_many():
- `test_req_2.py::test_key_down_no_event_when_polyphony_limit_reached` — KeyError: 'KEY0'def test_key_down_no_event_when_polyphony_limit_reached():
- `test_req_2.py::test_key_down_ignores_duplicate_in_active` — KeyError: 'D'def test_key_down_ignores_duplicate_in_active():
- `test_req_2.py::test_key_down_ignores_duplicate_in_pending` — KeyError: 'KEY0'def test_key_down_ignores_duplicate_in_pending():
- `test_req_2.py::test_key_up_active_with_pending` — KeyError: 'b'def test_key_up_active_with_pending():
- `test_req_2.py::test_main_releases_key_after_timeout` — StopIterationdef test_main_releases_key_after_timeout():
- `test_req_2.py::test_main_loops_until_quit` — StopIterationdef test_main_loops_until_quit():
- `test_req_4.py::test_render_representative_frame_count` — TypeError: _Voice.__init__() got an unexpected keyword argument 'note'def test_render_representative_frame_count():
- `test_req_4.py::test_render_zero_frames` — TypeError: _Voice.__init__() got an unexpected keyword argument 'note'def test_render_zero_frames():
- `test_req_4.py::test_render_one_frame` — TypeError: _Voice.__init__() got an unexpected keyword argument 'note'def test_render_one_frame():
- `test_req_4.py::test_render_many_frames` — TypeError: _Voice.__init__() got an unexpected keyword argument 'note'def test_render_many_frames():
- `test_req_4.py::test_render_with_release_active` — TypeError: _Voice.__init__() got an unexpected keyword argument 'note'def test_render_with_release_active():
- `test_req_4.py::test_render_release_completes` — TypeError: _Voice.__init__() got an unexpected keyword argument 'note'def test_render_release_completes():
- `test_req_4.py::test_key_down_representative_value` — KeyError: 'C4'def test_key_down_representative_value():
- `test_req_4.py::test_key_down_already_active` — KeyError: 'C4'def test_key_down_already_active():
- `test_req_4.py::test_key_down_already_pending` — KeyError: 'key_0'def test_key_down_already_pending():
- `test_req_4.py::test_key_down_within_voice_limit` — KeyError: 'C4'def test_key_down_within_voice_limit():
- `test_req_4.py::test_key_down_exceeds_voice_limit` — KeyError: 'key_0'def test_key_down_exceeds_voice_limit():
- `test_req_4.py::test_key_down_empty_state` — KeyError: 'C4'def test_key_down_empty_state():
- `test_req_4.py::test_key_down_one_element_state` — KeyError: 'C4'def test_key_down_one_element_state():
- `test_req_4.py::test_key_down_many_elements_state` — KeyError: 'key_0'def test_key_down_many_elements_state():
- `test_req_4.py::test_key_down_returns_none` — KeyError: 'C4'def test_key_down_returns_none():
- `test_req_4.py::test_key_down_emit_invoked` — KeyError: 'C4'def test_key_down_emit_invoked():

## Invalid tests caught by Meridian during generation

- **1 rejected attempt(s)**, each retried with the reason in the prompt
- missing: 1
  - python.audio_logic.NoteEngine.key_down / 1-3 — the model could not be reached: claude's answer is not the JSON object we asked for: ''

## Generation counts

- Items (function–requirement pairs + structural): 26
- Items that produced a mechanically valid test: 26
- **Test functions generated: 159** across 5 files
- Retries used: 1; exhausted: 0; skipped as category_leak: 0
- LLM calls: 27; reported cost: $3.6647 (2400 in / 141060 out tokens; zeros mean the backend reports no usage)

## Reproduce

```sh
meridian-parser <REPO_ROOT>/rainbow_keys --out results/rainbow_keys/ast.json   # meridian-parser 0.2.0, codebase commit 44e622551ef8f0a9c031707faf111a6a98d7263c
meridian-mapper results/rainbow_keys/ast.json <REPO_ROOT>/rainbow_keys/SampleRequirements.md <REPO_ROOT>/rainbow_keys --out results/rainbow_keys_snapshot_20260824_pre_safety/mapping_ast.json   # meridian-mapper 0.1.0
meridian-testgen results/rainbow_keys_snapshot_20260824_pre_safety/mapping_ast.json results/rainbow_keys_snapshot_20260824_pre_safety/mapping_requirements.json /private/tmp/rainbow_keys_claude_comparison --python <REPO_ROOT>/rainbow_keys/.venv/bin/python --out-dir results/rainbow_keys_claude_safety_comparison --llm-timeout 600 --prompt-debug
```

## Snapshot

Generated test files copied into `tests/` beside this report:

- `test_req_1.py`
- `test_req_2.py`
- `test_req_3.py`
- `test_req_4.py`
- `test_structural.py`
- `conftest.py`
