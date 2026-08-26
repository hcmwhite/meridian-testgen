"""Tests for the per-leaf mapping loop (chunk 3).

Every test drives :class:`ScriptedFakeLLM`; nothing here calls a real model
(D14).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from meridian_mapper.astload import load_ast_json
from meridian_mapper.llm import ScriptedFakeLLM, ScriptedScript
from meridian_mapper.mapping import (
    DEFAULT_CATEGORY_LEAK_THRESHOLD,
    MappingConfig,
    leaf_requirements,
    run_mapping,
)
from meridian_mapper.model import TIER_LLM_ASSERTED, Annotation, AstFunction, MapperModel
from meridian_mapper.requirements import load_into_model

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"


@pytest.fixture
def model():
    model = load_ast_json(FIXTURES / "ast.json")
    load_into_model(model, FIXTURES / "requirements_wellformed.md")
    return model


@pytest.fixture
def unit_ids(model):
    return [f.unit_id for f in model.ordered_functions()]


def _synthetic_model(count):
    """A model with *count* ast functions and one leaf requirement, ``1``."""
    from meridian_mapper.model import Requirement

    model = MapperModel()
    for index in range(count):
        unit_id = f"u{index:02d}"
        model.functions[unit_id] = AstFunction(
            unit_id=unit_id,
            record={
                "unit_id": unit_id,
                "dotted_name": f"m.f{index}",
                "signature": f"def f{index}()",
                "file_path": "m.py",
                "line_number": index,
                "end_line": index,
            },
            annotation=Annotation(),
        )
    model.requirements = [Requirement(code="1", text="Everything.")]
    return model


def test_only_leaves_are_mapped_and_in_hierarchy_order(model, unit_ids):
    fake = ScriptedFakeLLM(ScriptedScript(mappings={"1-1-1": [unit_ids[0]]}))

    run_mapping(model, fake)

    asked = [code for code, _ in fake.map_calls]
    assert asked == ["1-1-1", "1-1-2", "1-2", "2-1"]


def test_category_nodes_are_never_sent_to_the_llm(model):
    fake = ScriptedFakeLLM(ScriptedScript())

    run_mapping(model, fake)

    asked = {code for code, _ in fake.map_calls}
    categories = {"1", "1-1", "2"}
    assert asked & categories == set()
    assert [n.code for n in leaf_requirements(model)] == ["1-1-1", "1-1-2", "1-2", "2-1"]


def test_mapping_is_recorded_in_both_directions(model, unit_ids):
    fake = ScriptedFakeLLM(
        ScriptedScript(mappings={"1-2": [unit_ids[0], unit_ids[2]]})
    )

    run_mapping(model, fake)

    totals = next(n for n in leaf_requirements(model) if n.code == "1-2")
    assert totals.mapped_unit_ids == [unit_ids[0], unit_ids[2]]
    for unit_id in (unit_ids[0], unit_ids[2]):
        annotation = model.functions[unit_id].annotation
        assert annotation.requirement_codes == ["1-2"]
        assert annotation.tiers == {"1-2": TIER_LLM_ASSERTED}
    # A function nobody mapped is left untouched.
    assert model.functions[unit_ids[1]].annotation.requirement_codes == []


def test_every_candidate_is_offered_for_every_leaf(model, unit_ids):
    fake = ScriptedFakeLLM(ScriptedScript())

    run_mapping(model, fake)

    for _, offered in fake.map_calls:
        assert offered == unit_ids


def test_out_of_universe_id_is_dropped(model, unit_ids, caplog):
    fake = ScriptedFakeLLM(
        ScriptedScript(mappings={"2-1": [unit_ids[0], "not-a-real-unit"]})
    )

    with caplog.at_level(logging.WARNING):
        run_mapping(model, fake)

    invoicing = next(n for n in leaf_requirements(model) if n.code == "2-1")
    assert invoicing.mapped_unit_ids == [unit_ids[0]]
    assert "not-a-real-unit" in caplog.text


def test_zero_mapping_leaf_is_a_result_not_an_error(model, unit_ids):
    fake = ScriptedFakeLLM(ScriptedScript(mappings={"1-2": [unit_ids[0]]}))

    summary = run_mapping(model, fake)

    empty = next(n for n in leaf_requirements(model) if n.code == "1-1-1")
    assert empty.mapped_unit_ids == []
    assert empty.category_leak is False
    # The run carried on to the leaves after it.
    assert summary.leaves_mapped == 4
    assert summary.empty_leaves == 3
    assert [code for code, _ in fake.map_calls][-1] == "2-1"


def test_over_the_default_threshold_flags_category_leak():
    model = _synthetic_model(DEFAULT_CATEGORY_LEAK_THRESHOLD + 1)
    everything = list(model.functions)
    fake = ScriptedFakeLLM(ScriptedScript(mappings={"1": everything}))

    summary = run_mapping(model, fake)

    leaf = model.requirements[0]
    assert leaf.category_leak is True
    assert leaf.mapped_unit_ids == everything, "a flagged leaf keeps its mappings"
    assert summary.category_leaks == 1


def test_exactly_the_threshold_is_not_a_leak():
    model = _synthetic_model(DEFAULT_CATEGORY_LEAK_THRESHOLD)
    fake = ScriptedFakeLLM(ScriptedScript(mappings={"1": list(model.functions)}))

    run_mapping(model, fake)

    assert model.requirements[0].category_leak is False


def test_changing_the_threshold_changes_the_outcome():
    everything = list(_synthetic_model(3).functions)

    lenient = _synthetic_model(3)
    run_mapping(
        lenient,
        ScriptedFakeLLM(ScriptedScript(mappings={"1": everything})),
        MappingConfig(category_leak_threshold=3),
    )
    assert lenient.requirements[0].category_leak is False

    strict = _synthetic_model(3)
    run_mapping(
        strict,
        ScriptedFakeLLM(ScriptedScript(mappings={"1": everything})),
        MappingConfig(category_leak_threshold=2),
    )
    assert strict.requirements[0].category_leak is True
    assert strict.requirements[0].mapped_unit_ids == everything
