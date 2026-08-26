# Test-generation run — rainbow_keys — claude_cli

- **Date/time:** 2026-08-24 21:20 PDT (2026-08-25T04:20:17+00:00 UTC)
- **System under test:** rainbow_keys (`/private/tmp/rainbow_keys_opus_comparison`)
- **LLM:** backend `claude_cli`, model `claude-opus-5`
- **Tool:** meridian-testgen 0.1.0
- **Validation interpreter:** `<REPO_ROOT>/rainbow_keys/.venv/bin/python` (resolved from argument)
- **Note:** Opus-5 leg of the model comparison: same snapshot mapping artifacts, fresh copy at /private/tmp/rainbow_keys_opus_comparison, safety profile active. Re-recorded with --quarantine: wholly-invalid tests skip-marked in place.

## Results — runtime verdicts

- **Valid tests generated: 158** of 200 executed (154 pass; 4 are valid failures)
- Invalid tests that escaped to runtime: 42 (died on a non-assertion exception — defective test, not a finding)
- Files that crashed or hung: 0

*A failure on `AssertionError` means the test ran validly and disagreed with the code — a candidate finding pending human triage. Any other exception means the test itself is wrong.*

### Valid failures discovered (candidate findings)

- `test_req_1.py::test_key_order_is_the_ten_playable_keys_left_to_right` — AssertionError: assert ('a', 's', 'd...'g', 'j', ...) == ('a', 's', 'd...'g', 'j', ...)
- `test_req_2.py::test_run_returns_none_and_sends_colors_and_closes` — assert 1 is True
- `test_req_2.py::test_run_closes_engine_when_loop_raises` — assert 1 is True
- `test_req_4.py::test_render_release_branch_applies_release_envelope_without_finishing` — assert np.float32(0.2275) < np.float32(0.0)def test_render_release_branch_applies_release_envelope_without_finishing():

### Invalid tests that escaped to runtime

