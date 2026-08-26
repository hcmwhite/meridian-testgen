"""The whole stage-3 pipeline through the real CLI entry point.

Everything here drives ``meridian_testgen.cli.main`` exactly as a user would,
with the scripted fake injected in place of the real backend (D31) — no test
touches the network, spends money, or runs a generated test (D26). The three
exit codes of D22 are all exercised: 0 clean, 1 completed with an exhausted
item, 2 could not start.
"""

import json
import shutil
import sys
from pathlib import Path

import pytest

from meridian_testgen.cli import (
    EXIT_CANNOT_RUN,
    EXIT_EXHAUSTED,
    EXIT_OK,
    main,
)
from meridian_testgen.llm import ScriptedFakeLLM, ScriptedScript
from meridian_testgen.writers import REPORT_FILENAME

FIXTURES = Path(__file__).parent / "fixtures" / "testgen"

DISCOUNT = "aaaa11112222"      # requirement 1-1
CART = "bbbb33334444"          # requirement 1-2
FORMAT = "cccc55556666"        # structural_test_only
BADGE = "dddd77778888"         # requirement 2-1, which is category_leak


@pytest.fixture
def codebase(tmp_path):
    """A writable copy of the fixture codebase, configured with this python.

    The *code* never falls back to ``sys.executable`` (D23); writing it into
    the project config is how the resolution contract is meant to be fed.
    """
    root = tmp_path / "codebase"
    shutil.copytree(FIXTURES / "codebase", root)
    (root / ".meridian" / "config.json").write_text(
        json.dumps({"python": sys.executable}), encoding="utf-8")
    return root


def argv(codebase, out_dir, *extra):
    return [
        str(FIXTURES / "mapping_ast.json"),
        str(FIXTURES / "mapping_requirements.json"),
        str(codebase),
        "--out-dir", str(out_dir),
        *extra,
    ]


def read_report(out_dir):
    return json.loads((Path(out_dir) / REPORT_FILENAME).read_text(encoding="utf-8"))


def good_source(unit_id, code, name):
    return (
        f"def test_{name}():\n"
        f"    # meridian: unit_id={unit_id} requirement={code}\n"
        "    assert True\n"
    )


# --- the clean run --------------------------------------------------------

def test_a_clean_run_writes_the_files_the_report_and_exits_zero(
        codebase, tmp_path, capsys):
    out_dir = tmp_path / "out"

    code = main(argv(codebase, out_dir), llm=ScriptedFakeLLM())

    assert code == EXIT_OK
    written = sorted(p.name for p in (codebase / "test").glob("*.py"))
    # conftest.py is the import shim ensure_conftest writes (D24 note).
    assert written == ["conftest.py", "test_req_1.py", "test_structural.py"]

    report = read_report(out_dir)
    assert [f["relative_path"] for f in report["test_files"]] == [
        "test/test_req_1.py", "test/test_structural.py"]
    assert [f["category"] for f in report["test_files"]] == ["1", "structural"]
    assert [f["test_count"] for f in report["test_files"]] == [2, 1]
    assert report["error_notes"] == []
    # 2-1 is flagged category_leak in the fixture, so its pair never ran (D29).
    assert report["skipped_category_leak"] == 1
    assert report["counts"] == {
        "items": 3, "valid": 3, "exhausted": 0, "attempts": 3,
        "retries_used": 0, "llm_calls": 3, "files_written": 2,
        "tests_written": 3,
    }


def test_the_report_matches_what_is_actually_on_disk(codebase, tmp_path):
    out_dir = tmp_path / "out"

    main(argv(codebase, out_dir), llm=ScriptedFakeLLM())

    report = read_report(out_dir)
    on_disk = sorted(p.name for p in (codebase / "test").glob("*.py"))
    on_disk.remove("conftest.py")   # the import shim is not a test file
    assert sorted(Path(f["path"]).name for f in report["test_files"]) == on_disk
    for record in report["test_files"]:
        path = Path(record["path"])
        assert path.is_file()
        assert path.read_text(encoding="utf-8").count("def test") == \
            record["test_count"]


def test_the_report_carries_the_whole_traceability_chain(codebase, tmp_path):
    out_dir = tmp_path / "out"

    main(argv(codebase, out_dir), llm=ScriptedFakeLLM())
    report = read_report(out_dir)

    assert report["artifact"] == "testgen_report"
    assert report["tool"].startswith("meridian-testgen ")
    assert report["inputs"]["codebase"] == str(codebase)
    assert report["interpreter"] == {"path": sys.executable, "source": "config"}
    # Stage 2's envelope verbatim, and stage 1's inside it.
    assert report["source_run"]["tool"] == "meridian-mapper 0.1.0"
    assert report["source_run"]["source_run"]["tool"] == "meridian-parser 0.2.0"
    assert report["requirements_run"]["artifact"] == "mapping_requirements"


def test_the_report_records_llm_usage_totals_and_per_call(codebase, tmp_path):
    out_dir = tmp_path / "out"

    llm = ScriptedFakeLLM()
    main(argv(codebase, out_dir), llm=llm)
    report = read_report(out_dir)

    assert report["llm_usage"]["calls"] == 3 == len(llm.calls)
    assert len(report["llm_calls"]) == 3
    assert [record["call"] for record in report["llm_calls"]] == [1, 2, 3]
    assert set(report["llm_calls"][0]) == {
        "call", "input_tokens", "output_tokens",
        "cache_creation_input_tokens", "cache_read_input_tokens", "cost_usd"}


