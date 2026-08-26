"""Mechanical validation and the retry loop (D25a, D26, D27, D28).

Everything here drives the scripted fake and a real interpreter — the one the
codebase's config names, never ``sys.executable`` by default. No test reaches
the network, and no generated test is ever executed (D26).
"""

import json
import shutil
import stat
import sys
from pathlib import Path

import pytest

from meridian_testgen.config import resolve_interpreter
from meridian_testgen.generate import STRUCTURAL_GROUP, build_items
from meridian_testgen.inputs import load_model
from meridian_testgen.llm import LLMError, ScriptedFakeLLM, ScriptedScript
from meridian_testgen.validate import (
    NO_ANSWER_REASON,
    STAGE_COLLECTION,
    STAGE_SYNTAX,
    STAGE_TRACEABILITY,
    check_collection,
    check_syntax,
    check_traceability,
    generate_and_validate,
    generated_test_dir,
    validate_test,
)

FIXTURES = Path(__file__).parent / "fixtures" / "testgen"

DISCOUNT = "aaaa11112222"      # 1-1, deterministic
CART = "bbbb33334444"          # 1-2, deterministic
FORMAT = "cccc55556666"        # structural_test_only


@pytest.fixture
def model():
    return load_model(FIXTURES / "mapping_ast.json",
                      FIXTURES / "mapping_requirements.json")


@pytest.fixture
def codebase(tmp_path):
    """A writable copy of the fixture codebase whose config names this python.

    The *code* must never fall back to ``sys.executable`` (D23); a test
    fixture naming it is exactly how the resolution contract is meant to be
    fed.
    """
    root = tmp_path / "codebase"
    shutil.copytree(FIXTURES / "codebase", root)
    config = root / ".meridian" / "config.json"
    config.write_text(json.dumps({"python": sys.executable}), encoding="utf-8")
    return root


@pytest.fixture
def interpreter(codebase):
    return resolve_interpreter(codebase, None).path


def item_for(model, codebase, key):
    items, _ = build_items(model, codebase)
    return {item.key: item for item in items}[key]


def good_source(unit_id, code, name="one"):
    return (
        f"def test_{name}():\n"
        f"    # meridian: unit_id={unit_id} requirement={code}\n"
        "    assert True\n"
    )


# --- the three checks ----------------------------------------------------


def test_syntactically_bad_source_fails_stage_one(interpreter):
    reason = check_syntax(interpreter, "def test_x(:\n    pass\n")
    assert reason is not None
    assert "does not compile" in reason


def test_valid_source_passes_stage_one(interpreter):
    assert check_syntax(interpreter, good_source(DISCOUNT, "1-1")) is None


def test_missing_traceability_comment_fails(model, codebase):
    item = item_for(model, codebase, (DISCOUNT, "1-1"))
    reason = check_traceability("def test_x():\n    assert True\n", item)
    assert reason is not None
    assert "traceability comment" in reason
    assert f"unit_id={DISCOUNT} requirement=1-1" in reason


def test_traceability_comment_for_another_item_does_not_count(model, codebase):
    item = item_for(model, codebase, (DISCOUNT, "1-1"))
    assert check_traceability(good_source(CART, "1-2"), item) is not None


def test_traceability_passes_when_every_test_function_carries_it(model, codebase):
    item = item_for(model, codebase, (DISCOUNT, "1-1"))
    source = good_source(DISCOUNT, "1-1", "one") + good_source(DISCOUNT, "1-1", "two")
    assert check_traceability(source, item) is None


def test_one_uncommented_test_function_among_several_fails(model, codebase):
    item = item_for(model, codebase, (DISCOUNT, "1-1"))
    source = (good_source(DISCOUNT, "1-1", "one")
              + "def test_two():\n    assert True\n")
    reason = check_traceability(source, item)
    assert reason is not None and "test_two" in reason


def test_a_file_with_no_test_function_fails_traceability(model, codebase):
    item = item_for(model, codebase, (DISCOUNT, "1-1"))
    reason = check_traceability("VALUE = 1\n", item)
    assert reason is not None and "no test function" in reason


def test_a_valid_but_uncollectable_test_fails_stage_two(interpreter, codebase):
    source = ("import a_module_that_does_not_exist\n\n"
              + good_source(DISCOUNT, "1-1"))
    reason = check_collection(interpreter, source, codebase)
    assert reason is not None
    assert "does not collect" in reason


def test_a_collectable_test_passes_stage_two(interpreter, codebase):
    assert check_collection(interpreter, good_source(DISCOUNT, "1-1"), codebase) is None


