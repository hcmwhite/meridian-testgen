"""Tests for meridian_parser.config."""

from __future__ import annotations

from pathlib import Path

import pytest

from meridian_parser.config import (
    CONFIG_FILENAME,
    DEFAULT_EXCLUDE_DIRS,
    ConfigError,
    ParseConfig,
    discover_config,
    load_config,
    parse_config_text,
)


def test_parses_every_section() -> None:
    config = parse_config_text(
        "[exclude_dirs]\nvendor\n\n[exclude_files]\nsetup.py\n"
        "\n[include_dirs]\nbuild\n"
    )

    # A config EXTENDS the defaults rather than replacing them.
    assert config.exclude_dirs[: len(DEFAULT_EXCLUDE_DIRS)] == DEFAULT_EXCLUDE_DIRS
    assert config.exclude_dirs[-1] == "vendor"
    assert config.exclude_files == ("setup.py",)
    assert config.include_dirs == ("build",)


def test_ignores_comments_and_blank_lines() -> None:
    config = parse_config_text(
        "# a comment\n\n[exclude_dirs]\n\n  # indented comment\n  vendor  \n"
        "  generated   # trailing comment\n"
    )

    assert config.exclude_dirs[len(DEFAULT_EXCLUDE_DIRS):] == ("vendor", "generated")


def test_glob_patterns_match_base_names() -> None:
    config = parse_config_text("[exclude_dirs]\n*.egg-info\n[exclude_files]\n*_pb2.py\n")

    assert config.excludes_dir("meridian.egg-info")
    assert not config.excludes_dir("meridian")
    assert config.excludes_file("service_pb2.py")
    assert not config.excludes_file("service.py")


def test_unknown_section_is_an_error() -> None:
    with pytest.raises(ConfigError, match="unknown section"):
        parse_config_text("[exclude_everything]\nx\n")


def test_pattern_before_any_section_is_an_error() -> None:
    with pytest.raises(ConfigError, match="before any section"):
        parse_config_text(".venv\n")


def test_defaults_cover_the_usual_suspects() -> None:
    config = ParseConfig()

    for name in (".git", ".venv", "node_modules", "__pycache__", "build", "dist"):
        assert config.excludes_dir(name), name


def test_hidden_directories_are_excluded_by_default() -> None:
    config = ParseConfig()

    assert config.excludes_dir(".hidden")
    assert config.excludes_dir(".cache")
    assert not config.excludes_dir("hidden")


def test_discover_reads_the_file_from_the_input_directory(tmp_path: Path) -> None:
    (tmp_path / CONFIG_FILENAME).write_text("[exclude_dirs]\nvendor\n")

    config = discover_config(tmp_path)

    assert config.excludes_dir("vendor")
    assert config.excludes_dir(".venv")   # a config EXTENDS the defaults


def test_include_dirs_re_enables_an_excluded_default(tmp_path: Path) -> None:
    config = parse_config_text("[include_dirs]\nbuild\n")

    assert not config.excludes_dir("build")   # named explicitly, so walked
    assert config.excludes_dir("dist")        # still excluded by default


def test_include_dirs_wins_over_an_explicit_exclusion() -> None:
    config = parse_config_text("[exclude_dirs]\nvendor\n[include_dirs]\nvendor\n")

    assert not config.excludes_dir("vendor")


def test_discover_falls_back_to_defaults(tmp_path: Path) -> None:
    config = discover_config(tmp_path)

    assert config.exclude_dirs == DEFAULT_EXCLUDE_DIRS


def test_load_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        load_config(tmp_path / "nope.config")
