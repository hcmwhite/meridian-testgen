"""Tests for meridian_parser.walker."""

from __future__ import annotations

from pathlib import Path

from meridian_parser.config import parse_config_text
from meridian_parser.walker import walk_python_files


def build_tree(root: Path, files: list[str]) -> None:
    """Create every path in *files* (relative to *root*) as an empty file."""
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")


def relative_results(root: Path) -> list[str]:
    """Walk *root* and return the yielded paths relative to it, as strings."""
    return [str(p.relative_to(root)) for p in walk_python_files(root)]


def test_yields_ordinary_python_files(tmp_path: Path) -> None:
    build_tree(tmp_path, ["alpha.py", "beta.py", "notes.txt"])

    assert relative_results(tmp_path) == ["alpha.py", "beta.py"]


def test_skips_test_prefixed_files(tmp_path: Path) -> None:
    build_tree(tmp_path, ["alpha.py", "test_alpha.py", "testing.py"])

    results = relative_results(tmp_path)

    assert "test_alpha.py" not in results
    assert results == ["alpha.py", "testing.py"]


def test_skips_files_inside_test_directories(tmp_path: Path) -> None:
    build_tree(
        tmp_path,
        [
            "alpha.py",
            "tests/helper.py",
            "test_utils/helper.py",
            "test/deeper/helper.py",
        ],
    )

    assert relative_results(tmp_path) == ["alpha.py"]


def test_recurses_into_nested_subdirectories(tmp_path: Path) -> None:
    build_tree(
        tmp_path,
        [
            "alpha.py",
            "pkg/beta.py",
            "pkg/inner/gamma.py",
            "pkg/inner/test_gamma.py",
        ],
    )

    assert relative_results(tmp_path) == [
        "alpha.py",
        str(Path("pkg/beta.py")),
        str(Path("pkg/inner/gamma.py")),
    ]


def test_empty_directory_yields_nothing(tmp_path: Path) -> None:
    assert list(walk_python_files(tmp_path)) == []


def test_ordering_is_deterministic(tmp_path: Path) -> None:
    build_tree(tmp_path, ["zeta.py", "alpha.py", "pkg/mu.py", "abc/nu.py"])

    assert relative_results(tmp_path) == relative_results(tmp_path)
    assert relative_results(tmp_path) == [
        "alpha.py",
        "zeta.py",
        str(Path("abc/nu.py")),
        str(Path("pkg/mu.py")),
    ]


def test_default_config_skips_venv_and_vendor_directories(tmp_path: Path) -> None:
    build_tree(
        tmp_path,
        [
            "alpha.py",
            ".venv/lib/dep.py",
            ".git/hooks/thing.py",
            "node_modules/pkg/index.py",
            "__pycache__/alpha.py",
            "build/generated.py",
        ],
    )

    assert relative_results(tmp_path) == ["alpha.py"]


def test_config_can_exclude_a_project_directory(tmp_path: Path) -> None:
    build_tree(tmp_path, ["alpha.py", "vendor/dep.py", "pkg/beta.py"])
    config = parse_config_text("[exclude_dirs]\nvendor\n")

    results = [str(p.relative_to(tmp_path)) for p in walk_python_files(tmp_path, config)]

    assert results == ["alpha.py", str(Path("pkg/beta.py"))]


def test_config_can_exclude_files_by_glob(tmp_path: Path) -> None:
    build_tree(tmp_path, ["alpha.py", "service_pb2.py", "beta.py"])
    config = parse_config_text("[exclude_files]\n*_pb2.py\n")

    results = [str(p.relative_to(tmp_path)) for p in walk_python_files(tmp_path, config)]

    assert results == ["alpha.py", "beta.py"]


def test_spec_test_rules_apply_even_with_a_config(tmp_path: Path) -> None:
    """A config replaces the default exclusions but cannot switch off the
    design specification's own test-file and test-directory rules."""
    build_tree(tmp_path, ["alpha.py", "test_alpha.py", "tests/helper.py"])
    config = parse_config_text("[exclude_dirs]\nvendor\n")

    results = [str(p.relative_to(tmp_path)) for p in walk_python_files(tmp_path, config)]

    assert results == ["alpha.py"]


def test_config_extends_rather_than_replaces_the_defaults(tmp_path: Path) -> None:
    build_tree(tmp_path, ["alpha.py", "vendor/dep.py", ".venv/lib/dep.py"])
    config = parse_config_text("[exclude_dirs]\nvendor\n")

    results = [str(p.relative_to(tmp_path)) for p in walk_python_files(tmp_path, config)]

    assert results == ["alpha.py"]   # both vendor/ and .venv/ skipped


def test_include_dirs_walks_a_directory_the_defaults_exclude(tmp_path: Path) -> None:
    build_tree(tmp_path, ["alpha.py", "build/generated.py", "dist/other.py"])
    config = parse_config_text("[include_dirs]\nbuild\n")

    results = [str(p.relative_to(tmp_path)) for p in walk_python_files(tmp_path, config)]

    assert results == ["alpha.py", str(Path("build/generated.py"))]


def test_include_dirs_cannot_re_enable_test_directories(tmp_path: Path) -> None:
    """The specification's test rules sit outside the config entirely."""
    build_tree(tmp_path, ["alpha.py", "tests/helper.py"])
    config = parse_config_text("[include_dirs]\ntests\n")

    results = [str(p.relative_to(tmp_path)) for p in walk_python_files(tmp_path, config)]

    assert results == ["alpha.py"]