def test_collection_leaves_no_scratch_file_behind(interpreter, codebase):
    check_collection(interpreter, good_source(DISCOUNT, "1-1"), codebase)
    leftovers = [p.name for p in generated_test_dir(codebase).glob("*.py")]
    assert leftovers == []


def test_validate_test_reports_the_stage_that_rejected(model, codebase, interpreter):
    item = item_for(model, codebase, (DISCOUNT, "1-1"))
    assert validate_test(item, "def broken(:\n", interpreter, codebase).stage == STAGE_SYNTAX
    assert validate_test(item, "def test_x():\n    assert True\n", interpreter,
                         codebase).stage == STAGE_TRACEABILITY
    bad_import = "import nope_not_here\n\n" + good_source(DISCOUNT, "1-1")
    assert validate_test(item, bad_import, interpreter,
                         codebase).stage == STAGE_COLLECTION
    assert validate_test(item, good_source(DISCOUNT, "1-1"), interpreter, codebase).ok


# --- the resolved interpreter, not this one ------------------------------


def test_validation_runs_on_the_resolved_interpreter(tmp_path, model, codebase):
    """A stub interpreter records its argv; the tool must invoke *it* (D23)."""
    argv_log = tmp_path / "argv.log"
    stub = tmp_path / "stub_python"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"open({str(argv_log)!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    item = item_for(model, codebase, (DISCOUNT, "1-1"))
    result = validate_test(item, good_source(DISCOUNT, "1-1"), stub, codebase)

    assert result.ok
    recorded = argv_log.read_text(encoding="utf-8").splitlines()
    assert any(line.startswith("-m py_compile") for line in recorded)
    assert any("-m pytest --collect-only" in line for line in recorded)
    assert sys.executable not in "\n".join(recorded)


# --- the retry loop ------------------------------------------------------


def scripted(**tests):
    return ScriptedFakeLLM(ScriptedScript(tests=dict(tests)))


def test_a_valid_run_needs_no_retry(model, codebase, interpreter):
    llm = ScriptedFakeLLM()
    run = generate_and_validate(model, llm, codebase, interpreter)
    assert run.summary.items == 3
    assert run.summary.valid == 3
    assert run.summary.exhausted == 0
    assert run.summary.retries_used == 0
    assert len(llm.calls) == 3
    assert sorted(run.groups) == ["1", STRUCTURAL_GROUP]


def test_a_failed_item_is_retried_with_the_reason_in_the_prompt(model, codebase,
                                                                interpreter):
    script = ScriptedScript(tests={
        (DISCOUNT, "1-1"): ["def test_x(:\n", good_source(DISCOUNT, "1-1")],
    })
    llm = ScriptedFakeLLM(script)
    run = generate_and_validate(model, llm, codebase, interpreter)

    assert run.summary.valid == 3
    assert run.summary.exhausted == 0
    assert run.summary.retries_used == 1
    retried = [items for items in llm.items
               if any(item.key == (DISCOUNT, "1-1") for item in items)]
    assert len(retried) == 2
    second = [i for i in retried[1] if i.key == (DISCOUNT, "1-1")][0]
    assert second.prior_failure is not None
    assert "does not compile" in second.prior_failure


def test_only_the_failed_item_of_a_batch_is_re_sent(model, codebase, interpreter):
    script = ScriptedScript(tests={
        (CART, "1-2"): ["def test_x(:\n", good_source(CART, "1-2")],
    })
    llm = ScriptedFakeLLM(script)
    run = generate_and_validate(model, llm, codebase, interpreter, batch_size=3)

    assert [len(call) for call in llm.calls] == [3, 1]
    assert llm.calls[1] == [(CART, "1-2")]
    assert run.summary.valid == 3


def test_exhaustion_writes_an_error_note_with_every_attempt(model, codebase,
                                                            interpreter):
    script = ScriptedScript(tests={(DISCOUNT, "1-1"): "def test_x(:\n"})
    llm = ScriptedFakeLLM(script)
    run = generate_and_validate(model, llm, codebase, interpreter, max_retries=2)

    assert run.summary.exhausted == 1
    assert run.summary.valid == 2
    note = run.error_notes[0]
    assert note["unit_id"] == DISCOUNT
    assert note["requirement_code"] == "1-1"
    assert [a["attempt"] for a in note["attempts"]] == [1, 2, 3]
    assert all(a["stage"] == STAGE_SYNTAX for a in note["attempts"])
    assert all("does not compile" in a["reason"] for a in note["attempts"])
    # The item contributes no test file content at all.
    assert all(g.item.key != (DISCOUNT, "1-1")
               for tests in run.groups.values() for g in tests)


