# Codex CLI Backend

Use the Codex CLI as an alternative generator backend when Claude is
unavailable:

```bash
meridian-testgen mapping_ast.json mapping_requirements.json /path/to/codebase \
  --backend codex_cli --model gpt-5.3-codex
```

The backend invokes `codex exec --json` in read-only sandbox mode. It uses the
same prompt, JSON response shape, validation, retry behavior, and generated
test output as `claude_cli`; only the command-line adapter differs. Use
`--codex-binary /path/to/codex` when `codex` is not on `PATH`.

If `--model` is omitted, Meridian leaves model selection to Codex CLI's local
configuration. Supply `--model` only when you want to pin a Codex model.

Codex CLI JSONL does not provide the token and cost envelope that Meridian
records for Claude calls. Its report therefore counts completed calls but
records zero token and cost values.
