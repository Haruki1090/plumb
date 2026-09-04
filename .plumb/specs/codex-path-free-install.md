# Path-free Codex installation

## End state

Codex users install plumb from its GitHub marketplace without cloning the repository or replacing
placeholder paths. The normal installation is complete after the marketplace and plugin commands,
and the plugin is usable in a new Codex session.

The optional plumb profile and native custom-agent definitions remain additive. An installed plumb
plugin exposes `$plumb:setup`, which resolves its own installed plugin root and runs the existing safe,
idempotent installer. Users never need to locate the plugin cache or type a plumb filesystem path.

## Acceptance criteria

- The README's primary Codex install block contains only copy-pasteable GitHub marketplace and plugin
  commands and contains no `/absolute/path/to/plumb` placeholder.
- The current release installation page uses the same path-free flow and cannot send users back to a
  clone or placeholder path.
- The README says that a new ordinary Codex session can invoke `$plumb:plumb-codex` after installation.
- `$plumb:setup` installs or verifies the optional user-scoped profile and native agents through its
  executable adapter, which resolves `bin/plumb-codex-install` from the loaded skill path.
- `$plumb:setup` never passes `--force` without explicit user approval and supports project scope only
  when the user explicitly requests it.
- Runtime and scope documentation describe plugin installation as the normal path and setup as an
  optional enhancement without weakening the existing model-family caveat.
- The existing Claude installation path and canonical Claude-first corpus remain unchanged.
- Harness checks, self-tests, Codex plugin validation, skill validation, and strict Codex config
  validation pass.

## Chosen approach

Use Codex's supported GitHub marketplace shorthand (`Haruki1090/plumb`) for acquisition. Add a narrow
setup skill with a quoted executable adapter that delegates all writes to the existing installer,
preserving its preflight, symlink, idempotency, and force-overwrite protections. The installed-package
self-test executes that adapter rather than duplicating its path-resolution logic.

## Rejected approaches

- A SessionStart hook: plugin hooks require a separate trust step and would attempt home-directory
  mutation at session startup, making the default path less predictable.
- A documented plugin-cache path: the version component changes and recreates the original path-editing
  problem.
- Treating profile and native agents as plugin manifest content: the current Codex plugin manifest does
  not provide declarative profile or native custom-agent installation fields.
