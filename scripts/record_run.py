#!/usr/bin/env python3
"""Record one test-generation run under results/runs/, reproducibly.

    scripts/record_run.py --report <testgen_report.json> [--system NAME]
                          [--backend NAME] [--model NAME] [--note TEXT]

Creates ``results/runs/<UTC time>_<system>_<backend>/`` holding:

* ``report.md`` — when the run happened, what system was under test, which
  LLM answered, the commands that reproduce each pipeline stage, and the
  counts (items, generated test functions, retries, cost).
* ``testgen_report.json`` and the run/prompt logs found beside it — copied,
  so the record survives later runs overwriting the working directory.
* ``tests/`` — a snapshot of every generated test file the report names,
  taken the same way every time.

``--backend``/``--model`` override what the report's ``invocation`` block
says, for reports written before that block existed. The utility never
modifies its inputs; it only copies.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO / "results" / "runs"


def fail(message: str) -> "None":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def load_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"could not read report {path}: {exc}")


def reproduction_commands(report: dict, backend: str, model: str) -> list[str]:
    """The pipeline, stage by stage, as commands that rerun it."""
    mapper_env = report.get("requirements_run", {})
    parser_env = mapper_env.get("source_run", {})
    inputs = report.get("inputs", {})
    commands = []
    if parser_env:
        commands.append(
            f"meridian-parser {parser_env.get('input_dir', '<codebase>')} "
            f"--out {mapper_env.get('ast_json', 'ast.json')}"
            f"   # {parser_env.get('tool', '')}, codebase commit "
            f"{parser_env.get('git_commit', '?')}"
        )
    if mapper_env:
        commands.append(
            f"meridian-mapper {mapper_env.get('ast_json', 'ast.json')} "
            f"{mapper_env.get('requirements_doc', '<requirements>')} "
            f"{mapper_env.get('codebase', '<codebase>')} "
            f"--out {inputs.get('mapping_ast', 'mapping_ast.json')}"
            f"   # {mapper_env.get('tool', '')}"
        )
    invocation = report.get("invocation")
    if invocation and invocation.get("argv"):
        commands.append("meridian-testgen " + " ".join(invocation["argv"]))
    else:
        commands.append(
            f"meridian-testgen {inputs.get('mapping_ast', '?')} "
            f"{inputs.get('mapping_requirements', '?')} "
            f"{inputs.get('codebase', '?')} "
            f"--out-dir {inputs.get('out_dir', '?')} --backend {backend}"
            + (f" --model {model}" if model and "default" not in model else "")
            + "   # argv reconstructed — report predates invocation recording"
        )
    return commands


def run_and_classify(report: dict, test_dir: Path) -> "dict | None":
    """Execute each snapshot test file in isolation; classify every outcome.

    The buckets a results report needs:

    * ``passed`` — valid tests agreeing with the code.
    * ``findings`` — tests that ran and failed on an **AssertionError**: the
      test itself is valid, the disagreement is with the code (or the
      requirement). Candidate findings for human triage.
    * ``invalid_runtime`` — tests that died on any other exception
      (``KeyError``, ``TypeError``, …): the test is defective in a way only
      execution reveals; Meridian's mechanical validation cannot catch these.
    * ``crashes`` — files that killed the interpreter or hung: a resource
      boundary was not isolated.

    Uses the interpreter the report names. Returns None when it cannot run.
    """
    import subprocess
    import tempfile
    import xml.etree.ElementTree as ET

    interpreter = report.get("interpreter", {}).get("path")
    if not interpreter or not Path(interpreter).exists():
        return None
    results = {"passed": [], "findings": [], "invalid_runtime": [],
               "crashes": [], "unparsed": []}
    for name in sorted(p.name for p in test_dir.glob("test_*.py")):
        with tempfile.TemporaryDirectory() as tmp:
            junit = Path(tmp) / "junit.xml"
            try:
                completed = subprocess.run(
                    [interpreter, "-m", "pytest", name, "-q",
                     "-p", "no:cacheprovider", f"--junit-xml={junit}"],
                    cwd=test_dir, capture_output=True, text=True, timeout=180,
                )
            except subprocess.TimeoutExpired:
                results["crashes"].append((name, "hung past 180s"))
                continue
            if completed.returncode < 0:
                results["crashes"].append(
                    (name, f"killed by signal {-completed.returncode}"))
                continue
            if not junit.exists():
                results["unparsed"].append((name, f"exit {completed.returncode}"))
                continue
            for case in ET.parse(junit).getroot().iter("testcase"):
                test = f"{name}::{case.get('name')}"
                skipped = case.find("skipped")
                if skipped is not None:
                    # Already quarantined on a previous pass — still invalid,
                    # not passed; keep the recorded reason.
                    reason = (skipped.get("message") or "").strip()
                    results["invalid_runtime"].append(
                        (test, reason[:140] or "quarantined (skip-marked)"))
                    continue
                trouble = case.find("failure")
                if trouble is None:
                    trouble = case.find("error")
                if trouble is None:
                    results["passed"].append(test)
                    continue
                message = ((trouble.get("message") or "") + "\n"
                           + (trouble.text or ""))
                first = message.strip().splitlines()[0] if message.strip() else ""
                if "AssertionError" in message or first.startswith("assert"):
                    results["findings"].append((test, first[:140]))
                else:
                    results["invalid_runtime"].append((test, first[:140]))
    return results


def quarantine_invalid(test_dir: Path, runtime: dict) -> list[str]:
    """Mark runtime-invalid tests no-execute, in place, with the reason.

    A test function is quarantined only when EVERY executed case of it was
    invalid (a parametrized function with some valid cases is left alone
    rather than silencing them). The mark is a plain
    ``@pytest.mark.skip(reason="meridian: …")`` decorator inserted above the
    function — visible, reversible, and self-explaining in the file itself.
    Returns the ``file::function`` names marked.
    """
    import ast as pyast

    def function_of(test: str) -> tuple[str, str]:
        file_part, _, case = test.partition("::")
        return file_part, case.partition("[")[0]

    healthy = {function_of(t) for t in runtime["passed"]}
    healthy |= {function_of(t) for t, _ in runtime["findings"]}
    doomed: dict = {}
    for test, why in runtime["invalid_runtime"]:
        key = function_of(test)
        if key not in healthy:
            doomed.setdefault(key, why)

    marked: list[str] = []
    by_file: dict = {}
    for (file_name, func), why in doomed.items():
        by_file.setdefault(file_name, {})[func] = why
    for file_name, functions in sorted(by_file.items()):
        path = test_dir / file_name
        try:
            source = path.read_text(encoding="utf-8")
            tree = pyast.parse(source)
        except (OSError, SyntaxError):
            continue
        lines = source.splitlines()
        inserts: list[tuple[int, str]] = []
        needs_pytest = "import pytest" not in source
        for node in pyast.walk(tree):
            if not isinstance(node, (pyast.FunctionDef, pyast.AsyncFunctionDef)):
                continue
            why = functions.get(node.name)
            if why is None:
                continue
            if any("meridian:" in lines[d.lineno - 1]
                   for d in node.decorator_list):
                continue   # already quarantined on a previous pass
            first = min([node.lineno] + [d.lineno for d in node.decorator_list])
            indent = lines[first - 1][:len(lines[first - 1])
                                      - len(lines[first - 1].lstrip())]
            reason = why.replace('"', "'")[:120]
            inserts.append((first - 1,
                            f'{indent}@pytest.mark.skip(reason="meridian: '
                            f'invalid at runtime — {reason}")'))
            marked.append(f"{file_name}::{node.name}")
        if not inserts:
            continue
        for index, text in sorted(inserts, reverse=True):
            lines.insert(index, text)
        if needs_pytest:
            lines.insert(0, "import pytest")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return marked


def catches_from(report: dict, report_dir: Path) -> list[dict]:
    """Validation catches, from the report or (older runs) the run log."""
    catches = report.get("validation_catches")
    if catches:
        return catches
    log = report_dir / "testgen_run.log"
    if not log.exists():
        return []
    found = []
    for line in log.read_text(errors="replace").splitlines():
        if "  failed (" not in line:
            continue
        _, _, rest = line.partition("  failed (")
        stage, _, detail = rest.partition("): ")
        who, _, reason = detail.partition(" — ")
        found.append({"stage": stage, "dotted_name": who.split(" / ")[0],
                      "requirement": (who.split(" / ") + [""])[1],
                      "reason": reason, "attempt": "?"})
    return found


def pacific(iso_utc: "str | None") -> str:
    """An ISO UTC stamp rendered in Pacific time (the paper's timezone),
    with the UTC original kept in parentheses for cross-referencing logs."""
    if not iso_utc:
        return "unknown"
    import datetime as dt
    from zoneinfo import ZoneInfo

    try:
        moment = dt.datetime.fromisoformat(str(iso_utc))
    except ValueError:
        return str(iso_utc)
    local = moment.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"{local:%Y-%m-%d %H:%M %Z} ({iso_utc} UTC)"


def write_markdown(destination: Path, report: dict, system: str, backend: str,
                   model: str, note: str, snapshot: list[str],
                   runtime: "dict | None" = None,
                   catches: "list[dict] | None" = None,
                   quarantined: "list[str] | None" = None) -> None:
    counts = report.get("counts", {})
    usage = report.get("llm_usage", {})
    interpreter = report.get("interpreter", {})
    lines = [
        f"# Test-generation run — {system} — {backend}",
        "",
        f"- **Date/time:** {pacific(report.get('generated_at'))}",
        f"- **System under test:** {system} "
        f"(`{report.get('inputs', {}).get('codebase', '?')}`)",
        f"- **LLM:** backend `{backend}`, model `{model}`",
        f"- **Tool:** {report.get('tool', '?')}",
        f"- **Validation interpreter:** `{interpreter.get('path', '?')}` "
        f"(resolved from {interpreter.get('source', '?')})",
    ]
    if note:
        lines.append(f"- **Note:** {note}")
    if runtime is not None:
        total = (len(runtime["passed"]) + len(runtime["findings"])
                 + len(runtime["invalid_runtime"]))
        lines += [
            "",
            "## Results — runtime verdicts",
            "",
            f"- **Valid tests generated: "
            f"{len(runtime['passed']) + len(runtime['findings'])}** of "
            f"{total} executed "
            f"({len(runtime['passed'])} pass; {len(runtime['findings'])} are "
            f"valid failures)",
            f"- Invalid tests that escaped to runtime: "
            f"{len(runtime['invalid_runtime'])} (died on a non-assertion "
            f"exception — defective test, not a finding)",
            f"- Files that crashed or hung: {len(runtime['crashes'])}",
            "",
            "*A failure on `AssertionError` means the test ran validly and "
            "disagreed with the code — a candidate finding pending human "
            "triage. Any other exception means the test itself is wrong.*",
            "",
            "### Valid failures discovered (candidate findings)",
            "",
            *([f"- `{test}` — {why}" for test, why in runtime["findings"]]
              or ["- (none)"]),
            "",
            "### Invalid tests that escaped to runtime",
            "",
            *([f"- `{test}` — {why}" for test, why in runtime["invalid_runtime"]]
              or ["- (none)"]),
        ]
        if quarantined:
            lines += [
                "",
                "### Quarantined",
                "",
                f"{len(quarantined)} wholly-invalid test function(s) were "
                "marked `@pytest.mark.skip` in place, each with its failure "
                "as the reason — the delivered suite executes only valid "
                "tests. Remove a decorator to reinstate one:",
                "",
                *[f"- `{name}`" for name in quarantined],
            ]
        if runtime["crashes"]:
            lines += ["", "### Crashed files", ""] + [
                f"- `{name}` — {why}" for name, why in runtime["crashes"]]
        if runtime["unparsed"]:
            lines += ["", "### Files that could not be judged", ""] + [
                f"- `{name}` — {why}" for name, why in runtime["unparsed"]]
    if catches is not None:
        by_stage: dict = {}
        for catch in catches:
            by_stage.setdefault(catch.get("stage", "?"), []).append(catch)
        lines += [
            "",
            "## Invalid tests caught by Meridian during generation",
            "",
            f"- **{len(catches)} rejected attempt(s)**, each retried with "
            "the reason in the prompt"
            + ("" if catches else " — every attempt validated first time"),
        ]
        for stage, group in sorted(by_stage.items()):
            lines.append(f"- {stage}: {len(group)}")
            for catch in group[:6]:
                lines.append(
                    f"  - {catch.get('dotted_name', '?')} / "
                    f"{catch.get('requirement', '?')} — "
                    f"{str(catch.get('reason', ''))[:120]}")
    lines += [
        "",
        "## Generation counts",
        "",
        f"- Items (function–requirement pairs + structural): "
        f"{counts.get('items', '?')}",
        f"- Items that produced a mechanically valid test: "
        f"{counts.get('valid', '?')}",
        f"- **Test functions generated: {counts.get('tests_written', '?')}** "
        f"across {counts.get('files_written', '?')} files",
        f"- Retries used: {counts.get('retries_used', '?')}; exhausted: "
        f"{counts.get('exhausted', '?')}; skipped as category_leak: "
        f"{report.get('skipped_category_leak', '?')}",
        f"- LLM calls: {counts.get('llm_calls', '?')}; reported cost: "
        f"${usage.get('total_cost_usd', 0):.4f} "
        f"({usage.get('input_tokens', 0)} in / {usage.get('output_tokens', 0)}"
        f" out tokens; zeros mean the backend reports no usage)",
        "",
        "## Reproduce",
        "",
        "```sh",
        *reproduction_commands(report, backend, model),
        "```",
        "",
        "## Snapshot",
        "",
        "Generated test files copied into `tests/` beside this report:",
        "",
        *[f"- `{name}`" for name in snapshot],
        "",
    ]
    (destination / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record a test-generation run under results/runs/.")
    parser.add_argument("--report", type=Path, required=True,
                        help="the run's testgen_report.json")
    parser.add_argument("--system", default=None,
                        help="name of the system under test (default: the "
                             "codebase directory's base name)")
    parser.add_argument("--backend", default=None,
                        help="override the LLM backend name for reports that "
                             "did not record it")
    parser.add_argument("--model", default=None,
                        help="override the model name likewise")
    parser.add_argument("--note", default="",
                        help="free-text note for the report")
    parser.add_argument("--run-tests", action="store_true",
                        help="execute each generated test file (in its "
                             "original location, isolated per file) and "
                             "classify every outcome into the results report")
    parser.add_argument("--quarantine", action="store_true",
                        help="with --run-tests: mark each wholly-invalid "
                             "test function @pytest.mark.skip in place (its "
                             "failure as the reason) before snapshotting, so "
                             "the delivered suite executes only valid tests")
    parser.add_argument("--force", action="store_true",
                        help="re-record over an existing record directory")
    args = parser.parse_args()

    if not args.report.is_file():
        fail(f"report not found: {args.report}")
    report = load_report(args.report)

    invocation = report.get("invocation", {})
    backend = args.backend or invocation.get("backend") or "unrecorded"
    model = args.model or invocation.get("model") or "backend default (unrecorded)"
    codebase = report.get("inputs", {}).get("codebase", "")
    system = args.system or (Path(codebase).name if codebase else "unknown")

    stamp = str(report.get("generated_at", "")).replace(":", "").replace("-", "")
    stamp = stamp.replace("+0000", "Z").replace("T", "-") or "undated"
    destination = RUNS_DIR / f"{stamp}_{system}_{backend}"
    if destination.exists():
        if not args.force:
            fail(f"{destination} already exists — this run looks recorded "
                 "already (pass --force to re-record)")
        shutil.rmtree(destination)
    (destination / "tests").mkdir(parents=True)

    # Copy the report and every log sitting beside it.
    shutil.copy2(args.report, destination / "testgen_report.json")
    for pattern in ("testgen_run.log", "prompts-*.log", "testgen.stderr"):
        for found in sorted(args.report.parent.glob(pattern)):
            shutil.copy2(found, destination / found.name)

    test_paths = [Path(f["path"]) for f in report.get("test_files", [])]

    # Run/classify (and optionally quarantine) BEFORE the snapshot, so the
    # snapshot records the state the suite is actually delivered in.
    runtime = None
    quarantined: list[str] = []
    if args.run_tests:
        # Run in the ORIGINAL test directory: the conftest shim resolves the
        # codebase relative to itself, so the snapshot copies cannot import.
        if test_paths and test_paths[0].parent.is_dir():
            runtime = run_and_classify(report, test_paths[0].parent)
        if runtime is None:
            print("warning: --run-tests skipped — the original test "
                  "directory or interpreter is gone", file=sys.stderr)
        elif args.quarantine and runtime["invalid_runtime"]:
            quarantined = quarantine_invalid(test_paths[0].parent, runtime)
            print(f"quarantined {len(quarantined)} invalid test(s) with "
                  f"@pytest.mark.skip, reasons attached")

    # Snapshot the generated tests the report names, plus the conftest shim.
    snapshot: list[str] = []
    missing: list[str] = []
    if test_paths:
        shim = test_paths[0].parent / "conftest.py"
        if shim.exists():
            test_paths.append(shim)
    for path in test_paths:
        if path.is_file():
            shutil.copy2(path, destination / "tests" / path.name)
            snapshot.append(path.name)
        else:
            missing.append(str(path))
    if missing:
        print("warning: generated files named by the report are gone and "
              "were not snapshotted:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)

    write_markdown(destination, report, system, backend, model, args.note,
                   snapshot, runtime, catches_from(report, args.report.parent),
                   quarantined)
    print(f"recorded: {destination.relative_to(REPO)}")
    print(f"  report.md, testgen_report.json, {len(snapshot)} test file(s)")
    if runtime is not None:
        valid = len(runtime["passed"]) + len(runtime["findings"])
        print(f"  runtime: {valid} valid tests ({len(runtime['findings'])} "
              f"valid failures), {len(runtime['invalid_runtime'])} invalid "
              f"escaped, {len(runtime['crashes'])} crashed file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
