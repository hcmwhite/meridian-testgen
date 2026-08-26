"""The numbered-markdown requirements normalizer (chunk 1)."""

from pathlib import Path

import pytest

from meridian_mapper.model import MapperModel
from meridian_mapper.requirements import (
    NUMBERED_MARKDOWN,
    RequirementsError,
    iter_requirements,
    load_into_model,
    parse_requirements,
    parse_requirements_file,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"
WELLFORMED = FIXTURES / "requirements_wellformed.md"
MALFORMED = FIXTURES / "requirements_malformed.md"
DUPLICATE = FIXTURES / "requirements_duplicate.md"


def test_wellformed_fixture_codes_nesting_and_flags():
    roots = parse_requirements_file(WELLFORMED)

    assert [r.code for r in roots] == ["1", "2"]
    cart, invoicing = roots
    assert [c.code for c in cart.children] == ["1-1", "1-2"]
    assert [c.code for c in cart.children[0].children] == ["1-1-1", "1-1-2"]
    assert [c.code for c in invoicing.children] == ["2-1"]

    # Category/leaf is resolved here, once (D13).
    assert cart.is_category is True
    assert cart.children[0].is_category is True
    assert cart.children[0].children[0].is_category is False
    assert cart.children[1].is_category is False
    assert invoicing.children[0].is_category is False


def test_document_order_is_preserved():
    roots = parse_requirements_file(WELLFORMED)
    assert [r.code for r in iter_requirements(roots)] == [
        "1", "1-1", "1-1-1", "1-1-2", "1-2", "2", "2-1",
    ]


def test_text_captures_the_clause_and_its_continuation_lines():
    roots = parse_requirements_file(WELLFORMED)
    assert roots[0].text == (
        "Cart management The shopping cart holds the customer's chosen items."
    )
    assert roots[0].children[0].children[1].text == (
        "Adding an item with a non-positive quantity is rejected."
    )


def test_orphan_subsection_is_an_error_naming_the_line():
    with pytest.raises(RequirementsError) as exc:
        parse_requirements_file(MALFORMED)
    message = str(exc.value)
    assert "line 5" in message
    assert "2.1" in message
    assert str(MALFORMED) in message


def test_duplicate_code_is_an_error_naming_both_lines():
    with pytest.raises(RequirementsError) as exc:
        parse_requirements_file(DUPLICATE)
    message = str(exc.value)
    assert "line 5" in message
    assert "line 3" in message
    assert "duplicate" in message


def test_unknown_format_is_rejected():
    with pytest.raises(RequirementsError) as exc:
        parse_requirements("1. Something", format="json_tree")
    assert "json_tree" in str(exc.value)
    assert NUMBERED_MARKDOWN in str(exc.value)


def test_document_with_no_numbered_lines_is_an_error():
    with pytest.raises(RequirementsError):
        parse_requirements("# Just a heading\n\nprose only\n")


def test_load_into_model_fills_the_requirements_slot():
    model = MapperModel()
    assert model.requirements == []
    load_into_model(model, WELLFORMED)
    assert [r.code for r in model.requirements] == ["1", "2"]
