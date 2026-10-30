# Project contract, verification, work ledger and the improvement loop

Source: the SAKUJI-Platform agent-native work of 2026-10-28/29 (design
`docs/superpowers/specs/2026-10-24-agent-friendly-automerge-design.md` on that repository's branch
`chore/agent-friendly-automerge-design`). That work built a Feature Map, a verifier, a work ledger,
per-task cost records and a weekly improvement loop inside one product repository. About half of it
is not about that product. This spec moves the generic half into plumb and defines how a repository
hands plumb the facts plumb cannot know. Owner decisions of 2026-10-30: the three-layer split below
is accepted; plumb is the source of truth for the generic half; the SAKUJI pull requests that
carried generic tooling (#1644, #1645 and the unopened cost and loop branches) are not merged there.

## End state

Three layers, each with one owner and one way to change it.

| Layer | Holds | Lives in | Changed by |
|---|---|---|---|
| Harness (plumb) | How to work and how to judge, the same in every repository: playbooks, principles, skills, agents, generic tools | This repository, shipped as the plugin | A plumb release (semver, CHANGELOG, `check-harness`, `selftest`, evals). Reaches local and cloud sessions through plugin update |
| Project contract | What is true about one repository, and the deterministic checks that hold it: rules, CI gates, the feature map's data, how to start the app for verification, fixtures, thresholds, domain traps | The product repository, versioned with its code | A pull request there. A CI rule binds every contributor, so it is announced before it lands |
| Personal and environment | Where roles run, credentials, the cloud setup script | `~/.claude/plumb/config`, the cloud environment's settings | The owner |

A repository joins the harness by carrying `.plumb/project.toml`. Every plumb skill that needs a
project fact reads it through one command and degrades with a visible skip when a key is unset.

Afterwards a failure found anywhere — by the verifier, a reviewer, CI or production — is recorded
with one shared classification, triaged weekly to the layer that owns it, fixed there, and judged
by a number the ledger already prints.

## What is added

| Piece | What exists afterwards |
|---|---|
| A. Project contract | `.plumb/project.toml` schema (`docs/project-contract.md`); `plumb-project <key>` resolves a key like `plumb-config` does (unset returns empty, exit 0); `plumb-doctor` reports which contract keys are set and whether the commands they name exist |
| B. Rework link | `playbooks/opening-a-pr.md` writes a `Fixes-PR: none` / `Fixes-PR: #n[, #m]` line for the authors the contract names; `plumb-check-fixes` validates it (non-required authors always pass, the body is never parsed for them; no regex with nested quantifiers) |
| C. Work ledger | `plumb-ledger` builds one record per merged change from git history and pull-request metadata over REST (title, author, head ref, created/closed/merged times, the rework link, agent trailers from every commit the merge brought in), then a weekly rework summary scoped to the contract's authors. Change classification rules come from the contract, not from plumb |
| D. Cost per task | `plumb-ledger usage` reads transcripts **per request**: deduplicated by `requestId`, priced per request from a versioned price table (the version in effect at the request's time, long-context tiers decided per request), attributed to a task by the branch resolved for that request (a worktree subagent resolves from its `worktreePath`), kept at six decimals. Cloud sessions export their requests before they end (see "Decisions"). The weekly report shows cost by task, model, frontier share, role and token kind, and the cost of changes later fixed |
| E. Improvement loop | `plumb:retro` (weekly: ledger + cost + failures → at most three improvement proposals, each naming the layer it changes and the number that will show whether it worked); `plumb:failure-to-rule` (one failure → the highest layer that can stop it, a way to measure it, and a draft change; a project CI rule is proposed, never landed, by the skill); `docs/failure-taxonomy.md` (C01–C15, kinds, categories, where each layer's fix goes) |
| F. Verification | `plumb:verify` and the `verifier` agent: pick the affected features from the diff through the contract's lookup command, start base and candidate through the contract's start command, drive the contract's scenarios, compare base against candidate with a deterministic comparator, record runs in one schema, and **only ever report failures** — a clean comparison is "no regression found", never "passed". The comparator, the run-record schema and the refute-only rule are plumb's; the scenarios, the app start, fixtures, thresholds and traps are the project's |
| G. Cloud bootstrap | `docs/cloud-setup.md` and `plumb-bootstrap`: the lines a cloud environment's setup script runs to install the plugin, write `~/.claude/plumb/config` from the environment, check the judge's login, and run `plumb-doctor`; verified in a real cloud session |

## What is merged

- The SAKUJI cost tools (`usage.mjs`, `week.mjs`, `prices.json`) are rewritten into `plumb-ledger`
  in Python on top of `scripts/session-audit.py`'s transcript reader. One transcript reader, one
  price table.
- The claude.ai-synced `graph-engineering` skill duplicates `plumb:graph`. `plumb:graph` stays;
  the synced copy is retired by the owner.
- superpowers in a product repository is replaced by plumb for the owner's sessions; whether the
  repository itself drops superpowers stays that repository's decision (its other contributors).

## What is cut

Nothing is deleted on suspicion (**principle-subtract-before-you-add** cuts what is measured as
unused). This lap produces an inventory with evidence for each candidate, and cuts only what the
evidence supports:

- flows that cannot run in a cloud session (a visible pane through `pane.driver`, `gh-stack`) stay,
  but their cloud fallback must be the default path the docs describe first;
- lineage text in `docs/scope.md` and `docs/path-map.md` that no playbook reads to make a decision.

## Decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| 1 | Cloud cost export stores **per-request records** (request id, time, model, token kinds, resolved branch, role, agent id) on a dedicated orphan branch of the product repository (`plumb-ledger`, one file per session), written by `plumb-ledger usage --export` at the end of a cloud session | Exact deduplication by request id across local and cloud copies, forks and re-exports. The SAKUJI prototype stored aggregated rows in the PR body and needed five review rounds of reconciliation heuristics, each closing one double-count and exposing the next (the identity of a row changed with worktree cleanup, metadata loss, branch filtering) | Aggregated rows in the PR body (identity is lost; 65,536-character body limit). The untracked `.plumb/run/` (gone with the cloud container). An external store (a new service and credential) |
| 2 | Agent frontmatter still pins no model (harness rule 12). The explorer tier is reached through `role.explorer.model`; a personal override of the built-in `Explore` with a pinned model is the owner's own file, not a plumb asset | Keeps one place for model placement | Shipping a model-pinned `Explore` override in plumb |
| 3 | The project contract is a single TOML file read by a command; skills never parse it themselves | One parser, one place to evolve the schema; Python 3.11+ `tomllib` is in the standard library, and on an older Python `plumb-project` reports `--` with the reason, as `check-harness.sh` already does for its TOML checks | YAML (needs a parser plumb does not ship); keys spread over several files |
| 4 | The verifier's comparator and run schema are plumb's; the measuring browser scripts start in the project (SAKUJI's `scripts/feature-map/`) and move to plumb only after a second repository needs them | The first consumer defines the shape; moving it earlier would freeze one product's assumptions | Moving the browser harness now |

## Acceptance criteria

- A: `plumb-project` resolves set, unset and malformed keys like `plumb-config`; `plumb-doctor`
  prints the contract section with `--` for unset keys and `NG` only for a named command that is
  missing; selftest covers a repository with no contract, a partial one and a full one.
- B: `plumb-check-fixes` passes every body for a non-required author without reading it, fails a
  required author's missing or malformed line, and handles a multi-megabyte body in linear time;
  selftest covers each.
- C: on a fixture repository, merge commits contribute the trailers of the commits they brought in;
  date-only bounds start at midnight in the configured time zone; non-ASCII paths classify; output
  piped through a pager arrives complete; direct commits are reported, not counted as changes.
- D: per-request pricing (including a long-context request next to a short one), version switch by
  time, day boundary in the configured time zone, a $0.004 request surviving, worktree branch
  resolution with and without the worktree, export → re-read → no double count across local and
  cloud copies and forks; the weekly report on a fixture equals the hand-computed totals.
- E: `plumb:retro` and `plumb:failure-to-rule` stop with a visible reason when the ledger tools or
  the contract keys they need are missing; the taxonomy lists C01–C15 once and both skills cite it
  instead of restating the range.
- F: `plumb:verify` never emits a pass; the comparator returns regressed / incomplete / no_diff from
  fixtures; the verifier runs against SAKUJI's contract once end to end (base and candidate up,
  one feature, no_diff) and the run record validates against the schema.
- G: a fresh cloud session whose setup script contains only the documented lines has plumb loaded,
  `plumb-doctor` reports the routed judge, and the session's first `plumb:verify` dry run finds the
  contract.
- Every lap: `bash scripts/check-harness.sh`, `bash scripts/selftest.sh`, the plugin validator, and a
  judge pass in a different model family; CHANGELOG and version bumped.

## Order

Each lap is one pull request that leaves the harness working.

1. A + B — the contract and the rework link (everything else reads the contract).
2. C + D — ledger and cost per task.
3. E — the loop (needs C and D).
4. F — verification (needs A; SAKUJI is the first consumer).
5. G and the cut/merge inventory.

## Human gates and boundaries

- The owner merges every plumb pull request; nothing lands on `main` directly.
- A product repository's CI rule, its `.plumb/project.toml`, and the orphan `plumb-ledger` branch are
  created in that repository by a pull request or by the owner, never silently by a skill.
- No credential, transcript body or tool output leaves the machine; the ledger records usage
  metadata only.
- Prices are re-checked against the provider's published price list on the day a version is added.

## Inputs carried over from SAKUJI (open findings to close here, not there)

- Cost reconciliation double counts found by review (worktree cleanup changes a row's identity;
  missing subagent metadata changes its role; branch-filtered exports overlap) — closed by
  decision 1, not by more heuristics.
- `ledger-review` must count failures created in the period even when updated after it.
- The main session writing in another worktree with `git -C` is attributed to the main checkout's
  branch (SAKUJI U12) — the playbooks route such writes through a worktree subagent, or `cd` first.
