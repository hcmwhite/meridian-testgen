"""Tests for the verification loop (chunk 4).

Every test drives :class:`ScriptedFakeLLM` against the committed fixture
codebase; nothing here calls a real model or the network (D14).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from meridian_mapper.astload import load_ast_json
from meridian_mapper.llm import Claim, ScriptedFakeLLM, ScriptedScript
from meridian_mapper.mapping import MappingConfig, run_mapping
from meridian_mapper.model import TIER_DETERMINISTIC, TIER_LLM_ASSERTED
from meridian_mapper.requirements import load_into_model
from meridian_mapper.verification import (
    DEFAULT_MAX_RETRIES,
    VerificationConfig,
    normalize_whitespace,
    run_verification,
)

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"
CODEBASE = FIXTURES / "codebase"

# A line quoted verbatim from shop/cart.py's add_item body.
GOOD_EVIDENCE = "cart[item] = cart.get(item, 0) + quantity"
# Real text of add_item, but re-wrapped: whitespace normalization forgives it.
REWRAPPED_EVIDENCE = "cart[item]  =  cart.get(item, 0)\n        + quantity"
BAD_EVIDENCE = "raise ValueError('never written in this codebase')"

ADD_ITEM = "6ef3dca1dc5d"
TOTAL_PRICE = "129e61f608e7"


def _model():
    model = load_ast_json(FIXTURES / "ast.json")
    load_into_model(model, FIXTURES / "requirements_wellformed.md")
    return model


def _mapped(claims, mappings=None, mapping_config=None):
    """A model mapped by the fake, plus the fake, ready to verify."""
    model = _model()
    script = ScriptedScript(
        mappings=mappings if mappings is not None else {"1-1-1": [ADD_ITEM]},
        claims=claims,
    )
    fake = ScriptedFakeLLM(script)
    run_mapping(model, fake, mapping_config)
    return model, fake


def test_pass_on_first_attempt_is_deterministic():
    model, fake = _mapped({("1-1-1", ADD_ITEM): GOOD_EVIDENCE})

    summary = run_verification(model, fake, CODEBASE)

    assert summary.pairs_checked == 1
    assert summary.verified == 1
    assert summary.retries_used == 0
    assert summary.exhausted == 0
    annotation = model.functions[ADD_ITEM].annotation
    assert annotation.tiers["1-1-1"] == TIER_DETERMINISTIC
    assert annotation.error_notes == []
    assert len(fake.verify_calls) == 1
    assert fake.verify_calls[0][2] is None


def test_evidence_matches_whitespace_normalized():
    model, fake = _mapped({("1-1-1", ADD_ITEM): REWRAPPED_EVIDENCE})

    run_verification(model, fake, CODEBASE)

    assert model.functions[ADD_ITEM].annotation.tiers["1-1-1"] == TIER_DETERMINISTIC


def test_fail_fail_pass_consumes_two_retries():
    model, fake = _mapped(
        {("1-1-1", ADD_ITEM): [BAD_EVIDENCE, "", GOOD_EVIDENCE]}
    )

    summary = run_verification(model, fake, CODEBASE)

    assert summary.verified == 1
    assert summary.retries_used == 2
    assert summary.exhausted == 0
    assert model.functions[ADD_ITEM].annotation.tiers["1-1-1"] == TIER_DETERMINISTIC
    assert model.requirements[0].children[0].children[0].mapped_unit_ids == [ADD_ITEM]
    # Each retry was told why the previous attempt failed.
    reasons = [call[2] for call in fake.verify_calls]
    assert reasons[0] is None
    assert "does not appear" in reasons[1]
    assert "no evidence snippet" in reasons[2]


def test_three_failures_remove_the_mapping_and_write_an_error_note():
    model, fake = _mapped(
        {("1-1-1", ADD_ITEM): [BAD_EVIDENCE, BAD_EVIDENCE + "!", ""]}
    )

    summary = run_verification(model, fake, CODEBASE)

    assert summary.exhausted == 1
    assert summary.verified == 0
    leaf = model.requirements[0].children[0].children[0]
    assert leaf.code == "1-1-1"
    assert leaf.mapped_unit_ids == []
    annotation = model.functions[ADD_ITEM].annotation
    assert annotation.requirement_codes == []
    assert "1-1-1" not in annotation.tiers

    assert len(annotation.error_notes) == 1
    note = annotation.error_notes[0]
    assert note.requirement_code == "1-1-1"
    assert [a["attempt"] for a in note.attempts] == [1, 2, 3]
    assert [a["evidence"] for a in note.attempts] == [
        BAD_EVIDENCE, BAD_EVIDENCE + "!", "",
    ]
    assert all(a["reason"] for a in note.attempts)
    assert "does not appear" in note.attempts[0]["reason"]
    assert "no evidence snippet" in note.attempts[2]["reason"]


def test_retry_cap_is_exactly_two_retries():
    model, fake = _mapped({("1-1-1", ADD_ITEM): BAD_EVIDENCE})

    run_verification(model, fake, CODEBASE)

    assert DEFAULT_MAX_RETRIES == 2
    assert len(fake.verify_calls) == 3


def test_retry_cap_is_configurable():
    model, fake = _mapped({("1-1-1", ADD_ITEM): BAD_EVIDENCE})

    run_verification(model, fake, CODEBASE, VerificationConfig(max_retries=0))

    assert len(fake.verify_calls) == 1
    assert model.functions[ADD_ITEM].annotation.error_notes[0].attempts[0]["attempt"] == 1


def test_category_leak_pairs_are_skipped_and_stay_llm_asserted():
    model, fake = _mapped(
        claims={("1-2", TOTAL_PRICE): "return sum(prices[item] * count"},
        mappings={"1-1-1": [ADD_ITEM, TOTAL_PRICE], "1-2": [TOTAL_PRICE]},
        mapping_config=MappingConfig(category_leak_threshold=1),
    )
    leak = model.requirements[0].children[0].children[0]
    assert leak.category_leak is True

    summary = run_verification(model, fake, CODEBASE)

    assert summary.skipped_category_leak == 2
    assert [code for code, _, _ in fake.verify_calls] == ["1-2"]  # never 1-1-1
    assert model.functions[ADD_ITEM].annotation.tiers["1-1-1"] == TIER_LLM_ASSERTED
    assert leak.mapped_unit_ids == [ADD_ITEM, TOTAL_PRICE]


def test_a_claim_for_a_function_outside_the_universe_fails_rather_than_crashes():
    model, fake = _mapped({("1-1-1", ADD_ITEM): GOOD_EVIDENCE})
    leaf = model.requirements[0].children[0].children[0]
    leaf.mapped_unit_ids = ["not-a-real-unit"]

    summary = run_verification(model, fake, CODEBASE)

    assert summary.exhausted == 1
    assert leaf.mapped_unit_ids == []
    assert fake.verify_calls == []


def test_empty_leaf_is_left_alone():
    model, fake = _mapped(claims={}, mappings={})

    summary = run_verification(model, fake, CODEBASE)

    assert summary.pairs_checked == 0
    assert fake.verify_calls == []


def test_non_ascii_body_verifies_against_real_bytes():
    unit_id = "3c2c45288855"  # shop.facturé.résumé_français
    evidence = "résumé"
    model, fake = _mapped(
        claims={("1-1-1", unit_id): Claim("1-1-1", unit_id, "summarises", evidence)},
        mappings={"1-1-1": [unit_id]},
    )

    run_verification(model, fake, CODEBASE)

    assert model.functions[unit_id].annotation.tiers["1-1-1"] == TIER_DETERMINISTIC


@pytest.mark.parametrize(
    "text,expected",
    [("  a\n\t b  ", "a b"), ("a", "a"), ("", "")],
)
def test_normalize_whitespace(text, expected):
    assert normalize_whitespace(text) == expected


def test_a_passing_claim_is_persisted_on_the_annotation():
    model, fake = _mapped({("1-1-1", ADD_ITEM): GOOD_EVIDENCE})

    run_verification(model, fake, CODEBASE)

    claims = model.functions[ADD_ITEM].annotation.claims
    assert set(claims) == {"1-1-1"}
    assert claims["1-1-1"]["evidence"] == GOOD_EVIDENCE
    assert isinstance(claims["1-1-1"]["effect"], str)


def test_the_winning_retry_claim_is_the_one_persisted():
    model, fake = _mapped(
        {("1-1-1", ADD_ITEM): [BAD_EVIDENCE, "", GOOD_EVIDENCE]}
    )

    run_verification(model, fake, CODEBASE)

    claims = model.functions[ADD_ITEM].annotation.claims
    assert claims["1-1-1"]["evidence"] == GOOD_EVIDENCE


def test_an_exhausted_pair_persists_no_claim():
    model, fake = _mapped(
        {("1-1-1", ADD_ITEM): [BAD_EVIDENCE, BAD_EVIDENCE + "!", ""]}
    )

    run_verification(model, fake, CODEBASE)

    assert model.functions[ADD_ITEM].annotation.claims == {}
