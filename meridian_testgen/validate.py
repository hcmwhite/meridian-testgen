"""Mechanical validation of generated tests, and the retry loop (D25a, D27).

A generated test is *mechanically valid* when three things hold, all decided
with the target codebase's own interpreter (D23) and never with the one
running this tool:

1. it compiles — ``<python> -m py_compile`` on the source;
2. every test function in it carries the D29 traceability comment
   ``# meridian: unit_id=<id> requirement=<code>``;
3. it collects — ``<python> -m pytest --collect-only`` against the file put in
   place inside the codebase's ``test/`` directory, so its imports resolve the
   way they will for the user.

That is the whole verdict. Stage 3 never runs the tests (D26): a test that
collects is done, and one that would fail at runtime is a finding about the
code, not a reason to generate again.

A test that fails any check is a generation failure and takes the D27 retry
path: the item is re-asked with its specific failure reason in the prompt, up
to ``--max-retries`` times, and only the failed items of a batch are re-sent
(D28). An item that exhausts its attempts contributes no test and leaves an
error note recording every attempt and its reason, for the report to print.
Nothing is dropped silently.
"""

from __future__ import annotations

import ast
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from meridian_testgen.generate import (
    DEFAULT_BATCH_SIZE,
    GroupedTest,
    batches,
    build_items,
    generate,
    group_key,
)
from meridian_testgen.llm import GeneratedTest, LLMError
from meridian_testgen.runlog import CHECKPOINT_NAME, Checkpoint, RunLog
# --- codex generated ---
from meridian_testgen.codex_safety_profile import (
    SafetyProfile,
    default_safety_profile,
    unsafe_test_calls,
)
# --- end codex generated ---

LOG = logging.getLogger("meridian_testgen.validate")

DEFAULT_MAX_RETRIES = 2

STAGE_SYNTAX = "syntax"
STAGE_TRACEABILITY = "traceability"
STAGE_COLLECTION = "collection"
STAGE_MISSING = "missing"
# --- codex generated ---
STAGE_RESOURCE_SAFETY = "resource_safety"
# --- end codex generated ---

# The D29 comment, as validation reads it back off the generated source.
TRACEABILITY_RE = re.compile(
    r"#\s*meridian:\s*unit_id=(?P<unit_id>\S+)\s+requirement=(?P<requirement>\S+)"
)

# The reason recorded when the model answered for other items in a batch but
# not this one; it is a generation failure like any other (D27).
NO_ANSWER_REASON = "the model returned no test for this item"

# How long one interpreter subprocess may take before we call it a failure.
SUBPROCESS_TIMEOUT = 120.0


@dataclass(frozen=True)
class ValidationResult:
    """The verdict on one generated test source."""

    __test__ = False

    ok: bool
    stage: "str | None" = None
    reason: "str | None" = None


@dataclass
class ValidationSummary:
    """What the retry loop did, in counts the CLI and the report print."""

    __test__ = False

    items: int = 0
    valid: int = 0
    exhausted: int = 0
    attempts: int = 0
    retries_used: int = 0
    calls: int = 0
    skipped_category_leak: int = 0


@dataclass
class ValidationRun:
    """The loop's result: the tests that survived, and the notes for the rest."""

    __test__ = False

    # group key -> [GroupedTest], in item order — what the writer writes.
    groups: dict = field(default_factory=dict)
    # One note per exhausted item (D27), in item order.
    error_notes: list = field(default_factory=list)
    summary: ValidationSummary = field(default_factory=ValidationSummary)
    # The incremental checkpoint this run wrote; the caller clears it once
    # the real outputs are safely on disk.
    checkpoint: "Checkpoint | None" = None
    # Every attempt validation rejected — including ones whose item later
    # recovered on retry. This is the "invalid tests Meridian caught" record;
    # error_notes holds only the items that never recovered.
    validation_catches: list = field(default_factory=list)


