"""Codex CLI backend for Meridian test generation.

This is independent of the Claude backend. It uses Codex CLI's JSONL event
stream and extracts the final agent message, which must contain Meridian's
existing JSON test envelope.
"""

from __future__ import annotations

import json
import subprocess

from meridian_testgen.claude_cli import build_generation_prompt, payload_from_envelope
from meridian_testgen.llm import GeneratedTest, LLMError, TestgenLLM


class CodexCliLLM(TestgenLLM):
    """Talk to ``codex exec`` once for each generation batch."""

    def __init__(self, codebase_root=None, model=None, binary="codex",
                 timeout=300.0, runner=None):
        self.codebase_root = codebase_root
        self.model = model
        self.binary = binary
        self.timeout = timeout
        self._runner = runner if runner is not None else self._run_subprocess

    def build_command(self, prompt: str) -> list[str]:
        """The read-only JSONL Codex invocation for one batch."""
        command = [
            self.binary, "exec", "--json", "--sandbox", "read-only",
            "--skip-git-repo-check",
        ]
        if self.model:
            command += ["--model", self.model]
        if self.codebase_root is not None:
            command += ["-C", str(self.codebase_root)]
        command.append(prompt)
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
        payload, usage = parse_codex_jsonl(self._runner(self.build_command(prompt)))
        # Codex reports token usage but no dollar cost.  Keep the report's
        # provider-neutral accounting shape and never estimate a cost.
        self.usage.add(usage, None)
        tests = payload.get("tests")
        if not isinstance(tests, list):
            raise LLMError(f"codex answered without a 'tests' list: {payload!r}")
        results = []
        for entry in tests:
            if not isinstance(entry, dict):
                raise LLMError(f"a 'tests' entry is not an object: {entry!r}")
            unit_id = entry.get("unit_id")
            requirement = entry.get("requirement")
            source = entry.get("source")
            if not all(isinstance(value, str) for value in (unit_id, requirement, source)):
                raise LLMError(
                    "a 'tests' entry is missing string 'unit_id', 'requirement' "
                    f"or 'source': {entry!r}"
                )
            results.append(GeneratedTest(unit_id, requirement, source))
        return results


def parse_codex_jsonl(stdout: str) -> tuple[dict, "dict | None"]:
    """Extract Meridian's response and final token usage from Codex JSONL."""
    messages = []
    usage = None
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LLMError(f"codex did not print JSONL: {line[:200]!r}") from exc
        if event.get("type") == "turn.completed":
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                usage = {
                    "input_tokens": raw_usage.get("input_tokens"),
                    "output_tokens": raw_usage.get("output_tokens"),
                    "cache_creation_input_tokens": raw_usage.get(
                        "cache_write_input_tokens"),
                    "cache_read_input_tokens": raw_usage.get(
                        "cached_input_tokens"),
                }
            continue
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                messages.append(text)
    if not messages:
        raise LLMError("codex JSONL contained no completed agent message")
    return payload_from_envelope({"result": messages[-1]}), usage
