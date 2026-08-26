#!/usr/bin/env python3
"""RAW baseline: un-orchestrated test generation, measured Meridian's way.

    scripts/raw_baseline.py --codebase <dir> --backend claude|codex
                            [--model ID] [--python <interpreter>]
                            [--system NAME] [--timeout 1800]

One naive prompt — "Create unit tests for the app in <dir>" — is given to a
coding agent (claude or codex CLI) with write access to a FRESH TEMP COPY of
the codebase, so nothing it writes can collide with Meridian's generated
tests or the real project. No obligations, no mocking rules, no import
hints: the whole point is to measure what a frontier model does without
Meridian's structure.

The numbers are then computed by this script, not asked of the model, using
the same per-file, exception-classified execution as scripts/record_run.py:

* tests created (count of test functions), lines of test code;
* valid tests (pass, or fail on an AssertionError — a valid test whose
  disagreement is with the code);
* valid test failures (the AssertionError subset, listed);
* invalid tests (died on any other exception) and crashed/hung files;
* tokens out / cost where the backend's envelope reports them (claude does;
  codex reports none).

The record lands under results/runs/<UTC time>_<system>_raw-<backend>/ in
the same report.md shape as an orchestrated run, with the generated tests
snapshotted beside it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO / "results" / "runs"
sys.path.insert(0, str(REPO / "scripts"))
from record_run import pacific, run_and_classify  # noqa: E402  (shared)

RAW_TEST_DIR = "raw_tests"

PROMPT = """Create unit tests for the app in {workdir}.

