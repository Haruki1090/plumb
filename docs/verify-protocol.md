# Verification protocol

`plumb-verify` answers one question with numbers: **did this change make anything measurably worse
than its base, and what was left unmeasured?** The spec is section F of
`.plumb/specs/project-contract-and-improvement-loop.md`. The project owns everything product-specific
(how to start the app, the scenarios, the fixtures, the thresholds); plumb owns the record format, the
comparator and the preflight. plumb never interprets a product screen.

```bash
plumb-verify plan [--base <sha>] [--head <sha>] [--allow-untrusted-head] [--json]
plumb-verify compare --base <rows> --pr <rows> --thresholds <file> --expect <manifest> \
                     [--shot-diffs <rows>] [--out <file>]
```

**There is no pass.** The comparator returns `regressed`, `incomplete` or `no_diff`, and `no_diff`
reads "no regression found in what was compared". It says nothing about the screens, roles and
scenarios that were not compared.

## Observation row

JSON Lines, one object per scenario, role, side and run. The first consumer (SAKUJI) already writes
this shape as `verify-metrics/1`.

| Field | Meaning |
|---|---|
| `feature`, `scenario`, `role` | Non-empty strings. The row's key is `feature/scenario/role` |
| `side` | `base` or `pr`. Recorded only: the side of a row is the file it is passed in |
| `status` | `ok`, `start_failed`, `scenario_failed`, `harness_error` or `not_run` (below) |
| `error` | Why a row is not `ok`. An error beginning `harness:` is the verification environment's fault |
| `repeat` | How many times the scenario was repeated |
| metric fields | Numbers (`console_errors`), lists of strings such as `"404 GET /x"` (`http_4xx`), maps of id to number (`pageerrors_known`), and `growth_per_iter` with one number per field |
| `restore_check` | Optional `{ok, error?, ...}`: the state read back after the scenario put things back |
| `cleanup_error` | Optional string: the cleanup raised |
| `artifacts` | Paths of screenshots and other files. Never committed blobs |

The last row per key wins, per file. A row that is not a JSON object, has no key fields, or has an
unknown `status` is a malformed input (exit 2).

### Status and its legacy derivation

| Status | Meaning |
|---|---|
| `ok` | The scenario ran to the end and its metrics are valid |
| `start_failed` | The side did not start |
| `scenario_failed` | The product or the procedure stopped the scenario before its end |
| `harness_error` | The verification environment failed (role mismatch, login, tooling), not the product |
| `not_run` | The scenario was selected and not run |

A row **without `status`** derives it, so existing runs stay readable: `ok: true` is `ok`; otherwise
an `error` beginning `harness:` is `harness_error`; any other `ok: false` is `scenario_failed`. A row
with neither `status` nor a boolean `ok` is malformed.

## Thresholds file

JSON, named by the contract's `[verify] thresholds`. The comparator reads it and never supplies
defaults: one product's numbers must not become everyone's.

```json
{
  "version": "provisional-1",
  "status": "provisional",
  "min_repeat_for_growth": 3,
  "metrics": {
    "console_errors": { "rule": "increase_abs", "max": 0 },
    "growth.heap_mb": { "rule": "growth_diff", "max": 0.5 },
    "screenshot_diff_ratio": { "rule": "abs_max", "max": 0.01 }
  }
}
```

`version` and `status` are copied to the result. `min_repeat_for_growth` defaults to 3. Other fields
in a rule (`unit`, `desc`, `status`) are carried into a regression's `threshold` and otherwise
ignored. A missing or non-numeric parameter, or a `rule` that is not in the table, is an error (exit
2), never skipped.

### Rules

`b` is the base value and `p` the pr value. Both must be finite numbers (or, where noted, lists and
maps of them); otherwise the metric is `not_measured` and the row is incomplete. **Every comparison
is strict**: a delta equal to the limit is not a regression.

