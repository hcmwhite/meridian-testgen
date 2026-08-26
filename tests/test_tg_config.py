"""Interpreter resolution for stage 3 (D23)."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from meridian_testgen.cli import EXIT_CANNOT_RUN, main
from meridian_testgen.config import ConfigError, resolve_interpreter

FIXTURES = Path(__file__).parent / "fixtures" / "testgen"
CODEBASE = FIXTURES / "codebase"


def make_codebase(tmp_path, config=None) -> Path:
    """A codebase root, optionally carrying a .meridian/config.json."""
    root = tmp_path / "codebase"
    root.mkdir()
    if config is not None:
        meridian = root / ".meridian"
        meridian.mkdir()
        (meridian / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return root


def fake_interpreter(tmp_path, name="python3") -> Path:
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_config_file_wins_over_the_python_argument(tmp_path):
    from_config = fake_interpreter(tmp_path, "from-config")
    from_argument = fake_interpreter(tmp_path, "from-argument")
    root = make_codebase(tmp_path, {"python": str(from_config)})

    resolved = resolve_interpreter(root, str(from_argument))

    assert resolved.path == from_config
    assert resolved.source == "config"


def test_python_argument_is_the_fallback(tmp_path):
    from_argument = fake_interpreter(tmp_path, "from-argument")
    root = make_codebase(tmp_path)

    resolved = resolve_interpreter(root, str(from_argument))

    assert resolved.path == from_argument
    assert resolved.source == "argument"


def test_empty_python_key_falls_back_to_the_argument(tmp_path):
    from_argument = fake_interpreter(tmp_path, "from-argument")
    root = make_codebase(tmp_path, {"python": ""})

    assert resolve_interpreter(root, str(from_argument)).path == from_argument


def test_neither_option_is_an_error_naming_both(tmp_path):
    root = make_codebase(tmp_path)

    with pytest.raises(ConfigError) as excinfo:
        resolve_interpreter(root, None)

    message = str(excinfo.value)
    assert ".meridian/config.json" in message
    assert "--python" in message


def test_nonexistent_interpreter_is_an_error(tmp_path):
    root = make_codebase(tmp_path, {"python": str(tmp_path / "nope")})

    with pytest.raises(ConfigError) as excinfo:
        resolve_interpreter(root, None)

    assert "does not exist" in str(excinfo.value)


def test_non_executable_interpreter_is_an_error(tmp_path):
    plain = tmp_path / "not-executable"
    plain.write_text("", encoding="utf-8")
    plain.chmod(0o644)
    root = make_codebase(tmp_path, {"python": str(plain)})

    with pytest.raises(ConfigError) as excinfo:
        resolve_interpreter(root, None)

    assert "not executable" in str(excinfo.value)


def test_malformed_config_is_an_error_not_a_silent_fallback(tmp_path):
    root = make_codebase(tmp_path)
    (root / ".meridian").mkdir(exist_ok=True)
    (root / ".meridian" / "config.json").write_text("{oops", encoding="utf-8")

    with pytest.raises(ConfigError) as excinfo:
        resolve_interpreter(root, sys.executable)

    assert "not valid JSON" in str(excinfo.value)


def test_non_string_python_key_is_an_error(tmp_path):
    root = make_codebase(tmp_path, {"python": 3})

    with pytest.raises(ConfigError):
        resolve_interpreter(root, None)


def _cli_args(codebase, extra=()):
    return [
        str(FIXTURES / "mapping_ast.json"),
        str(FIXTURES / "mapping_requirements.json"),
        str(codebase),
        *extra,
    ]


def test_cli_exits_2_when_no_interpreter_is_resolvable(tmp_path, capsys):
    root = make_codebase(tmp_path)

    assert main(_cli_args(root)) == EXIT_CANNOT_RUN

    err = capsys.readouterr().err
    assert "--python" in err and ".meridian/config.json" in err


def test_cli_exits_2_on_a_nonexistent_interpreter_path(tmp_path, capsys):
    root = make_codebase(tmp_path)

    assert main(_cli_args(root, ["--python", str(tmp_path / "nope")])) == EXIT_CANNOT_RUN

    assert "does not exist" in capsys.readouterr().err


def test_cli_gets_past_resolution_with_a_good_interpreter(tmp_path):
    """A resolvable interpreter lets the run reach the work itself.

    The codebase here is empty, so generation fails on the first source slice
    — which is exactly the proof wanted: resolution and artifact loading both
    succeeded, and the failure came from a later step naming a source file.
    """
    from meridian_testgen.llm import ScriptedFakeLLM

    root = make_codebase(tmp_path)
    llm = ScriptedFakeLLM()

    assert main(_cli_args(root, ["--python", sys.executable, "--out-dir",
                                 str(tmp_path / "out")]), llm=llm) == EXIT_CANNOT_RUN
    assert llm.calls == []
