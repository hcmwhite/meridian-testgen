"""Build the generation items and drive the model in batches (D28, D29).

This is the middle of the pipeline: the model is loaded, the obligation
checklists are derivable, the LLM sits behind its interface — what is missing
is the work list. This module builds it.

One :class:`~meridian_testgen.llm.GenerationItem` is one *unit of generation
work*: a mapped (function, requirement) pair, or a structural-only function
with :data:`~meridian_testgen.model.STRUCTURAL_MARKER` where a requirement
code would go. Each item is assembled with D29's ingredients already gathered,
so prompt assembly (which lives in the backend module) has nothing left to
look up.

Two rules shape the loop:

* **Category-leak pairs are skipped** (D29). A requirement flagged
  `category_leak` in Artifact 2 is a parent-level "all shared logic is
  consistent" statement that mapped to everything; there is no assertion to
  write for it. The skips are counted, never silent.
* **A batch is one call** (D28). ``--batch-size`` items go out together and
  results come back matched by identity — the identity match itself is the
  interface's job (:meth:`TestgenLLM.generate_tests`), so an answer for an
  item that was not asked about never reaches this module.

Results are grouped here by top-level requirement category (plus one
``structural`` group). Deciding which *file* each group lands in is chunk 4's
concern; producing the grouping is this module's.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
# --- codex generated ---
from pathlib import Path
# --- end codex generated ---

from meridian_testgen.inputs import source_slice
from meridian_testgen.llm import GeneratedTest, GenerationItem, LLMError
from meridian_testgen.model import (
    STRUCTURAL_MARKER,
    TIER_DETERMINISTIC,
    TestgenModel,
)
from meridian_testgen.obligations import ObligationError, obligations_for_function
# --- codex generated ---
from meridian_testgen.codex_safety_profile import (
    SafetyProfile,
    default_safety_profile,
    dependencies_for_file_context,
)
# --- end codex generated ---

LOG = logging.getLogger("meridian_testgen.generate")

# The group key structural-only functions share; every other group key is a
# top-level requirement category code ("1", "2", …).
STRUCTURAL_GROUP = STRUCTURAL_MARKER

DEFAULT_BATCH_SIZE = 1


@dataclass
class GenerationSummary:
    """What the loop did, in counts the report and the CLI both print."""

    __test__ = False

    items: int = 0
    mapped_items: int = 0
    structural_items: int = 0
    skipped_category_leak: int = 0
    calls: int = 0
    generated: int = 0
    unanswered: int = 0


@dataclass(frozen=True)
class GroupedTest:
    """One generated test kept with the item that asked for it.

    The writer needs both: the source to write, and the item's identity and
    location for the file header and the report.
    """

    __test__ = False

    item: GenerationItem
    test: GeneratedTest

    @property
    def key(self) -> tuple:
        return self.item.key

    @property
    def source(self) -> str:
        return self.test.source


@dataclass
class GenerationRun:
    """The loop's result: the work list, the answers, and the grouping."""

    __test__ = False

    items: list = field(default_factory=list)
    # (unit_id, requirement code) -> the test the model wrote for it.
    results: dict = field(default_factory=dict)
    # (unit_id, requirement code) -> why its CALL failed (timeout, backend
    # error). A failure here cost only its own batch — other batches' results
    # stand. Items in neither dict were in a batch the model answered without
    # covering them.
    call_failures: dict = field(default_factory=dict)
    # group key -> GroupedTest, in item order.
    groups: dict = field(default_factory=dict)
    summary: GenerationSummary = field(default_factory=GenerationSummary)

    def unanswered_items(self) -> list:
        """Items the model returned nothing usable for — chunk 4 retries these."""
        return [item for item in self.items if item.key not in self.results]


def group_key(item: GenerationItem) -> str:
    """The group *item* belongs to: its category code, or ``structural``."""
    if item.is_structural:
        return STRUCTURAL_GROUP
    return TestgenModel.category_of(item.requirement_code)


def batches(items, size: int):
    """*items* in chunks of *size* (D28); a size below 1 reads as 1."""
    items = list(items)
    size = max(1, int(size))
    for start in range(0, len(items), size):
        yield items[start:start + size]


def claim_for(function, requirement_code: str):
    """The stage-2 effect claim for one pair, as ``(effect, evidence)``.

    D29 puts the verified claim and its evidence snippet into a deterministic
    pair's prompt. Stage 2 records the *failed* attempts of an exhausted pair
    in ``error_notes`` but does not, today, persist the claim of a pair that
    passed, so this reads an optional ``claims`` map on the unit record —
    ``{"1-1": {"effect": …, "evidence": …}}`` — and returns ``(None, None)``
    when it is absent. An absent claim costs the prompt one hint; it is never
    an error, and no other ingredient depends on it.
    """
    claims = function.record.get("claims")
    if not isinstance(claims, dict):
        return None, None
    claim = claims.get(requirement_code)
    if not isinstance(claim, dict):
        return None, None
    effect = claim.get("effect")
    evidence = claim.get("evidence")
    return (
        effect if isinstance(effect, str) else None,
        evidence if isinstance(evidence, str) else None,
    )


def _obligations(function, source: str) -> tuple:
    """The D33 checklist for *function*, or an empty one with a warning.

    A slice that will not parse is a broken input, not a reason to abandon the
    run: the item still goes out, with its source and without a checklist.
    """
    try:
        return tuple(obligations_for_function(function, source))
    except ObligationError as exc:
        LOG.warning(
            "no structural obligations for %s (%s): %s",
            function.dotted_name or function.unit_id, function.unit_id, exc,
        )
        return ()


