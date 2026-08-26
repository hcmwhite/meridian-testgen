"""The provider-agnostic agent interface, and the scripted fake (D14).

The mapper talks to an LLM only through :class:`MapperLLM`, which has exactly
two operations, one per neural step:

* :meth:`MapperLLM.map_requirement` — given one requirement and a bounded
  candidate list, return the unit_ids that satisfy it. The model *evaluates
  candidates*; it never discovers functions, so an id outside the candidate
  set is dropped with a warning rather than invented into the universe (D9).
* :meth:`MapperLLM.verify_claim` — given one requirement/function pair,
  return a :class:`Claim`: "F satisfies R by producing observable effect E",
  carrying a verbatim evidence snippet quoted from F's body. The snippet is
  what chunk 4's deterministic pass checks against the real source bytes
  (D15), so the interface promises the text, not a judgement.

Which backend runs is a config value (:class:`LLMConfig`, :func:`create_llm`),
never a hardcoded provider — docs/SPEC.md is explicit that models get swapped
for experimentation. Production is ``claude_cli``
(:mod:`meridian_mapper.claude_cli`); every test in this stage uses
:class:`ScriptedFakeLLM` and no test makes a network call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

LOG = logging.getLogger("meridian_mapper.llm")

BACKEND_CLAUDE_CLI = "claude_cli"
BACKEND_SCRIPTED_FAKE = "scripted_fake"

# No provider or model id is hardcoded anywhere in this stage; this is the
# default *configuration*, overridable from the CLI in chunk 6.
DEFAULT_MODEL = "claude-sonnet-4-5"


class LLMError(Exception):
    """The backend could not be run, or answered in a shape we cannot read."""


@dataclass
class LLMUsage:
    """Token and cost totals across every call one backend instance made.

    Filled in by backends that can see their provider's usage reporting (the
    claude CLI's response envelope carries ``usage`` and ``total_cost_usd``);
    a backend with nothing to report leaves it at zero, so ``calls`` is the
    honest signal that anything was measured. Costs are the provider's own
    figures, advisory on a subscription login.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    total_cost_usd: float = 0.0

    def add(self, usage: "dict | None", cost_usd: "float | None") -> None:
        """Fold one call's envelope figures into the totals. Tolerant of
        absent fields — an envelope without usage still counts the call."""
        self.calls += 1
        for name in ("input_tokens", "output_tokens",
                     "cache_creation_input_tokens", "cache_read_input_tokens"):
            value = (usage or {}).get(name)
            if isinstance(value, (int, float)):
                setattr(self, name, getattr(self, name) + int(value))
        if isinstance(cost_usd, (int, float)):
            self.total_cost_usd += float(cost_usd)

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
class Candidate:
    """One ast function as the model sees it in a mapping prompt.

    Deliberately narrow: dotted name, signature, file and line range — a code
    *reference*, never file contents (docs/SPEC.md).
    """

    unit_id: str
    dotted_name: str
    signature: str
    file_path: str
    line_number: int
    end_line: int

    @classmethod
    def from_function(cls, function) -> "Candidate":
        """Build a candidate from an :class:`~meridian_mapper.model.AstFunction`."""
        record = function.record
        return cls(
            unit_id=function.unit_id,
            dotted_name=record.get("dotted_name", ""),
            signature=record.get("signature", ""),
            file_path=record.get("file_path", ""),
            line_number=record.get("line_number", 0),
            end_line=record.get("end_line", 0),
        )


@dataclass(frozen=True)
class Claim:
    """The structured form of "F satisfies R by producing observable effect E".

    *evidence* is quoted verbatim from F's body; chunk 4 checks it,
    whitespace-normalized, against the byte-offset source slice (D15).
    """

    requirement_code: str
    unit_id: str
    effect: str
    evidence: str


@dataclass(frozen=True)
class VerifyRequest:
    """One pair to ask a claim for, as a batch member (D32).

    *prior_failure* is per request, not per batch: a re-batch carries each
    failed pair's own reason (D18, D32).
    """

    requirement: object
    ast_function: object
    prior_failure: "str | None" = None

    @property
    def key(self) -> tuple:
        """The identity a batched answer is matched back by (D32)."""
        return (
            getattr(self.requirement, "code", self.requirement),
            getattr(self.ast_function, "unit_id", self.ast_function),
        )


