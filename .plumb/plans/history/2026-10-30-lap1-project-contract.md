> **This is history. Do not execute it.**
> The current source of truth is `.plumb/specs/project-contract-and-improvement-loop.md`. **If this document disagrees with it, the source of
> truth wins.** Do not sync this back up — syncing it revives the second source of truth.

# Lap 1: project contract and rework link

Spec: `.plumb/specs/project-contract-and-improvement-loop.md` (sections A and B, the "Every lap"
gate). This plan implements lap 1 only. Read only your task; each task carries what it needs.

## Header for the implementer

- Repository: plumb (a Claude Code plugin harness, English throughout). Branch to work on is given
  in your brief. Do not push.
- Conventions: shell scripts are bash with `set -euo pipefail`; Python scripts are standard library
  only (Python 3.11+ features allowed only behind the documented fallback). Every `bin/plumb-*` is a
  thin wrapper that resolves its real path in a loop (copy `bin/plumb-config`) and execs the script
  under `scripts/`.
- Checks, run exactly these and read their last line:
  - `bash scripts/check-harness.sh` → ends with `→ passed (...)`
  - `bash scripts/selftest.sh` → ends with `→ passed`
- Tests live in `scripts/selftest.sh` (helpers `ok`, `ng`, `eq`; each case prints `ok`/`NG`). Add
  cases next to the related existing ones, in the same style. Write the failing case first, run
  selftest and see it fail, then implement.
- Never print file contents of a contract or body in error messages beyond the key and line number.

## File map

| File | Responsibility | Task |
|---|---|---|
| `scripts/plumb-path.sh` | add kind `project`: the contract file path | 1 |
| `scripts/plumb-project.py` (new), `bin/plumb-project` (new) | read the contract: outcomes, `--json`, `--enforce` | 2 |
| `scripts/check-fixes.py` (new), `bin/plumb-check-fixes` (new) | validate the `Fixes-PR:` line | 3 |
| `scripts/doctor.sh` | contract section | 4 |
| `docs/project-contract.md` (new), `playbooks/opening-a-pr.md`, `SKILL.md`, `docs/artifact-lifecycle.md` | schema, outcomes, trusted CI wiring; the PR line; index entries | 5 |
| `scripts/selftest.sh` | cases for tasks 1–4 and the integration fixture | 1–4, 6 |
| `CHANGELOG.md`, `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, `README.md` | 0.14.0 | 7 |

## Task 1 — `plumb-path project`

Behavior: `plumb-path project [repo]` prints `<git top-level of the current worktree>/.plumb/project.toml`
whether or not the file exists. It **ignores** `PLUMB_ROOT` and `.plumb/config root=` (those move run
artifacts; the contract belongs to the checkout). From a linked worktree it is that worktree's own
top level (not the main worktree). Outside a git repository without a repo argument: exit 1 with the
existing message. `--mkdir` is an error for this kind (exit 2): the contract is written by people.
Update the usage text and the header comment.

Selftest cases (fail first): from a subdirectory; from a linked worktree (create one in a temp repo);
with `PLUMB_ROOT=/tmp/x` set (still the repo's path); `--mkdir` exits 2.

## Task 2 — `plumb-project`

`plumb-project <dotted.key>` / `plumb-project --json [<key>]` / `plumb-project --enforce <key>`.
Reads the file from `plumb-path project` (call the script, do not rebuild the path).

Schema v1 (validate exactly this; unknown top-level tables or keys produce a `warning` on stderr,
not an error):

```toml
schema = 1
[repo]
base_branch = "develop"          # string
[rework]
required_authors = ["login"]     # array of strings (GitHub logins, case-insensitive)
lookahead_days = 7               # integer >= 1
[ledger]
classify = [ { glob = "frontend/**", class = "frontend" } ]   # array of tables {glob, class}
timezone = "Asia/Tokyo"          # IANA name (validate with zoneinfo)
[verify]
lookup = "node scripts/feature-map/lookup.mjs"   # string command
up = "node scripts/dev/verify-up.mjs"            # string command
down = "node scripts/dev/verify-down.mjs"        # string command
scenarios = "docs/agents/feature-map"            # string path
[failure]
extra_codes = [ { code = "P01", mechanism = "..." } ]  # array of tables {code, mechanism}
```

Outcomes and exit status (the JSON form always has `{"outcome": ..., "key": ..., "value": ..., "message": ...}`):

| Outcome | When | Plain form | Exit |
|---|---|---|---|
| absent | no file, or key not set | prints nothing | 0 |
| set | key set and valid | the value (a string as-is; an array of strings one per line; anything else as JSON) | 0 |
| invalid | TOML parse error, wrong type, `schema` missing or not 1 | `plumb-project: invalid: <key or file>: <reason>` on stderr | 2 |
| unavailable | `import tomllib` fails | `plumb-project: unavailable: Python 3.11+ (tomllib) is required` on stderr | 3 |

Validation runs on the whole file once, so an invalid file is invalid for every key (a wrong type in
`[verify]` makes `rework.required_authors` invalid too — a broken file is not partly trusted).

`--enforce <key>`: as above, except it is the only form a CI uses and the rule is stated in its help:
no file → empty, exit 0; invalid → exit 2; unavailable → exit 3; set or absent key in a valid file →
as above. (The difference from the plain form is documentation only today; keep one code path and test
that `--enforce` returns non-zero for invalid and unavailable.)

Selftest cases (fail first), each in a temp repo: no file; file with key unset; each type error;
bad TOML; `schema = 2`; unknown key warns but succeeds; `--json` shape for each outcome; unavailable,
simulated without a product flag by running the script through
`python3 -c 'import sys, runpy; sys.modules["tomllib"] = None; sys.argv = [...]; runpy.run_path(...)'`.

## Task 3 — `plumb-check-fixes`

`plumb-check-fixes --author <login> --required-authors <comma list> --pr <n> --body-file <path>`.

- Required = `--author` (case-insensitive) is in the list (entries trimmed, empty entries dropped).
  Not required → exit 0 **before opening the body file** (test with a path that does not exist).
- Required and `--author` empty or `--pr` missing/not a positive integer → exit 1 with the reason.
- Grammar, on the body with HTML comments removed (`<!-- ... -->`, unclosed comment kept as text),
  CR removed, lines that start with `Fixes-PR:`: exactly one such line; value after the colon,
  trimmed, is `none` or `#<1-9 digits>` items separated by `,` with optional spaces. Errors: zero
  lines, two or more lines, malformed item, duplicate number, the number equal to `--pr`.
