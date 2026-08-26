"""The deterministic structural-obligation checklist (D33).

Before a single prompt is assembled, this pass answers "what must a test suite
for this function touch at all?" from the function itself: its parameters and
their hints, its return annotation, the branches in its body and the exceptions
it raises. No LLM is involved and none is needed — every obligation here is a
fact about the source, and facts about source are cheaper and more reliable to
read than to ask for.

The reading is done with Python's own :mod:`ast` module on the function's byte
slice. That is not a second parser opinion competing with stage 1's
tree-sitter parse (D3): stage 1 decided *which* spans are functions, and this
module only re-reads a span already known to be a valid definition, to see
inside a body that the signature alone cannot describe.

Output is an ordered list of short strings, stable for identical input: the
same slice always yields the same checklist, in the same order, so a prompt
built from it is reproducible.
"""

from __future__ import annotations

import ast

# The obligations come out grouped, and the groups come out in this order:
# what goes in, what may be missing, what the edges are, what comes out, what
# paths exist, and what can go wrong.
_ORDER = (
    "parameter",
    "none",
    "boundary",
    "return",
    "branch",
    "raise",
)

# Annotations (or defaults) that mean "a number": boundary obligations are
# zero / one / many.
_NUMERIC_HINTS = frozenset({"int", "float", "complex", "Decimal", "Fraction"})

# Annotations that mean "a thing with a length": boundary obligations are
# empty / one element / many elements.
_SEQUENCE_HINTS = frozenset(
    {
        "list",
        "List",
        "tuple",
        "Tuple",
        "set",
        "Set",
        "frozenset",
        "dict",
        "Dict",
        "Mapping",
        "MutableMapping",
        "str",
        "bytes",
        "bytearray",
        "Sequence",
        "MutableSequence",
        "Iterable",
        "Iterator",
        "Collection",
    }
)

# The names a bound first parameter goes by; they are not inputs a test varies.
_IMPLICIT_FIRST = frozenset({"self", "cls"})


class ObligationError(Exception):
    """The body slice could not be read as a function definition."""


def obligations_for_function(function, body_source: str) -> list[str]:
    """The checklist for one model function and the source of its definition.

    *function* is a :class:`~meridian_testgen.model.TestgenFunction`; its
    ``line_number`` anchors the branch and exception obligations to lines in
    the real file rather than to lines within the slice.
    """
    return obligations_for_source(body_source, start_line=function.line_number or 1)


def obligations_for_source(source: str, start_line: int = 1) -> list[str]:
    """The checklist for a definition given as text.

    *start_line* is the line in the original file that the ``def`` sits on, so
    "cover the branch at line N" names a line the reader can go and look at.
    """
    node = _parse_definition(source)
    # Line L within the slice is line (start_line + L - def's own line) in the
    # file; a decorated definition therefore still anchors on its `def`.
    offset = start_line - node.lineno

    groups: dict[str, list[str]] = {kind: [] for kind in _ORDER}
    _parameter_obligations(node, groups)
    groups["return"].append(_return_obligation(node))
    _body_obligations(node, offset, groups)

    return [line for kind in _ORDER for line in groups[kind]]


# The checklist is never empty: a function with no parameters, no branches and
# no annotations still owes its caller a return obligation.


