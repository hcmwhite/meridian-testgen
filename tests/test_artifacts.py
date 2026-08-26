"""Tests for Artifact 1, the annotated AST list (chunk 5).

One fixture run is driven end to end with the scripted fake — map, verify,
classify, write — and the resulting file is asserted field by field. Nothing
here calls a real model (D14).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from meridian_mapper.artifacts import (
    ARTIFACT_AST,
    ARTIFACT_SCHEMA_VERSION,
    ArtifactError,
    write_artifact_one,
)
from meridian_mapper.astload import load_ast_json
from meridian_mapper.classify import classify
from meridian_mapper.llm import ScriptedFakeLLM, ScriptedScript
from meridian_mapper.mapping import MappingConfig, run_mapping
from meridian_mapper.model import TIER_DETERMINISTIC, TIER_LLM_ASSERTED
from meridian_mapper.requirements import load_into_model
from meridian_mapper.verification import run_verification

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"
CODEBASE = FIXTURES / "codebase"
AST_JSON = FIXTURES / "ast.json"
REQ_DOC = FIXTURES / "requirements_wellformed.md"

ADD_ITEM = "6ef3dca1dc5d"
TOTAL_PRICE = "129e61f608e7"
SUMMARISE = "a4aab26adc36"
CALCULER = "4c2f7c64368b"
RESUME = "3c2c45288855"

GOOD_EVIDENCE = "cart[item] = cart.get(item, 0) + quantity"
BAD_EVIDENCE = "raise ValueError('never written in this codebase')"
WORSE_EVIDENCE = "print('also never written')"
WORST_EVIDENCE = "return None  # nor this"


def _run(tmp_path):
    """The whole pipeline over the fixture, with one of everything.

    The scripted mapping is chosen so the artifact contains, in one file:
    a verified pair (``deterministic``), a pair that exhausts its retries and
    is removed, a category-leak requirement whose pairs stay ``llm_asserted``,
    an empty leaf, and a function nothing ever mapped.
    """
    model = load_ast_json(AST_JSON)
    load_into_model(model, REQ_DOC)
    fake = ScriptedFakeLLM(ScriptedScript(
        mappings={
            "1-1-1": [ADD_ITEM],
            "1-1-2": [TOTAL_PRICE],
            "1-2": [SUMMARISE, CALCULER],
            "2-1": [],
        },
        claims={
            ("1-1-1", ADD_ITEM): GOOD_EVIDENCE,
            ("1-1-2", TOTAL_PRICE): [BAD_EVIDENCE, WORSE_EVIDENCE, WORST_EVIDENCE],
        },
    ))
    # Threshold 1 makes the two-function leaf 1-2 a category leak on a
    # five-function fixture; the default of 10 could never be reached here.
    run_mapping(model, fake, MappingConfig(category_leak_threshold=1))
    run_verification(model, fake, CODEBASE)
    classify(model)

    out = tmp_path / "mapping_ast.json"
    count = write_artifact_one(model, out, AST_JSON, REQ_DOC, CODEBASE)
    return model, json.loads(out.read_text(encoding="utf-8")), count


def _units(data):
    return {unit["unit_id"]: unit for unit in data["units"]}


def test_envelope_and_record_order(tmp_path):
    model, data, count = _run(tmp_path)

    assert data["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert data["artifact"] == ARTIFACT_AST
    assert data["tool"].startswith("meridian-mapper ")
    assert data["ast_json"] == str(AST_JSON)
    assert data["requirements_doc"] == str(REQ_DOC)
    assert data["codebase"] == str(CODEBASE)
    # The stage-1 envelope of the universe this run mapped, kept for tracing.
    assert data["source_run"]["schema_version"] == 2
    assert count == len(data["units"]) == 5
    assert [u["unit_id"] for u in data["units"]] == [
        f.unit_id for f in model.ordered_functions()
    ]


def test_stage_one_fields_are_reemitted_verbatim(tmp_path):
    _, data, _ = _run(tmp_path)
    unit = _units(data)[ADD_ITEM]

    assert unit["dotted_name"] == "shop.cart.add_item"
    assert unit["file_path"] == "shop/cart.py"
    assert unit["signature"] == "def add_item(cart, item, quantity=1)"
    assert (unit["start_byte"], unit["end_byte"]) == (51, 241)


def test_verified_pair_is_deterministic(tmp_path):
    _, data, _ = _run(tmp_path)
    unit = _units(data)[ADD_ITEM]

    assert unit["requirement_codes"] == ["1-1-1"]
    assert unit["verification"] == {"1-1-1": TIER_DETERMINISTIC}
    assert unit["structural_test_only"] is False
    assert unit["error_notes"] == []


def test_category_leak_pairs_stay_llm_asserted(tmp_path):
    _, data, _ = _run(tmp_path)
    units = _units(data)

    for unit_id in (SUMMARISE, CALCULER):
        assert units[unit_id]["requirement_codes"] == ["1-2"]
        assert units[unit_id]["verification"] == {"1-2": TIER_LLM_ASSERTED}
        assert units[unit_id]["structural_test_only"] is False


def test_exhausted_function_is_tagged_and_carries_its_error_note(tmp_path):
    _, data, _ = _run(tmp_path)
    unit = _units(data)[TOTAL_PRICE]

    assert unit["requirement_codes"] == []
    assert unit["verification"] == {}
    assert unit["structural_test_only"] is True

    assert len(unit["error_notes"]) == 1
    note = unit["error_notes"][0]
    assert note["requirement_code"] == "1-1-2"
    assert [a["attempt"] for a in note["attempts"]] == [1, 2, 3]
    assert [a["evidence"] for a in note["attempts"]] == [
        BAD_EVIDENCE, WORSE_EVIDENCE, WORST_EVIDENCE,
    ]
    assert all(a["reason"] for a in note["attempts"])


def test_never_mapped_function_is_structural_test_only(tmp_path):
    _, data, _ = _run(tmp_path)
    unit = _units(data)[RESUME]

    assert unit["requirement_codes"] == []
    assert unit["structural_test_only"] is True
    assert unit["error_notes"] == []


def test_both_tiers_appear_in_one_artifact(tmp_path):
    _, data, _ = _run(tmp_path)
    tiers = {
        tier
        for unit in data["units"]
        for tier in unit["verification"].values()
    }
    assert tiers == {TIER_DETERMINISTIC, TIER_LLM_ASSERTED}


def test_artifact_is_written_from_the_model_alone(tmp_path):
    """No re-reading of inputs: a model with no paths still renders (D11)."""
    model = load_ast_json(AST_JSON)
    classify(model)
    out = tmp_path / "only_model.json"

    write_artifact_one(model, out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["ast_json"] is None
    assert all(u["structural_test_only"] for u in data["units"])


def test_missing_directory_is_a_clear_error(tmp_path):
    model = load_ast_json(AST_JSON)
    with pytest.raises(ArtifactError) as excinfo:
        write_artifact_one(model, tmp_path / "nope" / "mapping_ast.json")
    assert "does not exist" in str(excinfo.value)


def test_llm_usage_lands_in_artifact_one_metadata_when_given(tmp_path):
    model, _, _ = _run(tmp_path)
    out = tmp_path / "with_usage.json"
    usage = {"calls": 34, "input_tokens": 40000, "output_tokens": 5000,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
             "total_cost_usd": 1.23}
    write_artifact_one(model, out, llm_usage=usage)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["llm_usage"] == usage


def test_metadata_has_no_llm_usage_when_none_was_measured(tmp_path):
    model, data, _ = _run(tmp_path)
    assert "llm_usage" not in data


def test_verified_claims_land_on_the_artifact_record(tmp_path):
    model, data, _ = _run(tmp_path)
    by_id = {u["unit_id"]: u for u in data["units"]}
    verified = [u for u in data["units"]
                if "deterministic" in u["verification"].values()]
    assert verified, "fixture run should verify at least one pair"
    for unit in verified:
        for code, tier in unit["verification"].items():
            if tier == "deterministic":
                claim = unit["claims"][code]
                assert claim["effect"] and claim["evidence"]
    # And a record with no verified pair carries an empty map, not a missing key.
    assert all("claims" in u for u in data["units"])
