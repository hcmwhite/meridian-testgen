"""The production backend: headless ``claude -p`` in a subprocess (D14).

The agent is given read-only access to the parsed codebase (``--add-dir`` plus
an allow-list of read tools) so it can look at real source before answering,
and is asked for JSON on stdout (``--output-format json``, whose ``result``
field holds the model's text). The model id is a configuration value handed in
by the caller — nothing about a provider is hardcoded below.

Only the deterministic halves of this module are unit tested: prompt assembly
and response parsing against canned CLI output. No test invokes the real CLI.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess

from meridian_mapper.llm import Candidate, Claim, LLMError, MapperLLM

LOG = logging.getLogger("meridian_mapper.claude_cli")

# Read-only posture: the agent may look at the codebase and nothing else.
READ_ONLY_TOOLS = ("Read", "Grep", "Glob")
# NOT "plan": plan mode can make the CLI save a plan file and report that
# instead of answering (bit stage 3 on every call, 2026-08-24; the mapper's
# short answers mostly dodged it, but the hazard is the same). Read-only is
# enforced by the --allowed-tools list.
PERMISSION_MODE = "default"

MAP_INSTRUCTIONS = """\
You are mapping one software requirement onto an existing codebase.

Below is the requirement, then the complete list of candidate functions. Decide
which candidates implement the requirement. You may read the codebase to check,
but you must ONLY choose from the candidate list: never name a function that is
not listed, and never invent a unit_id.

Answer with JSON and nothing else, in this shape:

{"unit_ids": ["<unit_id>", ...]}

An empty list is a valid and expected answer when no candidate implements the
requirement."""

VERIFY_INSTRUCTIONS = """\
You are justifying one function's assignment to one requirement.

Produce a claim of the form "this function satisfies the requirement by
producing observable effect E", and support it with an evidence snippet copied
VERBATIM from the function's own body as shown below. The snippet is checked
literally against the source: if it is paraphrased, reformatted, or taken from
another function, the claim is rejected.

Answer with JSON and nothing else, in this shape:

{"effect": "<what the function observably does>", "evidence": "<verbatim lines from the body>"}"""

VERIFY_BATCH_INSTRUCTIONS = """\
You are justifying several function-to-requirement assignments at once.

For EACH numbered pair below, produce a claim of the form "this function
satisfies the requirement by producing observable effect E", supported by an
evidence snippet copied VERBATIM from that function's own body as shown. Each
snippet is checked literally against that function's source: if it is
paraphrased, reformatted, or taken from another function, that claim is
rejected. Answer for every pair listed, and for no other pair.

Answer with JSON and nothing else, in this shape:

