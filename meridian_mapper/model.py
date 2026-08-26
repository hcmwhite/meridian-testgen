"""The single in-memory structure both artifacts render from (D11).

The pipeline populates this left to right: ast loading fills
:attr:`MapperModel.functions`, the requirements normalizer fills
:attr:`MapperModel.requirements`, and the mapping, verification and
classification passes mutate the per-function :class:`Annotation`.

Later chunks add fields to these dataclasses rather than building a parallel
structure alongside them: there is one model, and both output passes read it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The two verification tiers (D15). A pair is `deterministic` when its
# evidence snippet was checked against the real source bytes, and
# `llm_asserted` when it never went through verification at all (a
# category-leak pair, D16). There is no third tier.
TIER_DETERMINISTIC = "deterministic"
TIER_LLM_ASSERTED = "llm_asserted"


@dataclass
class ErrorNote:
    """Why a function was removed from a requirement's mapping (D18).

    Written only on verification exhaustion, and only ever on an ast
    function's annotation — Artifact 2 never carries these (D20).
    """

    requirement_code: str
    attempts: list[dict] = field(default_factory=list)


@dataclass
class Annotation:
    """The mapper's mutable notes on one ast function. Empty at load time."""

    requirement_codes: list[str] = field(default_factory=list)
    # requirement code -> tier, for the codes in requirement_codes.
    tiers: dict[str, str] = field(default_factory=dict)
    # requirement code -> {"effect": …, "evidence": …}, for pairs that PASSED
    # verification. This is the claim stage 3 reads (its `claim_for()` looks
    # for exactly this shape under a `claims` key); failed attempts live in
    # error_notes instead, so the two never mix.
    claims: dict[str, dict] = field(default_factory=dict)
    error_notes: list[ErrorNote] = field(default_factory=list)
    structural_test_only: bool = False


@dataclass
class AstFunction:
    """One record from ``ast.json``'s ``units`` array, plus its annotation.

    *record* is kept verbatim so Artifact 1 can re-emit the stage-1 fields
    without this stage having to know all of them.
    """

    unit_id: str
    record: dict
    annotation: Annotation = field(default_factory=Annotation)

    @property
    def file_path(self) -> str:
        return self.record["file_path"]

    @property
    def start_byte(self) -> int:
        return self.record["start_byte"]

    @property
    def end_byte(self) -> int:
        return self.record["end_byte"]


@dataclass
class Requirement:
    """One node of the requirements tree. Filled by chunk 1."""

    code: str
    text: str
    children: list["Requirement"] = field(default_factory=list)
    is_category: bool = False
    category_leak: bool = False
    mapped_unit_ids: list[str] = field(default_factory=list)


@dataclass
class MapperModel:
    """Everything the stage knows, in one place."""

    # The run metadata from the input ast.json envelope, verbatim.
    source_meta: dict = field(default_factory=dict)
    # unit_id -> AstFunction, in the input file's order (dicts preserve it).
    functions: dict[str, AstFunction] = field(default_factory=dict)
    # The requirements tree's top-level nodes (chunk 1 fills this).
    requirements: list[Requirement] = field(default_factory=list)

    def ordered_functions(self) -> list[AstFunction]:
        """The ast functions in the input file's order."""
        return list(self.functions.values())
