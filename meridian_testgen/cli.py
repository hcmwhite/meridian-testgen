"""Command line entry point for the unit-test generator (stage 3).

The pipeline, left to right over one in-memory model: resolve the target
codebase's interpreter (D23) → load both stage-2 artifacts (D24) → derive the
structural-obligation checklist (D33) → generate per pair and per
structural-only function, batched and retried (D27, D28) → validate
mechanically (D25a) → write the test files and ``testgen_report.json`` (D30)
→ print the command that runs the generated tests, which this stage never
runs itself (D26).

Nothing here executes a generated test (D26): the run ends by printing the
exact command the user can run themselves, with the interpreter that was
resolved and the files that were actually written.

Exit codes (D22):

* ``0`` — the run completed and every item generated a mechanically valid test.
* ``1`` — the run completed and the artifacts are written, but at least one
  item exhausted its generation retries; the report's error notes say which.
* ``2`` — the run could not start or could not write.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from meridian_testgen import __version__
from meridian_testgen.config import ConfigError, resolve_interpreter
from meridian_testgen.inputs import InputError, load_model
from meridian_testgen.llm import LLMConfig, LLMError, create_llm
from meridian_testgen.promptlog import PromptLog
from meridian_testgen.validate import (
    ValidationEnvironmentError,
    generate_and_validate,
)
from meridian_testgen.writers import (
    WriterError,
    build_report,
    run_command,
    write_report,
    write_test_files,
)
# --- codex generated ---
from meridian_testgen.codex_safety_profile import (
    SafetyProfileError,
    load_safety_profile,
)
# --- end codex generated ---

EXIT_OK = 0
EXIT_EXHAUSTED = 1
EXIT_CANNOT_RUN = 2

# Backend names and the default model belong to llm.py (D31); the CLI names
# them for its --backend choices and nothing else.
from meridian_testgen.llm import (  # noqa: E402  (grouped with the names it re-exports)
    BACKEND_CLAUDE_CLI,
    # --- codex generated ---
    BACKEND_CODEX_CLI,
    # --- end codex generated ---
    BACKEND_SCRIPTED_FAKE,
    DEFAULT_MODEL,
)
DEFAULT_BATCH_SIZE = 1
DEFAULT_MAX_RETRIES = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meridian-testgen",
        description=(
            "Generate pytest files from the stage-2 mapping artifacts and the "
            "codebase they describe, grouped one file per requirement category."
        ),
    )
    parser.add_argument(
        "mapping_ast", type=Path,
        help="the stage-2 mapper's mapping_ast.json (Artifact 1).",
    )
    parser.add_argument(
        "mapping_requirements", type=Path,
        help="the stage-2 mapper's mapping_requirements.json (Artifact 2).",
    )
    parser.add_argument(
        "codebase", type=Path,
        help=(
            "root of the codebase the artifacts describe; generated tests are "
            "written into its test/ directory."
        ),
    )
    parser.add_argument(
        "--python", dest="python", default=None,
        help=(
            "interpreter to validate generated tests with, used only when the "
            "codebase has no .meridian/config.json 'python' key."
        ),
    )
    parser.add_argument(
        "--out-dir", type=Path, default=Path("."),
        help=(
            "where testgen_report.json and any prompt log are written "
            "(default: the current directory). The generated tests themselves "
            "always go to <codebase>/test/."
        ),
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"generation items per LLM call (default {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
        help=(
            "how many times a mechanically invalid test is re-asked before the "
            f"item is written off with an error note (default {DEFAULT_MAX_RETRIES})."
        ),
    )
    parser.add_argument(
        "--backend", default=BACKEND_CLAUDE_CLI,
        choices=(
            BACKEND_CLAUDE_CLI,
            # --- codex generated ---
            BACKEND_CODEX_CLI,
            # --- end codex generated ---
            BACKEND_SCRIPTED_FAKE,
        ),
        help=(
            f"which LLM backend to use (default {BACKEND_CLAUDE_CLI}). "
            f"{BACKEND_SCRIPTED_FAKE} answers from a test script and is not a "
            "production path."
        ),
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"the model id handed to the backend (default {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--claude-binary", default="claude",
        help="the headless claude executable to run (default claude).",
    )
    # --- codex generated ---
    parser.add_argument(
        "--codex-binary", default="codex",
        help="the Codex CLI executable to run with --backend codex_cli (default codex).",
    )
    # --- end codex generated ---
    parser.add_argument(
        "--llm-timeout", type=float, default=300.0,
        help="seconds to wait for one backend call (default 300).",
    )
    parser.add_argument(
        "--prompt-debug", action="store_true",
        help=(
            "append every prompt sent to a timestamped log in --out-dir; off "
            "by default, and free when off."
        ),
    )
    # --- codex generated ---
    parser.add_argument(
        "--safety-profile", type=Path, default=None,
        help=(
            "JSON resource-safety profile that extends the built-in policy; "
            "see docs/CODEX_SAFETY_PROFILES.md"
        ),
    )
    # --- end codex generated ---
    parser.add_argument("--version", action="version",
                        version=f"meridian-testgen {__version__}")
    return parser


def _validate(args) -> list[str]:
    problems = []
    if not args.mapping_ast.is_file():
        problems.append(f"mapping_ast.json not found: {args.mapping_ast}")
    if not args.mapping_requirements.is_file():
        problems.append(
            f"mapping_requirements.json not found: {args.mapping_requirements}"
        )
    if not args.codebase.is_dir():
        problems.append(f"codebase root is not a directory: {args.codebase}")
    if args.batch_size < 1:
        problems.append("--batch-size must be at least 1")
    if args.max_retries < 0:
        problems.append("--max-retries cannot be negative")
    # --- codex generated ---
    if args.safety_profile is not None and not args.safety_profile.is_file():
        problems.append(f"safety profile not found: {args.safety_profile}")
    # --- end codex generated ---
    return problems


def main(argv=None, llm=None) -> int:
    """Run the generator. *llm* overrides backend selection (tests inject the fake)."""
    args = build_parser().parse_args(argv)

    problems = _validate(args)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    try:
        interpreter = resolve_interpreter(args.codebase, args.python)
        model = load_model(args.mapping_ast, args.mapping_requirements)
    except (ConfigError, InputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    # --- codex generated ---
    try:
        safety_profile = load_safety_profile(args.safety_profile)
    except SafetyProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    # --- end codex generated ---

    prompt_log = PromptLog(args.out_dir) if args.prompt_debug else None
    # --- codex generated ---
    # The historical CLI default names a Claude model. Passing it to
    # Codex would fail, so an unspecified Codex model uses the local
    # Codex CLI's configured default instead.
    backend_model = (
        None if args.backend == BACKEND_CODEX_CLI and args.model == DEFAULT_MODEL
        else args.model
    )
    # --- end codex generated ---
    llm_was_created = llm is None
    if llm is None:
        try:
            llm = create_llm(
                LLMConfig(backend=args.backend,
                          # --- codex generated ---
                          model=backend_model,
                          # --- end codex generated ---
                          binary=args.claude_binary, timeout=args.llm_timeout,
                          # --- codex generated ---
                          codex_binary=args.codex_binary,
                ),
                # --- end codex generated ---
                codebase_root=args.codebase,
                prompt_log=prompt_log,
            )
        except LLMError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_CANNOT_RUN
    elif prompt_log is not None:
        llm.prompt_log = prompt_log

    try:
        run = generate_and_validate(
            model, llm, args.codebase, interpreter.path,
            batch_size=args.batch_size, max_retries=args.max_retries,
            out_dir=args.out_dir,
            # --- codex generated ---
            safety_profile=safety_profile,
            # --- end codex generated ---
        )
    except (InputError, ValidationEnvironmentError) as exc:
        # A source file that moved, or an interpreter that cannot be run at
        # all: the run could not do its work, which is exit 2, not a partial
        # result dressed up as one (D22).
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    try:
        written = write_test_files(
            args.codebase, run.groups, args.mapping_ast,
            args.mapping_requirements, model=model,
        )
        report = build_report(
            args.mapping_ast, args.mapping_requirements, args.codebase,
            args.out_dir, interpreter, model, written, run, llm,
            invocation={
                "backend": args.backend,
                # backend_model is what the backend was actually handed; None
                # means "the backend's own configured default".
                "model": backend_model if llm_was_created else args.model,
                "argv": list(argv) if argv is not None else sys.argv[1:],
            },
        )
        report_path = write_report(args.out_dir, report)
    except WriterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    # The real outputs are on disk; the checkpoint has done its job. Left in
    # place it would make the next run against fresh inputs say "resuming".
    if run.checkpoint is not None:
        run.checkpoint.clear()

    _print_summary(run, report, report_path, interpreter)
    return EXIT_EXHAUSTED if run.error_notes else EXIT_OK


def _print_summary(run, report, report_path, interpreter) -> None:
    """The run's last words: the counts, the report, and the D26 command."""
    summary = run.summary
    print(
        f"generated {summary.valid} of {summary.items} tests "
        f"in {len(report['test_files'])} files "
        f"({summary.exhausted} exhausted, "
        f"{summary.skipped_category_leak} skipped as category_leak, "
        f"{summary.calls} llm calls)"
    )
    for note in run.error_notes:
        print(
            f"  exhausted: {note['dotted_name'] or note['unit_id']} / "
            f"{note['requirement_code']} after {len(note['attempts'])} attempts",
            file=sys.stderr,
        )
    print(f"report: {report_path}")
    command = run_command(interpreter, report["test_files"])
    if command:
        print("to run the generated tests:")
        print(f"  cd {args_codebase(report)} && {command}")
    else:
        print("no test files were written, so there is nothing to run")


def args_codebase(report) -> str:
    """The codebase directory the run command is relative to."""
    return report["inputs"]["codebase"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