def _run(interpreter, argv, cwd=None) -> subprocess.CompletedProcess:
    """One interpreter subprocess, with its output captured as text."""
    command = [str(interpreter)] + [str(part) for part in argv]
    try:
        return subprocess.run(
            command, cwd=None if cwd is None else str(cwd),
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT,
        )
    except OSError as exc:
        raise ValidationEnvironmentError(
            f"could not run the configured interpreter {interpreter}: {exc}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise ValidationEnvironmentError(
            f"the configured interpreter {interpreter} did not finish "
            f"{' '.join(command[1:3])} within {SUBPROCESS_TIMEOUT:.0f}s"
        ) from exc


class ValidationEnvironmentError(Exception):
    """The resolved interpreter could not be run at all — exit 2 territory."""


def _first_lines(text: str, limit: int = 6) -> str:
    """The useful head of a subprocess's complaint, for the retry prompt."""
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    return " / ".join(lines[-limit:]) if lines else ""


def check_syntax(interpreter, source: str) -> "str | None":
    """``<python> -m py_compile`` on *source*; the reason it failed, or None."""
    with tempfile.TemporaryDirectory(prefix="meridian-testgen-") as tmp:
        path = Path(tmp) / "candidate.py"
        path.write_text(source, encoding="utf-8")
        completed = _run(interpreter, ["-m", "py_compile", path])
    if completed.returncode == 0:
        return None
    detail = _first_lines(completed.stderr) or _first_lines(completed.stdout)
    return f"the generated test does not compile: {detail}"


def check_traceability(source: str, item) -> "str | None":
    """Every test function carries the D29 comment for *item*, or the reason not."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:  # pragma: no cover - syntax is checked first
        return f"the generated test does not parse: {exc}"

    lines = source.splitlines()
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    ]
    expected = f"# meridian: unit_id={item.unit_id} requirement={item.requirement_code}"
    if not functions:
        return (
            "the generated test defines no test function, so the required "
            f"traceability comment '{expected}' has nowhere to live"
        )
    for node in functions:
        start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
        end = getattr(node, "end_lineno", node.lineno)
        found = False
        for line in lines[max(0, start - 1):end]:
            match = TRACEABILITY_RE.search(line)
            if (match and match.group("unit_id") == item.unit_id
                    and match.group("requirement") == item.requirement_code):
                found = True
                break
        if not found:
            return (
                f"test function {node.name} is missing the required "
                f"traceability comment '{expected}'"
            )
    return None


def check_collection(interpreter, source: str, codebase_root) -> "str | None":
    """``--collect-only`` on the file put in place under ``<codebase>/test/``.

    The file is written where the generated tests will live so its imports
    resolve as they will for the user, under a name of our own that is removed
    again whatever happens — no file that is not ours is touched (D24).
    """
    directory = generated_test_dir(codebase_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "test__meridian_collect_check.py"
    try:
        path.write_text(source, encoding="utf-8")
        completed = _run(
            interpreter,
            ["-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
             path.name],
            cwd=directory,
        )
    finally:
        path.unlink(missing_ok=True)
    if completed.returncode == 0:
        return None
    if completed.returncode == 5:
        return "the generated test collects no tests under pytest"
    detail = _first_lines(completed.stdout) or _first_lines(completed.stderr)
    return f"the generated test does not collect under pytest: {detail}"


def generated_test_dir(codebase_root) -> Path:
    """Where generated tests live: ``<codebase>/test/`` (D24)."""
    return Path(codebase_root) / "test"


CONFTEST_NAME = "conftest.py"


def ensure_conftest(codebase_root, source_dirs) -> bool:
    """Give the generated tests a working import path, once.

    Tests collected from ``test/`` cannot import a codebase whose modules sit
    in bare directories (no ``__init__.py``) — on the first live run every
    import style the model tried bounced off ``ModuleNotFoundError``
    (2026-08-24). This writes ``test/conftest.py`` putting the codebase root
    and every directory that holds a parsed source file on ``sys.path``, so a
    module imports by its file stem. Created ONLY when absent — an existing
    conftest belongs to the user and is never touched (D24's spirit).

    Returns True when the file was written.
    """
    directory = generated_test_dir(codebase_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / CONFTEST_NAME
    if path.exists():
        return False
    dirs = sorted(d for d in {str(d) for d in source_dirs} if d and d != ".")
    path.write_text(
        '"""Written by meridian-testgen so its generated tests can import the\n'
        'code under test. Yours to edit; recreated only if absent."""\n'
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "_root = Path(__file__).resolve().parent.parent\n"
        f"for _extra in [_root] + [_root / d for d in {dirs!r}]:\n"
        "    if str(_extra) not in sys.path:\n"
        "        sys.path.insert(0, str(_extra))\n",
        encoding="utf-8",
    )
    return True


