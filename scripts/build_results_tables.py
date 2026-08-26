#!/usr/bin/env python3
"""Regenerate results/summary.csv and the coverage CSVs from one run, so all
four tables come from one script instead of being hand-edited per run.

    scripts/build_results_tables.py --run-dir results/runs/<stamp>_... \
        --mode Meridian --model "Claude Opus 5" --coverage-label meridian_opus-5 \
        [--codebase DIR] [--source-subdir python] [--python INTERPRETER]

Reconstructs a runnable copy of the run's snapshotted tests (the original
generation workdir under /private/tmp is long gone), classifies each test
the same way
scripts/record_run.py does (reusing its run_and_classify), then measures
statement coverage twice: once over every snapshotted test, once over only
the valid ones (passed + findings, i.e. excluding invalid_runtime) — mirror-
ing the coverage_totals.csv vs. coverage_valid_only_totals.csv split, but
computed from a single classification pass instead of two disconnected
manual runs.

Appends one row to each of:
  results/summary.csv
  results/coverage_totals.csv
  results/coverage_valid_only_totals.csv
  results/coverage_valid_only_per_file.csv

Column semantics (fixed by this script, previously inconsistent by hand):
  tests_created    - test FUNCTIONS the generator/agent wrote (not cases)
  tests_executed   - test CASES pytest collected (parametrize expands this)
  valid_tests      - cases that passed
  valid_test_failures - cases that failed on AssertionError (findings)
  invalid_tests    - cases that died on any other exception
Note valid_tests + valid_test_failures is the "valid" total used for
coverage_valid_only_*.csv's valid_pass + valid_findings_assertion_fail.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

RESULTS = REPO / "results"
SUMMARY_CSV = RESULTS / "summary.csv"
COVERAGE_TOTALS_CSV = RESULTS / "coverage_totals.csv"
COVERAGE_VALID_TOTALS_CSV = RESULTS / "coverage_valid_only_totals.csv"
COVERAGE_PER_FILE_CSV = RESULTS / "coverage_valid_only_per_file.csv"

SUMMARY_HEADER = [
    "timestamp_pdt", "software_under_test", "mode", "model", "tests_created",
    "tests_executed", "valid_tests", "valid_test_failures", "invalid_tests",
    "crashed_files", "tokens_out", "reported_cost_usd", "record_dir",
]
COVERAGE_TOTALS_HEADER = ["run", "statements", "missed", "coverage_pct"]
COVERAGE_VALID_TOTALS_HEADER = [
    "run", "statements", "missed", "coverage_pct",
    "valid_pass", "valid_findings_assertion_fail", "invalid_excluded",
]
COVERAGE_PER_FILE_HEADER = ["run", "file", "statements", "missed", "coverage_pct"]

RECONSTRUCTED_CONFTEST = '''"""Reconstructed by build_results_tables.py: the original raw-baseline
conftest (which added the source dir to sys.path and faked sounddevice)
was never snapshotted into results/runs/. This recreates its effect."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("sounddevice", MagicMock())
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
'''


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def pacific_stamp(run_dir_name: str) -> str:
    """Derive a 'YYYY-MM-DD HH:MM' Pacific stamp from a results/runs/ dir
    name's leading UTC timestamp (…nothing else about the run needs to be
    re-derived; this one field is cosmetic and was never in dispute)."""
    import datetime as dt
    from zoneinfo import ZoneInfo

    stamp = run_dir_name.split("_", 1)[0]  # "20260825-051902Z"
    moment = dt.datetime.strptime(stamp, "%Y%m%d-%H%M%SZ").replace(
        tzinfo=dt.timezone.utc)
    local = moment.astimezone(ZoneInfo("America/Los_Angeles"))
    return f"{local:%Y-%m-%d %H:%M}"


def build_workspace(run_dir: Path, codebase: Path, source_subdir: str,
                    workspace: Path) -> Path:
    """workspace/ gets the source .py files at its root (so bare `import
    key_mapping` and Meridian's `_root`/`_root/python` conftest both
    resolve) and workspace/tests/ gets the run's snapshotted test files."""
    src = codebase / source_subdir
    for f in src.glob("*.py"):
        shutil.copy2(f, workspace / f.name)
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    snapshot_tests = run_dir / "tests"
    for f in snapshot_tests.glob("*.py"):
        if f.name != "conftest.py":
            shutil.copy2(f, tests_dir / f.name)
    conftest = snapshot_tests / "conftest.py"
    if conftest.exists():
        shutil.copy2(conftest, tests_dir / "conftest.py")
    else:
        (tests_dir / "conftest.py").write_text(RECONSTRUCTED_CONFTEST,
                                               encoding="utf-8")
    return tests_dir


def classify(python: Path, tests_dir: Path) -> dict:
    """Like scripts/record_run.py's run_and_classify, run per-file in
    isolation, EXCEPT a case already marked @pytest.mark.skip (a prior
    --quarantine pass over this same snapshot) is bucketed as invalid_runtime
    too, carrying forward the reason record_run wrote into the skip mark.
    run_and_classify only checks for a <failure>/<error> JUnit child, so a
    <skipped> case silently falls through to "passed" there — a real gap in
    that function for re-classifying an already-quarantined snapshot, not
    something specific to this script; left unpatched in record_run.py since
    fixing it is a separate decision."""
    import subprocess
    import tempfile
    import xml.etree.ElementTree as ET

    results = {"passed": [], "findings": [], "invalid_runtime": [],
               "crashes": [], "unparsed": []}
    for name in sorted(p.name for p in tests_dir.glob("test_*.py")):
        with tempfile.TemporaryDirectory() as tmp:
            junit = Path(tmp) / "junit.xml"
            try:
                completed = subprocess.run(
                    [str(python), "-m", "pytest", f"tests/{name}", "-q",
                     "-p", "no:cacheprovider", f"--junit-xml={junit}"],
                    cwd=tests_dir.parent, capture_output=True, text=True,
                    timeout=180)
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
                    reason = (skipped.get("message") or "").strip()[:140]
                    results["invalid_runtime"].append(
                        (test, reason or "quarantined (already skip-marked)"))
                    continue
                trouble = case.find("failure")
                if trouble is None:
                    trouble = case.find("error")
                if trouble is None:
                    results["passed"].append(test)
                    continue
                message = (trouble.get("message") or "") + (trouble.text or "")
                first = message.strip().splitlines()[0] if message.strip() else ""
                if "AssertionError" in message or first.startswith("assert"):
                    results["findings"].append((test, first[:140]))
                else:
                    results["invalid_runtime"].append((test, first[:140]))
    return results


def node_ids_by_file(cases: list) -> dict:
    by_file: dict = {}
    for case in cases:
        test = case if isinstance(case, str) else case[0]
        file_name, _, node = test.partition("::")
        by_file.setdefault(file_name, []).append(node)
    return by_file


def measure_coverage(python: Path, tests_dir: Path, source_modules: list,
                     deselect_by_file: dict, skip_files: set,
                     data_file: Path) -> dict:
    """One coverage sweep, per-file (matching HANDOFF's per-file-isolation
    methodology), appended into a single data file. deselect_by_file maps a
    test file's name to node ids to exclude from that file's run — pass {}
    for the 'all tests' sweep. skip_files names whole files to leave out
    entirely (crashed/hung files — nothing meaningful to measure)."""
    data_file.unlink(missing_ok=True)
    for test_file in sorted(tests_dir.glob("test_*.py")):
        if test_file.name in skip_files:
            continue
        command = [str(python), "-m", "coverage", "run", "-a",
                  f"--data-file={data_file}",
                  f"--source={','.join(source_modules)}",
                  "-m", "pytest", f"tests/{test_file.name}", "-q",
                  "-p", "no:cacheprovider"]
        for node in deselect_by_file.get(test_file.name, []):
            command += ["--deselect", f"tests/{test_file.name}::{node}"]
        try:
            subprocess.run(command, cwd=tests_dir.parent, capture_output=True,
                           text=True, timeout=180)
        except subprocess.TimeoutExpired:
            print(f"warning: {test_file.name} hung during coverage "
                  "measurement — skipped", file=sys.stderr)
    report = subprocess.run(
        [str(python), "-m", "coverage", "json", f"--data-file={data_file}",
         "-o", "-"],
        cwd=tests_dir.parent, capture_output=True, text=True, timeout=60)
    if report.returncode != 0:
        fail(f"coverage json failed: {report.stderr}")
    return json.loads(report.stdout)


def append_row(path: Path, header: list, row: list) -> None:
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if is_new:
            writer.writerow(header)
        writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--mode", required=True, choices=("Meridian", "RAW"))
    parser.add_argument("--model", required=True,
                        help='display model name, e.g. "Claude Opus 5"')
    parser.add_argument("--coverage-label", required=True,
                        help='row key for the coverage CSVs, e.g. '
                             '"meridian_opus-5"')
    parser.add_argument("--software-under-test", default="Rainbow Keys")
    parser.add_argument("--codebase", type=Path,
                        default=REPO / "rainbow_keys",
                        help="target app under test (default: the "
                             "rainbow_keys/ copy in this repository)")
    parser.add_argument("--source-subdir", default="python")
    parser.add_argument("--python", type=Path, default=None,
                        help="interpreter that runs the tests (default: "
                             "<codebase>/.venv/bin/python if present, else "
                             "the interpreter running this script — it needs "
                             "pytest, coverage, and numpy installed)")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        fail(f"run dir not found: {run_dir}")
    codebase = args.codebase.resolve()
    python = args.python
    if python is None:
        candidate = codebase / ".venv" / "bin" / "python"
        python = candidate if candidate.exists() else Path(sys.executable)
    if not Path(python).exists():
        fail(f"interpreter not found: {python}")
    source_modules = sorted(
        p.stem for p in (codebase / args.source_subdir).glob("*.py"))
    if not source_modules:
        fail(f"no .py files under {codebase / args.source_subdir}")

    report_path = run_dir / "testgen_report.json"
    if report_path.exists():
        # Authoritative: the generator's own count of functions it wrote.
        # (A naive text search for "def test" would double-count corrupted
        # quarantine skip-marks that swallowed a def line into a string.)
        tests_created = json.loads(report_path.read_text())["counts"]["tests_written"]
    else:
        import re
        tests_created = 0
        for test_file in (run_dir / "tests").glob("test_*.py"):
            tests_created += len(re.findall(
                r"^\s*def test", test_file.read_text(errors="replace"),
                re.MULTILINE))

    tmp = Path(tempfile.mkdtemp(prefix="meridian_build_results_"))
    try:
        tests_dir = build_workspace(run_dir, codebase, args.source_subdir, tmp)
        runtime = classify(python, tests_dir)

        tests_executed = (len(runtime["passed"]) + len(runtime["findings"])
                          + len(runtime["invalid_runtime"]))
        valid_pass = len(runtime["passed"])
        valid_findings = len(runtime["findings"])
        invalid = len(runtime["invalid_runtime"])
        crashed = len(runtime["crashes"])

        crashed_files = {name for name, _ in runtime["crashes"]}
        data_all = tmp / ".coverage.all"
        cov_all = measure_coverage(python, tests_dir, source_modules, {},
                                   crashed_files, data_all)
        invalid_by_file = node_ids_by_file(runtime["invalid_runtime"])
        data_valid = tmp / ".coverage.valid"
        cov_valid = measure_coverage(python, tests_dir, source_modules,
                                     invalid_by_file, crashed_files, data_valid)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    totals_all = cov_all["totals"]
    totals_valid = cov_valid["totals"]
    record_dir = str(run_dir.relative_to(REPO))

    append_row(SUMMARY_CSV, SUMMARY_HEADER, [
        pacific_stamp(run_dir.name), args.software_under_test, args.mode,
        args.model, tests_created, tests_executed, valid_pass, valid_findings,
        invalid, crashed, "", "", record_dir,
    ])
    append_row(COVERAGE_TOTALS_CSV, COVERAGE_TOTALS_HEADER, [
        args.coverage_label, totals_all["num_statements"],
        totals_all["missing_lines"], round(totals_all["percent_covered"]),
    ])
    append_row(COVERAGE_VALID_TOTALS_CSV, COVERAGE_VALID_TOTALS_HEADER, [
        args.coverage_label, totals_valid["num_statements"],
        totals_valid["missing_lines"], round(totals_valid["percent_covered"]),
        valid_pass, valid_findings, invalid,
    ])
    for name, info in sorted(cov_valid["files"].items()):
        summary = info["summary"]
        append_row(COVERAGE_PER_FILE_CSV, COVERAGE_PER_FILE_HEADER, [
            args.coverage_label, Path(name).name, summary["num_statements"],
            summary["missing_lines"], round(summary["percent_covered"]),
        ])
    append_row(COVERAGE_PER_FILE_CSV, COVERAGE_PER_FILE_HEADER, [
        args.coverage_label, "TOTAL", totals_valid["num_statements"],
        totals_valid["missing_lines"], round(totals_valid["percent_covered"]),
    ])

    print(f"{args.coverage_label}: {valid_pass + valid_findings} valid "
          f"({valid_pass} pass, {valid_findings} findings), {invalid} "
          f"invalid; coverage {round(totals_all['percent_covered'])}% all / "
          f"{round(totals_valid['percent_covered'])}% valid-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