| Rule | Parameters | Regression when |
|---|---|---|
| `increase_abs` | `max`, `field?` | `p - b > max`. The value is read from `field` (default: the metric name), falling back to the metric name when the field is absent |
| `known_diff` | `min_abs`, `max_ratio` | for each id in either map (a missing id is 0): `p - b > min_abs` and `p > b * max_ratio` |
| `list_new` | `max` | `size(p) - size(b) > max`. The size is the list length (duplicates count) or the number itself. Up to 10 added entries are listed, by multiset difference (`2x` marks a repeated one) |
| `increase_ratio_and_abs` | `min_abs`, `max_ratio` | `p - b > min_abs` and `p > b * max_ratio`. With `b = 0` only the absolute part can hold |
| `growth_diff` | `max` | `p - b > max`, on `growth_per_iter.<name>` for a metric called `growth.<name>`. Needs `repeat >= min_repeat_for_growth` on both sides |
| `abs_max` | `max` | a shot-diff `ratio > max`. Applies to shot-diff rows only; the first `abs_max` metric is the screenshot rule (`screenshot_diff_ratio` when there is one) |

Deltas in the output are `p - b`, rounded to 2 decimals for `increase_ratio_and_abs`, 3 for
`growth_diff` and 4 for a screenshot ratio.

## Shot-diff rows

JSON Lines, from the project's screenshot differ, passed with `--shot-diffs`:
`{"key": "feature/scenario/role", "name": "<shot>", "ratio": 0.004}`, or
`{"key": "...", "name": "...", "missing": "base" | "pr"}` when one side has no such screenshot.

## The manifest

The selection the run committed to. Rows alone cannot show what was never measured, so `compare`
requires it (`--expect`). JSON:

```json
{
  "schema": "verify-expect/1",
  "expected": ["feature/scenario/role"],
  "shots": { "feature/scenario/role": ["name"] },
  "unmapped": ["path/with/no/owning/feature"],
  "not_run": [{ "key": "feature/scenario/role", "reason": "why it was not run" }]
}
```

`schema` and `expected` are required; the other fields default to empty. `expected` lists every key the
selection committed to. `shots` lists the screenshots each key must have a shot-diff row for.
`unmapped` lists changed paths that no feature owns. `not_run` lists selected scenarios that were not
run, each with its reason.

## Comparator

`plumb-verify compare` prints the result as JSON and writes it to `--out` as well.

| Field | Meaning |
|---|---|
| `schema` | `verify-compare/1` |
| `result` | `regressed`, `incomplete` or `no_diff` |
| `summary` | One sentence with the counts |
| `thresholds` | `{version, status}` of the file used |
| `compared` | Keys that had a row on both sides |
| `regressions` | `[{key, metric, base, pr, delta, threshold}]`; a rule may add `added` (`list_new`), `repeat` (`growth_diff`) or `shot` (screenshots) |
| `notes` | `[{key, kind, detail}]`, one per cause or fact; `key` is `null` when no key applies |
| `missing` | Lists behind `incomplete`: `no_rows`, `only_in_base`, `only_in_pr`, `incomplete`, `start_failed`, `harness_error`, `shots_only_in_base`, `shots_only_in_pr`, `shots_without_diff`, `shots_not_measured`, `unmapped`, `not_run_scenarios` |

| Result | Exit |
|---|---|
| `no_diff` | 0 |
| `regressed` | 1 |
| `incomplete` | 3 |
| usage error, or malformed input (bad JSON with its file and line number, an unknown rule, a thresholds file with no rules, a row that is not an object, a missing required argument) | 2 |

**Precedence:** any regression makes the result `regressed` (the missing scope is still listed);
otherwise any incomplete cause makes it `incomplete`; otherwise `no_diff`. The word "pass" appears
nowhere in the output.

### Incomplete causes

Each is a `notes` kind and, where it names a key, an entry in `missing`.