def test_the_run_command_names_the_resolved_interpreter_and_files(
        codebase, tmp_path, capsys):
    out_dir = tmp_path / "out"

    main(argv(codebase, out_dir), llm=ScriptedFakeLLM())

    out = capsys.readouterr().out
    assert "to run the generated tests:" in out
    command = [line for line in out.splitlines() if "-m pytest" in line][0]
    assert sys.executable in command
    assert "test/test_req_1.py" in command
    assert "test/test_structural.py" in command
    assert str(out_dir / REPORT_FILENAME) in out


def test_batching_sends_one_call_for_the_whole_work_list(codebase, tmp_path):
    out_dir = tmp_path / "out"

    llm = ScriptedFakeLLM()
    assert main(argv(codebase, out_dir, "--batch-size", "5"), llm=llm) == EXIT_OK
    assert len(llm.calls) == 1
    assert read_report(out_dir)["counts"]["llm_calls"] == 1


# --- the exhausted run ----------------------------------------------------

def test_an_item_that_exhausts_its_retries_exits_one_and_is_written_down(
        codebase, tmp_path, capsys):
    out_dir = tmp_path / "out"
    # Never compiles, so it fails all three attempts (D27).
    broken = "def test_broken(:\n"
    llm = ScriptedFakeLLM(ScriptedScript(tests={(CART, "1-2"): broken}))

    code = main(argv(codebase, out_dir), llm=llm)

    assert code == EXIT_EXHAUSTED
    report = read_report(out_dir)
    assert len(report["error_notes"]) == 1
    note = report["error_notes"][0]
    assert note["unit_id"] == CART and note["requirement_code"] == "1-2"
    assert [a["attempt"] for a in note["attempts"]] == [1, 2, 3]
    assert all(a["stage"] == "syntax" for a in note["attempts"])
    assert report["counts"]["exhausted"] == 1
    assert report["counts"]["valid"] == 2
    # The surviving tests are still written, and the failed one is absent.
    text = (codebase / "test" / "test_req_1.py").read_text(encoding="utf-8")
    assert f"unit_id={DISCOUNT} requirement=1-1" in text
    assert f"unit_id={CART} requirement=1-2" not in text
    assert "exhausted:" in capsys.readouterr().err


def test_a_run_where_everything_exhausts_writes_a_report_and_no_test_files(
        codebase, tmp_path):
    out_dir = tmp_path / "out"
    llm = ScriptedFakeLLM(ScriptedScript(
        tests={}, answer_unscripted=False))

    code = main(argv(codebase, out_dir), llm=llm)

    assert code == EXIT_EXHAUSTED
    assert [p.name for p in (codebase / "test").glob("*.py")] == ["conftest.py"]
    report = read_report(out_dir)
    assert report["test_files"] == []
    assert len(report["error_notes"]) == 3


# --- the run that cannot start -------------------------------------------

def test_a_codebase_without_an_interpreter_exits_two_before_any_call(
        tmp_path, capsys):
    root = tmp_path / "codebase"
    shutil.copytree(FIXTURES / "codebase", root)
    (root / ".meridian" / "config.json").write_text("{}", encoding="utf-8")
    out_dir = tmp_path / "out"
    llm = ScriptedFakeLLM()

    code = main(argv(root, out_dir), llm=llm)

    assert code == EXIT_CANNOT_RUN
    assert llm.calls == []
    assert not (out_dir / REPORT_FILENAME).exists()
    assert "--python" in capsys.readouterr().err


def test_a_missing_artifact_exits_two(codebase, tmp_path, capsys):
    out_dir = tmp_path / "out"

    code = main([str(tmp_path / "nope.json"),
                 str(FIXTURES / "mapping_requirements.json"),
                 str(codebase), "--out-dir", str(out_dir)],
                llm=ScriptedFakeLLM())

    assert code == EXIT_CANNOT_RUN
    assert "mapping_ast.json not found" in capsys.readouterr().err


def test_a_codebase_whose_source_moved_exits_two(codebase, tmp_path, capsys):
    (codebase / "shop" / "pricing.py").write_text("x = 1\n", encoding="utf-8")
    out_dir = tmp_path / "out"

    code = main(argv(codebase, out_dir), llm=ScriptedFakeLLM())

    assert code == EXIT_CANNOT_RUN
    assert "may have changed since it was parsed" in capsys.readouterr().err


# --- the flags ------------------------------------------------------------

def test_help_documents_every_flag(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    text = capsys.readouterr().out
    for flag in ("--python", "--out-dir", "--batch-size", "--max-retries",
                 "--backend", "--model", "--claude-binary", "--llm-timeout",
                 "--prompt-debug", "--version"):
        assert flag in text, flag


def test_prompt_debug_writes_a_log_and_is_free_when_off(codebase, tmp_path):
    off = tmp_path / "off"
    main(argv(codebase, off), llm=ScriptedFakeLLM())
    assert list(off.glob("prompts-*.log")) == []

    on = tmp_path / "on"
    main(argv(codebase, on, "--prompt-debug"), llm=ScriptedFakeLLM())
    logs = list(on.glob("prompts-testgen-*.log"))
    assert len(logs) == 1
    assert "=== prompt 1 " in logs[0].read_text(encoding="utf-8")




def test_report_records_how_the_run_was_invoked(codebase, tmp_path):
    out_dir = tmp_path / "out"
    args = argv(codebase, out_dir, "--batch-size", "2")
    code = main(args, llm=ScriptedFakeLLM())

    assert code == EXIT_OK
    invocation = read_report(out_dir)["invocation"]
    assert invocation["backend"] == "claude_cli"   # the default; fake injected
    assert invocation["model"] == "claude-sonnet-4-5"
    assert invocation["argv"] == args
