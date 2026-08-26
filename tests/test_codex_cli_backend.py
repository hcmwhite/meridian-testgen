"""Tests for the isolated Codex CLI backend."""

import json

import pytest

from meridian_testgen.codex_cli import CodexCliLLM, parse_codex_jsonl
from meridian_testgen.llm import (
    BACKEND_CODEX_CLI,
    GenerationItem,
    LLMConfig,
    LLMError,
    create_llm,
)


def item():
    return GenerationItem(
        unit_id="pkg/mod.py::f", requirement_code="1-1", dotted_name="mod.f",
        signature="f()", file_path="pkg/mod.py", line_number=1, end_line=2,
        source="def f():\n    pass\n", requirement_text="The function works.",
    )


def event(payload):
    return json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": json.dumps(payload)},
    })


def completed_turn(**usage):
    return json.dumps({"type": "turn.completed", "usage": usage})


def test_command_is_read_only_and_scoped_to_target(tmp_path):
    llm = CodexCliLLM(codebase_root=tmp_path, model="codex-model", binary="codex")
    command = llm.build_command("PROMPT")

    assert command[:6] == ["codex", "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check"]
    assert command[command.index("--model") + 1] == "codex-model"
    assert command[command.index("-C") + 1] == str(tmp_path)
    assert command[-1] == "PROMPT"


def test_backend_extracts_a_completed_agent_message():
    requested = item()
    llm = CodexCliLLM(runner=lambda command: "\n".join((
        event({"tests": [{
            "unit_id": requested.unit_id,
            "requirement": requested.requirement_code,
            "source": "def test_one(): pass",
        }]}),
        completed_turn(
            input_tokens=120,
            cached_input_tokens=80,
            cache_write_input_tokens=4,
            output_tokens=25,
            reasoning_output_tokens=10,
        ),
    )))

    result = llm.generate_tests([requested])

    assert [test.key for test in result] == [requested.key]
    assert llm.usage.calls == 1
    assert llm.usage.input_tokens == 120
    assert llm.usage.output_tokens == 25
    assert llm.usage.cache_read_input_tokens == 80
    assert llm.usage.cache_creation_input_tokens == 4
    assert llm.usage.total_cost_usd == 0.0


def test_backend_without_usage_keeps_zero_token_fallback():
    requested = item()
    llm = CodexCliLLM(runner=lambda command: event({"tests": [{
        "unit_id": requested.unit_id,
        "requirement": requested.requirement_code,
        "source": "def test_one(): pass",
    }]}))

    llm.generate_tests([requested])

    assert llm.usage.as_dict() == {
        "calls": 1,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "total_cost_usd": 0.0,
    }


def test_jsonl_without_an_agent_message_is_an_error():
    with pytest.raises(LLMError, match="no completed agent message"):
        parse_codex_jsonl(json.dumps({"type": "turn.completed"}))


def test_parser_returns_final_turn_usage_with_the_payload():
    payload, usage = parse_codex_jsonl("\n".join((
        event({"tests": []}),
        completed_turn(input_tokens=12, output_tokens=3),
    )))

    assert payload == {"tests": []}
    assert usage == {
        "input_tokens": 12,
        "output_tokens": 3,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
    }


def test_backend_selection_creates_the_codex_adapter(tmp_path):
    llm = create_llm(
        LLMConfig(backend=BACKEND_CODEX_CLI, model="gpt-5.3-codex"),
        codebase_root=tmp_path,
    )

    assert isinstance(llm, CodexCliLLM)
