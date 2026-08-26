"""Codex-owned resource-safety profiles for generated tests.

Profiles describe external boundaries a unit test must isolate. They are small
JSON documents, so projects can add proprietary SDKs or devices without
changing Meridian itself. This module deliberately uses only stdlib modules.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path


class SafetyProfileError(Exception):
    """A safety profile could not be loaded or is not a valid policy."""


@dataclass(frozen=True)
class ResourceRule:
    """One resource boundary and the isolation a generated test must use."""

    name: str
    imports: tuple[str, ...]
    calls: tuple[str, ...]
    strategy: str
    guidance: str = ""
    enforce_test_calls: bool = True


@dataclass(frozen=True)
class ResourceDependency:
    """A resource boundary found in a function's source."""

    resource_type: str
    strategy: str
    guidance: str
    matches: tuple[str, ...]


@dataclass(frozen=True)
class SafetyProfile:
    """The immutable policy used for one test-generation run."""

    rules: tuple[ResourceRule, ...]


_DEFAULT_RESOURCE_TYPES = {
    "hardware": {
        "imports": ["serial", "gpiozero", "RPi.GPIO", "board", "busio", "cv2", "sounddevice"],
        "calls": ["serial.Serial", "cv2.VideoCapture", "sounddevice.OutputStream"],
        "strategy": "mock",
        "guidance": "Patch the symbol where the module under test looks it up; use a fake device response instead of real hardware.",
    },
    "network": {
        "imports": ["requests", "httpx", "aiohttp", "socket", "websocket", "grpc", "boto3"],
        "calls": ["requests.get", "requests.post", "httpx.get", "httpx.post", "socket.create_connection", "socket.socket"],
        "strategy": "mock",
        "guidance": "Patch the client or transport where it is looked up; never contact a live endpoint.",
    },
    "subprocess": {
        "imports": ["subprocess"],
        "calls": ["subprocess.run", "subprocess.Popen", "subprocess.call"],
        "strategy": "mock",
        "guidance": "Patch the subprocess entry point and assert its arguments or return a controlled CompletedProcess-like fake.",
    },
    "gui": {
        "imports": ["tkinter", "PyQt5", "PySide6", "wx"],
        "calls": ["tkinter.Tk"],
        "strategy": "mock",
        "guidance": "Patch window creation and verify state changes without opening a desktop window.",
    },
    "filesystem": {
        "imports": [],
        "calls": ["open", "pathlib.Path.open", "pathlib.Path.write_text"],
        "strategy": "tmp_path",
        "guidance": "Use pytest's tmp_path for file-backed behavior; do not use ambient paths or user files.",
        "enforce_test_calls": False,
    },
    "environment": {
        "imports": ["os"],
        "calls": ["os.getenv", "os.environ.get"],
        "strategy": "monkeypatch",
        "guidance": "Use monkeypatch to set only the environment values needed by the test.",
        "enforce_test_calls": False,
    },
}

_VALID_STRATEGIES = frozenset({"mock", "fake", "tmp_path", "monkeypatch", "skip"})


def default_safety_profile() -> SafetyProfile:
    """The built-in policy, copied into a profile object for callers."""
    return _profile_from_data({"resource_types": _DEFAULT_RESOURCE_TYPES})


def load_safety_profile(path=None) -> SafetyProfile:
    """Load a JSON profile, extending or replacing built-in resource types."""
    if path is None:
        return default_safety_profile()
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SafetyProfileError(f"could not read safety profile {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SafetyProfileError(f"invalid JSON in safety profile {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SafetyProfileError("safety profile must be a JSON object")
    custom = raw.get("resource_types")
    if not isinstance(custom, dict):
        raise SafetyProfileError("safety profile needs a 'resource_types' object")
    combined = dict(_DEFAULT_RESOURCE_TYPES)
    combined.update(custom)
    return _profile_from_data({"resource_types": combined})


def dependencies_for_source(source: str, profile: SafetyProfile,
                            module_source: "str | None" = None) -> tuple[ResourceDependency, ...]:
    """Return boundaries from a function slice and its module's imports.

    Test code commonly exercises a method by constructing its class. A device
    client may live in ``__init__`` while the mapped method itself contains no
    direct device call, so module imports are relevant context. Calls remain
    restricted to the function slice to avoid attributing every module call to
    every method.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    imports = _imports(tree)
    if module_source is not None:
        try:
            imports |= _imports(ast.parse(module_source))
        except SyntaxError:
            pass
    calls = _calls(tree)
    found = []
    for rule in profile.rules:
        matches = sorted({
            reference for reference in imports | calls
            if _matches(rule.imports, reference) or _matches(rule.calls, reference)
        })
        if matches:
            found.append(ResourceDependency(
                rule.name, rule.strategy, rule.guidance, tuple(matches)))
    return tuple(found)


def dependencies_for_file_context(path, function_source: str,
                                  profile: SafetyProfile) -> tuple[ResourceDependency, ...]:
    """Profile a function using its module import context when available."""
    try:
        module_source = Path(path).read_text(encoding="utf-8")
    except OSError:
        module_source = None
    return dependencies_for_source(function_source, profile, module_source)


def unsafe_test_calls(source: str, profile: SafetyProfile) -> tuple[tuple[str, str], ...]:
    """Known live resource calls directly made by generated test source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    calls = _calls(tree)
    unsafe = []
    for rule in profile.rules:
        if not rule.enforce_test_calls:
            continue
        for call in sorted(call for call in calls if _matches(rule.calls, call)):
            unsafe.append((rule.name, call))
    return tuple(unsafe)


def _profile_from_data(data: dict) -> SafetyProfile:
    rules = []
    for name, value in data["resource_types"].items():
        if not isinstance(name, str) or not name:
            raise SafetyProfileError("resource type names must be non-empty strings")
        if not isinstance(value, dict):
            raise SafetyProfileError(f"resource type '{name}' must be an object")
        imports = _strings(value.get("imports", []), name, "imports")
        calls = _strings(value.get("calls", []), name, "calls")
        strategy = value.get("strategy")
        if strategy not in _VALID_STRATEGIES:
            choices = ", ".join(sorted(_VALID_STRATEGIES))
            raise SafetyProfileError(f"resource type '{name}' needs strategy one of: {choices}")
        guidance = value.get("guidance", "")
        if not isinstance(guidance, str):
            raise SafetyProfileError(f"resource type '{name}' guidance must be a string")
        enforce = value.get("enforce_test_calls", strategy in {"mock", "fake"})
        if not isinstance(enforce, bool):
            raise SafetyProfileError(f"resource type '{name}' enforce_test_calls must be true or false")
        rules.append(ResourceRule(name, tuple(imports), tuple(calls), strategy,
                                  guidance, enforce))
    return SafetyProfile(tuple(rules))


def _strings(value, name: str, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SafetyProfileError(f"resource type '{name}' {field} must be a list of non-empty strings")
    return value


def _imports(tree: ast.AST) -> set[str]:
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.add(f"{node.module}.{alias.name}")
    return imports


def _calls(tree: ast.AST) -> set[str]:
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".", 1)[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _qualified_name(node.func)
            if name:
                root, dot, rest = name.partition(".")
                calls.add(aliases.get(root, root) + (dot + rest if dot else ""))
    return calls


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _matches(patterns: tuple[str, ...], reference: str) -> bool:
    return any(reference == pattern or reference.startswith(pattern + ".")
               for pattern in patterns)
