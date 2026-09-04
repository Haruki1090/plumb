> **This is history. Do not execute it.**
> The current source of truth is `.plumb/specs/codex-path-free-install.md`. **If this document disagrees with it, the source of
> truth wins.** Do not sync this back up — syncing it revives the second source of truth.

# Implement path-free Codex installation

Build a copy-pasteable remote-marketplace install flow and an installed-plugin setup skill for the
optional Codex sidecar. The approved specification is
`.plumb/specs/codex-path-free-install.md`.

Global constraints: preserve the Claude-first root router, `.claude-plugin/`, `agents/*.md`, and all
canonical playbooks and principles. Do not add an auto-running setup hook. Do not overwrite differing
Codex profile or agent files without explicit approval. Keep the different-family judge caveat intact.

Handoff: the main session executes this single tightly coupled task, then a separate `plumb_judge`
reviews the complete diff. The different-family judge line is handled separately from that same-family
review.

## Task 1: Make Codex installation path-free

Files:

- Create `skills/setup/SKILL.md` and `skills/setup/scripts/install.sh`: invoke the executable adapter in
  user scope by default; have it resolve the installed plugin root and delegate to
  `bin/plumb-codex-install`; require explicit user request for project scope and explicit approval
  before `--force`.
- Edit `README.md` lines 81-114: replace clone/path placeholders with `Haruki1090/plumb`, explain the
  normal two-command install and new-session boundary, and move profile/native-agent setup into the
  optional `$plumb:setup` flow.
- Edit `docs/openai-runtime.md` lines 7-38: distinguish normal plugin use from optional profile/native
  agent setup and name `$plumb:setup` as the path-free entrypoint.
- Edit `docs/scope.md` lines 172-174: record that the existing installer is reached through the setup
  skill after marketplace installation.
- Edit `docs/releases/v0.7.0.md` Install section: keep the shipped release instructions aligned with
  the path-free marketplace and optional setup flow.
- Edit `scripts/selftest.sh` near the existing Codex installer tests: validate the setup skill's actual
  entrypoint by copying the plugin tree to a temporary installed-plugin-shaped path and executing its
  adapter against a temporary `CODEX_HOME`.

Steps:

1. Add the self-test that executes `skills/setup/scripts/install.sh` from a temporary plugin copy and
   installs into a temporary `CODEX_HOME`.
2. Run `bash scripts/selftest.sh`; expect the new assertion to fail because `skills/setup/SKILL.md` is
   absent.
3. Create `skills/setup/SKILL.md` with the exact user/project/force boundaries above and its quoted,
   executable adapter.
4. Update README and runtime/scope documentation to expose the new normal and optional paths.
   Update the current release install page as part of the same public installation surface.
5. Run `bash scripts/selftest.sh`; expect zero failures and an `ok` line for installed-plugin setup
   resolution.
6. Run the full required verification: `bash scripts/check-harness.sh`, `bash scripts/selftest.sh`, the
   installed plugin validator on the repository root, the skill validator on `skills/setup`, and
   `codex --strict-config` against the repository configuration. Expect exit 0 from every command.
7. Exercise the plugin-creator local reinstall loop with a temporary cachebuster, reinstall
   `plumb@plumb`, inspect that the installed cache contains `skills/setup/SKILL.md`, execute the cached
   installer against a temporary `CODEX_HOME`, then restore the release version in the source manifest.
8. Retire this plan to `.plumb/history/codex-path-free-install.md` with the required history header.

If the adapter stops resolving the installed plugin root relative to itself, the self-test in step 1
fails. If the installed package omits the new skill/adapter or the cached installer cannot configure a
clean Codex home, the installed-cache exercise in step 7 fails.
