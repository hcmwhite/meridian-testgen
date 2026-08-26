"""Normalize a requirements document into the model's requirements tree.

The only format this stage parses is numbered markdown (D12): major
requirements numbered ``1``, ``2``, … with numbered subsections ``1.1``,
``2.3.1``, … Codes reproduce the document's own numbering, hyphen-dotted —
``1``, ``1-1``, ``2-3-1`` (D13) — so the mapper never renumbers anything.

The parser sits behind :func:`parse_requirements`, an adapter registry, so a
later format (bulleted markdown, a JSON tree, eventually Word/PDF per
docs/SPEC.md) is an additive adapter rather than a rework. Only the
numbered-markdown adapter exists now.

Category/leaf status is resolved here, once, and recorded on each node: a node
with children is a category and is never mapped or verified; a node without
children is a leaf. Nothing downstream re-decides it (D13).

Malformed input — a subsection with no parent, or a duplicate code — is a
clear :class:`RequirementsError` naming the line, never a silent skip.
"""

from __future__ import annotations

import re
from pathlib import Path

from meridian_mapper.model import Requirement

NUMBERED_MARKDOWN = "numbered_markdown"

# A requirement line: optional markdown heading marker or list bullet, then a
# dotted number ("1", "2.3.1"), an optional "." or ")" separator, then text.
_NUMBERED_LINE = re.compile(
    r"""^\s*
        (?:\#{1,6}\s*)?            # optional heading marker
        (?:[-*]\s*)?               # optional bullet marker
        (?P<number>\d+(?:\.\d+)*)  # the document's own numbering
        [.)]?                      # optional trailing separator
        \s+
        (?P<text>\S.*?)\s*$
    """,
    re.VERBOSE,
)


class RequirementsError(Exception):
    """The requirements document could not be normalized."""


def parse_requirements(text: str, format: str = NUMBERED_MARKDOWN) -> list[Requirement]:
    """Parse *text* into the top-level nodes of a requirements tree.

    *format* selects an adapter; only :data:`NUMBERED_MARKDOWN` is
    implemented. Raises :class:`RequirementsError` for an unknown format or a
    malformed document.
    """
    adapter = _ADAPTERS.get(format)
    if adapter is None:
        known = ", ".join(sorted(_ADAPTERS))
        raise RequirementsError(
            f"unknown requirements format {format!r}; this stage reads: {known}"
        )
    return adapter(text)


def parse_requirements_file(path, format: str = NUMBERED_MARKDOWN) -> list[Requirement]:
    """Read *path* and parse it with :func:`parse_requirements`."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RequirementsError(
            f"cannot read {path}: {exc.strerror or exc}"
        ) from exc
    try:
        return parse_requirements(text, format)
    except RequirementsError as exc:
        raise RequirementsError(f"{path}: {exc}") from exc


def load_into_model(model, path, format: str = NUMBERED_MARKDOWN) -> list[Requirement]:
    """Parse *path* and store the tree on *model* (the one structure, D11)."""
    model.requirements = parse_requirements_file(path, format)
    return model.requirements


def iter_requirements(nodes):
    """Yield every node of *nodes*, depth first, in document order."""
    for node in nodes:
        yield node
        yield from iter_requirements(node.children)


def _code_for(number: str) -> str:
    """``"2.3.1"`` -> ``"2-3-1"`` (D13)."""
    return number.replace(".", "-")


def _parse_numbered_markdown(text: str) -> list[Requirement]:
    roots: list[Requirement] = []
    # Numbering path -> node, for parent lookup and duplicate detection.
    by_number: dict[str, Requirement] = {}
    # The line each code was defined on, for the duplicate-code message.
    line_of: dict[str, int] = {}
    current: Requirement | None = None

    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        match = _NUMBERED_LINE.match(line)
        if match is None:
            # Free text: a continuation of the requirement it sits under, or
            # document preamble before the first numbered line.
            if current is not None:
                current.text = f"{current.text} {line.strip()}".strip()
            continue

        number = match.group("number")
        if number in by_number:
            raise RequirementsError(
                f"line {lineno}: duplicate requirement number {number!r} "
                f"(first seen on line {line_of[number]})"
            )

        parts = number.split(".")
        parent = None
        if len(parts) > 1:
            parent_number = ".".join(parts[:-1])
            parent = by_number.get(parent_number)
            if parent is None:
                raise RequirementsError(
                    f"line {lineno}: subsection {number!r} has no parent "
                    f"requirement {parent_number!r}"
                )

        node = Requirement(code=_code_for(number), text=match.group("text"))
        if parent is None:
            roots.append(node)
        else:
            parent.children.append(node)
        by_number[number] = node
        line_of[number] = lineno
        current = node

    if not roots:
        raise RequirementsError("no numbered requirements found")

    for node in iter_requirements(roots):
        node.is_category = bool(node.children)
    return roots


_ADAPTERS = {NUMBERED_MARKDOWN: _parse_numbered_markdown}
