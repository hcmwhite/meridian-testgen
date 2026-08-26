"""The generation loop: item assembly, category-leak skips, batching (D28, D29).

Every test drives the scripted fake — nothing here reaches the network.
"""

from pathlib import Path

import pytest

from meridian_testgen.claude_cli import GENERATE_INSTRUCTIONS, build_generation_prompt
from meridian_testgen.generate import (
    STRUCTURAL_GROUP,
    GenerationRun,
    batches,
    build_items,
    claim_for,
    generate,
    group_key,
)
from meridian_testgen.inputs import load_model
from meridian_testgen.llm import GeneratedTest, ScriptedFakeLLM, ScriptedScript
from meridian_testgen.model import STRUCTURAL_MARKER, TIER_DETERMINISTIC

FIXTURES = Path(__file__).parent / "fixtures" / "testgen"
CODEBASE = FIXTURES / "codebase"

DISCOUNT = "aaaa11112222"      # 1-1, deterministic
CART = "bbbb33334444"          # 1-2, deterministic
FORMAT = "cccc55556666"        # structural_test_only
RENDER = "dddd77778888"        # 2-1, llm_asserted, requirement is a category leak


@pytest.fixture
def model():
    return load_model(FIXTURES / "mapping_ast.json",
                      FIXTURES / "mapping_requirements.json")


def items_by_key(items):
    return {item.key: item for item in items}


# --- item assembly -------------------------------------------------------


def test_build_items_covers_every_pair_and_structural_function(model):
    items, summary = build_items(model, CODEBASE)
    assert [item.key for item in items] == [
        (DISCOUNT, "1-1"),
        (CART, "1-2"),
        (FORMAT, STRUCTURAL_MARKER),
    ]
    assert summary.items == 3
    assert summary.mapped_items == 2
    assert summary.structural_items == 1


def test_deterministic_pair_carries_requirement_claim_source_and_obligations(model):
    items, _ = build_items(model, CODEBASE)
    item = items_by_key(items)[(DISCOUNT, "1-1")]

    assert item.tier == TIER_DETERMINISTIC
    assert item.requirement_text.startswith("A discount reduces the price")
    # D29: the stage-2 claim and its evidence are prompt ingredients for a
    # deterministic pair.
    assert item.effect == "returns the price reduced by percent, never below zero"
    assert item.evidence == "return max(reduced, 0.0)"
    # The evidence is quoted verbatim from the function it belongs to.
    assert item.evidence in item.source
    assert item.source.startswith("def apply_discount(price, percent=0):")
    assert item.signature == "def apply_discount(price, percent=0)"
    assert (item.file_path, item.line_number, item.end_line) == (
        "shop/pricing.py", 4, 9,
    )
    assert any(ob.startswith("parameter 'price'") for ob in item.obligations)
    assert any("is raised" in ob for ob in item.obligations)


def test_structural_item_carries_no_requirement_text_claim_or_tier(model):
    items, _ = build_items(model, CODEBASE)
    item = items_by_key(items)[(FORMAT, STRUCTURAL_MARKER)]

    assert item.is_structural
    assert item.requirement_text == ""
    assert item.effect is None and item.evidence is None
    assert item.tier is None
    assert item.source.startswith("def format_currency(amount: float) -> str:")
    assert item.obligations  # D33's checklist is never empty


def test_claim_is_omitted_for_a_pair_with_no_recorded_claim(model):
    function = model.functions[DISCOUNT]
    del function.record["claims"]
    assert claim_for(function, "1-1") == (None, None)

    items, _ = build_items(model, CODEBASE)
    item = items_by_key(items)[(DISCOUNT, "1-1")]
    assert item.effect is None and item.evidence is None
    # An absent claim costs a hint, not the item.
    assert item.requirement_text and item.source


# --- category leaks ------------------------------------------------------


def test_category_leak_pair_is_skipped_and_counted(model):
    items, summary = build_items(model, CODEBASE)

    assert summary.skipped_category_leak == 1
    assert (RENDER, "2-1") not in items_by_key(items)
    assert all(item.unit_id != RENDER for item in items)


def test_category_leak_pair_never_reaches_the_model(model):
    fake = ScriptedFakeLLM(ScriptedScript())
    generate(model, fake, CODEBASE, batch_size=10)

    sent = [key for call in fake.calls for key in call]
    assert (RENDER, "2-1") not in sent


def test_a_pair_stops_being_skipped_once_the_leak_flag_clears(model):
    model.requirement("2-1").category_leak = False
    items, summary = build_items(model, CODEBASE)

    assert summary.skipped_category_leak == 0
    assert (RENDER, "2-1") in items_by_key(items)


# --- batching ------------------------------------------------------------


