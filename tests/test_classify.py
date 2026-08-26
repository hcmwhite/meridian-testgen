"""Tests for the structural-test-only cleanup pass (chunk 5, D19)."""

from __future__ import annotations

from pathlib import Path

from meridian_mapper.astload import load_ast_json
from meridian_mapper.classify import classify
from meridian_mapper.llm import ScriptedFakeLLM, ScriptedScript
from meridian_mapper.mapping import run_mapping
from meridian_mapper.requirements import load_into_model
from meridian_mapper.verification import run_verification

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"
CODEBASE = FIXTURES / "codebase"

ADD_ITEM = "6ef3dca1dc5d"
TOTAL_PRICE = "129e61f608e7"
GOOD_EVIDENCE = "cart[item] = cart.get(item, 0) + quantity"
BAD_EVIDENCE = "raise ValueError('never written in this codebase')"


def _model():
    model = load_ast_json(FIXTURES / "ast.json")
    load_into_model(model, FIXTURES / "requirements_wellformed.md")
    return model


def test_unmapped_functions_are_tagged_and_mapped_ones_are_not():
    model = _model()
    fake = ScriptedFakeLLM(ScriptedScript(
        mappings={"1-1-1": [ADD_ITEM]},
        claims={("1-1-1", ADD_ITEM): GOOD_EVIDENCE},
    ))
    run_mapping(model, fake)
    run_verification(model, fake, CODEBASE)

    summary = classify(model)

    assert model.functions[ADD_ITEM].annotation.structural_test_only is False
    assert model.functions[TOTAL_PRICE].annotation.structural_test_only is True
    assert summary.total == len(model.functions)
    assert summary.mapped == 1
    assert summary.structural_test_only == len(model.functions) - 1


def test_tag_is_absent_until_classify_runs():
    """The pass is post-loop, not an inline decision during the loops (D19)."""
    model = _model()
    fake = ScriptedFakeLLM(ScriptedScript(mappings={"1-1-1": [ADD_ITEM]}))
    run_mapping(model, fake)
    run_verification(model, fake, CODEBASE)

    assert all(
        f.annotation.structural_test_only is False
        for f in model.ordered_functions()
    ), "mid-pipeline, nothing should be tagged yet"

    classify(model)

    assert model.functions[TOTAL_PRICE].annotation.structural_test_only is True


def test_exhausted_function_is_tagged_and_keeps_its_error_note():
    """Losing the only mapping to exhaustion means both the tag and the note."""
    model = _model()
    fake = ScriptedFakeLLM(ScriptedScript(
        mappings={"1-1-1": [ADD_ITEM]},
        claims={("1-1-1", ADD_ITEM): BAD_EVIDENCE},
    ))
    run_mapping(model, fake)
    run_verification(model, fake, CODEBASE)

    assert model.functions[ADD_ITEM].annotation.requirement_codes == []
    classify(model)

    annotation = model.functions[ADD_ITEM].annotation
    assert annotation.structural_test_only is True
    assert [note.requirement_code for note in annotation.error_notes] == ["1-1-1"]


def test_classify_is_idempotent_and_clears_a_stale_tag():
    model = _model()
    fake = ScriptedFakeLLM(ScriptedScript(
        mappings={"1-1-1": [ADD_ITEM]},
        claims={("1-1-1", ADD_ITEM): GOOD_EVIDENCE},
    ))
    run_mapping(model, fake)
    run_verification(model, fake, CODEBASE)

    model.functions[ADD_ITEM].annotation.structural_test_only = True
    classify(model)
    classify(model)

    assert model.functions[ADD_ITEM].annotation.structural_test_only is False
