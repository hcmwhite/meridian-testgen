"""The provider-agnostic interface to the model, and the scripted fake (D31).

Stage 3 talks to an LLM through exactly one operation:
:meth:`TestgenLLM.generate_tests`, which takes a *batch* of
:class:`GenerationItem` requests and returns the test sources the model wrote
for them. Batching is the interface's business rather than the caller's
because D28 matches results back to items by identity — the base class does
that matching itself, so no backend can answer for an item it was not asked
about.

The pattern is stage 2's, copied rather than imported (D22): the same
:class:`LLMUsage` accumulator, the same ``LLMConfig``/``create_llm`` backend
selection by plain config value, the same discipline that every test in the
repository runs against :class:`ScriptedFakeLLM` and none touches the network
or spends money (D31).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace

from meridian_testgen.model import STRUCTURAL_MARKER

LOG = logging.getLogger("meridian_testgen.llm")

BACKEND_CLAUDE_CLI = "claude_cli"
BACKEND_SCRIPTED_FAKE = "scripted_fake"
# --- codex generated ---
BACKEND_CODEX_CLI = "codex_cli"
# --- end codex generated ---

# A default *configuration*, not a hardcoded provider: the CLI overrides it.
DEFAULT_MODEL = "claude-sonnet-4-5"


class LLMError(Exception):
    """The backend could not be run, or answered in a shape we cannot read."""


@dataclass
class LLMUsage:
    """Token and cost totals across every call one backend instance made.

    Identical accounting to stage 2's, so the two stages' reports read the
    same. Backends that cannot see their provider's usage reporting leave the
    figures at zero, which makes ``calls`` the honest signal that anything was
    measured at all. Costs are the provider's own numbers, advisory on a
    subscription login.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    total_cost_usd: float = 0.0
    # One entry per call, in call order — D30's per-call token/cost records.
    # Deliberately kept beside the totals rather than inside :meth:`as_dict`,
    # which stays the small totals-only shape stage 2 writes.
    records: list = field(default_factory=list)

    def add(self, usage: "dict | None", cost_usd: "float | None") -> None:
        """Fold one call's envelope figures into the totals. Tolerant of
        absent fields — an envelope without usage still counts the call."""
        self.calls += 1
        record = {"call": self.calls}
        for name in ("input_tokens", "output_tokens",
                     "cache_creation_input_tokens", "cache_read_input_tokens"):
            value = (usage or {}).get(name)
            value = int(value) if isinstance(value, (int, float)) else 0
            setattr(self, name, getattr(self, name) + value)
            record[name] = value
        cost = float(cost_usd) if isinstance(cost_usd, (int, float)) else 0.0
        self.total_cost_usd += cost
        record["cost_usd"] = round(cost, 6)
        self.records.append(record)

    def call_records(self) -> list:
        """The per-call records, copied, for the report (D30)."""
        return [dict(record) for record in self.records]

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
        }


@dataclass(frozen=True)
class GenerationItem:
    """One unit of generation work: write the test(s) for this identity.

    The fields are D29's prompt ingredients, already gathered — a mapped pair
    carries its requirement code and text, and (when its tier is
    ``deterministic``) the stage-2 effect claim and evidence snippet; a
    structural-only function carries :data:`STRUCTURAL_MARKER` as its
    requirement code and none of that. *source* is the function's byte-sliced
    definition text and *obligations* is the D33 checklist.

    *prior_failure* is the reason a previous attempt was rejected, carried per
    item so a batched retry can ask each failed item for a different fix
    (D27, D28); ``None`` on a first attempt.
    """

    __test__ = False

    unit_id: str
    requirement_code: str
    dotted_name: str
    signature: str
    file_path: str
    line_number: int
    end_line: int
    source: str
    requirement_text: str = ""
    tier: "str | None" = None
    effect: "str | None" = None
    evidence: "str | None" = None
    obligations: tuple = ()
    # --- codex generated ---
    resource_dependencies: tuple = ()
    # --- end codex generated ---
    prior_failure: "str | None" = None

    @property
    def key(self) -> tuple:
        """The identity D28 matches results back by."""
        return (self.unit_id, self.requirement_code)

    @property
    def is_structural(self) -> bool:
        return self.requirement_code == STRUCTURAL_MARKER

    def with_failure(self, reason: "str | None") -> "GenerationItem":
        """The same item, to be re-asked with *reason* in its prompt (D27)."""
        return replace(self, prior_failure=reason)