| Cause | Note kind |
|---|---|
| An expected key with no row on either side | `no_rows` |
| A key with a row on one side only | `only_in_base`, `only_in_pr` |
| `start_failed` on either side | `start_failed` |
| `not_run` on either side | `not_run` |
| `harness_error` on either side | `harness_error` |
| `scenario_failed` on both sides, on base only, on pr only | `both_failed`, `base_failed`, `pr_failed` (a scenario that fails only on the candidate is `incomplete`, not a regression: whether the product or a stale procedure is at fault is a person's call) |
| `cleanup_error` on either side | `cleanup_failed` |
| `restore_check.ok == false` on either side | `restore_failed` |
| A metric a rule names that is missing or not finite on either side | `not_measured` |
| A growth rule with `repeat` below `min_repeat_for_growth` on either side | `repeat_too_small` |
| A screenshot present on one side only | `shot_missing` |
| An expected screenshot with no shot-diff row (this includes `--shot-diffs` absent or empty) | `shot_no_diff` |
| A shot-diff row with no finite ratio, or no `abs_max` rule to judge it | `not_measured` |
| An unmapped path | `unmapped` |
| A not-run scenario in the manifest | `not_run_scenario` |
| No key compared at all | `nothing_compared` |

One more note is information only: `new_writes` lists write requests that the pr makes more of.

## Preflight

`plumb-verify plan` reports whether the project contract can drive verification, with one outcome.
Text form: one line per key (`name state value`) and a final `outcome:` line, the reason on stderr.
`--json` prints `{"outcome", "message", "contract_from", "keys"}` where `contract_from` is the base
commit or `worktree` and each key is `{"value", "state"}`. A key's state is `absent` (not set or
empty), `set` (set, not checked because the contract is partial), `resolves` or `unresolved`.

| Outcome | When | Exit |
|---|---|---|
| `runnable` | `lookup`, `up`, `down`, `scenarios` and `thresholds` are all set and resolve | 0 |
| `invalid` | The contract does not parse or break schema v1, the base is not a commit, or the contract cannot be located | 2 |
| `unavailable` | Python has no `tomllib` (older than 3.11); the same meaning as `plumb-project` | 3 |
| `absent` | No contract file, no `[verify]` table, or an empty one | 4 |
| `partial` | Some of the five keys are missing | 5 |
| `unresolved` | A command or path does not resolve | 6 |
| `untrusted_head` | `--head` is not contained in an `origin` branch (below) | 7 |
| `untrusted_base` | `--base` is not contained in an `origin` branch, so its contract is not one the repository accepted | 8 |

Resolution follows `plumb-doctor`: the first word of a command with a `/` is a path relative to the
repository top level and must be an executable file; without one it must be on PATH. `thresholds` must
be a file (a directory is not). `scenarios` is a file or a command that resolves. With `--base`, paths
resolve in the base commit's tree, and an absolute path does not resolve (it would leave that tree).
A caller continues only on `runnable`.
`untrusted_head` outranks every other outcome, since even the no-contract fallback runs the head's
code. `untrusted_base` outranks every outcome but `invalid` and `untrusted_head`.

## The trusted contract

**The base revision's contract is the trusted one.** `plumb-verify plan --base <sha>` reads
`.plumb/project.toml` from that commit (not from the worktree) and validates it with the parser
`plumb-project` uses. Every project command and the thresholds file are then taken from a worktree of
the base. A contract, procedure or thresholds file that the head changed is reported as a change under
test and never used: a head could otherwise rewrite `verify.up`, the procedure or the thresholds it is
judged by. The base itself is chosen without reading the head: the pull request's base branch, or
`origin`'s default branch, as `origin` has it.

**The head runs code, so it must be one the owner already trusts.** Starting the candidate executes
its build scripts and dependencies. `plan --head <sha>` refuses (`untrusted_head`) a head that is not
contained in a branch under `refs/remotes/origin/` (a fork's `refs/pull/N/head` is not) unless the
owner passes `--allow-untrusted-head`. Verification never runs in CI with secrets
(`pull_request_target`), and only in a disposable environment without production credentials.

## Project command interfaces

The contract's `[verify]` table names five things. Each command is one command line, run from a
worktree of the base ([the contract](project-contract.md)).

| Key | Interface |
|---|---|
| `lookup` | `lookup --base <sha> --head <sha>` prints JSON on stdout: `{features: [{id, distance, scenarios: [{id, repeat, auto_verify, draft, stateful, needs_ai}]}], unowned: [paths], skipped: [...]}` |
| `up` | `up --ref <sha> --label base\|pr [--role R]` prints, as its last stdout line, JSON `{ok, url, project, ...}`; progress goes to stderr. The labels are `base` and `pr` everywhere: rows, commands and output |
| `down` | `down --project <name>` or `down --all` |
| `scenarios` | A path to the project's procedure for writing and running one scenario and producing observation rows, or a command |
| `thresholds` | A path to the thresholds file above |

The scenarios, start command, fixtures, seeds, thresholds and browser measuring scripts stay in the
project. They move into plumb only when a second repository needs them.