class MapperLLM:
    """The interface both backends implement.

    Subclasses override :meth:`_map_requirement` and :meth:`verify_claim`;
    :meth:`map_requirement` wraps the former with the universe filter so no
    backend can widen the universe by accident.

    :meth:`verify_claims` is the batched form of :meth:`verify_claim` (D32):
    up to ``--batch-size`` pairs in one call, answers matched back by
    ``(requirement code, unit_id)``. The default implementation asks one pair
    at a time through :meth:`verify_claim`, so a backend that cannot batch
    still works and a batch of one is exactly today's single call.

    Every instance carries a :class:`LLMUsage` at :attr:`usage`, and an
    optional :attr:`prompt_log` — when ``--prompt-debug`` supplied one, each
    prompt sent is appended to it (D31). Off by default and free when off.
    """

    prompt_log = None

    @property
    def usage(self) -> LLMUsage:
        if not hasattr(self, "_usage"):
            self._usage = LLMUsage()
        return self._usage

    def map_requirement(self, requirement, candidates) -> list[str]:
        """The unit_ids among *candidates* that satisfy *requirement*."""
        candidates = list(candidates)
        returned = self._map_requirement(requirement, candidates)
        return self._keep_known(requirement, candidates, returned)

    def _map_requirement(self, requirement, candidates) -> list[str]:
        raise NotImplementedError

    def verify_claim(self, requirement, ast_function, prior_failure=None) -> Claim:
        """A claim that *ast_function* satisfies *requirement*.

        *prior_failure* is the reason the previous attempt failed, so a retry
        can ask for a better snippet (D18); ``None`` on the first attempt.
        """
        raise NotImplementedError

    def verify_claims(self, requests) -> dict:
        """Claims for a whole batch of *requests*, keyed by their identity.

        A batch is one call for backends that can batch. Answers are matched
        back by ``(requirement code, unit_id)``; an answer for a pair that was
        not asked about is dropped with a warning rather than let into the
        run (D32).
        """
        requests = list(requests)
        if not requests:
            return {}
        return self._keep_requested(requests, self._verify_claims(requests))

    def _verify_claims(self, requests) -> list:
        """One call per pair — the unbatched default (D32).

        A backend that overrides this sends the whole batch at once; one that
        does not still behaves correctly, only more expensively.
        """
        return [
            self.verify_claim(
                request.requirement, request.ast_function, request.prior_failure
            )
            for request in requests
        ]

    def _log_prompt(self, prompt: str) -> None:
        """Append *prompt* to the prompt log, if one is attached (D31)."""
        if self.prompt_log is not None:
            self.prompt_log.write(prompt)

    @staticmethod
    def _keep_requested(requests, claims) -> dict:
        """Index *claims* by identity, dropping any pair not in the batch."""
        wanted = {request.key for request in requests}
        kept: dict = {}
        for claim in claims:
            key = (claim.requirement_code, claim.unit_id)
            if key not in wanted:
                LOG.warning(
                    "dropping a claim for %s/%s — not in this batch",
                    claim.requirement_code, claim.unit_id,
                )
                continue
            if key in kept:
                LOG.warning(
                    "dropping a second claim for %s/%s in one batch",
                    claim.requirement_code, claim.unit_id,
                )
                continue
            kept[key] = claim
        return kept

    @staticmethod
    def _keep_known(requirement, candidates, returned) -> list[str]:
        """Drop ids the model returned that were not offered to it (D9).

        Order and duplicates come from the model's answer; a repeat is kept
        once.
        """
        known = {candidate.unit_id for candidate in candidates}
        code = getattr(requirement, "code", requirement)
        kept: list[str] = []
        for unit_id in returned:
            if unit_id not in known:
                LOG.warning(
                    "requirement %s: dropping unit_id %r — not in the candidate "
                    "list for this requirement",
                    code, unit_id,
                )
                continue
            if unit_id not in kept:
                kept.append(unit_id)
        return kept


@dataclass
class LLMConfig:
    """Backend selection and its settings — a plain config value (D14)."""

    backend: str = BACKEND_CLAUDE_CLI
    model: str = DEFAULT_MODEL
    binary: str = "claude"
    timeout: float = 300.0
    # Only for BACKEND_SCRIPTED_FAKE: the script the fake is driven by.
    script: "ScriptedScript | None" = None


def create_llm(config: LLMConfig, codebase_root=None, prompt_log=None) -> MapperLLM:
    """Build the backend *config* names.

    *codebase_root* is handed to backends that give the agent read access to
    the source; the fake ignores it. *prompt_log* is the ``--prompt-debug``
    sink, or ``None`` (D31).
    """
    if config.backend == BACKEND_SCRIPTED_FAKE:
        script = config.script if config.script is not None else ScriptedScript()
        llm: MapperLLM = ScriptedFakeLLM(script)
    elif config.backend == BACKEND_CLAUDE_CLI:
        from meridian_mapper.claude_cli import ClaudeCliLLM

        llm = ClaudeCliLLM(
            codebase_root=codebase_root,
            model=config.model,
            binary=config.binary,
            timeout=config.timeout,
        )
    else:
        known = ", ".join((BACKEND_CLAUDE_CLI, BACKEND_SCRIPTED_FAKE))
        raise LLMError(
            f"unknown llm backend {config.backend!r}; known backends: {known}"
        )
    llm.prompt_log = prompt_log
    return llm