{"claims": [{"requirement_code": "<code>", "unit_id": "<unit_id>", "effect": "<what the function observably does>", "evidence": "<verbatim lines from the body>"}, ...]}"""


def format_candidate(candidate: Candidate) -> str:
    """One candidate line: a code *reference*, never file contents."""
    return (
        f"- unit_id={candidate.unit_id} | {candidate.dotted_name} | "
        f"{candidate.signature} | {candidate.file_path}:"
        f"{candidate.line_number}-{candidate.end_line}"
    )


def build_map_prompt(requirement, candidates) -> str:
    code = getattr(requirement, "code", requirement)
    text = getattr(requirement, "text", "")
    lines = [format_candidate(c) for c in candidates] or ["(no candidates)"]
    return (
        f"{MAP_INSTRUCTIONS}\n\n"
        f"REQUIREMENT {code}: {text}\n\n"
        f"CANDIDATE FUNCTIONS ({len(lines) if candidates else 0}):\n"
        + "\n".join(lines)
        + "\n"
    )


def build_verify_prompt(requirement, candidate, body, prior_failure=None) -> str:
    code = getattr(requirement, "code", requirement)
    text = getattr(requirement, "text", "")
    prompt = (
        f"{VERIFY_INSTRUCTIONS}\n\n"
        f"REQUIREMENT {code}: {text}\n\n"
        f"FUNCTION {candidate.dotted_name} ({candidate.signature}) at "
        f"{candidate.file_path}:{candidate.line_number}-{candidate.end_line}\n\n"
        f"BODY:\n{body}\n"
    )
    if prior_failure:
        prompt += (
            "\nA previous attempt at this claim was rejected. Reason:\n"
            f"{prior_failure}\n"
            "Quote a different, exactly verbatim snippet this time.\n"
        )
    return prompt


def build_verify_batch_prompt(blocks) -> str:
    """The prompt for a batch of pairs — one call, one claim each (D32).

    *blocks* are ``(requirement, candidate, body, prior_failure)`` tuples in
    the order they were asked for; each carries its own prior failure, so a
    re-batch tells the model exactly what was wrong with each pair (D18).
    """
    blocks = list(blocks)
    parts = []
    for number, (requirement, candidate, body, prior_failure) in enumerate(
        blocks, start=1
    ):
        code = getattr(requirement, "code", requirement)
        text = getattr(requirement, "text", "")
        part = (
            f"PAIR {number}\n"
            f"requirement_code: {code}\n"
            f"unit_id: {candidate.unit_id}\n"
            f"REQUIREMENT {code}: {text}\n"
            f"FUNCTION {candidate.dotted_name} ({candidate.signature}) at "
            f"{candidate.file_path}:{candidate.line_number}-{candidate.end_line}\n\n"
            f"BODY:\n{body}\n"
        )
        if prior_failure:
            part += (
                "\nA previous attempt at this claim was rejected. Reason:\n"
                f"{prior_failure}\n"
                "Quote a different, exactly verbatim snippet this time.\n"
            )
        parts.append(part)
    return (
        f"{VERIFY_BATCH_INSTRUCTIONS}\n\n"
        f"PAIRS ({len(parts)}):\n\n"
        + "\n\n---\n\n".join(parts)
        + "\n"
    )


class ClaudeCliLLM(MapperLLM):
    """Talk to the headless ``claude`` CLI, one subprocess per call."""

    def __init__(self, codebase_root=None, model=None, binary="claude",
                 timeout=300.0, runner=None, body_reader=None):
        self.codebase_root = codebase_root
        self.model = model
        self.binary = binary
        self.timeout = timeout
        # Seams for tests: *runner* runs the command, *body_reader* returns a
        # function's source text. Neither is used by production callers.
        self._runner = runner if runner is not None else self._run_subprocess
        self._body_reader = body_reader

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
            raise LLMError(
                f"{self.binary} timed out after {self.timeout}s"
            ) from exc
        if completed.returncode != 0:
            raise LLMError(
                f"{self.binary} exited {completed.returncode}: "
                f"{(completed.stderr or '').strip()}"
            )
        return completed.stdout

    def _ask(self, prompt: str) -> dict:
        self._log_prompt(prompt)
        envelope = parse_cli_envelope(self._runner(self.build_command(prompt)))
        # Booked before payload extraction: a call that came back malformed
        # still consumed the tokens its envelope reports.
        self.usage.add(envelope.get("usage"), envelope.get("total_cost_usd"))
        return payload_from_envelope(envelope)

    def _map_requirement(self, requirement, candidates) -> list[str]:
        payload = self._ask(build_map_prompt(requirement, candidates))
        unit_ids = payload.get("unit_ids")
        if not isinstance(unit_ids, list) or not all(
            isinstance(u, str) for u in unit_ids
        ):
            raise LLMError(
                f"claude answered without a 'unit_ids' list of strings: {payload!r}"
            )
        return unit_ids

    def verify_claim(self, requirement, ast_function, prior_failure=None) -> Claim:
        candidate = Candidate.from_function(ast_function)
        body = self._read_body(ast_function)
        payload = self._ask(
            build_verify_prompt(requirement, candidate, body, prior_failure)
        )
        effect, evidence = payload.get("effect"), payload.get("evidence")
        if not isinstance(effect, str) or not isinstance(evidence, str):
            raise LLMError(
                f"claude answered without string 'effect' and 'evidence': {payload!r}"
            )
        return Claim(
            requirement_code=getattr(requirement, "code", requirement),
            unit_id=ast_function.unit_id,
            effect=effect,
            evidence=evidence,
        )

    def _verify_claims(self, requests) -> list:
        """A whole batch in one subprocess call (D32).

        A batch of one goes down the single-pair path unchanged, so batch size
        1 is byte-identical to the unbatched loop — same prompt, same parsing.
        """
        requests = list(requests)
        if len(requests) == 1:
            request = requests[0]
            return [
                self.verify_claim(
                    request.requirement, request.ast_function,
                    request.prior_failure,
                )
            ]
        blocks = [
            (
                request.requirement,
                Candidate.from_function(request.ast_function),
                self._read_body(request.ast_function),
                request.prior_failure,
            )
            for request in requests
        ]
        payload = self._ask(build_verify_batch_prompt(blocks))
        return parse_batch_claims(payload)

    def _read_body(self, ast_function) -> str:
        if self._body_reader is not None:
            return self._body_reader(ast_function)
        from meridian_mapper.astload import source_slice

        return source_slice(self.codebase_root, ast_function)


def parse_batch_claims(payload: dict) -> list:
    """The claims out of a batch answer's payload.

    An entry that is not a well-formed claim object is dropped with a warning
    — one malformed claim must not cost the rest of the batch its answers; the
    pairs it leaves unanswered fail their attempt and retry (D18, D32).
    """
    claims = payload.get("claims")
    if not isinstance(claims, list):
        raise LLMError(f"claude answered without a 'claims' list: {payload!r}")
    parsed = []
    for entry in claims:
        if not isinstance(entry, dict):
            LOG.warning("dropping a batch claim that is not an object: %r", entry)
            continue
        code = entry.get("requirement_code")
        unit_id = entry.get("unit_id")
        effect = entry.get("effect")
        evidence = entry.get("evidence")
        if not all(isinstance(v, str) for v in (code, unit_id, effect, evidence)):
            LOG.warning("dropping a malformed batch claim: %r", entry)
            continue
        parsed.append(Claim(requirement_code=code, unit_id=unit_id,
                            effect=effect, evidence=evidence))
    return parsed


_FENCE = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.DOTALL)


def parse_cli_envelope(stdout: str) -> dict:
    """The CLI's response envelope, out of ``--output-format json`` stdout.

    Beside ``result`` (the model's text) the envelope carries the call's
    accounting — ``usage`` token counts and ``total_cost_usd`` — which is why
    it is surfaced whole rather than unwrapped straight to the payload.
    """
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise LLMError(f"claude did not print JSON: {exc}") from exc
    if not isinstance(envelope, dict) or "result" not in envelope:
        raise LLMError(
            f"claude's JSON has no 'result' field: {stdout.strip()[:200]!r}"
        )
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
