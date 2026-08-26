"""Loading the two stage-2 artifacts into the stage-3 model (D24)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meridian_testgen.config import CONFIG_PYTHON_KEY, config_path
from meridian_testgen.inputs import (
    InputError,
    load_mapping_ast,
    load_mapping_requirements,
    load_model,
    source_slice,
)
from meridian_testgen.model import TIER_DETERMINISTIC, TIER_LLM_ASSERTED, TestgenModel

FIXTURES = Path(__file__).parent / "fixtures" / "testgen"
MAPPING_AST = FIXTURES / "mapping_ast.json"
MAPPING_REQUIREMENTS = FIXTURES / "mapping_requirements.json"
CODEBASE = FIXTURES / "codebase"


@pytest.fixture()
def model() -> TestgenModel:
    return load_model(MAPPING_AST, MAPPING_REQUIREMENTS)


def test_both_fixture_artifacts_load(model):
    assert [f.unit_id for f in model.ordered_functions()] == [
        "aaaa11112222", "bbbb33334444", "cccc55556666", "dddd77778888",
    ]
    assert [r.code for r in model.requirements] == ["1", "2"]


def test_annotations_come_through(model):
    discount = model.functions["aaaa11112222"]
    assert discount.requirement_codes == ["1-1"]
    assert discount.tier("1-1") == TIER_DETERMINISTIC
    assert discount.structural_test_only is False

    render = model.functions["dddd77778888"]
    assert render.tier("2-1") == TIER_LLM_ASSERTED
    assert render.scope == "Receipt"


def test_the_structural_only_function_is_identifiable(model):
    assert [f.unit_id for f in model.structural_only_functions()] == ["cccc55556666"]
    assert model.functions["cccc55556666"].requirement_codes == []


def test_error_notes_are_retained(model):
    notes = model.functions["bbbb33334444"].error_notes
    assert [n["requirement_code"] for n in notes] == ["1-3"]
    assert notes[0]["attempts"][0]["failure"]


def test_the_requirements_tree_carries_text_and_the_leak_flag(model):
    assert model.requirement_text("1-1").startswith("A discount reduces")
    assert model.requirement("1").is_category is True
    assert model.requirement("2-1").category_leak is True
    assert model.requirement("nope") is None


def test_category_grouping_uses_the_first_code_segment():
    assert TestgenModel.category_of("1-2") == "1"
    assert TestgenModel.category_of("10-3-4") == "10"
    assert TestgenModel.category_of("2") == "2"


def test_both_envelopes_are_kept_for_traceability(model):
    assert model.ast_meta["artifact"] == "mapping_ast"
    assert model.requirements_meta["artifact"] == "mapping_requirements"
    # The stage-1 envelope rides along inside the stage-2 one.
    assert model.ast_meta["source_run"]["tool"].startswith("meridian-parser")
    assert model.ast_meta["llm_usage"]["calls"] == 7


def _rewritten(tmp_path, source, **changes):
    data = json.loads(source.read_text(encoding="utf-8"))
    data.update(changes)
    path = tmp_path / source.name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_wrong_schema_version_is_a_clear_error(tmp_path):
    path = _rewritten(tmp_path, MAPPING_AST, schema_version=2)

    with pytest.raises(InputError) as excinfo:
        load_mapping_ast(path)

    assert "schema_version 2" in str(excinfo.value)


def test_wrong_artifact_name_is_a_clear_error(tmp_path):
    # The array key is right and only the artifact name is wrong, so nothing
    # but the artifact check can catch this.
    path = _rewritten(tmp_path, MAPPING_AST, artifact="something_else")

    with pytest.raises(InputError) as excinfo:
        load_mapping_ast(path)

    assert "'something_else'" in str(excinfo.value)
    assert "'mapping_ast'" in str(excinfo.value)


def test_the_two_artifacts_the_wrong_way_round_are_rejected():
    with pytest.raises(InputError) as excinfo:
        load_mapping_ast(MAPPING_REQUIREMENTS)
    assert "is artifact" in str(excinfo.value)

    with pytest.raises(InputError) as excinfo:
        load_mapping_requirements(MAPPING_AST)
    assert "is artifact" in str(excinfo.value)


def test_a_missing_file_names_itself(tmp_path):
    with pytest.raises(InputError) as excinfo:
        load_mapping_ast(tmp_path / "absent.json")

    assert "absent.json" in str(excinfo.value)


def test_a_unit_missing_span_fields_is_rejected(tmp_path):
    data = json.loads(MAPPING_AST.read_text(encoding="utf-8"))
    del data["units"][0]["start_byte"]
    path = tmp_path / "mapping_ast.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(InputError) as excinfo:
        load_mapping_ast(path)

    assert "start_byte" in str(excinfo.value)


def test_byte_slice_returns_exactly_the_definition(model):
    text = source_slice(CODEBASE, model.functions["aaaa11112222"])

    assert text.startswith("def apply_discount(price, percent=0):")
    assert text.endswith("return max(reduced, 0.0)")
    # The decorator-free definition and nothing after it.
    assert "def cart_total" not in text


def test_byte_slice_of_a_method_starts_at_its_def(model):
    text = source_slice(CODEBASE, model.functions["dddd77778888"])

    assert text.startswith("def render(self, lines: list, total: float) -> str:")
    assert text.endswith('return f"{body}\\nTOTAL {format_currency(total)}"')


def test_byte_slice_past_the_end_of_the_file_is_an_error(model, tmp_path):
    shrunk = tmp_path / "codebase" / "shop"
    shrunk.mkdir(parents=True)
    (shrunk / "pricing.py").write_text("# emptied\n", encoding="utf-8")

    with pytest.raises(InputError) as excinfo:
        source_slice(tmp_path / "codebase", model.functions["aaaa11112222"])

    assert "may have changed" in str(excinfo.value)


def test_the_fixture_codebase_carries_a_project_config():
    data = json.loads(config_path(CODEBASE).read_text(encoding="utf-8"))

    assert data[CONFIG_PYTHON_KEY]
