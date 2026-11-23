---
name: configure
description: Walk the owner through plumb's per-machine configuration file, asking only for what cannot be detected, and write it after showing the diff. Use when asked to "set up plumb", "configure plumb", "which models should plumb use" or "plumb setup for this machine". Not the optional sidecar install for the other runtime (plumb:setup) and not a health check (plumb:doctor).
---

# Configure plumb on this machine

**The owner's config file decides where each role runs and which model it gets. This skill settles
the unset keys with the owner and writes only those, after the diff is shown and approved.** It
never writes a secret, never edits the agent runtime's own settings, and never touches another
account's files.

## 1. See what is unset

Run `plumb-doctor`. Read the `--` lines for `role.judge`, `role.bulk`, `role.implementer`,
`pane.driver`, `role.explorer.model`, `role.implementer.model` and `stack.tool`; those are unset.
The doctor does not report `worker.rules.types`; ask it with `plumb-config worker.rules.types ""`. An `NG` line
for a key already set is not this skill's job to hide: report it, and offer to fix that key too.
`plumb-config --help` prints the path of the file; use that path, not a remembered one.

## 2. Settle, in one batched question

Ask the owner once, in one message, only for what is unset and cannot be detected. Each item lists
what this machine can run and ends with "leave unset".

- **Judge role** (`role.judge`): a command whose model is **a different family from this session's**.
  Unset means every judge line in a plan is a visible skip (`docs/role-map.md`). You cannot tell a
  command's family from its name; ask, and do not suggest one by guess.
- **Implementer, explorer, bulk**: `role.implementer` and `role.bulk` are commands;
  `role.implementer.model` is the model the fallback subagent runs on, in the owner's words;
  `role.explorer.model` is an alias the Agent tool accepts (read the list in the header of
  `scripts/plumb-config.sh`, do not recall it).
- **`pane.driver`** and **`stack.tool`**: the driver command that opens visible panes; `gh-stack`
  for stacked pull requests.
- **`worker.rules.types`**: the delegate types (comma-separated) whose prompts get the shared
  worker rules prepended by the hook (`docs/role-map.md`). Offer the types this session's Agent
  tool lists; unset leaves the feature off.

**Offer only what runs here.** For a command, check its first word with `command -v`; for
`gh-stack`, check `gh extension list`. Drop what fails and say why. **Never guess a model name and
never carry a default the owner did not confirm**: a key the owner leaves open stays unset.

## 3. Write the file, idempotently

1. Read the existing file (it may not exist). Build the new text in a temporary file beside it.
2. Change only the keys settled: replace that key's own line, or append `key = value` at the end.
   Keep every other line, comment and blank line byte for byte. A key whose value is already the
   settled one is not touched.
3. Give the file a version line, `printf '# %s-config-defaults: 1\n' plumb` (written so, because
   a literal command-shaped name in a body must be a real command). Add it as the first line when
   no line like it exists; if a managed block starts the file, add it on the line after the block's
   closing line. A later release that changes a default can then migrate a file with an older
   number, and leave a key the owner set by hand alone. Never change the number of a file that has
   one.
4. **If the file has a managed block** (`# >>> plumb-bootstrap` to `# <<< plumb-bootstrap`), do
   not edit inside it. Say so. A key the block already sets wins over any line outside it
   (`plumb-config` reads the first match), so tell the owner to change that key by rerunning
   `plumb-bootstrap` with its flag.
5. Show `diff -u` of the old file against the new one. **Write only after the owner says yes**, by
   moving the temporary file over the original. No yes, no write; delete the temporary file.
6. A value that looks like a credential or carries one in a URL is refused, not written. The file
   holds commands, aliases and names, never secrets.

## 4. Check and report

Run `plumb-doctor` again. Report line by line what changed against step 1, including a key that is
now set but reports `NG` (its command does not resolve, or it is not logged in): that is the
owner's next action, not something to quietly revert. Do not claim a role works because its key is
set; the doctor line is the evidence.

Then, **once**, if the current repository has no project contract (`.plumb/project.toml`) or its
contract has no `[verify]` table, add one sentence: `plumb:verify-init` can write one. It is an
offer; do not start it.

## What this skill does not do

- It does not install or verify the other runtime's sidecar (`plumb:setup`) or judge the install's
  health (`plumb:doctor`); it only writes the keys they read.
- It does not log in to anything, install a tool, or start a delegate to test a role.
- It does not edit another file to make a key take effect.