def _parse_definition(source: str) -> ast.AST:
    """The single function definition in *source*, dedented if it is a method.

    A method's byte slice starts at its ``def`` — column zero as far as the
    text is concerned — while its body carries the class's indentation, which
    is a syntax error on its own. Re-parse with the body's common indent
    removed rather than guessing how deeply the class was nested.
    """
    for candidate in (source, _dedent_body(source)):
        if candidate is None:
            continue
        try:
            tree = ast.parse(candidate)
        except SyntaxError:
            continue
        for entry in tree.body:
            if isinstance(entry, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return entry
        raise ObligationError("source contains no function definition")
    raise ObligationError("source could not be parsed as a function definition")


def _dedent_body(source: str) -> "str | None":
    """*source* with the common indentation of its non-first lines removed."""
    lines = source.splitlines()
    if len(lines) < 2:
        return None
    rest = [line for line in lines[1:] if line.strip()]
    if not rest:
        return None
    indent = min(len(line) - len(line.lstrip()) for line in rest)
    if indent == 0:
        return None
    trimmed = [lines[0]] + [line[indent:] if line.strip() else line for line in lines[1:]]
    return "\n".join(trimmed) + "\n"


def _parameters(node) -> list[tuple[str, "ast.expr | None", bool]]:
    """(name, annotation, has_none_default) for every parameter that is an input.

    ``self`` and ``cls`` in first position are the bound receiver, not an input
    a test varies, so they are dropped.
    """
    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    # Defaults fill the positional list from the right.
    defaults: dict[int, ast.expr] = {}
    if args.defaults:
        first = len(positional) - len(args.defaults)
        for index, default in enumerate(args.defaults):
            defaults[first + index] = default

    out: list[tuple[str, ast.expr | None, bool]] = []
    for index, arg in enumerate(positional):
        if index == 0 and arg.arg in _IMPLICIT_FIRST:
            continue
        out.append((arg.arg, arg.annotation, _is_none(defaults.get(index))))
    if args.vararg is not None:
        out.append(("*" + args.vararg.arg, args.vararg.annotation, False))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        out.append((arg.arg, arg.annotation, _is_none(default)))
    if args.kwarg is not None:
        out.append(("**" + args.kwarg.arg, args.kwarg.annotation, False))
    return out


def _is_none(expr) -> bool:
    return isinstance(expr, ast.Constant) and expr.value is None


def _render(annotation) -> "str | None":
    if annotation is None:
        return None
    return ast.unparse(annotation)


def _hint_names(annotation) -> set[str]:
    """Every bare name mentioned in an annotation, for classifying it."""
    if annotation is None:
        return set()
    names = set()
    for sub in ast.walk(annotation):
        if isinstance(sub, ast.Name):
            names.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            names.add(sub.attr)
    return names


def _is_optional(annotation) -> bool:
    """True when the annotation admits ``None`` — ``Optional[X]`` or ``X | None``."""
    if annotation is None:
        return False
    if "Optional" in _hint_names(annotation):
        return True
    for sub in ast.walk(annotation):
        if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
            if _is_none(sub.left) or _is_none(sub.right):
                return True
        if isinstance(sub, ast.Constant) and sub.value is None:
            # `Union[X, None]` unparses its None as a constant inside the
            # subscript; either spelling counts.
            return True
    return False


def _parameter_obligations(node, groups: dict[str, list[str]]) -> None:
    for name, annotation, none_default in _parameters(node):
        rendered = _render(annotation)
        if rendered is None:
            groups["parameter"].append(
                f"parameter '{name}' — untyped — exercise a representative and "
                f"a wrong-type value"
            )
        else:
            groups["parameter"].append(
                f"parameter '{name}' ({rendered}) — exercise a representative value"
            )

        if _is_optional(annotation) or none_default:
            reason = "default is None" if none_default else "the hint admits None"
            groups["none"].append(
                f"parameter '{name}' — cover None ({reason}) and a present value"
            )

        names = _hint_names(annotation)
        if names & _NUMERIC_HINTS:
            groups["boundary"].append(
                f"parameter '{name}' — cover the numeric boundaries: zero, one, many"
            )
        elif names & _SEQUENCE_HINTS:
            groups["boundary"].append(
                f"parameter '{name}' — cover the sequence boundaries: empty, one "
                f"element, many elements"
            )


def _return_obligation(node) -> str:
    rendered = _render(node.returns)
    if rendered is None:
        return (
            "return — no annotation — assert the returned value itself, "
            "including None where the function falls off its end"
        )
    return f"return — assert the result is {rendered} and has the expected value"


# The compound statements whose arms are separate paths through the body. Each
# entry maps the node type to the label the obligation uses.
def _body_obligations(node, offset: int, groups: dict[str, list[str]]) -> None:
    branches: list[tuple[int, int, str]] = []
    raises: list[tuple[int, int, str]] = []

    for sub in _own_body(node):
        line = sub.lineno + offset
        if isinstance(sub, ast.If):
            # `elif` is an If nested in an else; ast cannot tell them apart, so
            # both read as "the if branch" — the line number disambiguates.
            branches.append((line, sub.col_offset, "the if branch"))
            if sub.orelse and not (
                len(sub.orelse) == 1 and isinstance(sub.orelse[0], ast.If)
            ):
                branches.append((line, sub.col_offset, "the else branch of the if"))
        elif isinstance(sub, (ast.For, ast.AsyncFor)):
            branches.append((line, sub.col_offset, "the loop body"))
            if sub.orelse:
                branches.append((line, sub.col_offset, "the else branch of the loop"))
        elif isinstance(sub, ast.While):
            branches.append((line, sub.col_offset, "the loop body"))
            if sub.orelse:
                branches.append((line, sub.col_offset, "the else branch of the loop"))
        elif isinstance(sub, ast.Try) or type(sub).__name__ == "TryStar":
            branches.append((line, sub.col_offset, "the try body"))
            for handler in sub.handlers:
                caught = _render(handler.type) or "any exception"
                branches.append(
                    (
                        handler.lineno + offset,
                        handler.col_offset,
                        f"the except {caught} handler",
                    )
                )
            if sub.orelse:
                branches.append((line, sub.col_offset, "the else branch of the try"))
            if sub.finalbody:
                branches.append((line, sub.col_offset, "the finally block"))
        elif isinstance(sub, ast.Match):
            for case in sub.cases:
                pattern = ast.unparse(case.pattern)
                branches.append(
                    (
                        case.pattern.lineno + offset,
                        case.pattern.col_offset,
                        f"the match arm '{pattern}'",
                    )
                )
        elif isinstance(sub, ast.Raise):
            raised = _render(sub.exc) or "the exception"
            raises.append((line, sub.col_offset, raised))

    # Sorted by position only, and stably: arms discovered at the same
    # position keep the order they were emitted in, which is the order they
    # read in the source (`try` body before its handlers, `if` before `else`).
    for line, _col, label in sorted(branches, key=lambda item: item[:2]):
        groups["branch"].append(f"cover {label} at line {line}")
    for line, _col, raised in sorted(raises, key=lambda item: item[:2]):
        groups["raise"].append(f"assert `{raised}` is raised, from line {line}")


def _own_body(node):
    """Every statement of *node*'s own body, depth-first, in source order.

    Nested definitions are skipped: their branches belong to their own
    checklist, not to their enclosing function's.
    """
    def _walk(statements):
        for statement in statements:
            yield statement
            if isinstance(
                statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                continue
            for field in ("body", "orelse", "finalbody"):
                yield from _walk(getattr(statement, field, []) or [])
            for handler in getattr(statement, "handlers", []) or []:
                yield from _walk(handler.body)
            for case in getattr(statement, "cases", []) or []:
                yield from _walk(case.body)

    return _walk(node.body)
