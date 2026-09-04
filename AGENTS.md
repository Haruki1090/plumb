# Repository guidance for Codex

plumb is Claude-first. Preserve `.claude-plugin/`, the root `SKILL.md`, `agents/*.md`, and the existing
playbooks and principles as the canonical behavior. Codex support is additive; do not rename Claude
tools or paths across the shared corpus merely to simplify the adapter.

When using plumb in this repository, read `SKILL.md` and then `docs/openai-runtime.md`. The latter
overrides only runtime-specific role, tool, return-value, path, and model-placement instructions.

For non-trivial work, keep the required judge todo visible. A Luna review is a useful separate pass but
is not a different-family verdict from a Sol main thread.

When changing the Codex sidecar, verify all of the following:

- `bash scripts/check-harness.sh`
- `bash scripts/selftest.sh`
- `.codex-plugin/plugin.json` with the installed plugin validator
- `.codex/config.toml` through `codex --strict-config`

Use native custom agents under `.codex/agents/` according to `docs/openai-runtime.md`. Delegate only when
the user asks for parallel agents or an active plumb playbook explicitly requires a role.