@dataclass(frozen=True)
class GeneratedTest:
    """What the model wrote for one item: its identity, and the test source."""

    __test__ = False

    unit_id: str
    requirement_code: str
    source: str

    @property
    def key(self) -> tuple:
        return (self.unit_id, self.requirement_code)


class TestgenLLM:
    """The interface both backends implement.

    Subclasses override :meth:`_generate_tests`; :meth:`generate_tests` wraps
    it with the D28 identity match, so a result for an item that was not in
    the batch is dropped with a warning rather than smuggled into the run.

    Every instance carries an :class:`LLMUsage` at :attr:`usage`, and an
    optional :attr:`prompt_log` — when ``--prompt-debug`` supplied one, each
    prompt sent is appended to it (D31). Off by default and free when off.
    """

    prompt_log = None

    @property
    def usage(self) -> LLMUsage:
        if not hasattr(self, "_usage"):
            self._usage = LLMUsage()
        return self._usage

    def generate_tests(self, items) -> list[GeneratedTest]:
        """The tests the model wrote for *items*, one batch, one call."""
        items = list(items)
        if not items:
            return []
        returned = self._generate_tests(items)
        return self._keep_requested(items, returned)

    def _generate_tests(self, items) -> list[GeneratedTest]:
        raise NotImplementedError

    def _log_prompt(self, prompt: str) -> None:
        """Append *prompt* to the prompt log, if one is attached (D31)."""
        if self.prompt_log is not None:
            self.prompt_log.write(prompt)

    @staticmethod
    def _keep_requested(items, returned) -> list[GeneratedTest]:
        """Drop results for identities that were not in the batch (D28).

        Order is the model's answer; a repeated identity keeps its first
        result, so a model that answers twice for one item cannot silently
        overwrite the answer we already accepted.
        """
        wanted = {item.key for item in items}
        kept: list[GeneratedTest] = []
        seen: set = set()
        for test in returned:
            if test.key not in wanted:
                LOG.warning(
                    "dropping generated test for %s/%s — not in this batch",
                    test.unit_id, test.requirement_code,
                )
                continue
            if test.key in seen:
                # Several entries for one item are almost always the model
                # splitting its test CASES one-per-entry, not rival answers —
                # dropping them threw away four of five real tests on the
                # first live run (2026-08-23). Merge the sources instead;
                # validation still judges the combined file as a whole.
                LOG.info(
                    "merging an additional generated test for %s/%s",
                    test.unit_id, test.requirement_code,
                )
                index = next(i for i, kept_test in enumerate(kept)
                             if kept_test.key == test.key)
                merged = kept[index].source.rstrip() + "\n\n\n" + test.source.lstrip()
                kept[index] = GeneratedTest(
                    test.unit_id, test.requirement_code, merged)
                continue
            seen.add(test.key)
            kept.append(test)
        return kept


@dataclass
class LLMConfig:
    """Backend selection and its settings — a plain config value (D31)."""

    backend: str = BACKEND_CLAUDE_CLI
    model: str = DEFAULT_MODEL
    binary: str = "claude"
    timeout: float = 300.0
    # --- codex generated ---
    codex_binary: str = "codex"
    # --- end codex generated ---
    # Only for BACKEND_SCRIPTED_FAKE: the script the fake is driven by.
    script: "ScriptedScript | None" = None


def create_llm(config: LLMConfig, codebase_root=None, prompt_log=None) -> TestgenLLM:
    """Build the backend *config* names.

    *codebase_root* is handed to backends that give the agent read access to
    the source (D29 asks the structural prompt to go and read callers).
    *prompt_log* is the ``--prompt-debug`` sink, or ``None``.
    """
    if config.backend == BACKEND_SCRIPTED_FAKE:
        script = config.script if config.script is not None else ScriptedScript()
        llm = ScriptedFakeLLM(script)
    elif config.backend == BACKEND_CLAUDE_CLI:
        from meridian_testgen.claude_cli import ClaudeCliLLM

        llm = ClaudeCliLLM(
            codebase_root=codebase_root,
            model=config.model,
            binary=config.binary,
            timeout=config.timeout,
        )
    # --- codex generated ---
    elif config.backend == BACKEND_CODEX_CLI:
        from meridian_testgen.codex_cli import CodexCliLLM

        llm = CodexCliLLM(
            codebase_root=codebase_root,
            model=config.model,
            binary=config.codex_binary,
            timeout=config.timeout,
        )
    # --- end codex generated ---
    else:
        # --- codex generated ---
        known = ", ".join((BACKEND_CLAUDE_CLI, BACKEND_CODEX_CLI,
                           BACKEND_SCRIPTED_FAKE))
        # --- end codex generated ---
        raise LLMError(
            f"unknown llm backend {config.backend!r}; known backends: {known}"
        )
    llm.prompt_log = prompt_log
    return llm