def source_dirs_of(model) -> list:
    """The relative directories holding the parsed source files."""
    from pathlib import PurePosixPath

    return sorted({
        str(PurePosixPath(f.record.get("file_path", "")).parent)
        for f in model.functions.values()
    } - {"", "."})


def validate_test(item, source: str, interpreter, codebase_root,
                  safety_profile: "SafetyProfile | None" = None) -> ValidationResult:
    """The three D25a checks, in the order that fails cheapest first."""
    reason = check_syntax(interpreter, source)
    if reason is not None:
        return ValidationResult(False, STAGE_SYNTAX, reason)
    reason = check_traceability(source, item)
    if reason is not None:
        return ValidationResult(False, STAGE_TRACEABILITY, reason)
    # --- codex generated ---
    unsafe = unsafe_test_calls(source, safety_profile or default_safety_profile())
    if unsafe:
        rendered = ", ".join(f"{kind}: {call}" for kind, call in unsafe)
        return ValidationResult(
            False, STAGE_RESOURCE_SAFETY,
            "the generated test directly calls denied external resource APIs: "
            f"{rendered}; mock or fake the boundary instead",
        )
    # --- end codex generated ---
    reason = check_collection(interpreter, source, codebase_root)
    if reason is not None:
        return ValidationResult(False, STAGE_COLLECTION, reason)
    return ValidationResult(True)


def error_note(item, attempts: list) -> dict:
    """The D27 record of an item that never produced a valid test.

    Shape follows stage 2's error notes deliberately: the identity, then one
    entry per attempt with its 1-based number, the stage that rejected it and
    the reason, so the report can print the whole history rather than a last
    word.
    """
    return {
        "unit_id": item.unit_id,
        "requirement_code": item.requirement_code,
        "dotted_name": item.dotted_name,
        "file_path": item.file_path,
        "line_number": item.line_number,
        "attempts": list(attempts),
    }


