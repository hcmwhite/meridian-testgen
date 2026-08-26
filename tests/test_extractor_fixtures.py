"""Run the extractor over each fixture file and check it against that file's
header comment.

Every file in ``tests/fixtures/sample_project/`` starts with machine-readable
``# EXPECTED-INCLUDE: <dotted_name>`` and
``# EXPECTED-EXCLUDE: <dotted_name> :: <reason>`` lines. Those lines are the
source of truth: this module parses them and asserts the extractor reproduces
them exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from meridian_parser.extractor import extract
from meridian_parser.walker import walk_python_files

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_project"

ALL_FIXTURE_FILES = sorted(FIXTURE_ROOT.rglob("*.py"))
WALKED_FIXTURE_FILES = list(walk_python_files(FIXTURE_ROOT))


def read_header(path: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """Return the (includes, excludes) declared by *path*'s header comment."""
    includes: list[str] = []
    excludes: list[tuple[str, str]] = []
    for line in path.read_text().splitlines():
        if not line.startswith("#"):
            continue
        body = line.lstrip("#").strip()
        if body.startswith("EXPECTED-INCLUDE:"):
            includes.append(body.split(":", 1)[1].strip())
        elif body.startswith("EXPECTED-EXCLUDE:"):
            name, _, reason = body.split(":", 1)[1].partition("::")
            excludes.append((name.strip(), reason.strip()))
    return includes, excludes


def ids(paths):
    return [str(path.relative_to(FIXTURE_ROOT)) for path in paths]


def test_fixture_files_were_discovered():
    assert ALL_FIXTURE_FILES, "the fixture codebase is missing"


@pytest.mark.parametrize("path", ALL_FIXTURE_FILES, ids=ids(ALL_FIXTURE_FILES))
def test_extractor_matches_the_file_header(path: Path):
    relative = path.relative_to(FIXTURE_ROOT)
    expected_includes, expected_excludes = read_header(path)

    included, excluded = extract(path.read_text(), relative)

    if path not in WALKED_FIXTURE_FILES:
        # Skipped by the walker: its header declares no expectations, so it
        # contributes to neither output file in a real run.
        assert (expected_includes, expected_excludes) == ([], [])
        return

    assert [record["dotted_name"] for record in included] == expected_includes
    assert [
        (record["dotted_name"], record["reason"]) for record in excluded
    ] == expected_excludes

    for record in included + excluded:
        assert record["file_path"] == str(relative)
        assert record["line_number"] >= 1
        assert record["signature"].startswith(("def ", "async def "))

    assert set(expected_includes).isdisjoint(name for name, _ in expected_excludes)


def test_walked_fixture_files_declare_expectations():
    for path in WALKED_FIXTURE_FILES:
        includes, excludes = read_header(path)
        assert includes or excludes, f"{path} declares no expected output"