@dataclass
class ScriptedScript:
    """What :class:`ScriptedFakeLLM` should answer.

    *mappings*: requirement code -> the unit_ids to return. Ids that are not
    in the candidate list are allowed here on purpose — that is how a test
    simulates the model naming a function outside the universe.

    *claims*: ``(requirement code, unit_id)`` -> either one
    :class:`Claim`/``str`` returned for every attempt, or a list consumed one
    entry per call, which is how retry behaviour is scripted. A ``str`` is
    shorthand for a claim whose evidence is that string. An ``Exception``
    entry is raised instead of returned.
    """

    mappings: dict = field(default_factory=dict)
    claims: dict = field(default_factory=dict)
    # The effect text used for str shorthand and for unscripted pairs.
    default_effect: str = "scripted effect"


class ScriptedFakeLLM(MapperLLM):
    """A deterministic backend driven entirely by a test's script (D14).

    It records every call — :attr:`map_calls` and :attr:`verify_calls` — so a
    test can assert what was, and was not, sent to the model (chunk 3 needs
    "category nodes were never passed to the LLM").
    """

    def __init__(self, script: ScriptedScript | None = None):
        self.script = script if script is not None else ScriptedScript()
        self.map_calls: list[tuple[str, list[str]]] = []
        self.verify_calls: list[tuple[str, str, "str | None"]] = []
        # One entry per verify_claims call: the identities that went out
        # together, so a test can assert what was batched with what (D32).
        self.verify_batches: list[list[tuple]] = []
        self.prompts: list[str] = []
        self._consumed: dict = {}

    def _map_requirement(self, requirement, candidates) -> list[str]:
        code = getattr(requirement, "code", requirement)
        self.map_calls.append((code, [c.unit_id for c in candidates]))
        if self.prompt_log is not None:
            from meridian_mapper.claude_cli import build_map_prompt

            self._record_prompt(build_map_prompt(requirement, candidates))
        return list(self.script.mappings.get(code, []))

    def _verify_claims(self, requests) -> list:
        """A batch the fake answers pair by pair, recorded as one call (D32).

        The fake sends nothing, so "one call" is what it records here; the
        per-pair script and :attr:`verify_calls` are unchanged, which is why a
        batch of one behaves exactly as the unbatched loop did.
        """
        requests = list(requests)
        self.verify_batches.append([request.key for request in requests])
        if self.prompt_log is not None and len(requests) > 1:
            from meridian_mapper.claude_cli import build_verify_batch_prompt

            self._record_prompt(
                build_verify_batch_prompt(
                    [
                        (
                            request.requirement,
                            Candidate.from_function(request.ast_function),
                            "",
                            request.prior_failure,
                        )
                        for request in requests
                    ]
                )
            )
            return [
                self._claim_for(
                    request.requirement, request.ast_function,
                    request.prior_failure,
                )
                for request in requests
            ]
        return super()._verify_claims(requests)

    def _record_prompt(self, prompt: str) -> None:
        """Keep the prompt and append it to the log (D31, D32).

        Prompt assembly lives in the real backend's module; the fake borrows
        it so ``--prompt-debug`` is exercisable without the CLI, and only when
        a log is attached, so it stays free when off. The fake never reads
        source, so a batched record carries an empty BODY.
        """
        self.prompts.append(prompt)
        self._log_prompt(prompt)

    def verify_claim(self, requirement, ast_function, prior_failure=None) -> Claim:
        if self.prompt_log is not None and hasattr(ast_function, "record"):
            from meridian_mapper.claude_cli import build_verify_prompt

            self._record_prompt(
                build_verify_prompt(
                    requirement, Candidate.from_function(ast_function), "",
                    prior_failure,
                )
            )
        return self._claim_for(requirement, ast_function, prior_failure)

    def _claim_for(self, requirement, ast_function, prior_failure=None) -> Claim:
        code = getattr(requirement, "code", requirement)
        unit_id = getattr(ast_function, "unit_id", ast_function)
        self.verify_calls.append((code, unit_id, prior_failure))

        scripted = self.script.claims.get((code, unit_id))
        if isinstance(scripted, list):
            index = self._consumed.get((code, unit_id), 0)
            if index >= len(scripted):
                raise LLMError(
                    f"scripted fake ran out of claims for {code}/{unit_id} "
                    f"after {len(scripted)} calls"
                )
            self._consumed[(code, unit_id)] = index + 1
            scripted = scripted[index]

        if isinstance(scripted, Exception):
            raise scripted
        if scripted is None:
            scripted = ""
        if isinstance(scripted, str):
            return Claim(
                requirement_code=code,
                unit_id=unit_id,
                effect=self.script.default_effect,
                evidence=scripted,
            )
        return scripted
