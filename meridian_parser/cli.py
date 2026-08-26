"""Command-line entry point for the Meridian AST Parser."""

from __future__ import annotations

import argparse
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from meridian_parser import SCHEMA_VERSION, __version__

from meridian_parser.config import (
    CONFIG_FILENAME,
    ConfigError,
    ParseConfig,
    discover_config,
    load_config,
)
from meridian_parser.extractor import ParseError, extract
from meridian_parser.walker import walk_python_files
from meridian_parser.writer import JsonArrayWriter, WriterError


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the Meridian AST Parser."""
    parser = argparse.ArgumentParser(
        prog="meridian_parser",
        description=(
            "Parse a Python codebase and emit a flat JSON list of every "
            "function and method that requires testing."
        ),
    )
    parser.add_argument(
        "input_dir",
        help="Directory containing the Python codebase to parse.",
    )
    parser.add_argument(
        "--out",
        default="ast.json",
        help=(
            "Write output to the specified file instead of ast.json. "
            "May include a path (e.g. --out results/my_parse.json)."
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help=(
            f"Read exclusions from this file instead of {CONFIG_FILENAME} in "
            f"the input directory. Missing config files are an error only "
            f"when named explicitly."
        ),
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help=(
            "Ignore any config file and use the built-in exclusions "
            "(.git, .venv, node_modules, build caches, and similar)."
        ),
    )
    return parser


def git_commit(input_dir: Path) -> "str | None":
    """The input directory's current git commit, or None when it has none."""
    try:
        result = subprocess.run(
            ["git", "-C", str(input_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def run_metadata(input_dir: Path) -> dict:
    """The fields that describe this run, written at the top of both files.

    Kept deliberately small until the database work decides what a run
    record really needs: enough to tell which tool produced the file, when,
    from what source, and with which Python doing the syntax checking.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": f"meridian-parser {__version__}",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input_dir": str(input_dir.resolve()),
        "git_commit": git_commit(input_dir),
        "python": platform.python_version(),
    }


def run(input_dir: Path, out_path: Path,
        config: ParseConfig | None = None) -> tuple[int, int, int, int]:
    """Walk *input_dir*, extract every unit, and stream both output files.

    Returns ``(written, excluded, files_processed, files_failed)``.
    ``excluded.json`` is written beside the resolved *out_path* (D4). A file
    that cannot be read or parsed is reported on stderr and skipped; the run
    continues (D5).
    """
    excluded_path = out_path.parent / "excluded.json"
    written = excluded_count = files_processed = files_failed = 0
    meta = run_metadata(input_dir)

    with JsonArrayWriter(out_path, meta) as ast_writer, \
            JsonArrayWriter(excluded_path, meta) as exc_writer:
        for path in walk_python_files(input_dir, config):
            relative = path.relative_to(input_dir)
            try:
                source = path.read_text(encoding="utf-8")
                included, excluded = extract(source, relative)
            except (OSError, UnicodeDecodeError, ParseError) as exc:
                print(f"error: could not parse {relative}: {exc}", file=sys.stderr)
                files_failed += 1
                # Syntax is judged by the interpreter running this tool, so a
                # file using newer syntax than that interpreter reads as a
                # syntax error. Name the interpreter once, on the first such
                # failure, so the fix (update the venv) is obvious.
                if isinstance(exc, ParseError) and files_failed == 1:
                    print(
                        f"note: syntax was checked with Python "
                        f"{platform.python_version()} at {sys.executable}. "
                        f"If this file uses newer syntax than that, rebuild "
                        f"your virtual environment on a newer Python and run "
                        f"again.",
                        file=sys.stderr,
                    )
                continue
            files_processed += 1
            # A "-N" suffix on a unit_id means this definition has the same
            # name and signature as an earlier one in the same scope. Python
            # will only ever call the last one; the earlier ones are shadowed.
            # Flag it, but keep every definition in the queue.
            for record in included + excluded:
                if "-" in record["unit_id"]:
                    print(
                        f"warning: {relative}: {record['dotted_name']} "
                        f"(line {record['line_number']}) repeats the name and "
                        f"signature of an earlier definition — Python calls "
                        f"only the last one",
                        file=sys.stderr,
                    )
            for record in included:
                ast_writer.write(record)
                written += 1
            for record in excluded:
                exc_writer.write(record)
                excluded_count += 1

    return written, excluded_count, files_processed, files_failed


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, validate the input directory, and return an exit code.

    Exit codes: 0 every file parsed; 1 the run completed but at least one file
    could not be parsed, so the output is incomplete; 2 the run could not
    start or could not write (bad input directory, unreadable config,
    unwritable output).
    """
    args = build_parser().parse_args(argv)

    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"error: input directory does not exist: {input_dir}", file=sys.stderr)
        return 2
    if not input_dir.is_dir():
        print(f"error: input path is not a directory: {input_dir}", file=sys.stderr)
        return 2

    try:
        if args.no_config:
            config = ParseConfig()
        elif args.config is not None:
            config = load_config(args.config)
        else:
            config = discover_config(input_dir)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    try:
        written, excluded, files_processed, files_failed = run(
            input_dir, out_path, config)
    except WriterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"units written: {written}")
    print(f"units excluded: {excluded}")
    print(f"files processed: {files_processed}")
    print(f"files failed: {files_failed}")

    # A file that could not be parsed contributed no units, so the output is
    # silently incomplete. Exiting zero there would tell a calling orchestrator
    # the queue is whole when it is not. Both output files are still written
    # and still valid — the non-zero code reports partial success, per the
    # usual convention that zero means "did what was asked".
    return 1 if files_failed else 0


if __name__ == "__main__":
    sys.exit(main())
