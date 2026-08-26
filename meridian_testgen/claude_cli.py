"""The production backend: headless ``claude -p`` in a subprocess (D31).

Same shape as stage 2's backend, copied rather than imported (D22): one
subprocess per call, read-only tools plus ``--add-dir <codebase>`` so the
agent can look at real source before writing a test (D29 asks the structural
prompt to go and find callers), ``--output-format json`` so the response
envelope carries both the model's text and the call's usage and cost.

Only the deterministic halves are unit tested — prompt assembly, and envelope
parsing against canned CLI output. No test invokes the real CLI.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import PurePosixPath

from meridian_testgen.llm import (
    GeneratedTest,
    LLMError,
    TestgenLLM,
)
from meridian_testgen.model import TIER_DETERMINISTIC

# Read-only posture: the agent may look at the codebase and nothing else.
READ_ONLY_TOOLS = ("Read", "Grep", "Glob")
# NOT "plan": plan mode makes the CLI research and save a *plan file* instead
# of answering — every call then fails JSON parsing ("I've completed the test
# generation plan. The plan file at …", seen live 2026-08-24). Read-only is
# enforced by the --allowed-tools list, which is the right guard for a
# produce-an-answer call.
PERMISSION_MODE = "default"

GENERATE_INSTRUCTIONS = """\
You are writing pytest unit tests for functions in an existing codebase.

Below is one or more generation items. For each item you are given the
function's source, its location, a checklist of structural obligations the
tests should cover, and — for a mapped item — the requirement the function is
supposed to satisfy. Write pytest test functions for each item.

Rules:

* Test the code as it is. If the code looks wrong, still write the test that
  the requirement or the structure demands: a failing test is a finding, not a
  mistake to write around.
* Every test function you write must carry the comment
  `# meridian: unit_id=<unit_id> requirement=<requirement>` on its own line
  inside the function, copying the item's unit_id and requirement exactly.
* Import what you use. The test source must compile and be collectable by
  pytest on its own.
* Tests must never touch real external resources — no audio or video
  devices, no network connections, no subprocesses, no GUI windows, no
  writes outside pytest's tmp_path. Where the code under test opens such a
  boundary (an audio stream, a socket, a server), stub that library with
  unittest.mock BEFORE importing the module, and test the logic around the
  boundary. A test that opens a real device can crash the whole suite.
* Answer for every item you were given, and for no other item — ONE entry per
  item. To write several test functions for an item (the checklist usually
  wants several), put them all inside that item's single "source" string.

Answer with JSON and nothing else, in this shape:

