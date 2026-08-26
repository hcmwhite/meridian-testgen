# Codex Test Safety Profiles

`meridian-testgen` treats external boundaries as unsafe by default. Its built-in
profile recognizes common hardware, network, subprocess, GUI, filesystem, and
environment APIs. Provide `--safety-profile path/to/profile.json` to add a
proprietary SDK, device library, database client, emulator, or other boundary.

The file is JSON and has one `resource_types` object. A custom resource type
with the same name replaces the built-in rule; a new name extends it.

```json
{
  "resource_types": {
    "lab_controller": {
      "imports": ["acme_lab", "acme_lab.client"],
      "calls": ["acme_lab.client.connect", "acme_lab.Device"],
      "strategy": "fake",
      "guidance": "Use the lab_controller_fake fixture; never connect to a bench device.",
      "enforce_test_calls": true
    }
  }
}
```

Each rule supports:

- `imports`: module names whose presence identifies a resource dependency.
- `calls`: qualified functions or constructors to detect. Import aliases are resolved.
- `strategy`: `mock`, `fake`, `tmp_path`, `monkeypatch`, or `skip`.
- `guidance`: project-specific instructions included verbatim in the generation prompt.
- `enforce_test_calls`: defaults to `true` for `mock` and `fake`. When true,
  direct matching calls in generated test source are rejected before pytest
  collection. Set it to `false` for resource types that are safe only through
  a fixture, such as `tmp_path` filesystem work.

When an unfamiliar boundary is blocked, add a rule and regenerate. If real
integration coverage is necessary, keep it outside generated unit tests:
mark it `integration` or `requires_hardware`, skip it by default, and require
an explicit command plus dedicated test credentials or an emulator endpoint.
The static guard catches known direct calls; dynamic imports and reflection
still need a runtime sandbox or a boundary adapter in the application.
