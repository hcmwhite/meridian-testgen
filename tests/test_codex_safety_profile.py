"""Tests for the isolated Codex safety-profile feature."""

import json

import pytest

from meridian_testgen.codex_safety_profile import (
    SafetyProfileError,
    default_safety_profile,
    dependencies_for_source,
    dependencies_for_file_context,
    load_safety_profile,
    unsafe_test_calls,
)


def test_default_profile_detects_aliased_hardware_calls():
    profile = default_safety_profile()
    source = "import serial as wire\n\ndef read():\n    return wire.Serial('/dev/ttyUSB0')\n"

    dependencies = dependencies_for_source(source, profile)

    assert len(dependencies) == 1
    assert dependencies[0].resource_type == "hardware"
    assert dependencies[0].strategy == "mock"
    assert dependencies[0].matches == ("serial", "serial.Serial")


def test_profile_extends_defaults_with_a_project_resource(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({"resource_types": {
        "lab": {
            "imports": ["lab_sdk"],
            "calls": ["lab_sdk.connect"],
            "strategy": "fake",
            "guidance": "Use fake_lab.",
        },
    }}), encoding="utf-8")

    profile = load_safety_profile(path)
    dependencies = dependencies_for_source(
        "from lab_sdk import connect\n\ndef sample():\n    return connect()\n", profile)

    assert [(item.resource_type, item.matches) for item in dependencies] == [
        ("lab", ("lab_sdk.connect",)),
    ]
    assert any(rule.name == "hardware" for rule in profile.rules)


def test_module_import_context_marks_sounddevice_for_a_method(tmp_path):
    module = tmp_path / "audio_logic.py"
    module.write_text(
        "import sounddevice as sd\n\n"
        "class Engine:\n"
        "    def __init__(self):\n"
        "        self.stream = sd.OutputStream()\n\n"
        "    def key_down(self):\n"
        "        return None\n",
        encoding="utf-8",
    )

    dependencies = dependencies_for_file_context(
        module, "def key_down(self):\n    return None\n", default_safety_profile())

    assert [(item.resource_type, item.matches) for item in dependencies] == [
        ("hardware", ("sounddevice",)),
    ]


def test_static_guard_rejects_direct_live_call_but_allows_a_mock_patch():
    profile = default_safety_profile()
    unsafe = "import requests\n\ndef test_live():\n    requests.get('https://example.test')\n"
    safe = "from unittest.mock import patch\n\ndef test_mocked():\n    with patch('requests.get'):\n        pass\n"

    assert unsafe_test_calls(unsafe, profile) == (("network", "requests.get"),)
    assert unsafe_test_calls(safe, profile) == ()


def test_invalid_profile_has_a_specific_error(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text('{"resource_types": {"device": {"strategy": "real"}}}',
                    encoding="utf-8")

    with pytest.raises(SafetyProfileError, match="strategy"):
        load_safety_profile(path)
