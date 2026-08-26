"""Argument parsing and input validation for meridian-testgen."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from meridian_testgen.cli import (
    EXIT_CANNOT_RUN,
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_RETRIES,
    build_parser,
    main,
)

FIXTURES = Path(__file__).parent / "fixtures" / "testgen"
CODEBASE = FIXTURES / "codebase"


def _args(**overrides):
    values = {
        "mapping_ast": str(FIXTURES / "mapping_ast.json"),
        "mapping_requirements": str(FIXTURES / "mapping_requirements.json"),
        "codebase": str(CODEBASE),
    }
    values.update(overrides)
    return [values["mapping_ast"], values["mapping_requirements"], values["codebase"]]


def test_defaults_match_the_rulings():
    args = build_parser().parse_args(_args())

    assert args.batch_size == DEFAULT_BATCH_SIZE == 1
    assert args.max_retries == DEFAULT_MAX_RETRIES == 2
    assert args.prompt_debug is False
    assert args.out_dir == Path(".")


def test_missing_inputs_are_reported_together(tmp_path, capsys):
    code = main([
        str(tmp_path / "no_ast.json"),
        str(tmp_path / "no_reqs.json"),
        str(tmp_path / "no_codebase"),
    ])

    assert code == EXIT_CANNOT_RUN
    err = capsys.readouterr().err
    assert "no_ast.json" in err and "no_reqs.json" in err and "no_codebase" in err


def test_nonsense_tuning_values_are_rejected(capsys):
    code = main(_args() + ["--batch-size", "0", "--max-retries", "-1"])

    assert code == EXIT_CANNOT_RUN
    err = capsys.readouterr().err
    assert "--batch-size" in err and "--max-retries" in err


def test_console_script_help_runs():
    result = subprocess.run(
        [sys.executable, "-m", "meridian_testgen.cli", "--help"],
        capture_output=True, text=True, check=False,
        cwd=str(Path(__file__).resolve().parents[1]),
    )

    assert result.returncode == 0
    assert "meridian-testgen" in result.stdout
    assert "--prompt-debug" in result.stdout


def test_pyproject_declares_the_console_script():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert (
        data["project"]["scripts"]["meridian-testgen"]
        == "meridian_testgen.cli:main"
    )
    assert "meridian_testgen" in data["tool"]["setuptools"]["packages"]
