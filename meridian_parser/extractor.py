"""Pure extraction of testable units from one Python source file.

``extract`` takes the text of a file and that file's path relative to the input
root and returns two lists of records — units to include in ``ast.json`` and
units to exclude, each excluded record carrying its reason. It writes no files
and keeps no state between calls.

Syntax validity is decided by Python itself (:func:`ast.parse`), not by this
module and not by tree-sitter. Python owns the definition of what its own
grammar accepts; re-deciding that here would mean maintaining a second, always
slightly wrong, opinion about it. tree-sitter is used only to walk the shape of
source already known to be valid.

One consequence worth naming: :func:`ast.parse` is the grammar of the
*interpreter running this tool*, so source using syntax newer than that
interpreter is reported as a syntax error rather than parsed.
"""

from __future__ import annotations

import ast
import hashlib
import os
from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

REASON_DUNDER = "dunder_method"
REASON_PRIVATE = "private_name"
REASON_TEST = "test_function"
REASON_NESTED = "nested_function"

_LANGUAGE = Language(tree_sitter_python.language())

# Node types that introduce a new naming scope. Their bodies are walked by
# _collect itself, which extends the dotted prefix before descending.
_SCOPE_NODES = frozenset({"function_definition", "class_definition"})

# Compound statements whose bodies are walked WITHOUT changing the dotted
# prefix, because Python lets a definition sit inside one and still bind at the
# enclosing scope.
#
# PYTHON-SPECIFIC — DOES NOT PORT CLEANLY TO OTHER LANGUAGES.
# Python has no separate declaration space: `def` is an executable statement
# that binds a name wherever it runs. So all of these are ordinary, idiomatic
# places to define a module-level or class-level function:
#
#     if sys.version_info >= (3, 11):     # version-gated implementations
#         def parse(s): ...
#     try:                                 # optional-dependency fallbacks
#         from fast import parse
#     except ImportError:
#         def parse(s): ...
#     if TYPE_CHECKING:                    # typing-only overloads
#         def parse(s: str) -> Node: ...
#
# In C, Java, C#, Go or Rust a function cannot be declared inside a conditional
# at all, and a port to those languages should delete this set rather than
# translate it. In JavaScript and Ruby the equivalent exists but the node names
# and hoisting rules differ enough that the list has to be rebuilt from that
# language's own grammar, not transliterated from this one.
_TRANSPARENT_BLOCKS = frozenset({
    "block",
    "if_statement", "elif_clause", "else_clause",
    "for_statement", "while_statement",
    "try_statement", "except_clause", "except_group_clause",
    "finally_clause",
    "with_statement",
    "match_statement", "case_clause",
})


class ParseError(Exception):
    """Raised when the source is not valid Python.

    Carries the line, column and message from :class:`SyntaxError` where the
    failure came from Python's own parser, so a caller can report where the
    problem is rather than only which file it was in.
    """

    def __init__(self, message: str, *, line: int | None = None,
                 column: int | None = None) -> None:
        super().__init__(message)
        self.line = line
        self.column = column


def module_dotted_name(relative_path: str | os.PathLike[str]) -> str:
    """Return the module part of a dotted name for a path below the root.

    Leading dots are stripped from each segment. A directory named `.hidden`
    would otherwise contribute an empty segment ("pkg..hidden.mod"), which
    breaks any consumer that splits the dotted name on ".". Hidden directories
    are excluded by default anyway; this is the backstop for a config that
    opts back into one.
    """
    parts = PurePosixPath(str(relative_path).replace(os.sep, "/")).parts
    stem = parts[-1][: -len(".py")] if parts[-1].endswith(".py") else parts[-1]
    parts = parts[:-1] if stem == "__init__" else (*parts[:-1], stem)
    cleaned = [segment.lstrip(".") for segment in parts]
    return ".".join(segment for segment in cleaned if segment)