def test_an_unanswered_item_is_retried_and_then_exhausts(model, codebase,
                                                         interpreter):
    script = ScriptedScript(tests={(FORMAT, "structural"): None})
    llm = ScriptedFakeLLM(script)
    run = generate_and_validate(model, llm, codebase, interpreter)

    note = run.error_notes[0]
    assert note["unit_id"] == FORMAT
    assert [a["reason"] for a in note["attempts"]] == [NO_ANSWER_REASON] * 3
    assert STRUCTURAL_GROUP not in run.groups


def test_a_missing_traceability_comment_drives_the_retry_loop(model, codebase,
                                                              interpreter):
    """It compiles and it collects — the D29 comment is the only thing wrong."""
    script = ScriptedScript(tests={
        (DISCOUNT, "1-1"): "def test_untraceable():\n    assert True\n",
    })
    llm = ScriptedFakeLLM(script)
    run = generate_and_validate(model, llm, codebase, interpreter)

    assert run.summary.exhausted == 1
    note = run.error_notes[0]
    assert [a["stage"] for a in note["attempts"]] == [STAGE_TRACEABILITY] * 3
    assert "traceability comment" in note["attempts"][0]["reason"]
    retried = [i for items in llm.items for i in items if i.key == (DISCOUNT, "1-1")]
    assert "traceability comment" in retried[1].prior_failure


def test_max_retries_zero_gives_one_attempt(model, codebase, interpreter):
    script = ScriptedScript(tests={(DISCOUNT, "1-1"): "def test_x(:\n"})
    llm = ScriptedFakeLLM(script)
    run = generate_and_validate(model, llm, codebase, interpreter, max_retries=0)
    assert len(run.error_notes[0]["attempts"]) == 1


def test_a_backend_failure_is_recorded_not_raised(model, codebase, interpreter):
    """A call that dies costs only its own batch: the other items' tests
    stand, and the failed item exhausts alone with the reason recorded.
    (The old behaviour — one timeout discarding the whole round's finished
    work — is what the first real run tripped over on 2026-08-23.)"""
    script = ScriptedScript(tests={(DISCOUNT, "1-1"): LLMError("cli exploded")})
    llm = ScriptedFakeLLM(script)
    run = generate_and_validate(model, llm, codebase, interpreter)
    assert run.summary.exhausted == 1
    assert run.summary.valid == 2
    assert "cli exploded" in run.error_notes[0]["attempts"][0]["reason"]


def test_a_call_failure_retries_and_can_recover(model, codebase, interpreter):
    script = ScriptedScript(tests={
        (DISCOUNT, "1-1"): [LLMError("claude timed out after 300.0s"),
                            good_source(DISCOUNT, "1-1")],
    })
    llm = ScriptedFakeLLM(script)
    run = generate_and_validate(model, llm, codebase, interpreter)
    assert run.summary.valid == 3
    assert run.summary.exhausted == 0
    # The retry carried the call failure's reason, and re-sent only the
    # failed item.
    retried = llm.items[-1]
    assert [item.key for item in retried] == [(DISCOUNT, "1-1")]
    assert "timed out" in retried[0].prior_failure


def test_the_model_sees_the_validated_groups(model, codebase, interpreter):
    run = generate_and_validate(model, ScriptedFakeLLM(), codebase, interpreter)
    assert model.generated_groups is run.groups


# ---------------------------------------------------------------------------
# checkpoint and run log (crash insurance)


def test_decided_items_are_checkpointed_as_they_happen(model, codebase,
                                                       interpreter, tmp_path):
    import json as _json

    out = tmp_path / "out"
    script = ScriptedScript(tests={(DISCOUNT, "1-1"): LLMError("dead network")})
    run = generate_and_validate(model, ScriptedFakeLLM(script), codebase,
                                interpreter, out_dir=out)
    # The run finished, so the CLI would clear it — but at this layer the
    # file still exists and holds every decided item.
    lines = [_json.loads(l) for l in
             (out / "testgen_checkpoint.jsonl").read_text().splitlines()]
    assert "source_generated_at" in lines[0]
    statuses = {(r["unit_id"], r["requirement"]): r["status"]
                for r in lines[1:]}
    assert statuses[(DISCOUNT, "1-1")] == "exhausted"
    assert sum(1 for s in statuses.values() if s == "valid") == 2
    valid_line = next(r for r in lines[1:] if r["status"] == "valid")
    assert "def test_" in valid_line["source"]


