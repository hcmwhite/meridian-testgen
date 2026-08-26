"""Unit tests for the AST extractor against small inline source strings."""

from __future__ import annotations

import textwrap

import pytest

from meridian_parser.extractor import (
    REASON_DUNDER,
    REASON_PRIVATE,
    REASON_TEST,
    ParseError,
    extract,
    module_dotted_name,
)


def names(records):
    return [record["dotted_name"] for record in records]


def test_module_level_function_is_included():
    included, excluded = extract("def widget():\n    return 1\n", "shop.py")

    assert names(included) == ["shop.widget"]
    assert excluded == []


def test_dotted_name_is_anchored_to_the_relative_path():
    source = "class Report:\n    def summarize(self):\n        return 1\n"
    included, _ = extract(source, "core/analytics.py")

    assert names(included) == ["core.analytics.Report.summarize"]
    assert included[0]["file_path"] == "core/analytics.py"


def test_signature_keeps_annotations_and_defaults():
    source = "def total(items: list[float], rate: float = 0.0) -> float:\n    return 0.0\n"
    included, _ = extract(source, "billing.py")

    assert included[0]["signature"] == (
        "def total(items: list[float], rate: float = 0.0) -> float"
    )


def test_line_number_is_one_based():
    source = "\n\ndef later():\n    return None\n"
    included, _ = extract(source, "mod.py")

    assert included[0]["line_number"] == 3


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("__init__", REASON_DUNDER),
        ("_helper", REASON_PRIVATE),
        ("test_thing", REASON_TEST),
    ],
)
def test_each_exclusion_reason(name, reason):
    included, excluded = extract(f"def {name}(self):\n    return None\n", "mod.py")

    assert included == []
    assert names(excluded) == [f"mod.{name}"]
    assert excluded[0]["reason"] == reason


def test_overloads_get_numbered_suffixes():
    source = textwrap.dedent(
        """
        def render():
            return 1

        def render(a):
            return 2

        def render(a, b):
            return 3
        """
    )
    included, _ = extract(source, "mod.py")

    assert names(included) == ["mod.render", "mod.render#2", "mod.render#3"]


def test_counter_is_per_scope():
    source = textwrap.dedent(
        """
        def render():
            return 1

        class A:
            def render(self):
                return 2

        class B:
            def render(self):
                return 3
        """
    )
    included, _ = extract(source, "mod.py")

    assert names(included) == ["mod.render", "mod.A.render", "mod.B.render"]


def test_counter_is_not_carried_across_files():
    source = "def render():\n    return 1\n"
    first, _ = extract(source, "a.py")
    second, _ = extract(source, "b.py")

    assert names(first) == ["a.render"]
    assert names(second) == ["b.render"]


def test_no_unit_appears_in_both_lists():
    source = textwrap.dedent(
        """
        def public():
            return 1

        def _private():
            return 2

        class Thing:
            def __init__(self):
                pass

            def method(self):
                return 3
        """
    )
    included, excluded = extract(source, "mod.py")

    assert set(names(included)).isdisjoint(names(excluded))
    assert names(included) == ["mod.public", "mod.Thing.method"]


def test_decorated_and_async_definitions_are_found():
    source = textwrap.dedent(
        """
        import functools

        @functools.cache
        async def fetch(url: str) -> str:
            return url
        """
    )
    included, _ = extract(source, "net.py")

    assert names(included) == ["net.fetch"]
    assert included[0]["signature"] == "async def fetch(url: str) -> str"


def test_locals_inside_a_function_are_excluded_not_dropped():
    """A local cannot be imported, so it is not testable — but it is recorded
    with a reason rather than silently missing."""
    source = "def outer():\n    def inner():\n        return 1\n    return inner\n"
    included, excluded = extract(source, "mod.py")

    assert names(included) == ["mod.outer"]
    assert names(excluded) == ["mod.outer.inner"]
    assert excluded[0]["reason"] == "nested_function"


def test_nesting_beats_the_name_based_reasons():
    source = "def outer():\n    def _helper():\n        pass\n"
    _, excluded = extract(source, "mod.py")

    assert excluded[0]["reason"] == "nested_function"


def test_methods_of_a_class_defined_in_a_function_are_nested():
    source = "def factory():\n    class Inner:\n        def method(self):\n            pass\n"
    included, excluded = extract(source, "mod.py")

    assert names(included) == ["mod.factory"]
    assert names(excluded) == ["mod.factory.Inner.method"]
    assert excluded[0]["reason"] == "nested_function"


def test_definitions_inside_conditionals_are_extracted():
    """A `def` inside if/try/with binds at the enclosing scope, so it is a
    unit of that scope — see _TRANSPARENT_BLOCKS in the extractor."""
    source = (
        "import sys\n"
        "if sys.version_info >= (3, 11):\n"
        "    def gated():\n        pass\n"
        "else:\n"
        "    def gated():\n        pass\n"
        "try:\n"
        "    def in_try():\n        pass\n"
        "except ImportError:\n"
        "    def in_except():\n        pass\n"
        "with open('f') as fh:\n"
        "    def in_with():\n        pass\n"
        "for _ in range(1):\n"
        "    def in_for():\n        pass\n"
    )
    included, _ = extract(source, "mod.py")

    assert names(included) == [
        "mod.gated", "mod.gated#2", "mod.in_try", "mod.in_except",
        "mod.in_with", "mod.in_for",
    ]


