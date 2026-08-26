"""Tests for the LLM interface, the scripted fake, and the claude-cli backend.

Every test here uses the fake or canned CLI text: nothing invokes the real
`claude` binary and nothing makes a network call (D14).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from meridian_mapper.astload import load_ast_json
from meridian_mapper.claude_cli import (
    ClaudeCliLLM,
    build_map_prompt,
    build_verify_prompt,
    parse_cli_response,
)
from meridian_mapper.llm import (
    BACKEND_CLAUDE_CLI,
    BACKEND_SCRIPTED_FAKE,
    Candidate,
    Claim,
    LLMConfig,
    LLMError,
    ScriptedFakeLLM,
    ScriptedScript,
    create_llm,
)
from meridian_mapper.model import Requirement

FIXTURES = Path(__file__).parent / "fixtures" / "mapper"


@pytest.fixture
def model():
    return load_ast_json(FIXTURES / "ast.json")


@pytest.fixture
def candidates(model):
    return [Candidate.from_function(f) for f in model.ordered_functions()]


def _requirement(code="1-1", text="The cart totals its items."):
    return Requirement(code=code, text=text)


def test_candidate_carries_only_a_code_reference(model):
    function = model.ordered_functions()[0]
    candidate = Candidate.from_function(function)

    assert candidate.unit_id == function.unit_id
    assert candidate.dotted_name == function.record["dotted_name"]
    assert candidate.signature == function.record["signature"]
    assert candidate.file_path == function.record["file_path"]
    assert (candidate.line_number, candidate.end_line) == (
        function.record["line_number"], function.record["end_line"],
    )


def test_fake_maps_from_the_script_and_records_the_call(candidates):
    wanted = [candidates[0].unit_id, candidates[2].unit_id]
    llm = ScriptedFakeLLM(ScriptedScript(mappings={"1-1": wanted}))

    assert llm.map_requirement(_requirement(), candidates) == wanted
    assert llm.map_calls == [("1-1", [c.unit_id for c in candidates])]


def test_unscripted_requirement_maps_to_nothing(candidates):
    llm = ScriptedFakeLLM()

    assert llm.map_requirement(_requirement("9"), candidates) == []


def test_out_of_universe_id_is_dropped_with_a_warning(candidates, caplog):
    real = candidates[1].unit_id
    llm = ScriptedFakeLLM(
        ScriptedScript(mappings={"1-1": [real, "not-a-real-unit-id"]})
    )

    with caplog.at_level(logging.WARNING, logger="meridian_mapper.llm"):
        assert llm.map_requirement(_requirement(), candidates) == [real]

    assert "not-a-real-unit-id" in caplog.text
    assert "1-1" in caplog.text


def test_duplicate_ids_are_kept_once(candidates):
    unit_id = candidates[0].unit_id
    llm = ScriptedFakeLLM(ScriptedScript(mappings={"1-1": [unit_id, unit_id]}))

    assert llm.map_requirement(_requirement(), candidates) == [unit_id]


def test_fake_returns_a_claim_and_records_prior_failure(model):
    function = model.ordered_functions()[0]
    claim = Claim(
        requirement_code="1-1", unit_id=function.unit_id,
        effect="adds an item to the cart", evidence="cart.append(item)",
    )
    llm = ScriptedFakeLLM(
        ScriptedScript(claims={("1-1", function.unit_id): claim})
    )

    assert llm.verify_claim(_requirement(), function) is claim
    assert llm.verify_claim(_requirement(), function, "snippet not found") is claim
    assert llm.verify_calls == [
        ("1-1", function.unit_id, None),
        ("1-1", function.unit_id, "snippet not found"),
    ]


def test_fake_scripts_a_per_call_sequence_for_retries(model):
    function = model.ordered_functions()[0]
    llm = ScriptedFakeLLM(ScriptedScript(claims={
        ("1-1", function.unit_id): ["invented", "still invented", "cart.append"],
    }))
    requirement = _requirement()

    evidence = [
        llm.verify_claim(requirement, function).evidence,
        llm.verify_claim(requirement, function, "not found").evidence,
        llm.verify_claim(requirement, function, "not found").evidence,
    ]

    assert evidence == ["invented", "still invented", "cart.append"]
    with pytest.raises(LLMError, match="ran out of claims"):
        llm.verify_claim(requirement, function, "not found")


def test_fake_can_raise_a_scripted_error(model):
    function = model.ordered_functions()[0]
    llm = ScriptedFakeLLM(ScriptedScript(claims={
        ("1-1", function.unit_id): LLMError("backend fell over"),
    }))

    with pytest.raises(LLMError, match="backend fell over"):
        llm.verify_claim(_requirement(), function)


def test_backend_selection_is_a_config_value():
    fake = create_llm(LLMConfig(backend=BACKEND_SCRIPTED_FAKE))
    real = create_llm(
        LLMConfig(backend=BACKEND_CLAUDE_CLI, model="some-model-id"),
        codebase_root=FIXTURES / "codebase",
    )

    assert isinstance(fake, ScriptedFakeLLM)
    assert isinstance(real, ClaudeCliLLM)
    assert real.model == "some-model-id"
    with pytest.raises(LLMError, match="unknown llm backend"):
        create_llm(LLMConfig(backend="telepathy"))


def test_map_prompt_lists_every_candidate_as_a_reference(candidates):
    prompt = build_map_prompt(_requirement(), candidates)

    for candidate in candidates:
        assert f"unit_id={candidate.unit_id}" in prompt
        assert candidate.signature in prompt
    assert "1-1" in prompt
    assert "The cart totals its items." in prompt
    assert '{"unit_ids": ["<unit_id>", ...]}' in prompt


def test_verify_prompt_includes_the_body_and_the_prior_failure(candidates):
    prompt = build_verify_prompt(
        _requirement(), candidates[0], "def add_item(cart, item):\n    ...",
        prior_failure="evidence snippet not found in the body",
    )

    assert "def add_item(cart, item):" in prompt
    assert "evidence snippet not found in the body" in prompt
    assert "verbatim" in prompt.lower()


def test_command_carries_model_read_only_tools_and_add_dir():
    llm = ClaudeCliLLM(
        codebase_root=FIXTURES / "codebase", model="some-model-id",
        binary="claude",
    )

    command = llm.build_command("hello")

    assert command[:5] == ["claude", "-p", "hello", "--output-format", "json"]
    assert command[command.index("--model") + 1] == "some-model-id"
    assert command[command.index("--allowed-tools") + 1] == "Read,Grep,Glob"
    assert command[command.index("--add-dir") + 1] == str(FIXTURES / "codebase")
    assert "--permission-mode" in command
    # Nothing that writes.
    assert "Edit" not in command and "Write" not in command and "Bash" not in command


def _canned(result_text: str) -> str:
    return json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "num_turns": 2, "session_id": "abc", "result": result_text,
    })


def test_parses_a_canned_map_response(model, candidates):
    real = candidates[0].unit_id
    stdout = _canned(
        '```json\n{"unit_ids": ["%s", "ghost-id"]}\n```' % real
    )
    llm = ClaudeCliLLM(runner=lambda command: stdout)

    assert llm.map_requirement(_requirement(), candidates) == [real]


def test_parses_a_canned_claim_response(model):
    function = model.ordered_functions()[0]
    stdout = _canned(
        '{"effect": "appends the item", "evidence": "cart.append(item)"}'
    )
    llm = ClaudeCliLLM(
        runner=lambda command: stdout, body_reader=lambda f: "cart.append(item)",
    )

    claim = llm.verify_claim(_requirement(), function)

    assert claim == Claim(
        requirement_code="1-1", unit_id=function.unit_id,
        effect="appends the item", evidence="cart.append(item)",
    )


def test_a_cli_error_envelope_is_an_llm_error():
    with pytest.raises(LLMError, match="reported an error"):
        parse_cli_response(json.dumps({"is_error": True, "result": "boom"}))


def test_non_json_and_prose_answers_are_llm_errors(candidates):
    with pytest.raises(LLMError, match="did not print JSON"):
        parse_cli_response("not json at all")
    with pytest.raises(LLMError, match="no 'result' field"):
        parse_cli_response(json.dumps({"session_id": "abc"}))
    with pytest.raises(LLMError, match="not the JSON object"):
        parse_cli_response(_canned("I think function three does it."))

    llm = ClaudeCliLLM(runner=lambda command: _canned('{"answer": "maybe"}'))
    with pytest.raises(LLMError, match="unit_ids"):
        llm.map_requirement(_requirement(), candidates)


# ---------------------------------------------------------------------------
# usage accounting


def _canned_with_usage(result_text: str, usage=None, cost=None) -> str:
    envelope = json.loads(_canned(result_text))
    if usage is not None:
        envelope["usage"] = usage
    if cost is not None:
        envelope["total_cost_usd"] = cost
    return json.dumps(envelope)


def test_backend_accumulates_usage_and_cost_across_calls(model, candidates):
    real = candidates[0].unit_id
    stdout = _canned_with_usage(
        '{"unit_ids": ["%s"]}' % real,
        usage={"input_tokens": 1000, "output_tokens": 50,
               "cache_creation_input_tokens": 200, "cache_read_input_tokens": 300},
        cost=0.0125,
    )
    llm = ClaudeCliLLM(runner=lambda command: stdout)

    llm.map_requirement(_requirement(), candidates)
    llm.map_requirement(_requirement(), candidates)

    assert llm.usage.calls == 2
    assert llm.usage.input_tokens == 2000
    assert llm.usage.output_tokens == 100
    assert llm.usage.cache_creation_input_tokens == 400
    assert llm.usage.cache_read_input_tokens == 600
    assert llm.usage.total_cost_usd == pytest.approx(0.025)
    assert llm.usage.as_dict()["calls"] == 2


def test_an_envelope_without_usage_still_counts_the_call(model, candidates):
    stdout = _canned('{"unit_ids": []}')
    llm = ClaudeCliLLM(runner=lambda command: stdout)

    llm.map_requirement(_requirement(), candidates)

    assert llm.usage.calls == 1
    assert llm.usage.input_tokens == 0
    assert llm.usage.total_cost_usd == 0.0


def test_the_fake_reports_zero_usage(candidates):
    fake = ScriptedFakeLLM()
    fake.map_requirement(_requirement(), candidates)
    assert fake.usage.calls == 0
