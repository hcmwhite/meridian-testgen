"""End-to-end tests: run the CLI as a subprocess and check the files it writes.

The fixture codebase at ``tests/fixtures/sample_project/`` carries per-file
``# EXPECTED-INCLUDE`` / ``# EXPECTED-EXCLUDE`` header comments. Those comments
are the source of truth here, exactly as they are for the extractor tests.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from meridian_parser.walker import walk_python_files

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "sample_project"


def run_cli(*argv, cwd):
    return subprocess.run(
        [sys.executable, "-m", "meridian_parser.cli", *argv],
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )


def expected_from_headers() -> tuple[set[str], dict[str, str]]:
    """Collect every EXPECTED-INCLUDE / EXPECTED-EXCLUDE across walked files."""
    includes: set[str] = set()
    excludes: dict[str, str] = {}
    for path in walk_python_files(FIXTURE_ROOT):
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("# EXPECTED-INCLUDE:"):
                includes.add(line.split(":", 1)[1].strip())
            elif line.startswith("# EXPECTED-EXCLUDE:"):
                body = line.split(":", 1)[1].strip()
                name, _, reason = body.partition("::")
                excludes[name.strip()] = reason.strip()
    return includes, excludes


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    """Run the CLI once over the fixture project and return both JSON files."""
    out_dir = tmp_path_factory.mktemp("e2e")
    result = run_cli(str(FIXTURE_ROOT), cwd=out_dir)
    assert result.returncode == 0, result.stderr
    ast = json.loads((out_dir / "ast.json").read_text())["units"]
    excluded = json.loads((out_dir / "excluded.json").read_text())["units"]
    return result, ast, excluded


def test_every_expected_unit_appears_in_ast_json(parsed):
    _, ast, _ = parsed
    expected_includes, _ = expected_from_headers()
    assert {r["dotted_name"] for r in ast} == expected_includes


def test_every_expected_exclusion_appears_with_its_reason(parsed):
    _, _, excluded = parsed
    _, expected_excludes = expected_from_headers()
    assert {r["dotted_name"]: r["reason"] for r in excluded} == expected_excludes


def test_no_unit_appears_in_both_files(parsed):
    _, ast, excluded = parsed
    assert not {r["dotted_name"] for r in ast} & {r["dotted_name"] for r in excluded}


def test_dotted_names_are_anchored_to_the_input_root(parsed):
    _, ast, excluded = parsed
    for record in [*ast, *excluded]:
        # The fixture root itself is never part of a name or a path.
        assert not record["dotted_name"].startswith("sample_project.")
        assert not record["file_path"].startswith("/")
    names = {r["dotted_name"] for r in ast}
    assert "core.analytics.aggregate" in names
    assert any(r["file_path"] == "core/analytics.py" for r in ast)


def test_overloads_carry_their_suffixes(parsed):
    _, ast, _ = parsed
    names = {r["dotted_name"] for r in ast}
    assert "billing.compute_total" in names
    assert "billing.compute_total#2" in names
    assert "core.analytics.Report.summarize#3" in names


def test_test_files_and_test_dirs_are_in_neither_file(parsed):
    _, ast, excluded = parsed
    paths = {r["file_path"] for r in [*ast, *excluded]}
    assert not any(p.startswith("test") for p in paths)


def test_records_carry_line_numbers_and_signatures(parsed):
    _, ast, _ = parsed
    for record in ast:
        assert record["line_number"] >= 1
        assert record["signature"].startswith("def ")


def test_summary_counts_match_the_file_contents(parsed):
    result, ast, excluded = parsed
    walked = len(list(walk_python_files(FIXTURE_ROOT)))
    assert f"units written: {len(ast)}" in result.stdout
    assert f"units excluded: {len(excluded)}" in result.stdout
    assert f"files processed: {walked}" in result.stdout


def test_out_redirects_ast_json_and_places_excluded_beside_it(tmp_path):
    (tmp_path / "results").mkdir()
    result = run_cli(str(FIXTURE_ROOT), "--out", "results/my_parse.json", cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "results" / "my_parse.json").read_text())["units"]
    assert json.loads((tmp_path / "results" / "excluded.json").read_text())["units"]
    assert not (tmp_path / "ast.json").exists()
    assert not (tmp_path / "excluded.json").exists()


def test_empty_input_directory_produces_two_empty_arrays(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run_cli(str(empty), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "ast.json").read_text())["units"] == []
    assert json.loads((tmp_path / "excluded.json").read_text())["units"] == []
    assert "files processed: 0" in result.stdout


def test_unparsable_file_is_reported_on_stderr_and_the_run_continues(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.py").write_text("def works():\n    return 1\n")
    (src / "broken.py").write_text("def oops(:\n")
    result = run_cli(str(src), cwd=tmp_path)
    # The run finishes and writes both files, but the output is incomplete, so
    # the exit code says so.
    assert result.returncode == 1
    assert "broken.py" in result.stderr
    ast = json.loads((tmp_path / "ast.json").read_text())["units"]
    assert [r["dotted_name"] for r in ast] == ["good.works"]
    # A parse failure is not an exclusion (D5).
    assert json.loads((tmp_path / "excluded.json").read_text())["units"] == []
    assert "files processed: 1" in result.stdout
    assert "files failed: 1" in result.stdout


def test_two_runs_produce_identical_units(tmp_path):
    """D6: the units are deterministic. The metadata header carries the run's
    own timestamp, so the comparison is on the parsed units, not raw bytes."""
    outputs = []
    for name in ("a", "b"):
        run_dir = tmp_path / name
        run_dir.mkdir()
        assert run_cli(str(FIXTURE_ROOT), cwd=run_dir).returncode == 0
        outputs.append((
            json.loads((run_dir / "ast.json").read_text())["units"],
            json.loads((run_dir / "excluded.json").read_text())["units"],
        ))
    assert outputs[0] == outputs[1]
    assert outputs[0][0]          # sanity: not comparing two empties


def test_metadata_header_describes_the_run(tmp_path):
    result = run_cli(str(FIXTURE_ROOT), cwd=tmp_path)
    assert result.returncode == 0

    for name in ("ast.json", "excluded.json"):
        doc = json.loads((tmp_path / name).read_text())
        assert doc["schema_version"] == 2
        assert doc["tool"].startswith("meridian-parser ")
        assert doc["generated_at"]
        assert doc["input_dir"]
        assert doc["python"]
        assert "git_commit" in doc     # may be None outside a git repo
        assert isinstance(doc["units"], list)
