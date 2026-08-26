"""The verification loop: the LLM quotes, the code checks (chunk 4).

Every function–requirement pair the mapping loop produced is put through one
deterministic gate (D15). The LLM is asked for a :class:`~meridian_mapper.llm.Claim`
— "F satisfies R by producing observable effect E" — carrying an evidence
snippet quoted verbatim from F's body, and this module checks two things and
nothing else:

1. F's ``unit_id`` is in the ast list. The mapping loop already enforces the
   universe (D9), so a miss should be impossible; it is treated as a
   verification failure rather than a crash all the same.
2. The snippet, whitespace-normalized, appears in F's byte-offset source slice
   (:func:`meridian_mapper.astload.source_slice`).

No fuzzy matching, no NLP, no judgement call. A pair that passes is tier
``deterministic``.

**Retries (D18).** A failed attempt is re-asked with the failure's reason as
``prior_failure``, up to two retries — three attempts in total. After the
second failed retry the function is removed from that requirement's mapping
and an :class:`~meridian_mapper.model.ErrorNote` is written on the ast
function's annotation recording the requirement code and every attempted
claim with the reason it failed. Exhaustion is never silent: no mapping is
ever dropped without its error note.

**What is skipped.** A requirement flagged ``category_leak`` (D16) is
probably parent-level and is not verifiable at function level, so its pairs
never enter this loop and stay tier ``llm_asserted``. That is the only route
to that tier — there is no purely LLM-asserted success path here.

**Batching (D32).** ``--batch-size`` pairs of one requirement go out in one
call; only the pairs that failed are re-batched, each carrying its own
failure reason. Attempt counts, the two-retry cap and the error notes are
per pair either way, so a batch of one is the unbatched loop exactly.

Per-pair attempt counts and accumulated failure reasons live in this module
for the duration of the loop; only the outcomes — tier, removal, error notes —
land on the model (D11).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from meridian_mapper.astload import AstLoadError, source_slice
from meridian_mapper.llm import LLMError, VerifyRequest
from meridian_mapper.mapping import leaf_requirements
from meridian_mapper.model import TIER_DETERMINISTIC, ErrorNote

LOG = logging.getLogger("meridian_mapper.verification")


class _NotAsked(LLMError):
    """A pair that never reached the model — its own failure, not a call's."""


# D18: two retries, three attempts in total. A plain config value.
DEFAULT_MAX_RETRIES = 2
# D32: one pair per call unless the caller asks for more.
DEFAULT_BATCH_SIZE = 1


@dataclass
class VerificationConfig:
    """Settings for the verification loop.

    *max_retries*: how many times a failed pair is re-asked. The total number
    of attempts is ``max_retries + 1``.

    *batch_size*: how many pairs go out in one call (D32). Attempt counts,
    the retry cap and the error notes are per pair regardless — batching
    changes how many calls carry the questions, nothing about what counts as
    a failure. A batch of one is the unbatched loop exactly.
    """

    max_retries: int = DEFAULT_MAX_RETRIES
    batch_size: int = DEFAULT_BATCH_SIZE


@dataclass
class VerificationSummary:
    """What the loop did, for the CLI's run summary (chunk 6)."""

    pairs_checked: int = 0
    verified: int = 0
    retries_used: int = 0
    exhausted: int = 0
    skipped_category_leak: int = 0
    calls: int = 0


@dataclass
class _Attempt:
    """One try at a pair, kept in this module until the pair is decided."""

    attempt: int
    effect: str
    evidence: str
    reason: str

    def as_dict(self) -> dict:
        return {
            "attempt": self.attempt,
            "effect": self.effect,
            "evidence": self.evidence,
            "reason": self.reason,
        }


@dataclass
class _PairState:
    """The per-pair bookkeeping the loop needs and the model never sees."""

    attempts: list[_Attempt] = field(default_factory=list)

    @property
    def last_reason(self) -> "str | None":
        return self.attempts[-1].reason if self.attempts else None


def normalize_whitespace(text: str) -> str:
    """Collapse every run of whitespace to a single space, and strip.

    Both sides of the containment check go through this, so an evidence
    snippet that differs from the source only in indentation or line wrapping
    still matches — and nothing else is forgiven.
    """
    return " ".join(text.split())


def run_verification(model, llm, codebase_root, config: VerificationConfig | None = None) -> VerificationSummary:
    """Verify every non-category-leak pair in *model* against real source bytes.

    Returns a :class:`VerificationSummary`; tiers, removals and error notes
    land on the model.
    """
    config = config or VerificationConfig()
    summary = VerificationSummary()

    for requirement in leaf_requirements(model):
        if requirement.category_leak:
            # D16: parent-level in disguise; its pairs keep llm_asserted.
            summary.skipped_category_leak += len(requirement.mapped_unit_ids)
            continue

        unit_ids = list(requirement.mapped_unit_ids)
        summary.pairs_checked += len(unit_ids)
        states: dict = {}
        for batch in _batches(unit_ids, config.batch_size):
            states.update(
                _verify_batch(model, llm, codebase_root, requirement, batch,
                              config, summary)
            )

        survivors: list[str] = []
        for unit_id in unit_ids:
            state = states[unit_id]
            summary.retries_used += max(0, len(state.attempts) - 1)
            if state.attempts[-1].reason == "":
                summary.verified += 1
                survivors.append(unit_id)
                annotation = model.functions[unit_id].annotation
                annotation.tiers[requirement.code] = TIER_DETERMINISTIC
                # Persist the claim that passed (open decision s3c3, ruled):
                # stage 3's generation prompt carries it for deterministic
                # pairs (D29), and the artifact then shows WHY the pair
                # verified, not just that it did.
                winning = state.attempts[-1]
                annotation.claims[requirement.code] = {
                    "effect": winning.effect,
                    "evidence": winning.evidence,
                }
            else:
                summary.exhausted += 1
                _record_exhaustion(model, requirement, unit_id, state)
        requirement.mapped_unit_ids = survivors

    return summary


