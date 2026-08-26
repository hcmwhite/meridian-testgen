"""The single in-memory structure a stage-3 run fills in (D24).

Loading fills it from the two stage-2 artifacts; later passes (obligations,
generation, validation, the report) hang their results off the same objects
rather than building a parallel structure beside them. There is one model.

The two artifacts overlap on purpose: Artifact 1 (``mapping_ast.json``) is the
function-first view carrying the tiers, the ``structural_test_only`` tags and
the error notes, and Artifact 2 (``mapping_requirements.json``) is the
requirement-first view carrying the requirement *text* and the category
hierarchy. Generation needs both, so the model holds both and joins them on
the requirement code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The stage-2 verification tiers, re-declared here rather than imported (D22).
TIER_DETERMINISTIC = "deterministic"
TIER_LLM_ASSERTED = "llm_asserted"

# The marker used where a mapped pair would carry a requirement code: a
# structural-only function has no requirement to assert against (D29).
STRUCTURAL_MARKER = "structural"


@dataclass
class TestgenFunction:
    """One record from Artifact 1's ``units`` array.

    *record* is kept verbatim so the report can re-emit stage-1 and stage-2
    fields without this stage having to know all of them; the named fields
    below are the ones generation actually reads.
    """

    # pytest would otherwise try to collect this class for its name alone.
    __test__ = False

    unit_id: str
    record: dict
    requirement_codes: list[str] = field(default_factory=list)
    # requirement code -> "deterministic" | "llm_asserted"
    tiers: dict[str, str] = field(default_factory=dict)
    structural_test_only: bool = False
    error_notes: list[dict] = field(default_factory=list)

    @property
    def dotted_name(self) -> str:
        return self.record.get("dotted_name", "")

    @property
    def name(self) -> str:
        return self.record.get("name", "")

    @property
    def scope(self) -> str:
        return self.record.get("scope", "")

    @property
    def module(self) -> str:
        return self.record.get("module", "")

    @property
    def signature(self) -> str:
        return self.record.get("signature", "")

    @property
    def file_path(self) -> str:
        return self.record["file_path"]

    @property
    def line_number(self) -> int:
        return self.record.get("line_number", 0)

    @property
    def end_line(self) -> int:
        return self.record.get("end_line", 0)

    @property
    def start_byte(self) -> int:
        return self.record["start_byte"]

    @property
    def end_byte(self) -> int:
        return self.record["end_byte"]

    def tier(self, requirement_code: str) -> "str | None":
        return self.tiers.get(requirement_code)


@dataclass
class Requirement:
    """One node of the requirements tree, from Artifact 2, in document order."""

    code: str
    text: str
    is_category: bool = False
    category_leak: bool = False
    # The code *references* Artifact 2 carries; never file contents.
    code_blocks: list[dict] = field(default_factory=list)
    children: list["Requirement"] = field(default_factory=list)


@dataclass
class TestgenModel:
    """Everything a generation run knows, in one place."""

    __test__ = False

    # The two stage-2 envelopes, verbatim, for the report's traceability chain
    # (each already carries the stage-1 envelope under `source_run`).
    ast_meta: dict = field(default_factory=dict)
    requirements_meta: dict = field(default_factory=dict)
    # unit_id -> function, in Artifact 1's order (dicts preserve it).
    functions: dict[str, TestgenFunction] = field(default_factory=dict)
    # The top-level requirement nodes, in document order.
    requirements: list[Requirement] = field(default_factory=list)
    # Generated tests grouped by top-level category code, plus the
    # `structural` group (filled by generate.py; read by the writer).
    generated_groups: dict = field(default_factory=dict)

    def ordered_functions(self) -> list[TestgenFunction]:
        """The functions in Artifact 1's order."""
        return list(self.functions.values())

    def structural_only_functions(self) -> list[TestgenFunction]:
        """The functions with no requirement to assert against."""
        return [f for f in self.ordered_functions() if f.structural_test_only]

    def walk_requirements(self):
        """Every requirement node, depth-first, in document order."""
        def _walk(nodes):
            for node in nodes:
                yield node
                yield from _walk(node.children)
        return _walk(self.requirements)

    def requirement(self, code: str) -> "Requirement | None":
        """The requirement node with *code*, or None if the tree has no such."""
        for node in self.walk_requirements():
            if node.code == code:
                return node
        return None

    def requirement_text(self, code: str) -> str:
        """The text of requirement *code*, or "" when it is not in the tree."""
        node = self.requirement(code)
        return node.text if node is not None else ""

    @staticmethod
    def category_of(code: str) -> str:
        """The top-level category code a requirement code belongs to.

        Stage-2 codes reproduce the document's numbering, hyphenated, so the
        category is the first segment: ``1-2-3`` belongs to category ``1``.
        Test files are named from this (D24).
        """
        return code.split("-", 1)[0]
