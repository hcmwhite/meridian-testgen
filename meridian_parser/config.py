"""Reading `.ast_parse.config` — the exclusion list for a parse run.

The file is gitignore-flavoured but sectioned, because directories and files
are skipped at different points in the walk: a directory match prunes the
whole subtree without descending, a file match drops one file.

    # .ast_parse.config
    [exclude_dirs]
    vendor
    generated

    [exclude_files]
    *_pb2.py

    [include_dirs]
    build            # walk this one after all, despite the default

Patterns are matched with :mod:`fnmatch` against the *base name* of the entry,
not the full path — `node_modules` matches at any depth. Blank lines and lines
beginning with ``#`` are ignored.

A config file **extends** :data:`DEFAULT_EXCLUDE_DIRS` rather than replacing
it. That way a project adding one entry cannot accidentally re-enable walking
`.venv` or `.git`, which is the expensive mistake — it fills the queue with
third-party functions. To walk a directory the defaults exclude, name it under
``[include_dirs]``; that section wins over every exclusion.

The test-file and test-directory rules from the design specification are not
part of any of these lists and are always applied — a config cannot switch
them off, with ``[include_dirs]`` or otherwise.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = ".ast_parse.config"

SECTION_EXCLUDE_DIRS = "exclude_dirs"
SECTION_EXCLUDE_FILES = "exclude_files"
SECTION_INCLUDE_DIRS = "include_dirs"
_SECTIONS = (SECTION_EXCLUDE_DIRS, SECTION_EXCLUDE_FILES, SECTION_INCLUDE_DIRS)

# Directories that are never source worth parsing: version control, virtual
# environments, dependency trees, build output, and tool caches. Walking these
# is not merely slow — it queues third-party functions for test generation as
# if they were the project's own.
DEFAULT_EXCLUDE_DIRS: tuple[str, ...] = (
    # Every hidden directory. Named entries below are redundant against this
    # but document what the rule is actually for.
    ".*",
    ".git", ".hg", ".svn",
    ".venv", "venv", "env", ".env",
    "node_modules",
    "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".nox",
    "build", "dist", "*.egg-info",
    "site-packages",
    ".idea", ".vscode",
)

DEFAULT_EXCLUDE_FILES: tuple[str, ...] = ()


class ConfigError(Exception):
    """The config file exists but could not be understood."""


@dataclass(frozen=True)
class ParseConfig:
    """Which directories and files a walk should skip.

    ``exclude_dirs`` and ``exclude_files`` are the *effective* lists — the
    built-in defaults plus whatever a config file added. ``include_dirs``
    overrides them for named directories.
    """

    exclude_dirs: tuple[str, ...] = DEFAULT_EXCLUDE_DIRS
    exclude_files: tuple[str, ...] = DEFAULT_EXCLUDE_FILES
    include_dirs: tuple[str, ...] = ()
    source: str = "built-in defaults"

    def excludes_dir(self, name: str) -> bool:
        """Return True if a directory named *name* should not be descended."""
        if any(fnmatch.fnmatch(name, pattern) for pattern in self.include_dirs):
            return False
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.exclude_dirs)

    def excludes_file(self, name: str) -> bool:
        """Return True if a file named *name* should not be parsed."""
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.exclude_files)


def parse_config_text(text: str, source: str = "<string>") -> ParseConfig:
    """Parse the contents of a config file into a :class:`ParseConfig`.

    The returned config's exclusion lists are the built-in defaults with the
    file's own patterns appended.
    """
    collected: dict[str, list[str]] = {section: [] for section in _SECTIONS}
    current: list[str] | None = None

    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith("#") else ""
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            name = line[1:-1].strip()
            if name not in _SECTIONS:
                raise ConfigError(
                    f"{source}:{number}: unknown section [{name}] "
                    f"(expected {', '.join(f'[{s}]' for s in _SECTIONS)})"
                )
            current = collected[name]
            continue
        if current is None:
            raise ConfigError(
                f"{source}:{number}: pattern {line!r} appears before any "
                f"section header"
            )
        current.append(line)

    return ParseConfig(
        exclude_dirs=DEFAULT_EXCLUDE_DIRS + tuple(collected[SECTION_EXCLUDE_DIRS]),
        exclude_files=DEFAULT_EXCLUDE_FILES + tuple(collected[SECTION_EXCLUDE_FILES]),
        include_dirs=tuple(collected[SECTION_INCLUDE_DIRS]),
        source=source,
    )


def load_config(path: str | os.PathLike[str]) -> ParseConfig:
    """Read and parse a config file. Raises :class:`ConfigError` if unreadable."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror or exc}") from exc
    return parse_config_text(text, str(path))


def discover_config(input_dir: str | os.PathLike[str]) -> ParseConfig:
    """Load `.ast_parse.config` from *input_dir*, or fall back to the defaults."""
    candidate = Path(input_dir) / CONFIG_FILENAME
    if candidate.is_file():
        return load_config(candidate)
    return ParseConfig()
