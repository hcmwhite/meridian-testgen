"""Recursive discovery of the ``.py`` files that should be parsed.

Two independent things prune the walk:

* The design specification's own rules — files matching ``test_*.py`` and
  directories whose name is or begins with ``test``. These are always applied
  and cannot be switched off, so their contents appear in neither
  ``ast.json`` nor ``excluded.json``.
* The exclusion list from `.ast_parse.config` (see :mod:`meridian_parser.config`),
  which defaults to version-control, virtualenv, dependency and build
  directories. Without it a walk descends into `.venv` and queues third-party
  functions for test generation as if they were the project's own.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from meridian_parser.config import ParseConfig


def is_test_file(name: str) -> bool:
    """Return True for a file name matching ``test_*.py``."""
    return name.startswith("test_") and name.endswith(".py")


def is_test_dir(name: str) -> bool:
    """Return True for a directory whose name is or begins with ``test``."""
    return name.startswith("test")


def walk_python_files(
    root: str | os.PathLike[str],
    config: ParseConfig | None = None,
) -> Iterator[Path]:
    """Yield every ``.py`` file under *root*, skipping test and excluded paths.

    Paths are yielded in a deterministic order: each directory's entries are
    sorted by name, files before recursing into subdirectories, so two runs
    over an unchanged tree produce identical output (D6).
    """
    if config is None:
        config = ParseConfig()
    root = Path(root)
    entries = sorted(root.iterdir(), key=lambda p: p.name)

    for entry in entries:
        if entry.is_dir():
            continue
        if entry.suffix != ".py":
            continue
        if is_test_file(entry.name) or config.excludes_file(entry.name):
            continue
        yield entry

    for entry in entries:
        if not entry.is_dir():
            continue
        if is_test_dir(entry.name) or config.excludes_dir(entry.name):
            continue
        yield from walk_python_files(entry, config)