Write them as pytest test files in a new directory named {workdir}/{testdir}/.
Make sure the tests can be run with: python -m pytest {testdir}/
Do not modify any existing file."""


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(2)


def claude_command(prompt: str, model: "str | None", workdir: Path) -> list[str]:
    command = ["claude", "-p", prompt, "--output-format", "json",
               "--permission-mode", "bypassPermissions",
               "--add-dir", str(workdir)]
    if model:
        command += ["--model", model]
    return command


def codex_command(prompt: str, model: "str | None", workdir: Path) -> list[str]:
    command = ["codex", "exec", "--json", "--sandbox", "workspace-write",
               "--skip-git-repo-check", "-C", str(workdir)]
    if model:
        command += ["--model", model]
    command.append(prompt)
    return command


def claude_usage(stdout: str) -> dict:
    """Tokens and cost out of the claude CLI's JSON envelope."""
    try:
        envelope = json.loads(stdout)
    except ValueError:
        return {}
    usage = envelope.get("usage") or {}
    return {
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
        "total_cost_usd": envelope.get("total_cost_usd", 0.0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Un-orchestrated (RAW) test-generation baseline.")
    parser.add_argument("--codebase", type=Path, required=True)
    parser.add_argument("--backend", choices=("claude", "codex"), required=True)
    parser.add_argument("--model", default=None,
                        help="model id (claude default: the CLI's default; "
                             "codex default: its local configuration)")
    parser.add_argument("--python", type=Path, default=None,
                        help="interpreter that runs the generated tests "
                             "(default: <codebase>/.venv/bin/python)")
    parser.add_argument("--system", default=None,
                        help="system-under-test name (default: codebase "
                             "directory name)")
    parser.add_argument("--timeout", type=float, default=1800.0,
                        help="seconds for the single agent call (default 1800)")
    parser.add_argument("--keep-workdir", action="store_true",
                        help="keep the temp copy instead of deleting it")
    args = parser.parse_args()

    codebase = args.codebase.resolve()
    if not codebase.is_dir():
        fail(f"codebase not found: {codebase}")
    interpreter = args.python or (codebase / ".venv" / "bin" / "python")
    if not Path(interpreter).exists():
        fail(f"interpreter not found: {interpreter} (pass --python)")
    system = args.system or codebase.name

    started = dt.datetime.now(dt.timezone.utc)
    stamp = started.strftime("%Y%m%d-%H%M%SZ")
    workdir = Path(tempfile.mkdtemp(prefix=f"raw_{args.backend}_{system}_"))
    shutil.rmtree(workdir)   # copytree wants to create it
    shutil.copytree(codebase, workdir,
                    ignore=shutil.ignore_patterns(".venv", ".git",
                                                  "__pycache__", "test",
                                                  RAW_TEST_DIR))

    prompt = PROMPT.format(workdir=workdir, testdir=RAW_TEST_DIR)
    build = claude_command if args.backend == "claude" else codex_command
    command = build(prompt, args.model, workdir)

    print(f"raw baseline: {args.backend} on a copy of {system} at {workdir}")
    print("one naive prompt, no Meridian structure; this can take a while…")
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=args.timeout, cwd=workdir)
    except FileNotFoundError as exc:
        fail(f"cannot run the {args.backend} CLI: {exc}")
    except subprocess.TimeoutExpired:
        fail(f"the agent ran past {args.timeout:.0f}s and was killed; "
             f"workdir kept at {workdir}")
    if completed.returncode != 0:
        fail(f"the agent exited {completed.returncode}: "
             f"{(completed.stderr or '')[-400:]}; workdir kept at {workdir}")

    usage = claude_usage(completed.stdout) if args.backend == "claude" else {}

    test_dir = workdir / RAW_TEST_DIR
    test_files = sorted(test_dir.glob("test_*.py")) if test_dir.is_dir() else []
    # The naive prompt names raw_tests/, but a raw agent may ignore it.
    strayed = []
    if not test_files:
        strayed = [p for p in workdir.rglob("test_*.py")
                   if RAW_TEST_DIR not in p.parts]
        if strayed:
            test_dir.mkdir(exist_ok=True)
            for stray in strayed:
                shutil.copy2(stray, test_dir / stray.name)
            test_files = sorted(test_dir.glob("test_*.py"))
    if not test_files:
        fail(f"the agent wrote no test_*.py anywhere under {workdir}")

    tests_created = sum(f.read_text(errors="replace").count("def test")
                        for f in test_files)
    lines_of_code = sum(len(f.read_text(errors="replace").splitlines())
                        for f in test_files)

    print(f"agent wrote {len(test_files)} file(s), {tests_created} test "
          f"function(s), {lines_of_code} lines — executing and classifying…")
    runtime = run_and_classify({"interpreter": {"path": str(interpreter)}},
                               test_dir)

    model_label = args.model or f"{args.backend} CLI default"
    destination = RUNS_DIR / f"{stamp}_{system}_raw-{args.backend}"
    (destination / "tests").mkdir(parents=True, exist_ok=True)
    # Snapshot EVERYTHING in the agent's test directory, not just test_*.py:
    # a raw agent typically writes a conftest.py (fixtures, import shims)
    # the tests cannot run without. An early version copied only test files,
    # which made one recorded run impossible to re-execute later.
    support_files = [p for p in sorted(test_dir.iterdir())
                     if p.is_file() and p not in test_files]
    for f in test_files + support_files:
        shutil.copy2(f, destination / "tests" / f.name)
    (destination / "agent_output.json").write_text(completed.stdout,
                                                   encoding="utf-8")

    valid = len(runtime["passed"]) + len(runtime["findings"])
    invalid = len(runtime["invalid_runtime"])
    lines = [
        f"# Test-generation run — {system} — RAW {args.backend}",
        "",
        f"- **Date/time:** {pacific(started.isoformat(timespec='seconds'))}",
        f"- **System under test:** {system} (`{codebase}`)",
        f"- **LLM:** RAW (un-orchestrated) `{args.backend}`, model "
        f"`{model_label}`",
        f"- **Validation interpreter:** `{interpreter}`",
        f"- **Note:** single naive prompt, no Meridian structure; agent had "
        f"write access to a fresh copy at `{workdir}`"
        + ("; the agent ignored the named test directory and its files were "
           "gathered from where it left them" if strayed else ""),
        "",
        "## Results — runtime verdicts",
        "",
        f"- Tests created (total): **{tests_created}** in {len(test_files)} "
        f"file(s), {lines_of_code} lines of test code",
        f"- **Valid tests: {valid}** ({len(runtime['passed'])} pass; "
        f"{len(runtime['findings'])} are valid failures)",
        f"- Invalid tests: {invalid}",
        f"- Files that crashed or hung: {len(runtime['crashes'])}",
        f"- Tokens out: {usage.get('output_tokens', 'not reported')}; "
        f"reported cost: "
        + (f"${usage['total_cost_usd']:.4f}" if usage else "not reported"),
        "",
        "### Valid failures discovered (candidate findings)",
        "",
        *([f"- `{t}` — {w}" for t, w in runtime["findings"]] or ["- (none)"]),
        "",
        "### Invalid tests",
        "",
        *([f"- `{t}` — {w}" for t, w in runtime["invalid_runtime"]]
          or ["- (none)"]),
    ]
    if runtime["crashes"]:
        lines += ["", "### Crashed files", ""] + [
            f"- `{n}` — {w}" for n, w in runtime["crashes"]]
    lines += [
        "",
        "## Reproduce",
        "",
        "```sh",
        f"scripts/raw_baseline.py --codebase {codebase} "
        f"--backend {args.backend}"
        + (f" --model {args.model}" if args.model else "")
        + f" --python {interpreter}",
        "```",
        "",
        "## Invalid tests caught by Meridian during generation",
        "",
        "- (not applicable — RAW runs bypass Meridian entirely)",
        "",
    ]
    (destination / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"recorded: {destination.relative_to(REPO)}")
    print(f"  tests created {tests_created}; valid {valid} "
          f"({len(runtime['findings'])} valid failures); invalid {invalid}; "
          f"crashed files {len(runtime['crashes'])}")
    if args.keep_workdir:
        print(f"  workdir kept: {workdir}")
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
