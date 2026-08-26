"""Loading a stage-1 ast.json into the mapper model, and slicing source bytes."""

from pathlib import Path

import pytest

from meridian_mapper.astload import AstLoadError, load_ast_json, source_slice
from meridian_mapper.model import MapperModel

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"
AST_JSON = FIXTURES / "ast.json"
CODEBASE = FIXTURES / "codebase"

# The two fixture units the byte-slice tests pin, by dotted name.
ADD_ITEM = "shop.cart.add_item"
NON_ASCII = "shop.facturé.résumé_français"


def unit_id_for(model, dotted_name):
    for function in model.ordered_functions():
        if function.record["dotted_name"] == dotted_name:
            return function.unit_id
    raise AssertionError(f"fixture has no unit named {dotted_name}")


def test_loads_fixture_into_model():
    model = load_ast_json(AST_JSON)
    assert isinstance(model, MapperModel)
    assert len(model.functions) == 5
    assert model.source_meta["schema_version"] == 2
    assert model.source_meta["tool"].startswith("meridian-parser")
    assert "units" not in model.source_meta


def test_keeps_input_file_order():
    model = load_ast_json(AST_JSON)
    names = [f.record["dotted_name"] for f in model.ordered_functions()]
    assert names == [
        "shop.cart.add_item",
        "shop.cart.total_price",
        "shop.cart.Checkout.summarise",
        "shop.facturé.calculer_montant",
        "shop.facturé.résumé_français",
    ]


def test_annotations_start_empty():
    model = load_ast_json(AST_JSON)
    for function in model.ordered_functions():
        assert function.annotation.requirement_codes == []
        assert function.annotation.tiers == {}
        assert function.annotation.error_notes == []
        assert function.annotation.structural_test_only is False


def test_wrong_schema_version_is_a_clear_error():
    with pytest.raises(AstLoadError) as excinfo:
        load_ast_json(FIXTURES / "ast_schema_v1.json")
    message = str(excinfo.value)
    assert "schema_version" in message
    assert "1" in message and "2" in message


def test_missing_schema_version_is_a_clear_error():
    with pytest.raises(AstLoadError, match="schema_version"):
        load_ast_json(FIXTURES / "ast_no_schema.json")


def test_missing_file_is_an_error_naming_the_file(tmp_path):
    missing = tmp_path / "nope.json"
    with pytest.raises(AstLoadError, match="nope.json"):
        load_ast_json(missing)


def test_invalid_json_is_an_error(tmp_path):
    broken = tmp_path / "ast.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(AstLoadError, match="not valid JSON"):
        load_ast_json(broken)


def test_bare_array_is_rejected(tmp_path):
    bare = tmp_path / "ast.json"
    bare.write_text("[]", encoding="utf-8")
    with pytest.raises(AstLoadError, match="schema_version"):
        load_ast_json(bare)


def test_unit_missing_required_fields_is_an_error(tmp_path):
    path = tmp_path / "ast.json"
    path.write_text(
        '{"schema_version": 2, "units": [{"unit_id": "a"}]}', encoding="utf-8"
    )
    with pytest.raises(AstLoadError, match="start_byte"):
        load_ast_json(path)


def test_duplicate_unit_id_is_an_error(tmp_path):
    unit = ('{"unit_id": "a", "file_path": "x.py", '
            '"start_byte": 0, "end_byte": 1}')
    path = tmp_path / "ast.json"
    path.write_text(
        '{"schema_version": 2, "units": [%s, %s]}' % (unit, unit), encoding="utf-8"
    )
    with pytest.raises(AstLoadError, match="duplicate unit_id"):
        load_ast_json(path)


def test_source_slice_is_exactly_the_definition():
    model = load_ast_json(AST_JSON)
    function = model.functions[unit_id_for(model, ADD_ITEM)]
    text = source_slice(CODEBASE, function)
    assert text.startswith("def add_item(cart, item, quantity=1):")
    assert text.endswith("return sum(cart.values())")
    assert "def total_price" not in text


def test_source_slice_handles_non_ascii():
    model = load_ast_json(AST_JSON)
    function = model.functions[unit_id_for(model, NON_ASCII)]
    text = source_slice(CODEBASE, function)
    assert text == (
        'def résumé_français(client):\n'
        '    """Renvoie un résumé lisible pour l\'entête de la facture."""\n'
        '    return f"Facture pour {client} — merci de votre confiance ★"'
    )


def test_source_slice_reports_a_span_past_the_end_of_the_file():
    model = load_ast_json(AST_JSON)
    function = model.functions[unit_id_for(model, ADD_ITEM)]
    function.record["end_byte"] = 10 ** 6
    with pytest.raises(AstLoadError, match="outside"):
        source_slice(CODEBASE, function)


def test_source_slice_reports_a_missing_source_file(tmp_path):
    model = load_ast_json(AST_JSON)
    function = model.functions[unit_id_for(model, ADD_ITEM)]
    with pytest.raises(AstLoadError, match="cannot read source"):
        source_slice(tmp_path, function)