def _batches(items, size: int):
    """*items* in chunks of *size* (D32); a size below 1 reads as 1."""
    items = list(items)
    size = max(1, int(size))
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _verify_batch(model, llm, codebase_root, requirement, unit_ids, config,
                  summary) -> dict:
    """Ask, check, re-batch the failures. Returns each pair's final state.

    Every round is one call carrying only the pairs still failing, each with
    its own prior failure reason (D32). A pair is decided the moment an
    attempt passes or its attempts run out (D18) — the cap is per pair, not
    per batch.
    """
    states = {unit_id: _PairState() for unit_id in unit_ids}
    pending = list(unit_ids)
    for attempt in range(1, config.max_retries + 2):
        if not pending:
            break
        results = _ask_batch(
            model, llm, requirement, pending, states, summary
        )
        still_failing: list[str] = []
        for unit_id in pending:
            effect, evidence, reason = _check_answer(
                model, codebase_root, requirement, unit_id, results.get(unit_id)
            )
            states[unit_id].attempts.append(
                _Attempt(attempt, effect, evidence, reason)
            )
            if reason == "":
                continue
            LOG.warning(
                "requirement %s / %s: attempt %d failed: %s",
                requirement.code, unit_id, attempt, reason,
            )
            still_failing.append(unit_id)
        pending = still_failing
    return states


def _ask_batch(model, llm, requirement, unit_ids, states, summary) -> dict:
    """One call for the pairs in *unit_ids*; unit_id -> claim, or a failure.

    A pair whose unit_id is not in the ast list never reaches the model: the
    mapping loop enforces the universe (D9), so this is a verification
    failure rather than a crash, and it costs no call. An :class:`LLMError`
    is the whole call's failure and lands on every pair it carried.
    """
    results: dict = {}
    requests = []
    for unit_id in unit_ids:
        function = model.functions.get(unit_id)
        if function is None:
            results[unit_id] = _NotAsked(
                f"unit_id {unit_id!r} is not in the ast list"
            )
            continue
        requests.append(
            VerifyRequest(requirement, function, states[unit_id].last_reason)
        )
    if not requests:
        return results

    summary.calls += 1
    try:
        claims = llm.verify_claims(requests)
    except LLMError as exc:
        for request in requests:
            results[request.key[1]] = exc
        return results

    for request in requests:
        unit_id = request.key[1]
        claim = claims.get(request.key)
        results[unit_id] = claim if claim is not None else LLMError(
            "the batch answer carried no claim for this pair"
        )
    return results


def _check_answer(model, codebase_root, requirement, unit_id, answer):
    """Check one answer. Returns ``(effect, evidence, reason)``.

    An empty *reason* is a pass; anything else is the failure text handed back
    to the model as ``prior_failure`` on the next attempt and written into the
    error note if the pair exhausts.
    """
    if isinstance(answer, _NotAsked):
        # Never asked: the id was not in the universe at all (D9).
        return "", "", str(answer)
    if isinstance(answer, LLMError):
        return "", "", f"the model did not return a claim: {answer}"

    effect = getattr(answer, "effect", "") or ""
    evidence = getattr(answer, "evidence", "") or ""
    if not evidence.strip():
        return effect, evidence, "the claim carried no evidence snippet"

    function = model.functions[unit_id]
    try:
        body = source_slice(codebase_root, function)
    except AstLoadError as exc:
        return effect, evidence, f"could not read the function's source: {exc}"

    if normalize_whitespace(evidence) not in normalize_whitespace(body):
        return (
            effect,
            evidence,
            "the evidence snippet does not appear in the function's source",
        )
    return effect, evidence, ""


def _record_exhaustion(model, requirement, unit_id, state: _PairState) -> None:
    """Remove the pair and write down why (D18) — never silently."""
    function = model.functions.get(unit_id)
    if function is None:
        # Nothing to annotate — the id was never in the universe. The removal
        # from the requirement's mapping still stands.
        LOG.warning(
            "requirement %s: dropped %s, which is not in the ast list",
            requirement.code, unit_id,
        )
        return
    annotation = function.annotation
    if requirement.code in annotation.requirement_codes:
        annotation.requirement_codes.remove(requirement.code)
    annotation.tiers.pop(requirement.code, None)
    annotation.error_notes.append(
        ErrorNote(
            requirement_code=requirement.code,
            attempts=[attempt.as_dict() for attempt in state.attempts],
        )
    )
    LOG.warning(
        "requirement %s: removed %s after %d failed verification attempts; "
        "see its error note",
        requirement.code, unit_id, len(state.attempts),
    )
