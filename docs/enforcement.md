# What enforces each rule

`docs/enforcement.tsv` has one row for each rule plumb states as a hard rule: what the rule says, where
it is written, how it is enforced, and by what. Its job is to make visible which rules rest on prose
alone. `plumb-enforcement` reads it, checks every row against the tree and prints the counts;
`plumb-doctor` prints the same summary line and reports a missing or invalid table as NG.

Columns: `rule`, `stated_in`, `mechanism`, `enforced_by`. `rule` is one short sentence. `stated_in` is a
repository path, optionally `path#heading`, where the heading is a part of a heading line of that file.

The four mechanisms:

- `check`: a script or a numbered rule of `scripts/check-harness.sh` fails when the rule is broken. `enforced_by` is `check-harness rule N` or the script path.
- `hook`: a hook in `hooks/hooks.json` changes or blocks the action. `enforced_by` is `hook <Event>` or `hook <Event>:<matcher>`.
- `command`: a plumb command reports a break, and nothing runs it automatically. `enforced_by` is the command, with any arguments that pick the check.
- `prose`: nothing but the text. `enforced_by` is `-`.

To add a row, append a line to the table with the four fields separated by tabs, then run
`plumb-enforcement --check`. It fails on a wrong column count, an unknown mechanism, a path or heading
that does not exist, a `check-harness rule N` with no matching `# N.` comment, a hook missing from
`hooks/hooks.json`, a prose row whose `enforced_by` is not `-`, and a rule written twice.

A new hard rule in prose gets a row in the same change. When a rule later gains a check, a hook or a
command, change its mechanism and `enforced_by` in that change, so the prose count falls. Without flags
`plumb-enforcement` also lists the prose rows; `--json` prints the whole table.
