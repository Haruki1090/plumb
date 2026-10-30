# Project contract

A repository hands plumb the facts plumb cannot know through one small file, the **project
contract**. It is the second of three layers (design: section A of
[the spec](../.plumb/specs/project-contract-and-improvement-loop.md)):

| Layer | Holds | Changed by |
|---|---|---|
| Harness (plumb) | How to work and how to judge, the same everywhere | A plumb release |
| **Project contract** | What is true about one repository and the checks that hold it | A pull request to that repository |
| Personal and environment | Where roles run, credentials, the cloud setup | The owner |

A fact belongs in the layer that owns the invariant. A product rule does not move into plumb
because plumb could check it; plumb reads it from the contract.

## Where it lives

```bash
plumb-path project    # the contract file for the checkout you are in
```

It is `project.toml` under the `.plumb/` directory at the **top level of the current worktree**, and
it is tracked with the code. `plumb-path project` prints that path whether or not the file exists;
nothing else builds it. `plumb-path project --mkdir` is an error (exit 2): people write the contract.

It **ignores `PLUMB_ROOT` and `root =` in `.plumb/config`**. Those move run artifacts (ledgers,
decision logs). A contract that followed an override would stop being the repository's: two
checkouts of one commit would disagree about the rules. A linked worktree reads its own checkout's
file, so a branch carries the contract it was cut with.

## Reading it

```bash
plumb-project rework.required_authors   # one login per line
plumb-project ledger.timezone           # a string as-is
plumb-project --json [<key>]            # {"outcome", "key", "value", "message"}
plumb-project --enforce <key>           # the form a CI uses
```

The whole file is validated once against schema v1, so **a broken file is invalid for every key**:
a wrong type in `[verify]` also makes `rework.required_authors` invalid. A broken contract is not
partly trusted. Unknown tables or keys print a `warning` on stderr and do not fail.

Run it inside the checkout. Values print as follows: a string as-is, an array of strings one per
line, anything else as JSON.

### The four outcomes

| Outcome | When | Plain form | Exit |
|---|---|---|---|
| `absent` | No file, or the key is not set | Prints nothing | 0 |
| `set` | The key is set and the file is valid | The value | 0 |
| `invalid` | TOML syntax error, wrong type, `schema` missing or not 1 | `plumb-project: invalid: <key or file>: <reason>` on stderr | 2 |
| `unavailable` | Python has no `tomllib` (older than 3.11) | `plumb-project: unavailable: Python 3.11+ (tomllib) is required` on stderr | 3 |

An optional workflow step may skip on `absent` or `unavailable`, with a visible `skip:` line.
**Nothing may treat `invalid` as `absent`.** Messages name the key (or the line of a syntax error)
and never print the file's contents. If the file cannot be located at all (outside a git
repository), the answer is `invalid`, not `absent`: a caller that cannot find the contract must not
read that as "no policy".

### `--enforce`

`--enforce <key>` is the only form a CI may use. The rule: **no contract file** means the repository
has opted out, so the output is empty and the exit is 0. A file that is **invalid** exits 2, and an
**unavailable** parser exits 3, so the required job fails instead of enforcing nothing. Otherwise
it answers as the plain form does (an unset key in a valid file is empty, exit 0). A CI treats every
non-zero exit as a failure and runs Python 3.11+. Today `--enforce` and the plain form share one
code path; the difference is the contract between plumb and the CI.

## Schema v1

```toml
schema = 1

[repo]
base_branch = "develop"

[rework]
required_authors = ["some-login"]
lookahead_days = 7

[ledger]
classify = [ { glob = "frontend/**", class = "frontend" } ]
timezone = "Asia/Tokyo"

[verify]
lookup = "node scripts/feature-map/lookup.mjs"
up = "node scripts/dev/verify-up.mjs"
down = "node scripts/dev/verify-down.mjs"
scenarios = "docs/agents/feature-map"

[failure]
extra_codes = [ { code = "P01", mechanism = "describe the failure mechanism" } ]
```

| Key | Type | Meaning |
|---|---|---|
| `schema` | integer, must be `1` | Required. Any other value is `invalid` |
| `repo.base_branch` | string | The branch pull requests target |
| `rework.required_authors` | array of strings | GitHub logins (compared case-insensitively) who must write the `Fixes-PR:` line |
| `rework.lookahead_days` | integer, at least 1 | How long after landing a later fix still counts as rework |
| `ledger.classify` | array of tables `{glob, class}` | Ordered path-glob to class rules for the work ledger |
| `ledger.timezone` | string | An IANA name (`Asia/Tokyo`), checked with `zoneinfo` |
| `verify.lookup`, `verify.up`, `verify.down` | string | Commands; `plumb-doctor` checks that the first word resolves |
| `verify.scenarios` | string | A path |
| `failure.extra_codes` | array of tables `{code, mechanism}` | Product-specific failure codes |

`plumb-doctor` prints a `contract` block: `none` when the file is absent, `ok` or `--` for each key,
one `NG` line naming the key and reason when the file is invalid, and an `NG` for a verify command
whose first word is neither on PATH nor an executable file under the repository top level. Without
`tomllib` the block is skipped, never an `NG`.