def default_test_source(item: GenerationItem) -> str:
    """A minimal, mechanically valid test for *item*.

    The fake's answer for an item a test did not bother to script: it carries
    the D29 traceability comment and collects, so a test about batching or
    logging does not have to spell out test source it does not care about.
    """
    slug = item.unit_id.replace(".", "_").replace("/", "_").replace("-", "_")
    slug = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in slug)
    suffix = item.requirement_code.replace("-", "_")
    return (
        f"def test_{slug}_{suffix}():\n"
        f"    # meridian: unit_id={item.unit_id} "
        f"requirement={item.requirement_code}\n"
        f"    assert True\n"
    )


@dataclass
class ScriptedScript:
    """What :class:`ScriptedFakeLLM` should answer.

    *tests*: ``(unit_id, requirement code)`` -> either one answer returned for
    every attempt, or a *list* consumed one entry per call, which is how a
    test scripts a fail-fail-pass retry sequence (D27). An answer is a
    :class:`GeneratedTest`, a ``str`` (shorthand for that test source — the
    empty string is the model returning nothing), an ``Exception`` (raised
    instead of returned), or ``None`` (the model answered for other items in
    the batch but not this one).

    *extra*: :class:`GeneratedTest` objects appended to every answer whatever
    was asked — how a test simulates the model answering for an item that was
    not in the batch (D28's drop-with-a-warning path).
    """

    tests: dict = field(default_factory=dict)
    extra: list = field(default_factory=list)
    # Items with no entry in *tests* get default_test_source(); set this False
    # to make an unscripted item an answer the model simply omitted.
    answer_unscripted: bool = True


class ScriptedFakeLLM(TestgenLLM):
    """A deterministic backend driven entirely by a test's script (D31).

    It records every call — :attr:`calls`, one list of item keys per call, and
    :attr:`items` with the items themselves — so a test can assert what was,
    and was not, sent: that only failed items were re-batched, that a
    category-leak requirement never reached the model, that the retry cap
    held.
    """

    def __init__(self, script: "ScriptedScript | None" = None):
        self.script = script if script is not None else ScriptedScript()
        self.calls: list[list[tuple]] = []
        self.items: list[list[GenerationItem]] = []
        self.prompts: list[str] = []
        self._consumed: dict = {}

    def _generate_tests(self, items) -> list[GeneratedTest]:
        self.calls.append([item.key for item in items])
        self.items.append(list(items))
        # The fake spends nothing, but a call is still a call: counting it
        # keeps the report's per-call records honest under the fake, which is
        # the only backend any test drives (D31).
        self.usage.add(None, None)
        if self.prompt_log is not None:
            # Prompt assembly lives in the real backend's module; the fake
            # borrows it so --prompt-debug is exercisable without the CLI, and
            # only when a log is attached, so it stays free when off.
            from meridian_testgen.claude_cli import build_generation_prompt

            prompt = build_generation_prompt(items)
            self.prompts.append(prompt)
            self._log_prompt(prompt)

        results: list[GeneratedTest] = []
        for item in items:
            answer = self._answer_for(item)
            if answer is None:
                continue
            results.append(answer)
        results.extend(self.script.extra)
        return results

    def _answer_for(self, item: GenerationItem) -> "GeneratedTest | None":
        if item.key not in self.script.tests:
            if not self.script.answer_unscripted:
                return None
            return GeneratedTest(item.unit_id, item.requirement_code,
                                 default_test_source(item))

        scripted = self.script.tests[item.key]
        if isinstance(scripted, list):
            index = self._consumed.get(item.key, 0)
            if index >= len(scripted):
                raise LLMError(
                    f"scripted fake ran out of answers for {item.unit_id}/"
                    f"{item.requirement_code} after {len(scripted)} calls"
                )
            self._consumed[item.key] = index + 1
            scripted = scripted[index]

        if isinstance(scripted, Exception):
            raise scripted
        if scripted is None:
            return None
        if isinstance(scripted, str):
            return GeneratedTest(item.unit_id, item.requirement_code, scripted)
        return scripted
