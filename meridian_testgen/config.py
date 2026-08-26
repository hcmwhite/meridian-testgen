"""Resolve the interpreter mechanical validation runs on (D23).

Generated tests are compiled and collected with the *target codebase's*
interpreter, never with the interpreter running this tool — the codebase may
need imports (NumPy, say) that this process has never heard of.

Resolution order, and only this order:

1. a ``python`` key in ``<codebase>/.meridian/config.json`` — the contract a
   future stage-0 setup tool will write, and the reason stage 3 is buildable
   before stage 0 exists;
2. the ``--python`` command-line argument.

Neither present, or a path that does not exist or is not executable, is a
:class:`ConfigError`, which the CLI turns into exit 2. A bad interpreter is
found here, at the start of the run, not as a crash after the LLM has been
paid.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_RELATIVE_PATH = Path(".meridian") / "config.json"
CONFIG_PYTHON_KEY = "python"

# Named in every failure message, so the fix is always visible from the error.
_BOTH_OPTIONS = (
    f"set the {CONFIG_PYTHON_KEY!r} key in <codebase>/{CONFIG_RELATIVE_PATH} "
    f"or pass --python"
)


class ConfigError(Exception):
    """The interpreter for mechanical validation could not be resolved."""


@dataclass(frozen=True)
class ResolvedInterpreter:
    """Which interpreter to validate with, and where the choice came from."""

    path: Path
    # "config" or "argument" — reported in the run summary and the artifact.
    source: str

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return str(self.path)


def config_path(codebase_root) -> Path:
    """Where the project config file would live for *codebase_root*."""
    return Path(codebase_root) / CONFIG_RELATIVE_PATH


def read_project_config(codebase_root) -> dict:
    """The parsed ``.meridian/config.json``, or ``{}`` when there is none.

    A file that exists but is not a JSON object is an error rather than a
    silent fallback: a typo in the config should not quietly promote
    ``--python`` past the file that was meant to win.
    """
    path = config_path(codebase_root)
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(
            f"{path} must hold a JSON object, found {type(data).__name__}"
        )
    return data


def resolve_interpreter(codebase_root, python_argument=None) -> ResolvedInterpreter:
    """Resolve the validation interpreter for *codebase_root* (D23)."""
    data = read_project_config(codebase_root)
    candidate = data.get(CONFIG_PYTHON_KEY)
    source = "config"
    if candidate is not None and not isinstance(candidate, str):
        raise ConfigError(
            f"{config_path(codebase_root)}: {CONFIG_PYTHON_KEY!r} must be a "
            f"string, found {type(candidate).__name__}"
        )
    if not candidate:
        candidate = str(python_argument) if python_argument is not None else None
        source = "argument"
    if not candidate:
        raise ConfigError(
            f"no interpreter for the target codebase: {_BOTH_OPTIONS}"
        )

    path = Path(candidate).expanduser()
    if not path.exists():
        raise ConfigError(
            f"interpreter does not exist: {path} (from the {source}); "
            f"{_BOTH_OPTIONS}"
        )
    if path.is_dir() or not os.access(path, os.X_OK):
        raise ConfigError(
            f"interpreter is not executable: {path} (from the {source}); "
            f"{_BOTH_OPTIONS}"
        )
    return ResolvedInterpreter(path=path, source=source)