- Implement with `str.find` loops and `split` — no regular expression with nested quantifiers. One
  `re.fullmatch(r"#[0-9]{1,9}", item)` per item is fine.
- Exit 0 ok, 1 not ok (message names the rule, never echoes the body), 2 usage error.

Selftest cases (fail first): non-required with a missing body file; each error; ok with `none`,
`#12`, `#12, #34`; a 5 MB body (`Fixes-PR: ` + `#1, ` repeated, and a 5 MB line without a newline)
finishing in under 2 seconds (measure with `date +%s%N` around the call; fail the case if slower).

## Task 4 — doctor

`plumb-doctor` gains a `contract` block after the roles block: `--  contract: none` when the file is
absent; otherwise one line per schema key: `ok  <key>` when set, `--  <key>` when unset, `NG <key>:
<reason>` when the file is invalid (then one NG line for the file and stop listing), and for
`verify.lookup|up|down` an `NG` when the first word of the command does not resolve (relative to the
repository top level, or on PATH). Unavailable parser → `--  contract: skipped, Python 3.11+ (tomllib)
is unavailable`. Selftest: absent, partial, full, invalid, missing command.

## Task 5 — docs

- `docs/project-contract.md`: what the contract is (the second of the three layers, link the spec),
  where it lives (`plumb-path project`; why it ignores `PLUMB_ROOT`), the schema table, the four
  outcomes, `--enforce`, and **trusted CI wiring** with two examples:
  1. repository variable: the CI passes `--required-authors "${{ vars.FIXES_PR_AUTHORS }}"`,
     `--author "${{ github.event.pull_request.user.login }}"`, `--pr "${{ github.event.pull_request.number }}"`,
     the body through an environment variable written to a file;
  2. base commit: the CI checks out the base SHA (`github.event.pull_request.base.sha`) into a
     separate directory, runs `plumb-project --enforce rework.required_authors` there with Python 3.11+,
     and fails the job on a non-zero exit.
  State plainly that reading the policy from the pull request's own head is wrong (the branch could
  remove its author), and that the checker never reads policy itself.
- `playbooks/opening-a-pr.md`, section "The body": one paragraph — when `plumb-project
  rework.required_authors` lists the author, write exactly one `Fixes-PR:` line (grammar as above),
  naming the earlier landed pull requests this one fixes, or `none`.
- `SKILL.md`: add `plumb-project` and `plumb-check-fixes` where the router lists tools, in the
  existing style. `docs/artifact-lifecycle.md`: one line that `plumb-path project` is the contract
  and is not moved by `PLUMB_ROOT`.

Check: `bash scripts/check-harness.sh` passes (it checks that `bin/` names in docs resolve).

## Task 6 — integration fixture

A selftest case that builds a temp repository with a base commit carrying an **invalid** contract and
a head commit carrying a valid one that drops the author, then runs the documented base-commit wiring
(as a small shell function in the test) and shows: invalid base contract → job fails; unavailable
parser → job fails; valid base contract with the author → the checker is required; the head's
weakened contract is never read.

## Task 7 — release

`CHANGELOG.md` `## [0.14.0] - 2026-10-30` with Added / Changed in the existing style (both manifests
bump to 0.14.0). README: one short subsection "Project contract" pointing at `docs/project-contract.md`.
Run both checks; they pass.