## The `Fixes-PR:` line

`plumb-check-fixes --author <login> --required-authors <a,b,...> --pr <n> --body-file <path>`
validates one line of a pull request body (the author's side is `playbooks/opening-a-pr.md`):

- A non-required author passes **without the body file being opened**.
- A required author needs exactly one line starting `Fixes-PR:` (HTML comments are ignored), whose
  value is `none` or `#<number>` items separated by commas. A missing line, a second line, a
  malformed item, a duplicate number and the pull request's own number are errors. An empty
  `--author` while the list is not empty, or a missing `--pr`, is an error too.
- Exit 0 ok, 1 not ok, 2 usage. Messages name the rule and never echo the body. Parsing is linear,
  so an adversarial 5 MB body is answered in well under a second.

**The checker never reads policy itself.** The caller passes the required authors, the author and
the pull request number, and the CI must take them from sources the pull request cannot change.

## Trusted CI wiring

**Reading the policy from the pull request's own head is wrong.** The branch could remove its own
author from `rework.required_authors` in the same diff and then pass its own check. The workflow
file is also policy: with a plain `pull_request` trigger a branch can edit the workflow. Run the
job from the base branch (`pull_request_target`, or an organization-required workflow), never check
out the head, and never put the pull request body into a shell command line; pass it through an
environment variable and write it to a file.

Both examples fetch plumb at a pinned release (a tag or a commit SHA you reviewed) and use only
the pull request's event data and the base branch.

### 1. A repository variable

The policy is a repository variable (`FIXES_PR_AUTHORS`, a comma-separated list of logins) that
only repository admins change.

```yaml
name: fixes-pr
on:
  pull_request_target:
    types: [opened, edited, reopened, synchronize]
permissions:
  contents: read
jobs:
  fixes-pr:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          repository: Haruki1090/plumb
          ref: <a plumb release tag or commit SHA>
          path: plumb
      - name: Check the Fixes-PR line
        env:
          PR_BODY: ${{ github.event.pull_request.body }}
          PR_AUTHOR: ${{ github.event.pull_request.user.login }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          REQUIRED_AUTHORS: ${{ vars.FIXES_PR_AUTHORS }}
        run: |
          printf '%s' "$PR_BODY" > "$RUNNER_TEMP/pr-body.md"
          plumb/bin/plumb-check-fixes \
            --author "$PR_AUTHOR" \
            --required-authors "$REQUIRED_AUTHORS" \
            --pr "$PR_NUMBER" \
            --body-file "$RUNNER_TEMP/pr-body.md"
```

The four values are exactly `--required-authors "${{ vars.FIXES_PR_AUTHORS }}"`,
`--author "${{ github.event.pull_request.user.login }}"` and
`--pr "${{ github.event.pull_request.number }}"`, passed through `env:` so no expression is spliced
into the script text, plus the body file written from `PR_BODY`.

### 2. The base commit's contract

The policy is `rework.required_authors` in the contract **as it is on the base commit**, the code the
pull request is about to land on, not the proposed one. Changing the policy then takes a pull request
that the old policy already governs.

```yaml
name: fixes-pr
on:
  pull_request_target:
    types: [opened, edited, reopened, synchronize]
permissions:
  contents: read
jobs:
  fixes-pr:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: actions/checkout@v4
        with:
          repository: Haruki1090/plumb
          ref: <a plumb release tag or commit SHA>
          path: plumb
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.base.sha }}
          path: base
      - name: Read the policy from the base commit
        id: policy
        working-directory: base
        run: |
          set -euo pipefail
          authors=$("$GITHUB_WORKSPACE/plumb/bin/plumb-project" --enforce rework.required_authors)
          printf 'authors=%s\n' "$(printf '%s' "$authors" | paste -sd, -)" >> "$GITHUB_OUTPUT"
      - name: Check the Fixes-PR line
        env:
          PR_BODY: ${{ github.event.pull_request.body }}
          PR_AUTHOR: ${{ github.event.pull_request.user.login }}
          PR_NUMBER: ${{ github.event.pull_request.number }}
          REQUIRED_AUTHORS: ${{ steps.policy.outputs.authors }}
        run: |
          printf '%s' "$PR_BODY" > "$RUNNER_TEMP/pr-body.md"
          plumb/bin/plumb-check-fixes \
            --author "$PR_AUTHOR" \
            --required-authors "$REQUIRED_AUTHORS" \
            --pr "$PR_NUMBER" \
            --body-file "$RUNNER_TEMP/pr-body.md"
```

The policy step runs `plumb-project --enforce rework.required_authors` inside the base checkout, with
Python 3.11+, and **fails the job on any non-zero exit**: an invalid base contract (exit 2) or a
runner without `tomllib` (exit 3) fails the job instead of enforcing nothing. Do not add
`continue-on-error` or `|| true` to that step. A base commit with no contract opts out: the list is
empty and nobody is required. The head's contract is never read.