def test_a_killed_run_resumes_from_the_checkpoint(model, codebase,
                                                  interpreter, tmp_path):
    out = tmp_path / "out"
    # First run: decide everything, keep the checkpoint (no CLI clear here).
    first = generate_and_validate(model, ScriptedFakeLLM(), codebase,
                                  interpreter, out_dir=out)
    assert first.summary.valid == 3

    # Second run over the same inputs: nothing is re-asked.
    fake = ScriptedFakeLLM()
    second = generate_and_validate(model, fake, codebase, interpreter,
                                   out_dir=out)
    assert fake.calls == []
    assert second.summary.valid == 3
    assert sorted(second.groups) == sorted(first.groups)


def test_a_checkpoint_from_different_inputs_is_ignored(model, codebase,
                                                       interpreter, tmp_path):
    import json as _json

    out = tmp_path / "out"
    out.mkdir()
    (out / "testgen_checkpoint.jsonl").write_text(
        _json.dumps({"source_generated_at": "some-other-run"}) + "\n"
        + _json.dumps({"unit_id": DISCOUNT, "requirement": "1-1",
                       "status": "valid", "source": "def test_stale(): pass"})
        + "\n"
    )
    fake = ScriptedFakeLLM()
    run = generate_and_validate(model, fake, codebase, interpreter,
                                out_dir=out)
    # All three were regenerated; the stale source appears nowhere.
    assert len(fake.calls) == 3
    assert run.summary.valid == 3
    assert all("test_stale" not in g.test.source
               for group in run.groups.values() for g in group)


def test_progress_lands_in_the_run_log_file(model, codebase, interpreter,
                                            tmp_path):
    out = tmp_path / "out"
    generate_and_validate(model, ScriptedFakeLLM(), codebase, interpreter,
                          out_dir=out)
    text = (out / "testgen_run.log").read_text()
    assert "generating 3 tests" in text
    assert "valid:" in text
    # Every line is timestamped.
    assert all(line[:4].isdigit() for line in text.splitlines() if line)


def test_a_crash_mid_round_leaves_earlier_items_checkpointed(model, codebase,
                                                             interpreter,
                                                             tmp_path):
    """The checkpoint must be written per batch, not per round: a run dying
    on call 2 keeps call 1's finished work (the first live run lost 7
    finished tests to a round-level failure, 2026-08-23)."""
    import json as _json

    out = tmp_path / "out"
    script = ScriptedScript(tests={(CART, "1-2"): RuntimeError("hard crash")})
    with pytest.raises(RuntimeError):
        generate_and_validate(model, ScriptedFakeLLM(script), codebase,
                              interpreter, out_dir=out)

    lines = [_json.loads(l) for l in
             (out / "testgen_checkpoint.jsonl").read_text().splitlines()]
    decided = {(r.get("unit_id"), r.get("requirement")): r.get("status")
               for r in lines[1:]}
    assert decided == {(DISCOUNT, "1-1"): "valid"}


# ---------------------------------------------------------------------------
# the import path for generated tests (test/conftest.py)


def test_conftest_is_written_with_the_source_dirs(model, codebase):
    from meridian_testgen.validate import ensure_conftest, source_dirs_of

    wrote = ensure_conftest(codebase, source_dirs_of(model))
    assert wrote
    text = (codebase / "test" / "conftest.py").read_text()
    assert "sys.path" in text
    for d in source_dirs_of(model):
        assert repr(d)[1:-1] in text


def test_an_existing_conftest_is_never_touched(codebase):
    from meridian_testgen.validate import ensure_conftest

    target = codebase / "test" / "conftest.py"
    target.parent.mkdir(exist_ok=True)
    target.write_text("# the user's own conftest\n")
    assert ensure_conftest(codebase, ["python"]) is False
    assert target.read_text() == "# the user's own conftest\n"


def test_conftest_makes_a_bare_stem_import_collect(model, codebase, interpreter):
    """The failure that burned the first live run: a module in a bare
    subdirectory is unimportable from test/ without the conftest."""
    from meridian_testgen.validate import ensure_conftest, source_dirs_of

    source = ("from pricing import apply_discount\n\n"
              + good_source(DISCOUNT, "1-1"))
    assert check_collection(interpreter, source, codebase) is not None

    ensure_conftest(codebase, source_dirs_of(model))
    assert check_collection(interpreter, source, codebase) is None