{"tests": [{"unit_id": "<unit_id>", "requirement": "<requirement code or 'structural'>", "source": "<the test source>"}, ...]}"""

STRUCTURAL_NOTE = """\
This item is structural: no requirement is assigned to it. Before writing,
read the codebase you have access to — find this function's callers and the
module around it — and derive from that context what the function is for and
what must hold of it."""


def format_item(item, index: int) -> str:
    """One generation item as the model sees it (D29's ingredients)."""
    lines = [
        f"ITEM {index}",
        f"unit_id: {item.unit_id}",
        f"requirement: {item.requirement_code}",
    ]
    if item.is_structural:
        lines.append(STRUCTURAL_NOTE)
    else:
        lines.append(f"REQUIREMENT {item.requirement_code}: {item.requirement_text}")
        # The stage-2 claim is evidence only where a deterministic pass
        # checked it against the real source bytes (D29).
        if item.tier == TIER_DETERMINISTIC and item.effect:
            lines.append(f"stage-2 effect claim: {item.effect}")
            if item.evidence:
                lines.append(f"stage-2 evidence snippet:\n{item.evidence}")
    lines.append(
        f"FUNCTION {item.dotted_name} ({item.signature}) at "
        f"{item.file_path}:{item.line_number}-{item.end_line}"
    )
    # No guessing at import styles: test/conftest.py puts the source
    # directories on sys.path, so the module imports by its file stem —
    # every other spelling failed collection on the first live run.
    stem = PurePosixPath(item.file_path).stem
    lines.append(
        f"IMPORT: the test directory's conftest puts this file's directory "
        f"on sys.path — import the code under test as "
        f"`from {stem} import …` (or `import {stem}`). Do not use any other "
        f"import path and do not modify sys.path yourself."
    )
    lines.append(f"SOURCE:\n{item.source}")
    checklist = "\n".join(f"- {ob}" for ob in item.obligations) or "- (none derived)"
    lines.append(f"STRUCTURAL OBLIGATIONS:\n{checklist}")
    # --- codex generated ---
    if item.resource_dependencies:
        boundaries = []
        for dependency in item.resource_dependencies:
            matched = ", ".join(dependency.matches)
            guidance = f" {dependency.guidance}" if dependency.guidance else ""
            boundaries.append(
                f"- {dependency.resource_type}: matched {matched}; required "
                f"strategy: {dependency.strategy}.{guidance}"
            )
        lines.append(
            "RESOURCE SAFETY PROFILE:\n"
            "These boundaries are present in the code under test. Isolate every "
            "one using its required strategy; do not call it directly.\n"
            + "\n".join(boundaries)
        )
    # --- end codex generated ---
    if item.prior_failure:
        lines.append(
            "A previous attempt at this item was rejected. Reason:\n"
            f"{item.prior_failure}\n"
            "Fix exactly that and answer again."
        )
    return "\n\n".join(lines)


def build_generation_prompt(items) -> str:
    """The prompt for one batch of items (D28: a batch is one call)."""
    items = list(items)
    blocks = [format_item(item, n) for n, item in enumerate(items, start=1)]
    return (
        f"{GENERATE_INSTRUCTIONS}\n\n"
        f"GENERATION ITEMS ({len(items)}):\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n"
    )


class ClaudeCliLLM(TestgenLLM):
    """Talk to the headless ``claude`` CLI, one subprocess per batch."""

    def __init__(self, codebase_root=None, model=None, binary="claude",
                 timeout=300.0, runner=None):
        self.codebase_root = codebase_root
        self.model = model
        self.binary = binary
        self.timeout = timeout
        # Seam for tests: *runner* runs the command and returns its stdout.
        # Production callers never pass it.
        self._runner = runner if runner is not None else self._run_subprocess

    def build_command(self, prompt: str) -> list[str]:
        """The full argv for one headless call."""
        command = [self.binary, "-p", prompt, "--output-format", "json"]
        if self.model:
            command += ["--model", self.model]
        command += ["--permission-mode", PERMISSION_MODE]
        command += ["--allowed-tools", ",".join(READ_ONLY_TOOLS)]
        if self.codebase_root is not None:
            command += ["--add-dir", str(self.codebase_root)]
        return command

    def _run_subprocess(self, command: list[str]) -> str:
        try:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise LLMError(f"cannot run {self.binary!r}: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"{self.binary} timed out after {self.timeout}s") from exc
        if completed.returncode != 0:
            raise LLMError(
                f"{self.binary} exited {completed.returncode}: "
                f"{(completed.stderr or '').strip()}"
            )
        return completed.stdout

    def _generate_tests(self, items) -> list[GeneratedTest]:
        prompt = build_generation_prompt(items)
        self._log_prompt(prompt)
        envelope = parse_cli_envelope(self._runner(self.build_command(prompt)))
        # Booked before payload extraction: a call that came back malformed
        # still consumed the tokens its envelope reports.
        self.usage.add(envelope.get("usage"), envelope.get("total_cost_usd"))
        payload = payload_from_envelope(envelope)

        tests = payload.get("tests")
        if not isinstance(tests, list):
            raise LLMError(f"claude answered without a 'tests' list: {payload!r}")
        results = []
        for entry in tests:
            if not isinstance(entry, dict):
                raise LLMError(f"a 'tests' entry is not an object: {entry!r}")
            unit_id = entry.get("unit_id")
            requirement = entry.get("requirement")
            source = entry.get("source")
            if not all(isinstance(v, str) for v in (unit_id, requirement, source)):
                raise LLMError(
                    "a 'tests' entry is missing string 'unit_id', 'requirement' "
                    f"or 'source': {entry!r}"
                )
            results.append(GeneratedTest(unit_id, requirement, source))
        return results


_FENCE = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.DOTALL)


def parse_cli_envelope(stdout: str) -> dict:
    """The CLI's response envelope, out of ``--output-format json`` stdout.

    Surfaced whole rather than unwrapped straight to the payload because
    beside ``result`` it carries the call's accounting — ``usage`` token
    counts and ``total_cost_usd``.
    """
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise LLMError(f"claude did not print JSON: {exc}") from exc
    if not isinstance(envelope, dict) or "result" not in envelope:
        raise LLMError(f"claude's JSON has no 'result' field: {stdout.strip()[:200]!r}")
    if envelope.get("is_error"):
        raise LLMError(f"claude reported an error: {envelope.get('result')!r}")
    return envelope


def payload_from_envelope(envelope: dict) -> dict:
    """The model's JSON object, out of the envelope's ``result`` text.

    The text is JSON, optionally inside a ``` fence.
    """
    result = envelope["result"]
    if not isinstance(result, str):
        raise LLMError(f"claude's 'result' is not text: {result!r}")
    text = result.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group("body").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(
            f"claude's answer is not the JSON object we asked for: {text[:200]!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise LLMError(f"claude's answer is not a JSON object: {text[:200]!r}")
    return payload


def parse_cli_response(stdout: str) -> dict:
    """Envelope and payload parsing in one step, for callers (and tests) that
    do not need the accounting."""
    return payload_from_envelope(parse_cli_envelope(stdout))
