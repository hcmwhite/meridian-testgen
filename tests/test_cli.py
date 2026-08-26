"""Tests for the CLI argument parsing and input-directory validation."""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from meridian_parser.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(*argv, cwd=None):
    return subprocess.run(
        [sys.executable, "-m", "meridian_parser.cli", *argv],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )


def test_existing_directory_exits_zero(tmp_path):
    # Run from tmp_path so the output files land there, not in the repo.
    result = _run_cli(str(tmp_path), cwd=tmp_path)
    assert result.returncode == 0, result.stderr


def test_missing_path_exits_non_zero_with_stderr_message(tmp_path):
    missing = tmp_path / "no-such-dir"
    result = _run_cli(str(missing))
    assert result.returncode != 0
    assert "no-such-dir" in result.stderr


def test_file_instead_of_directory_exits_non_zero(tmp_path):
    a_file = tmp_path / "notadir.py"
    a_file.write_text("")
    assert main([str(a_file)]) != 0


def test_help_documents_input_directory_and_out():
    result = _run_cli("--help")
    assert result.returncode == 0
    assert "input_dir" in result.stdout
    assert "--out" in result.stdout
    assert "results/my_parse.json" in result.stdout


def test_out_defaults_to_ast_json(tmp_path):
    from meridian_parser.cli import build_parser

    args = build_parser().parse_args([str(tmp_path)])
    assert args.out == "ast.json"


def test_config_file_in_the_input_directory_is_used(tmp_path, capsys):
    (tmp_path / "keep.py").write_text("def kept(): pass\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "dep.py").write_text("def vendored(): pass\n")
    (tmp_path / ".ast_parse.config").write_text("[exclude_dirs]\nvendor\n")
    out = tmp_path / "out" / "ast.json"
    out.parent.mkdir()

    assert main([str(tmp_path), "--out", str(out)]) == 0

    names = [r["dotted_name"] for r in json.loads(out.read_text())["units"]]
    assert names == ["keep.kept"]


def test_no_config_falls_back_to_built_in_defaults(tmp_path):
    (tmp_path / "keep.py").write_text("def kept(): pass\n")
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "dep.py").write_text("def vendored(): pass\n")
    (tmp_path / ".ast_parse.config").write_text("[exclude_dirs]\nvendor\n")
    out = tmp_path / "out" / "ast.json"
    out.parent.mkdir()

    assert main([str(tmp_path), "--out", str(out), "--no-config"]) == 0

    names = [r["dotted_name"] for r in json.loads(out.read_text())["units"]]
    assert names == ["keep.kept", "vendor.dep.vendored"]


def test_named_config_that_does_not_exist_is_an_error(tmp_path, capsys):
    assert main([str(tmp_path), "--config", str(tmp_path / "nope")]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_venv_is_not_walked_by_default(tmp_path):
    (tmp_path / "keep.py").write_text("def kept(): pass\n")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "dep.py").write_text("def vendored(): pass\n")
    out = tmp_path / "out" / "ast.json"
    out.parent.mkdir()

    assert main([str(tmp_path), "--out", str(out)]) == 0

    names = [r["dotted_name"] for r in json.loads(out.read_text())["units"]]
    assert names == ["keep.kept"]


def test_a_syntax_error_is_reported_and_exits_nonzero(tmp_path, capsys):
    (tmp_path / "good.py").write_text("def kept(): pass\n")
    (tmp_path / "bad.py").write_text("def broken(:\n    pass\n")
    out = tmp_path / "out" / "ast.json"
    out.parent.mkdir()

    # 1, not 0: the output is incomplete, and 2 is reserved for a run that
    # could not start at all.
    assert main([str(tmp_path), "--out", str(out)]) == 1

    captured = capsys.readouterr()
    assert "could not parse bad.py" in captured.err
    assert "line 1" in captured.err
    assert "files failed: 1" in captured.out
    assert "files processed: 1" in captured.out


def test_duplicate_definitions_are_flagged_but_still_queued(tmp_path, capsys):
    (tmp_path / "mod.py").write_text(
        "def twin():\n    pass\n\ndef twin():\n    pass\n"
    )
    out = tmp_path / "out" / "ast.json"
    out.parent.mkdir()

    assert main([str(tmp_path), "--out", str(out)]) == 0

    captured = capsys.readouterr()
    assert "repeats the name and signature" in captured.err
    records = json.loads(out.read_text())["units"]
    assert len(records) == 2          # both stay in the queue
    ids = [r["unit_id"] for r in records]
    assert len(set(ids)) == 2         # ids still unique


def test_syntax_failure_names_the_interpreter(tmp_path, capsys):
    (tmp_path / "bad.py").write_text("def broken(:\n    pass\n")
    out = tmp_path / "out" / "ast.json"
    out.parent.mkdir()

    assert main([str(tmp_path), "--out", str(out)]) == 1

    err = capsys.readouterr().err
    assert "syntax was checked with Python" in err
    assert platform.python_version() in err
    assert "rebuild" in err and "virtual environment" in err
