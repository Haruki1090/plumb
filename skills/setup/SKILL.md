---
name: setup
description: "Codex only: not for Claude Code. Install or verify plumb's optional Codex profile and custom agents when explicitly asked to set up the plumb Codex sidecar; not for ordinary plumb work."
---

# Set up the optional Codex sidecar

Codex only. In Claude Code, stop here: this skill writes Codex configuration, and the Claude plugin
needs no setup step.

The plugin is already installed. This skill adds only the optional plumb profile and native custom
agents; it does not install or modify the Claude side.

1. Resolve this loaded skill's directory. Do not ask the user to find the plugin cache or provide a
   plumb path. The bundled executable adapter is `skills/setup/scripts/install.sh` under the plugin
   root. Resolve it to an absolute path before execution.
2. Unless the user explicitly requested project scope, execute
   `"<absolute-adapter-path>" --user`.
3. For an explicitly requested project-scoped setup, execute
   `"<absolute-adapter-path>" --project "<absolute-project-root>"`. Resolve the project root from the
   active workspace; ask only when more than one target remains possible after inspection.
4. Never add `--force` on the first run. If the installer reports differing destination files, show
   the exact destinations and obtain explicit approval before rerunning with `--force`.
   A project `.codex/config.toml` that plumb did not write is reported as `skip` and never replaced,
   even with `--force`. Show the user the settings the installer lists and let them merge those by
   hand; do not edit that file for them unless asked.
5. On success, tell the user to start a new session with `codex --profile plumb` for user scope, or a
   new trusted-project session for project scope.

The adapter resolves the installed plugin root and delegates every argument to the installer. The
installer owns preflight, idempotency, atomic replacement, and symlink refusal. Do not reproduce those
checks in this skill.