def build_item(model, function, requirement_code: str, source: str,
               obligations: tuple, resource_dependencies: tuple = ()) -> GenerationItem:
    """One generation item, with D29's ingredients for its kind.

    A structural item carries no requirement text, tier or claim — there is no
    requirement behind it; the backend's prompt tells the model to go and read
    the codebase for context instead.
    """
    structural = requirement_code == STRUCTURAL_MARKER
    tier = None if structural else function.tier(requirement_code)
    effect = evidence = None
    if not structural and tier == TIER_DETERMINISTIC:
        effect, evidence = claim_for(function, requirement_code)
    return GenerationItem(
        unit_id=function.unit_id,
        requirement_code=requirement_code,
        dotted_name=function.dotted_name,
        signature=function.signature,
        file_path=function.file_path,
        line_number=function.line_number,
        end_line=function.end_line,
        source=source,
        requirement_text="" if structural else model.requirement_text(requirement_code),
        tier=tier,
        effect=effect,
        evidence=evidence,
        obligations=obligations,
        # --- codex generated ---
        resource_dependencies=resource_dependencies,
        # --- end codex generated ---
    )


def build_items(model, codebase_root, safety_profile: "SafetyProfile | None" = None):
    """The whole work list for a run, with the skip counts (D29).

    Functions come in Artifact 1's order and each function's requirements in
    its own order, so two runs over the same artifacts build the same list.
    """
    items: list[GenerationItem] = []
    summary = GenerationSummary()
    # --- codex generated ---
    safety_profile = safety_profile or default_safety_profile()
    # --- end codex generated ---
    for function in model.ordered_functions():
        codes = ([STRUCTURAL_MARKER] if function.structural_test_only
                 else list(function.requirement_codes))
        wanted = []
        for code in codes:
            requirement = None if code == STRUCTURAL_MARKER else model.requirement(code)
            if requirement is not None and requirement.category_leak:
                summary.skipped_category_leak += 1
                LOG.info(
                    "skipping %s / %s: requirement is flagged category_leak",
                    function.unit_id, code,
                )
                continue
            wanted.append(code)
        if not wanted:
            continue
        # Slice and analyse the source once per function, not once per pair.
        source = source_slice(codebase_root, function)
        obligations = _obligations(function, source)
        # --- codex generated ---
        resource_dependencies = dependencies_for_file_context(
            Path(codebase_root) / function.file_path, source, safety_profile)
        # --- end codex generated ---
        for code in wanted:
            items.append(build_item(
                model, function, code, source, obligations,
                # --- codex generated ---
                resource_dependencies,
                # --- end codex generated ---
            ))
            if code == STRUCTURAL_MARKER:
                summary.structural_items += 1
            else:
                summary.mapped_items += 1
    summary.items = len(items)
    return items, summary


def generate(model, llm, codebase_root, batch_size: int = DEFAULT_BATCH_SIZE,
             items=None, runlog=None, progress_offset: int = 0,
             progress_total: "int | None" = None) -> GenerationRun:
    """Build the items (unless given), ask the model, group the answers.

    *items* is the seam chunk 4's retry loop needs: it re-drives a subset of
    an existing work list without rebuilding it. Answers are grouped into
    :attr:`TestgenModel.generated_groups` as well as into the returned run,
    because there is one model and later passes read it rather than threading
    this object through.
    """
    if items is None:
        items, summary = build_items(model, codebase_root)
    else:
        items = list(items)
        summary = GenerationSummary(items=len(items))
        summary.mapped_items = sum(1 for i in items if not i.is_structural)
        summary.structural_items = sum(1 for i in items if i.is_structural)

    run = GenerationRun(items=items, summary=summary)

    def say(message: str) -> None:
        # Progress for a person watching the run — an LLM call can take
        # minutes. Through the run log when the caller passed one (stderr +
        # the on-disk testgen_run.log), plain stderr otherwise.
        if runlog is not None:
            runlog.say(message)
        else:
            print(message, file=sys.stderr, flush=True)

    done = progress_offset
    total = progress_total if progress_total is not None else len(items)
    for batch in batches(items, batch_size):
        first = batch[0]
        what = ("structural" if first.is_structural
                else f"requirement {first.requirement_code}")
        say(
            f"generating {done + 1}"
            + (f"-{done + len(batch)}" if len(batch) > 1 else "")
            + f" of {total}: {first.dotted_name} ({what})…"
        )
        done += len(batch)
        summary.calls += 1
        # One call's failure costs only its own batch (a 300s timeout on call
        # 8 of 26 must not throw away seven finished tests — seen live on the
        # first real run, 2026-08-23). The failed items carry the reason into
        # the retry round; every other batch's results stand.
        try:
            answers = llm.generate_tests(batch)
        except LLMError as exc:
            reason = f"the model could not be reached: {exc}"
            LOG.warning("generation call failed for %d item(s): %s",
                        len(batch), exc)
            say(f"  call failed ({exc}) — will retry these items")
            for item in batch:
                run.call_failures[item.key] = reason
            continue
        for test in answers:
            run.results[test.key] = test
    summary.generated = len(run.results)

    for item in items:
        test = run.results.get(item.key)
        if test is None:
            continue
        run.groups.setdefault(group_key(item), []).append(GroupedTest(item, test))
    summary.unanswered = len(items) - summary.generated
    for item in run.unanswered_items():
        LOG.warning(
            "no usable test for %s / %s", item.unit_id, item.requirement_code,
        )
    model.generated_groups = run.groups
    return run