def generate_and_validate(model, llm, codebase_root, interpreter,
                          batch_size: int = DEFAULT_BATCH_SIZE,
                          max_retries: int = DEFAULT_MAX_RETRIES,
                          items=None, out_dir=None,
                          safety_profile: "SafetyProfile | None" = None) -> ValidationRun:
    """Generate, validate, retry the failures, and write down the exhausted.

    Attempts per item are ``max_retries + 1`` (three by default, D27). Each
    round re-drives *only* the items that failed the last one, each carrying
    its own failure reason (D28), so a passing item from a mixed batch is
    never re-asked and never re-validated.

    With *out_dir*, every progress line also lands timestamped in
    ``testgen_run.log`` there, and every decided item is appended to
    ``testgen_checkpoint.jsonl`` the moment it is decided — a killed run
    resumes from the checkpoint instead of starting over, and the caller
    deletes it (``run.checkpoint.clear()``) once the real outputs are
    written.
    """
    if items is None:
        items, generation_summary = build_items(
            model, codebase_root,
            # --- codex generated ---
            safety_profile=safety_profile,
            # --- end codex generated ---
        )
        skipped = generation_summary.skipped_category_leak
    else:
        items = list(items)
        skipped = 0

    runlog = RunLog(out_dir)
    checkpoint = Checkpoint(
        out_dir, str(model.ast_meta.get("generated_at", "")))

    if ensure_conftest(codebase_root, source_dirs_of(model)):
        runlog.say("wrote test/conftest.py so generated tests can import "
                   "the code under test")

    run = ValidationRun()
    run.checkpoint = checkpoint
    run.summary.items = len(items)
    run.summary.skipped_category_leak = skipped

    mapped = sum(1 for i in items if not i.is_structural)
    runlog.say(
        f"generating {len(items)} tests ({mapped} requirement-mapped, "
        f"{len(items) - mapped} structural"
        + (f"; {skipped} pairs skipped as category_leak" if skipped else "")
        + ")"
    )

    accepted: dict = {}
    history: dict = {item.key: [] for item in items}
    original = {item.key: item for item in items}

    if checkpoint.stale:
        runlog.say("found a checkpoint from different inputs — starting fresh")
    done = checkpoint.decided & set(original)
    if done:
        runlog.say(
            f"resuming: {len(done)} of {len(items)} items already decided in "
            f"{CHECKPOINT_NAME} ({len(checkpoint.valid)} valid, "
            f"{len(checkpoint.exhausted)} exhausted)"
        )
        for key, source in checkpoint.valid.items():
            if key in original:
                item = original[key]
                accepted[key] = GroupedTest(
                    item, GeneratedTest(key[0], key[1], source))
        for key, attempts in checkpoint.exhausted.items():
            if key in original:
                history[key] = list(attempts)

    pending = [item for item in items if item.key not in done]

    for attempt in range(1, max(1, max_retries + 1) + 1):
        if not pending:
            break
        if attempt > 1:
            run.summary.retries_used += len(pending)
            runlog.say(
                f"retrying {len(pending)} failed test(s), attempt {attempt}…")
        # One BATCH at a time: generate it, validate its items, checkpoint
        # the decisions — then the next batch. Validating only after a whole
        # round had generated meant a kill mid-round still lost every call
        # (found on the very first look at the live checkpoint, 2026-08-23);
        # now at most one call's work is ever un-checkpointed.
        retry: list = []
        generated_so_far = 0
        for batch in batches(pending, batch_size):
            # generate() contains a call failure to its own batch and reports
            # it in call_failures; an LLMError escaping it means nothing was
            # asked at all (kept as a backstop so one broken call still
            # cannot crash the run or silently drop items).
            try:
                generated = generate(model, llm, codebase_root,
                                     batch_size=batch_size, items=batch,
                                     runlog=runlog,
                                     progress_offset=generated_so_far,
                                     progress_total=len(pending))
                results = generated.results
                call_failures = generated.call_failures
                run.summary.calls += generated.summary.calls
            except LLMError as exc:
                results = {}
                LOG.warning("generation failed on attempt %d: %s", attempt, exc)
                failure = f"the model could not be reached: {exc}"
                call_failures = {item.key: failure for item in batch}
            generated_so_far += len(batch)

            for item in batch:
                run.summary.attempts += 1
                test = results.get(item.key)
                if test is None:
                    stage = STAGE_MISSING
                    reason = call_failures.get(item.key) or NO_ANSWER_REASON
                else:
                    verdict = validate_test(
                        item, test.source, interpreter, codebase_root,
                        # --- codex generated ---
                        safety_profile=safety_profile,
                        # --- end codex generated ---
                    )
                    if verdict.ok:
                        accepted[item.key] = GroupedTest(original[item.key], test)
                        checkpoint.record_valid(item.key, test.source)
                        runlog.say(f"  valid: {item.dotted_name} / "
                                   f"{item.requirement_code}")
                        continue
                    stage, reason = verdict.stage, verdict.reason
                history[item.key].append(
                    {"attempt": attempt, "stage": stage, "reason": reason}
                )
                run.validation_catches.append({
                    "unit_id": item.unit_id,
                    "dotted_name": item.dotted_name,
                    "requirement": item.requirement_code,
                    "attempt": attempt,
                    "stage": stage,
                    "reason": reason,
                })
                runlog.say(f"  failed ({stage}): {item.dotted_name} / "
                           f"{item.requirement_code} — {str(reason)[:110]}")
                retry.append(item.with_failure(reason))
        pending = retry

    for item in items:
        grouped = accepted.get(item.key)
        if grouped is None:
            if item.key not in checkpoint.exhausted:
                checkpoint.record_exhausted(item.key, history[item.key])
            run.error_notes.append(error_note(item, history[item.key]))
            continue
        run.groups.setdefault(group_key(item), []).append(grouped)

    run.summary.valid = len(accepted)
    run.summary.exhausted = len(run.error_notes)
    model.generated_groups = run.groups
    return run
