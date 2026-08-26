"""Command line entry point for the requirements mapper.

The whole pipeline in one place, run left to right over the one in-memory
model (D11): load ``ast.json`` → normalize the requirements document → map
every leaf → verify every non-category-leak pair against real source bytes →
tag the unmapped functions ``structural_test_only`` → write both artifacts.

Everything the pipeline can be tuned by is a plain config value on the command
line — which LLM backend and model, the category-leak threshold, the retry cap
(D14, D16, D18). No provider is hardcoded; the default backend is the headless
``claude`` CLI.

Exit codes (D21):

* ``0`` — the run completed and every pair either verified or was never
  verified by design.
* ``1`` — the run completed, both artifacts are written and valid, but at
  least one pair exhausted its retries and was removed. The non-zero code
  says "look at the error notes in Artifact 1"; it is partial success, not a
  crash.
* ``2`` — the run could not start or could not write.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from meridian_mapper import __version__
from meridian_mapper.artifacts import (
    ArtifactError,
    artifact_two_path,
    write_artifact_one,
    write_artifact_two,
)
from meridian_mapper.astload import AstLoadError, load_ast_json
from meridian_mapper.classify import classify
from meridian_mapper.llm import (
    BACKEND_CLAUDE_CLI,
    BACKEND_SCRIPTED_FAKE,
    DEFAULT_MODEL,
    LLMConfig,
    LLMError,
    create_llm,
)
from meridian_mapper.mapping import (
    DEFAULT_CATEGORY_LEAK_THRESHOLD,
    MappingConfig,
    run_mapping,
)
from meridian_mapper.promptlog import PromptLog
from meridian_mapper.requirements import (
    NUMBERED_MARKDOWN,
    RequirementsError,
    load_into_model,
)
from meridian_mapper.verification import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_RETRIES,
    VerificationConfig,
    run_verification,
)

EXIT_OK = 0
EXIT_EXHAUSTED = 1
EXIT_CANNOT_RUN = 2

DEFAULT_OUT = "mapping_ast.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meridian-mapper",
        description=(
            "Map a requirements document onto the functions in a stage-1 "
            "ast.json, and write the two mapping artifacts."
        ),
    )
    parser.add_argument(
        "ast_json", type=Path,
        help="the stage-1 parser's ast.json (schema v2).",
    )
    parser.add_argument(
        "requirements_doc", type=Path,
        help="the requirements document, as numbered markdown.",
    )
    parser.add_argument(
        "codebase", type=Path, nargs="?", default=None,
        help=(
            "root of the codebase ast.json was parsed from; evidence snippets "
            "are checked against its bytes. May also be given as --codebase."
        ),
    )
    parser.add_argument(
        "--codebase", dest="codebase_flag", type=Path, default=None,
        help="the same path as the positional codebase argument.",
    )
    parser.add_argument(
        "--out", type=Path, default=Path(DEFAULT_OUT),
        help=(
            f"where to write the annotated AST artifact (default {DEFAULT_OUT}). "
            "mapping_requirements.json is written beside it."
        ),
    )
    parser.add_argument(
        "--requirements-format", default=NUMBERED_MARKDOWN,
        help=(
            "the requirements document's format (default "
            f"{NUMBERED_MARKDOWN}; the only one this stage reads)."
        ),
    )
    parser.add_argument(
        "--backend", default=BACKEND_CLAUDE_CLI,
        choices=(BACKEND_CLAUDE_CLI, BACKEND_SCRIPTED_FAKE),
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
    parser.add_argument(
        "--llm-timeout", type=float, default=300.0,
        help="seconds to wait for one backend call (default 300).",
    )
    parser.add_argument(
        "--category-leak-threshold", type=int,
        default=DEFAULT_CATEGORY_LEAK_THRESHOLD,
        help=(
            "a leaf mapping to more functions than this is flagged "
            "category_leak and its pairs skip verification (default "
            f"{DEFAULT_CATEGORY_LEAK_THRESHOLD})."
        ),
    )
    parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=(
            "how many verification claims are asked for in one LLM call "
            f"(default {DEFAULT_BATCH_SIZE}). Only failed pairs are re-asked, "
            "and the retry cap stays per pair."
        ),
    )
    parser.add_argument(
        "--prompt-debug", action="store_true",
        help=(
            "append every prompt sent to a timestamped log beside the "
            "artifacts; off by default, and free when off."
        ),
    )
    parser.add_argument(
        "--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
        help=(
            "how many times a failed verification is re-asked before the "
            f"mapping is removed with an error note (default {DEFAULT_MAX_RETRIES})."
        ),
    )
    parser.add_argument("--version", action="version",
                        version=f"meridian-mapper {__version__}")
    return parser


def resolve_codebase(args) -> "Path | None":
    """The codebase root, from either the positional or the flag form."""
    return args.codebase_flag if args.codebase_flag is not None else args.codebase


def _validate(args, codebase) -> list[str]:
    problems = []
    if not args.ast_json.is_file():
        problems.append(f"ast.json not found: {args.ast_json}")
    if not args.requirements_doc.is_file():
        problems.append(f"requirements document not found: {args.requirements_doc}")
    if codebase is None:
        problems.append(
            "no codebase root given: pass it positionally or with --codebase"
        )
    elif not codebase.is_dir():
        problems.append(f"codebase root is not a directory: {codebase}")
    if args.category_leak_threshold < 0:
        problems.append("--category-leak-threshold cannot be negative")
    if args.max_retries < 0:
        problems.append("--max-retries cannot be negative")
    if args.batch_size < 1:
        problems.append("--batch-size must be at least 1")
    return problems


def main(argv=None, llm=None) -> int:
    """Run the mapper. *llm* overrides backend selection (tests inject the fake)."""
    args = build_parser().parse_args(argv)
    codebase = resolve_codebase(args)

    problems = _validate(args, codebase)
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    # D31/D32: the log lands beside the artifacts, and is only built when
    # asked for — no file appears on a run without --prompt-debug.
    prompt_log = PromptLog(args.out.parent) if args.prompt_debug else None
    try:
        model = load_ast_json(args.ast_json)
        load_into_model(model, args.requirements_doc, args.requirements_format)
        if llm is None:
            llm = create_llm(
                LLMConfig(
                    backend=args.backend, model=args.model,
                    binary=args.claude_binary, timeout=args.llm_timeout,
                ),
                codebase_root=codebase,
                prompt_log=prompt_log,
            )
        elif prompt_log is not None:
            llm.prompt_log = prompt_log
    except (AstLoadError, RequirementsError, LLMError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    mapped = run_mapping(
        model, llm,
        MappingConfig(category_leak_threshold=args.category_leak_threshold),
    )
    verified = run_verification(
        model, llm, codebase,
        VerificationConfig(max_retries=args.max_retries,
                           batch_size=args.batch_size),
    )
    classified = classify(model)

    try:
        usage = llm.usage
        write_artifact_one(model, args.out, args.ast_json,
                           args.requirements_doc, codebase,
                           llm_usage=usage.as_dict() if usage.calls else None)
        write_artifact_two(model, args.out, args.ast_json,
                           args.requirements_doc, codebase)
    except ArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    _print_summary(args, mapped, verified, classified, llm.usage)
    # D21: exhaustion is partial success — both artifacts are written and
    # valid, and the exit code points the caller at the error notes.
    return EXIT_EXHAUSTED if verified.exhausted else EXIT_OK


def _print_summary(args, mapped, verified, classified, usage=None) -> None:
    print(
        f"mapped {mapped.leaves_mapped} leaf requirements "
        f"({mapped.pairs} pairs, {mapped.empty_leaves} empty, "
        f"{mapped.category_leaks} flagged category_leak)"
    )
    print(
        f"verified {verified.verified}/{verified.pairs_checked} pairs "
        f"({verified.retries_used} retries, {verified.exhausted} exhausted, "
        f"{verified.skipped_category_leak} skipped as category_leak)"
    )
    print(
        f"{classified.structural_test_only}/{classified.total} functions "
        f"tagged structural_test_only"
    )
    if usage is not None and usage.calls:
        print(
            f"llm usage: {usage.calls} calls, "
            f"{usage.input_tokens} input / {usage.output_tokens} output tokens "
            f"({usage.cache_creation_input_tokens} cache-write, "
            f"{usage.cache_read_input_tokens} cache-read), "
            f"${usage.total_cost_usd:.4f} at the provider's reported rates"
        )
    print(f"wrote {args.out}")
    print(f"wrote {artifact_two_path(args.out)}")
    if verified.exhausted:
        print(
            f"{verified.exhausted} mapping(s) removed after exhausting "
            f"verification retries — see the error notes in {args.out}",
            file=sys.stderr,
        )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