- `test_req_1.py::test_key_down_starts_note_and_returns_none` — KeyError: 'C4'engine = <audio_logic.NoteEngine object at 0x106a6ecf0>
- `test_req_1.py::test_key_down_empty_string_key_is_treated_as_a_key` — KeyError: ''engine = <audio_logic.NoteEngine object at 0x107022e90>
- `test_req_1.py::test_duplicate_key_down_is_ignored_so_the_note_sustains` — KeyError: 'C4'engine = <audio_logic.NoteEngine object at 0x107023250>
- `test_req_1.py::test_key_down_for_a_pending_key_is_also_ignored` — KeyError: 'k0'engine = <audio_logic.NoteEngine object at 0x10718c640>
- `test_req_1.py::test_key_down_beyond_the_voice_limit_queues_without_emitting` — KeyError: 'k0'engine = <audio_logic.NoteEngine object at 0x10718cd60>
- `test_req_1.py::test_many_distinct_keys_each_get_their_own_voice` — KeyError: 'k0'engine = <audio_logic.NoteEngine object at 0x10713dfd0>
- `test_req_1.py::test_voice_is_created_with_the_frequency_for_the_key` — AttributeError: '_Voice' object has no attribute 'frequency'engine = <audio_logic.NoteEngine object at 0x1070f05a0>
- `test_req_1.py::test_key_down_single_key_activates_and_returns_none` — AttributeError: 'function' object has no attribute 'assert_called_once_with'engine = <audio_logic.NoteEngine object at 0x1070f1590>
- `test_req_1.py::test_key_down_no_keys_pressed_yet_leaves_engine_empty` — AttributeError: 'function' object has no attribute 'assert_not_called'engine = <audio_logic.NoteEngine object at 0x1070d9550>
- `test_req_1.py::test_key_down_empty_string_key_is_treated_as_an_ordinary_key` — KeyError: ''engine = <audio_logic.NoteEngine object at 0x1070dbd50>
- `test_req_1.py::test_key_down_fills_up_to_the_polyphony_limit` — KeyError: 'k0'engine = <audio_logic.NoteEngine object at 0x107152300>
- `test_req_1.py::test_key_down_beyond_the_limit_queues_instead_of_sounding` — KeyError: 'k0'engine = <audio_logic.NoteEngine object at 0x107153200>
- `test_req_1.py::test_key_down_many_extra_keys_queue_in_press_order` — KeyError: 'k0'engine = <audio_logic.NoteEngine object at 0x107094bb0>
- `test_req_1.py::test_key_down_ignores_duplicate_press_of_an_active_key` — AttributeError: 'function' object has no attribute 'reset_mock'engine = <audio_logic.NoteEngine object at 0x107095e10>
- `test_req_1.py::test_key_down_ignores_duplicate_press_of_a_pending_key` — KeyError: 'k0'engine = <audio_logic.NoteEngine object at 0x1072447a0>
- `test_req_1.py::test_active_voice_carries_the_frequency_for_the_key` — AttributeError: '_Voice' object has no attribute 'frequency'engine = <audio_logic.NoteEngine object at 0x1070e6a50>
- `test_req_1.py::test_key_down_representative_key_activates_and_emits_note_on` — KeyError: 'C4'engine = <audio_logic.NoteEngine object at 0x1070e6d50>
- `test_req_1.py::test_key_down_duplicate_while_active_is_ignored` — KeyError: 'C4'engine = <audio_logic.NoteEngine object at 0x107175440>
- `test_req_1.py::test_key_down_many_keys_up_to_limit_all_emit_note_on` — KeyError: 'K0'engine = <audio_logic.NoteEngine object at 0x107175a70>
- `test_req_1.py::test_key_down_beyond_voice_limit_goes_to_pending_without_emitting` — KeyError: 'K0'engine = <audio_logic.NoteEngine object at 0x10717c730>
- `test_req_1.py::test_key_down_duplicate_while_pending_is_ignored` — KeyError: 'K0'engine = <audio_logic.NoteEngine object at 0x10717c910>
- `test_req_1.py::test_key_down_voice_uses_frequency_for_key` — AttributeError: '_Voice' object has no attribute 'frequency'engine = <audio_logic.NoteEngine object at 0x1061b3920>
- `test_req_1.py::test_key_up_releases_active_note_and_returns_none` — TypeError: _make_engine() takes 0 positional arguments but 1 was givendef test_key_up_releases_active_note_and_returns_none():
- `test_req_1.py::test_key_up_promotes_first_pending_key_immediately` — TypeError: _make_engine() takes 0 positional arguments but 1 was givendef test_key_up_promotes_first_pending_key_immediately():
- `test_req_1.py::test_key_up_with_empty_pending_queue_promotes_nothing` — TypeError: _make_engine() takes 0 positional arguments but 1 was givendef test_key_up_with_empty_pending_queue_promotes_nothing():
- `test_req_1.py::test_key_up_with_one_pending_key_empties_the_queue` — TypeError: _make_engine() takes 0 positional arguments but 1 was givendef test_key_up_with_one_pending_key_empties_the_queue():
- `test_req_1.py::test_key_up_with_many_pending_keys_promotes_in_fifo_order` — TypeError: _make_engine() takes 0 positional arguments but 1 was givendef test_key_up_with_many_pending_keys_promotes_in_fifo_order():
- `test_req_1.py::test_key_up_for_pending_key_removes_it_without_sounding` — TypeError: _make_engine() takes 0 positional arguments but 1 was givendef test_key_up_for_pending_key_removes_it_without_sounding():
- `test_req_1.py::test_key_up_for_unknown_key_is_a_no_op` — TypeError: _make_engine() takes 0 positional arguments but 1 was givendef test_key_up_for_unknown_key_is_a_no_op():
- `test_req_1.py::test_all_ten_keys_are_mapped` — KeyError: ';'def test_all_ten_keys_are_mapped():
- `test_req_1.py::test_frequencies_ascend_left_to_right` — KeyError: ';'def test_frequencies_ascend_left_to_right():
- `test_req_1.py::test_second_group_is_one_octave_above_first` — KeyError: ';'def test_second_group_is_one_octave_above_first():
- `test_req_2.py::test_key_up_on_sounding_key_emits_unhighlight_and_returns_none` — KeyError: 'C4'def test_key_up_on_sounding_key_emits_unhighlight_and_returns_none():
- `test_req_2.py::test_key_up_with_empty_pending_emits_only_the_stopped_key` — KeyError: 'C4'def test_key_up_with_empty_pending_emits_only_the_stopped_key():
- `test_req_2.py::test_key_up_promotes_one_pending_key_and_highlights_it` — KeyError: 'C4'def test_key_up_promotes_one_pending_key_and_highlights_it():
- `test_req_2.py::test_key_up_promotes_only_the_first_of_many_pending_keys` — KeyError: 'C4'def test_key_up_promotes_only_the_first_of_many_pending_keys():
- `test_req_2.py::test_key_up_on_pending_key_never_highlights_it` — KeyError: 'C4'def test_key_up_on_pending_key_never_highlights_it():
- `test_req_2.py::test_run_dispatches_key_down_and_key_up` — AttributeError: 'FakeEngine' object has no attribute 'calls'patched = ([<test_req_2.FakeEngine object at 0x1098779d0>], <Mock id='4457496992
- `test_req_2.py::test_run_skips_blank_and_whitespace_only_lines` — AttributeError: 'FakeEngine' object has no attribute 'calls'patched = ([<test_req_2.FakeEngine object at 0x109abd350>], <Mock id='4445492224
- `test_req_2.py::test_run_ignores_malformed_json_and_keeps_processing` — AttributeError: 'FakeEngine' object has no attribute 'calls'patched = ([<test_req_2.FakeEngine object at 0x109abcd60>], <Mock id='4457499008
- `test_req_2.py::test_run_ignores_messages_without_key_or_unknown_type` — AttributeError: 'FakeEngine' object has no attribute 'calls'patched = ([<test_req_2.FakeEngine object at 0x109abc8a0>], <Mock id='4457500688
- `test_req_4.py::test_key_down_representative_key_activates_voice_and_returns_none` — AttributeError: '_Voice' object has no attribute 'frequency'def test_key_down_representative_key_activates_voice_and_returns_none():

### Quarantined

43 wholly-invalid test function(s) were marked `@pytest.mark.skip` in place, each with its failure as the reason — the delivered suite executes only valid tests. Remove a decorator to reinstate one:

- `test_req_1.py::test_key_down_starts_note_and_returns_none`
- `test_req_1.py::test_key_down_empty_string_key_is_treated_as_a_key`
- `test_req_1.py::test_duplicate_key_down_is_ignored_so_the_note_sustains`
- `test_req_1.py::test_key_down_for_a_pending_key_is_also_ignored`
- `test_req_1.py::test_key_down_beyond_the_voice_limit_queues_without_emitting`
- `test_req_1.py::test_many_distinct_keys_each_get_their_own_voice`
- `test_req_1.py::test_voice_is_created_with_the_frequency_for_the_key`
- `test_req_1.py::test_key_down_single_key_activates_and_returns_none`
- `test_req_1.py::test_key_down_no_keys_pressed_yet_leaves_engine_empty`
- `test_req_1.py::test_key_down_empty_string_key_is_treated_as_an_ordinary_key`
- `test_req_1.py::test_key_down_fills_up_to_the_polyphony_limit`
- `test_req_1.py::test_key_down_beyond_the_limit_queues_instead_of_sounding`
- `test_req_1.py::test_key_down_many_extra_keys_queue_in_press_order`
- `test_req_1.py::test_key_down_ignores_duplicate_press_of_an_active_key`
- `test_req_1.py::test_key_down_ignores_duplicate_press_of_a_pending_key`
- `test_req_1.py::test_active_voice_carries_the_frequency_for_the_key`
- `test_req_1.py::test_key_down_representative_key_activates_and_emits_note_on`
- `test_req_1.py::test_key_down_empty_string_key_is_treated_as_an_ordinary_key`
- `test_req_1.py::test_key_down_duplicate_while_active_is_ignored`
- `test_req_1.py::test_key_down_many_keys_up_to_limit_all_emit_note_on`
- `test_req_1.py::test_key_down_beyond_voice_limit_goes_to_pending_without_emitting`
- `test_req_1.py::test_key_down_duplicate_while_pending_is_ignored`
- `test_req_1.py::test_key_down_voice_uses_frequency_for_key`
- `test_req_1.py::test_key_up_releases_active_note_and_returns_none`
- `test_req_1.py::test_key_up_promotes_first_pending_key_immediately`
- `test_req_1.py::test_key_up_with_empty_pending_queue_promotes_nothing`
- `test_req_1.py::test_key_up_with_one_pending_key_empties_the_queue`
- `test_req_1.py::test_key_up_with_many_pending_keys_promotes_in_fifo_order`
- `test_req_1.py::test_key_up_for_pending_key_removes_it_without_sounding`
- `test_req_1.py::test_key_up_for_unknown_key_is_a_no_op`
- `test_req_1.py::test_all_ten_keys_are_mapped`
- `test_req_1.py::test_frequencies_ascend_left_to_right`
- `test_req_1.py::test_second_group_is_one_octave_above_first`
- `test_req_2.py::test_key_up_on_sounding_key_emits_unhighlight_and_returns_none`
- `test_req_2.py::test_key_up_with_empty_pending_emits_only_the_stopped_key`
- `test_req_2.py::test_key_up_promotes_one_pending_key_and_highlights_it`
- `test_req_2.py::test_key_up_promotes_only_the_first_of_many_pending_keys`
- `test_req_2.py::test_key_up_on_pending_key_never_highlights_it`
- `test_req_2.py::test_run_dispatches_key_down_and_key_up`
- `test_req_2.py::test_run_skips_blank_and_whitespace_only_lines`
- `test_req_2.py::test_run_ignores_malformed_json_and_keeps_processing`
- `test_req_2.py::test_run_ignores_messages_without_key_or_unknown_type`
- `test_req_4.py::test_key_down_representative_key_activates_voice_and_returns_none`

## Invalid tests caught by Meridian during generation

- **0 rejected attempt(s)**, each retried with the reason in the prompt — every attempt validated first time

## Generation counts

- Items (function–requirement pairs + structural): 26
- Items that produced a mechanically valid test: 26
- **Test functions generated: 201** across 5 files
- Retries used: 0; exhausted: 0; skipped as category_leak: 0
- LLM calls: 26; reported cost: $5.1918 (178 in / 69189 out tokens; zeros mean the backend reports no usage)

## Reproduce

```sh
meridian-parser <REPO_ROOT>/rainbow_keys --out results/rainbow_keys/ast.json   # meridian-parser 0.2.0, codebase commit 44e622551ef8f0a9c031707faf111a6a98d7263c
meridian-mapper results/rainbow_keys/ast.json <REPO_ROOT>/rainbow_keys/SampleRequirements.md <REPO_ROOT>/rainbow_keys --out results/rainbow_keys_snapshot_20260824_pre_safety/mapping_ast.json   # meridian-mapper 0.1.0
meridian-testgen results/rainbow_keys_snapshot_20260824_pre_safety/mapping_ast.json results/rainbow_keys_snapshot_20260824_pre_safety/mapping_requirements.json /private/tmp/rainbow_keys_opus_comparison --python <REPO_ROOT>/rainbow_keys/.venv/bin/python --out-dir results/rainbow_keys_opus_safety_comparison --model claude-opus-5 --llm-timeout 600 --prompt-debug
```

## Snapshot

Generated test files copied into `tests/` beside this report:

- `test_req_1.py`
- `test_req_2.py`
- `test_req_3.py`
- `test_req_4.py`
- `test_structural.py`
- `conftest.py`