def test_batches_splits_in_order_and_treats_zero_as_one():
    assert list(batches([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
    assert list(batches([1, 2], 0)) == [[1], [2]]
    assert list(batches([], 3)) == []


def test_batch_size_one_sends_one_call_per_item(model):
    fake = ScriptedFakeLLM(ScriptedScript())
    run = generate(model, fake, CODEBASE, batch_size=1)

    assert len(fake.calls) == 3
    assert run.summary.calls == 3
    assert all(len(call) == 1 for call in fake.calls)


def test_a_larger_batch_size_sends_fewer_calls(model):
    fake = ScriptedFakeLLM(ScriptedScript())
    run = generate(model, fake, CODEBASE, batch_size=3)

    assert len(fake.calls) == 1
    assert run.summary.calls == 1
    assert fake.calls[0] == [
        (DISCOUNT, "1-1"), (CART, "1-2"), (FORMAT, STRUCTURAL_MARKER),
    ]
    assert run.summary.generated == 3


def test_a_result_for_an_item_that_was_not_asked_about_is_dropped(model):
    stranger = GeneratedTest("zzzz99998888", "9-9", "def test_x():\n    pass\n")
    fake = ScriptedFakeLLM(ScriptedScript(extra=[stranger]))
    run = generate(model, fake, CODEBASE, batch_size=3)

    assert stranger.key not in run.results
    assert len(run.results) == 3


def test_an_omitted_answer_leaves_the_item_unanswered(model):
    script = ScriptedScript(tests={(CART, "1-2"): None})
    fake = ScriptedFakeLLM(script)
    run = generate(model, fake, CODEBASE, batch_size=3)

    assert [item.key for item in run.unanswered_items()] == [(CART, "1-2")]
    assert run.summary.unanswered == 1
    assert run.summary.generated == 2


def test_generate_can_re_drive_a_given_subset_of_items(model):
    items, _ = build_items(model, CODEBASE)
    failed = [items[1].with_failure("no traceability comment")]
    fake = ScriptedFakeLLM(ScriptedScript())

    run = generate(model, fake, CODEBASE, batch_size=5, items=failed)

    assert fake.calls == [[(CART, "1-2")]]
    assert fake.items[0][0].prior_failure == "no traceability comment"
    assert run.summary.items == 1


# --- grouping ------------------------------------------------------------


def test_results_are_grouped_by_top_level_category_plus_structural(model):
    fake = ScriptedFakeLLM(ScriptedScript())
    run = generate(model, fake, CODEBASE, batch_size=3)

    assert set(run.groups) == {"1", STRUCTURAL_GROUP}
    assert [g.key for g in run.groups["1"]] == [(DISCOUNT, "1-1"), (CART, "1-2")]
    assert [g.key for g in run.groups[STRUCTURAL_GROUP]] == [
        (FORMAT, STRUCTURAL_MARKER),
    ]
    assert run.groups[STRUCTURAL_GROUP][0].source
    # The grouping hangs off the one model, for the passes that come later.
    assert model.generated_groups == run.groups


def test_group_key_uses_the_first_code_segment(model):
    items, _ = build_items(model, CODEBASE)
    lookup = items_by_key(items)
    assert group_key(lookup[(DISCOUNT, "1-1")]) == "1"
    assert group_key(lookup[(FORMAT, STRUCTURAL_MARKER)]) == STRUCTURAL_GROUP


def test_an_unanswered_item_contributes_no_group_entry(model):
    script = ScriptedScript(tests={(FORMAT, STRUCTURAL_MARKER): None})
    fake = ScriptedFakeLLM(script)
    run = generate(model, fake, CODEBASE, batch_size=3)

    assert STRUCTURAL_GROUP not in run.groups


# --- the prompt the items feed ------------------------------------------


def test_the_prompt_states_the_traceability_comment_format(model):
    items, _ = build_items(model, CODEBASE)
    prompt = build_generation_prompt(items)

    assert "# meridian: unit_id=<unit_id> requirement=<requirement>" in prompt
    assert "# meridian: unit_id=<unit_id> requirement=<requirement>" in (
        GENERATE_INSTRUCTIONS
    )
    # D29's ingredients survive into the text the model sees.
    assert "stage-2 effect claim: returns the price reduced" in prompt
    assert f"unit_id: {FORMAT}" in prompt
    assert f"requirement: {STRUCTURAL_MARKER}" in prompt


def test_the_structural_prompt_tells_the_model_to_read_the_codebase(model):
    items, _ = build_items(model, CODEBASE)
    structural = [i for i in items if i.is_structural]
    prompt = build_generation_prompt(structural)

    assert "find this function's callers" in prompt
    assert "REQUIREMENT" not in prompt
    assert "stage-2 effect claim" not in prompt


def test_a_failed_call_costs_only_its_own_batch(model):
    from meridian_testgen.llm import LLMError

    script = ScriptedScript(tests={
        (CART, "1-2"): LLMError("claude timed out after 300.0s"),
    })
    fake = ScriptedFakeLLM(script)
    run = generate(model, fake, CODEBASE, batch_size=1)

    # The two other calls' results stand; only the dead call's item failed.
    assert set(run.results) == {(DISCOUNT, "1-1"), (FORMAT, STRUCTURAL_MARKER)}
    assert set(run.call_failures) == {(CART, "1-2")}
    assert "timed out" in run.call_failures[(CART, "1-2")]
    assert run.summary.calls == 3
