---
name: setup
description: Install or verify plumb's optional Codex profile and native custom agents after plugin installation. Use when explicitly asked to set up, repair, or update the plumb Codex sidecar; do not use for ordinary plumb work.
---

# Set up the optional Codex sidecar

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
5. On success, tell the user to start a new session with `codex --profile plumb` for user scope, or a
   new trusted-project session for project scope.

The adapter resolves the installed plugin root and delegates every argument to the installer. The
installer owns preflight, idempotency, atomic replacement, and symlink refusal. Do not reproduce those
checks in this skill.