def exclusion_reason(name: str, *, nested: bool = False) -> str | None:
    """Return the exclusion reason for a definition, or None if it is included.

    *nested* means at least one enclosing scope is a function. Such a
    definition is a local: it is not bound at module or class level, so it
    cannot be imported and cannot be unit tested on its own terms. That is a
    structural fact rather than a naming convention, so it is decided before
    the name-based rules and wins over them — a `_helper` inside a function is
    reported as ``nested_function``, not ``private_name``.
    """
    if nested:
        return REASON_NESTED
    if name.startswith("__") and name.endswith("__"):
        return REASON_DUNDER
    if name.startswith("_"):
        return REASON_PRIVATE
    if name.startswith("test_"):
        return REASON_TEST
    return None


def check_syntax(source: str, relative_path: str | os.PathLike[str]) -> None:
    """Raise :class:`ParseError` if *source* is not valid Python.

    Delegates to :func:`ast.parse`, so the answer is Python's own rather than
    this tool's approximation of it, and the diagnostic is the interpreter's.
    """
    try:
        ast.parse(source, filename=str(relative_path))
    except SyntaxError as exc:
        detail = exc.msg or "invalid syntax"
        where = f" (line {exc.lineno}" + (f", column {exc.offset}" if exc.offset else "") + ")" \
            if exc.lineno else ""
        raise ParseError(f"{detail}{where}", line=exc.lineno,
                         column=exc.offset) from exc
    except ValueError as exc:
        # Source containing a null byte, and similar cases ast.parse rejects
        # without raising SyntaxError.
        raise ParseError(str(exc) or "could not parse source") from exc


def _text(source_bytes: bytes, node: Node) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _signature(source_bytes: bytes, node: Node) -> str:
    """Return the signature as written in source, without the trailing colon."""
    body = node.child_by_field_name("body")
    end = body.start_byte if body is not None else node.end_byte
    text = source_bytes[node.start_byte : end].decode("utf-8", "replace").rstrip()
    return text[:-1].rstrip() if text.endswith(":") else text


def _disambiguate(counters: dict[tuple[str, str], int], scope: str, name: str) -> str:
    """Return *name* with a ``#N`` suffix for its second and later definitions."""
    key = (scope, name)
    counters[key] = counters.get(key, 0) + 1
    count = counters[key]
    return name if count == 1 else f"{name}#{count}"


def _unit_id(hash_counts: dict[str, int], file_path: str, scope: str,
             name: str, signature: str) -> str:
    """A stable id for one definition, included in every output record.

    It is a hash of what the function IS — its file, scope, bare name, and
    signature (whitespace collapsed) — not where it sits in the file. Adding
    or removing a neighbouring definition therefore never changes an existing
    unit's id, unlike the positional ``#N`` in the dotted name.

    Two definitions with the same name and signature in one scope (Python
    allows this — the later one simply wins at runtime) would hash the same,
    so the second and later occurrences get a ``-2``, ``-3`` suffix. The
    suffix doubles as the duplicate signal the CLI reports to the user.
    """
    base = hashlib.sha1(
        f"{file_path}\x00{scope}\x00{name}\x00{' '.join(signature.split())}"
        .encode()
    ).hexdigest()[:12]
    hash_counts[base] = hash_counts.get(base, 0) + 1
    count = hash_counts[base]
    return base if count == 1 else f"{base}-{count}"


def _definitions(node: Node) -> "list[Node]":
    """Every definition bound in *node*'s own scope, in source order.

    Descends through the compound statements in :data:`_TRANSPARENT_BLOCKS` —
    a `def` inside `if`/`try`/`with` binds at the enclosing scope, so it belongs
    to this scope's list — but never through a nested function or class body,
    which :func:`_collect` handles separately so the dotted prefix grows.
    """
    found: list[Node] = []
    for child in node.named_children:
        if child.type == "decorated_definition":
            inner = child.child_by_field_name("definition")
            if inner is not None:
                found.append(inner)
            continue
        if child.type in _SCOPE_NODES:
            found.append(child)
            continue
        if child.type in _TRANSPARENT_BLOCKS:
            found.extend(_definitions(child))
    return found


