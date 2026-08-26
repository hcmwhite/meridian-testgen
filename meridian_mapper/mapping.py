"""The per-leaf mapping loop and category-leak flagging (chunk 3).

For each *leaf* requirement, in hierarchy order, this asks the LLM which of
the ast functions satisfy it and records the answer in both directions of the
one in-memory model (D11): on the requirement node
(:attr:`~meridian_mapper.model.Requirement.mapped_unit_ids`) and on each ast
function's annotation. There is no second bookkeeping copy.

Category nodes are never mapped and never sent to the LLM (D13): their
category status was resolved once, during normalization, and this loop only
reads it.

Two rulings shape the rest:

* **D16, category leak.** If a leaf's mapping comes back with more functions
  than the configured threshold (default 10), the requirement is flagged
  ``category_leak`` — it is probably a parent-level requirement that should
  not be verified at function level. It keeps every mapping and appears in
  both artifacts with the flag visible; chunk 4 reads the flag to skip its
  pairs, which therefore stay tier ``llm_asserted``. The threshold is a plain
  config value: the LLM is never the judge of it, and flagging happens inline,
  once, without re-running or second-guessing the mapping.
* **D17, an empty mapping is a result.** A leaf that maps to zero functions is
  recorded with an empty set and the run continues. It is not an error, not
  retried, and not removed from the output.

Every pair leaves this loop at tier ``llm_asserted``; chunk 4's deterministic
check is what promotes one to ``deterministic``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from meridian_mapper.llm import Candidate
from meridian_mapper.model import TIER_LLM_ASSERTED
from meridian_mapper.requirements import iter_requirements

LOG = logging.getLogger("meridian_mapper.mapping")

# D16's default, as a plain config value.
DEFAULT_CATEGORY_LEAK_THRESHOLD = 10


@dataclass
class MappingConfig:
    """Settings for the mapping loop.

    *category_leak_threshold*: a leaf mapping to strictly more functions than
    this is flagged ``category_leak`` (D16).
    """

    category_leak_threshold: int = DEFAULT_CATEGORY_LEAK_THRESHOLD


@dataclass
class MappingSummary:
    """What the loop did, for the CLI's run summary."""

    leaves_mapped: int = 0
    pairs: int = 0
    empty_leaves: int = 0
    category_leaks: int = 0


def leaf_requirements(model) -> list:
    """The leaf nodes of *model*'s requirements tree, in hierarchy order.

    Hierarchy order is document order, depth first — the order Artifact 2
    renders in.
    """
    return [node for node in iter_requirements(model.requirements) if not node.is_category]


def run_mapping(model, llm, config: MappingConfig | None = None) -> MappingSummary:
    """Map every leaf requirement of *model* with *llm*.

    Returns a :class:`MappingSummary`; everything else lands on the model.
    """
    config = config or MappingConfig()
    summary = MappingSummary()
    candidates = [Candidate.from_function(f) for f in model.ordered_functions()]

    for requirement in leaf_requirements(model):
        unit_ids = llm.map_requirement(requirement, candidates)
        _record(model, requirement, unit_ids)
        summary.leaves_mapped += 1
        summary.pairs += len(unit_ids)

        if not unit_ids:
            # D17: a legitimate result, recorded and carried on.
            summary.empty_leaves += 1
        elif len(unit_ids) > config.category_leak_threshold:
            requirement.category_leak = True
            summary.category_leaks += 1
            LOG.warning(
                "requirement %s: mapped %d functions, over the category-leak "
                "threshold of %d — flagged category_leak; its pairs skip "
                "verification",
                requirement.code, len(unit_ids), config.category_leak_threshold,
            )
    return summary


def _record(model, requirement, unit_ids) -> None:
    """Write the mapping onto the requirement node and each function."""
    requirement.mapped_unit_ids = list(unit_ids)
    for unit_id in unit_ids:
        annotation = model.functions[unit_id].annotation
        if requirement.code not in annotation.requirement_codes:
            annotation.requirement_codes.append(requirement.code)
        # Nothing has been verified yet; chunk 4 promotes the tier.
        annotation.tiers.setdefault(requirement.code, TIER_LLM_ASSERTED)