def test_conditional_methods_inside_a_class_are_extracted():
    source = (
        "class C:\n"
        "    if True:\n"
        "        def cond(self):\n            pass\n"
        "    def plain(self):\n        pass\n"
    )
    included, _ = extract(source, "mod.py")

    assert names(included) == ["mod.C.cond", "mod.C.plain"]


def test_span_fields_cover_the_definition_without_decorators():
    source = "@decorator\ndef fn(a):\n    return a\n"
    included, _ = extract(source, "mod.py")

    record = included[0]
    assert record["line_number"] == 2      # the `def` line, not the decorator
    assert record["end_line"] == 3         # the last line of the body
    assert record["column"] == 0
    assert source.encode()[record["start_byte"]:record["end_byte"]].startswith(b"def fn")


def test_syntax_error_reports_the_line():
    with pytest.raises(ParseError) as caught:
        extract("def broken(:\n    pass\n", "mod.py")

    assert caught.value.line == 1


def test_dotted_name_never_has_an_empty_segment():
    """A dot-prefixed directory must not produce "pkg..hidden.mod"."""
    assert module_dotted_name("pkg/.hidden/mod.py") == "pkg.hidden.mod"
    assert ".." not in module_dotted_name("pkg/.hidden/mod.py")


def test_package_init_uses_the_directory_name():
    assert module_dotted_name("core/__init__.py") == "core"
    assert module_dotted_name("core/analytics.py") == "core.analytics"


def test_unparseable_source_raises():
    with pytest.raises(ParseError):
        extract("def broken(:\n", "mod.py")


def test_every_record_carries_a_unit_id():
    source = "def visible():\n    pass\n\ndef _hidden():\n    pass\n"
    included, excluded = extract(source, "mod.py")

    for record in included + excluded:
        assert record["unit_id"]
        assert len(record["unit_id"]) == 12


def test_unit_id_survives_inserting_a_sibling_above():
    """The whole point of the hash: the #N in dotted_name shifts when a
    same-named definition is inserted above, but unit_id must not."""
    before = "def validate():\n    pass\n\ndef validate(x):\n    pass\n"
    after = (
        "def validate(y, z):\n    pass\n\n"
        "def validate():\n    pass\n\ndef validate(x):\n    pass\n"
    )
    ids_before = {r["signature"]: r["unit_id"] for r, _ in
                  [(r, None) for r in extract(before, "mod.py")[0]]}
    ids_after = {r["signature"]: r["unit_id"] for r in extract(after, "mod.py")[0]}

    assert ids_after["def validate()"] == ids_before["def validate()"]
    assert ids_after["def validate(x)"] == ids_before["def validate(x)"]


def test_identical_definitions_get_suffixed_duplicate_ids():
    source = "def twin():\n    pass\n\ndef twin():\n    pass\n"
    included, _ = extract(source, "mod.py")

    first, second = included
    assert "-" not in first["unit_id"]
    assert second["unit_id"] == first["unit_id"] + "-2"


def test_unit_id_ignores_signature_whitespace():
    one = "def fn(a, b):\n    pass\n"
    two = "def fn(a,\n       b):\n    pass\n"
    assert extract(one, "mod.py")[0][0]["unit_id"] == \
        extract(two, "mod.py")[0][0]["unit_id"]


def test_module_scope_and_name_are_emitted_separately():
    """A consumer must never have to split dotted_name — packages and classes
    use the same separator, so the split is ambiguous."""
    source = "class C:\n    def method(self):\n        pass\n"
    included, _ = extract(source, "pkg/sub/mod.py")

    record = included[0]
    assert record["module"] == "pkg.sub.mod"
    assert record["scope"] == "C"
    assert record["name"] == "method"
    assert record["dotted_name"] == "pkg.sub.mod.C.method"


def test_scope_is_empty_for_a_module_level_function():
    included, _ = extract("def fn():\n    pass\n", "mod.py")

    assert included[0]["scope"] == ""
    assert included[0]["module"] == "mod"
    assert included[0]["name"] == "fn"


def test_name_is_the_bare_identifier_not_the_disambiguated_one():
    """dotted_name carries the "#N"; `name` stays the importable identifier."""
    source = "def fn():\n    pass\n\ndef fn():\n    pass\n"
    included, _ = extract(source, "mod.py")

    assert [r["name"] for r in included] == ["fn", "fn"]
    assert [r["dotted_name"] for r in included] == ["mod.fn", "mod.fn#2"]


def test_columns_are_byte_offsets_not_character_offsets():
    source = "class Caf\u00e9:\n    def m\u00e9thode(self): pass\n"
    included, _ = extract(source, "u.py")

    record = included[0]
    line = source.splitlines()[1]
    assert record["end_column"] == len(line.encode("utf-8"))
    assert record["end_column"] != len(line)