def _span(node: Node) -> dict:
    """Positional fields for *node*.

    The span runs from the `def` or `class` keyword to the last byte of the
    body. It deliberately EXCLUDES decorator lines, so it agrees with
    ``line_number``; a caller wanting the decorators has to walk upward from
    ``line_number``.

    Lines are 1-indexed. ``start_byte`` is inclusive and ``end_byte``
    exclusive, so ``source_bytes[start_byte:end_byte]`` is exactly the
    definition.

    ``column`` and ``end_column`` are 0-indexed BYTE offsets within their
    line, not character offsets — they come straight from tree-sitter, which
    counts UTF-8 bytes. On a line containing non-ASCII text they will not
    agree with a character index or with a JavaScript string index (UTF-16
    code units): a method named ``méthode`` on a 27-character line reports
    ``end_column: 28``. A consumer highlighting source should slice by
    ``start_byte``/``end_byte`` against the file's bytes, which is exact in
    every case, or convert byte columns to character columns itself.
    """
    start_row, start_column = node.start_point
    end_row, end_column = node.end_point
    return {
        "line_number": start_row + 1,
        "column": start_column,
        "end_line": end_row + 1,
        "end_column": end_column,
        "start_byte": node.start_byte,
        "end_byte": node.end_byte,
    }


def _collect(
    node: Node,
    source_bytes: bytes,
    module: str,
    scope: str,
    file_path: str,
    counters: dict[tuple[str, str], int],
    hash_counts: dict[str, int],
    included: list[dict],
    excluded: list[dict],
    nested: bool = False,
) -> None:
    """Record every function in *node*'s scope, then descend into its scopes.

    *nested* is sticky: once inside a function body it stays true for
    everything below, including the methods of a class defined there, because
    none of them are reachable from outside the call that creates them.
    """
    body = node.child_by_field_name("body") if node.type != "module" else node
    if body is None:
        return

    for child in _definitions(body):
        name_node = child.child_by_field_name("name")
        if name_node is None:
            continue
        name = _text(source_bytes, name_node)

        if child.type == "function_definition":
            local = _disambiguate(counters, scope, name)
            prefix = f"{module}.{scope}" if scope else module
            dotted = f"{prefix}.{local}" if prefix else local
            signature = _signature(source_bytes, child)
            record = {
                "unit_id": _unit_id(hash_counts, file_path, scope, name, signature),
                "dotted_name": dotted,
                # The three parts dotted_name is built from, emitted separately
                # so a consumer never has to split the dotted name — which is
                # ambiguous, since packages and classes use the same separator.
                # `name` is the bare Python identifier (what you would import
                # or getattr); dotted_name's final segment is this plus any
                # "#N" suffix.
                "module": module,
                "scope": scope,
                "name": name,
                "file_path": file_path,
                **_span(child),
                "signature": signature,
            }
            reason = exclusion_reason(name, nested=nested)
            if reason is None:
                included.append(record)
            else:
                excluded.append({**record, "reason": reason})
            # A function's own body is a scope: definitions inside it are
            # recorded beneath it, as `module.outer.inner`, and are locals.
            _collect(
                child, source_bytes, module, f"{scope}.{local}" if scope else local,
                file_path, counters, hash_counts, included, excluded, True,
            )
        elif child.type == "class_definition":
            inner = f"{scope}.{name}" if scope else name
            _collect(
                child, source_bytes, module, inner, file_path, counters,
                hash_counts, included, excluded, nested,
            )


def extract(source: str, relative_path: str | os.PathLike[str]) -> tuple[list[dict], list[dict]]:
    """Extract (included, excluded) unit records from one Python source file.

    *relative_path* is the file's path relative to the input root; it anchors
    both ``file_path`` and the module part of every ``dotted_name``. The
    overload counter is local to this call, so ``#N`` suffixes never carry
    across files.

    Raises :class:`ParseError` if the source is not valid Python.
    """
    check_syntax(source, relative_path)

    source_bytes = source.encode("utf-8")
    tree = Parser(_LANGUAGE).parse(source_bytes)

    file_path = str(relative_path).replace(os.sep, "/")
    included: list[dict] = []
    excluded: list[dict] = []
    _collect(
        tree.root_node, source_bytes, module_dotted_name(file_path), "",
        file_path, {}, {}, included, excluded,
    )
    return included, excluded
