# Test-generation run — rainbow_keys — RAW claude

- **Date/time:** 2026-08-24 21:44 PDT (2026-08-25T04:44:48+00:00 UTC)
- **System under test:** rainbow_keys (`<REPO_ROOT>/rainbow_keys`)
- **LLM:** RAW (un-orchestrated) `claude`, model `claude-opus-5`
- **Validation interpreter:** `<REPO_ROOT>/rainbow_keys/.venv/bin/python`
- **Note:** single naive prompt, no Meridian structure; agent had write access to a fresh copy at `/var/folders/s3/yj7knz911m13_1p7qz17c_km0000gn/T/raw_claude_rainbow_keys_t51g11fz`

## Results — runtime verdicts

- Tests created (total): **59** in 4 file(s), 593 lines of test code
- **Valid tests: 75** (75 pass; 0 are valid failures)
- Invalid tests: 0
- Files that crashed or hung: 0
- Tokens out: 14741; reported cost: $1.1764

### Valid failures discovered (candidate findings)

- (none)

### Invalid tests

- (none)

## Reproduce

```sh
scripts/raw_baseline.py --codebase <REPO_ROOT>/rainbow_keys --backend claude --model claude-opus-5 --python <REPO_ROOT>/rainbow_keys/.venv/bin/python
```

## Invalid tests caught by Meridian during generation

- (not applicable — RAW runs bypass Meridian entirely)
