# Project contract, verification, work ledger and the improvement loop

Source: the SAKUJI-Platform agent-native work of 2026-10-28/29 (design
`docs/superpowers/specs/2026-10-24-agent-friendly-automerge-design.md` on that repository's branch
`chore/agent-friendly-automerge-design`). That work built a Feature Map, a verifier, a work ledger,
per-task cost records and a weekly improvement loop inside one product repository. About half of it
is not about that product. This spec moves the generic half into plumb and defines how a repository
hands plumb the facts plumb cannot know.

Owner decisions of 2026-10-30: the three-layer split below is accepted; plumb is the source of truth
for the generic half; the SAKUJI pull requests that carried generic tooling (#1644, #1645 and the
unopened cost and loop branches) are not merged there.

Revision 3 (2026-10-30) answers the second judge pass: the CI must fail on an invalid or unreadable contract (`--enforce`), the pull-request number is required for self-reference, capture is opt-in and budgeted, export failures are defined, request-to-task assignment is unique, attribution uses the transcript's per-request branch where it is valid, and the 250-commit limit is reconciled.

Revision 2 (2026-10-30) answers an independent judge pass (Codex, read-only) that found 14 issues:
undefined invalid-contract behavior, contract path policy, untrusted rework-policy input, a shared
push target and repository-policy exposure for cost export, privacy and clone growth, request
identity the existing reader drops, attribution inferred after the fact, merge histories the ledger
would miss, an undefined failure input, verifier negative controls, missing release gates, taxonomy
portability, and inventory order.

## End state

Three layers, each with one owner and one way to change it.

| Layer | Holds | Lives in | Changed by |
|---|---|---|---|
| Harness (plumb) | How to work and how to judge, the same in every repository: playbooks, principles, skills, agents, generic tools and their record formats | This repository, shipped as the plugin | A plumb release (semver, CHANGELOG, `check-harness`, `selftest`, evals, both manifests validated). Reaches local and cloud sessions through plugin update |
| Project contract | What is true about one repository and the deterministic checks that hold it: rules, CI gates, feature data, how to start the app for verification, fixtures, thresholds, domain traps, product-specific failure codes | The product repository, versioned with its code | A pull request there. A CI rule binds every contributor, so it is announced before it lands |
| Personal and environment | Where roles run, credentials, the cost store, the cloud setup script | `~/.claude/plumb/config`, the cloud environment's settings | The owner |

A failure is fixed in **the layer that owns the invariant it broke**, not in whichever layer could
enforce it. A product rule is not promoted into plumb because plumb could check it.

## What is added

### A. Project contract

- One tracked file per repository: `<git top-level of the current worktree>/.plumb/project.toml`.
  It is **not** moved by `PLUMB_ROOT` or `.plumb/config root=` — those move run artifacts, and a
  contract that follows an override would stop being the repository's. The only resolver is
  `plumb-path project` (a new kind); nothing else assembles the path. Linked worktrees read their
  own checkout's file.
- Minimum schema (`docs/project-contract.md`): `schema = 1`, `[repo] base_branch`, `[rework]
  required_authors` (array of logins), `[ledger] classify` (ordered path-glob → class rules),
  `[verify] lookup`, `[verify] up`, `[verify] down`, `[verify] scenarios` (commands or paths),
  `[failure] extra_codes`. Unknown keys are reported, not rejected.
- `plumb-project <key>` and `plumb-project --json` return one of four outcomes, distinguishable by
  exit status and in JSON: **absent** (no file, or key unset — empty, exit 0), **set** (value, exit 0),
  **invalid** (parse error, wrong type, unsupported `schema` — message, exit 2), **unavailable**
  (no `tomllib`, Python < 3.11 — message, exit 3). Optional workflow steps may skip on absent or
  unavailable with a visible `skip:` line; nothing may treat invalid as absent.
- `plumb-project --enforce <key>` is the only form a CI may use: no contract file → empty, exit 0
  (the repository has opted out); file present but **invalid or unavailable → exit non-zero**, so the
  required job fails instead of enforcing nothing. An enforcing CI runs Python 3.11+.
- `plumb-doctor` prints a contract section: `--` for absent keys, `NG` for invalid content or a
  named command that does not resolve, `ok` otherwise.

### B. Rework link

- `playbooks/opening-a-pr.md` writes exactly one `Fixes-PR:` line when the author is required:
  `Fixes-PR: none`, or `Fixes-PR: #<n>` with further `, #<n>` items. Duplicates, a self-reference
  and a second line are errors.
- `plumb-check-fixes --author <login> --required-authors <list> --pr <n> --body-file <f>`:
  a non-required author passes without the body being read; a required author fails on a missing,
  duplicate, malformed or self-referencing line; a missing `--author` or `--pr` with a non-empty
  requirement fails (self-reference cannot be checked without the event's pull-request number).
  The checker never reads policy itself.
- **Trusted input:** a CI that enforces the line passes the policy and the author from sources the
  pull request cannot change — a repository variable or the base commit's contract, and the event's
  author. Reading the policy from the proposed branch is documented as wrong (the branch could
  remove its own author). `docs/project-contract.md` shows both wirings.

### C. Work ledger

- `plumb-ledger changes` builds one record per landed change. Attribution (agent trailers,
  co-authors, session links) comes from the pull request's own commits over REST
  (`/pulls/{n}/commits`, paginated), so squash and rebase merges keep it. That endpoint returns at
  most 250 commits: the record compares the count it read with the pull request's `commits` field,
  and when they differ it marks attribution `incomplete` and adds landed history as a second source.
  The record always says which sources it used. A shallow clone that cannot reach the
  requested period fails with the depth it needs; nothing is silently truncated.
- Classification uses the contract's `[ledger] classify` rules; with none set, every change is
  `unclassified` and the summary says so.
- `plumb-ledger rework` defines the rate once: the cohort is changes by the contract's
  `required_authors` that landed in the period; a change counts as reworked when any later change
  (any author) lists it in `Fixes-PR` within the look-ahead window (default 7 days). Changes whose
  window has not closed are reported as pending, not as clean. One fix that lists several originals
  counts for each. Direct commits are reported separately and never enter the cohort.

### D. Cost per task

- **Capture at the event, opt-in and cheap.** Capture is off unless `ledger.capture = on` in the
  personal config. When on, a plumb `Stop` hook (`plumb-ledger capture`) runs in the background,
  reads each transcript incrementally from a saved byte offset, makes no network call, and appends
  the requests new since the last capture. When off, the hook returns before starting Python (a shell
  check of the config). Attribution per request, in order of evidence: the request's own `cwd` and
  `gitBranch` from the transcript when its `cwd` is the checkout that field describes; for a worktree
  subagent (whose `gitBranch` describes the parent), the `worktreePath`'s HEAD at capture time,
  marked `attribution_source = worktree_at_capture`; otherwise `unknown`. Later reads never infer a
  past branch from today's checkout. plumb ships no hook today; this is the first, and its cost is a
  release gate (below).
- **Identity.** Request ids are runtime-qualified. Claude ids are `claude:<message.id>`, because
  `requestId` is absent on many records and mixing the two keys double-counts; Codex ids are
  synthetic per session and become `codex:<session>:<n>`, never deduplicated across sessions. A request without an
  id is kept, counted as unidentified, and never merged with another. Copies of one request in a
  forked or copied transcript share the Claude id and count once; conflicting copies of one id are
  reported. `scripts/session-audit.py`'s existing audit output is unchanged; the reader gains the
  fields, it does not change what the audit prints.
- **Price.** A versioned price table; each request is priced with the version in effect at its time,
  with long-context tiers decided per request. An unknown model or missing token counts makes that
  request's cost unknown (counted and shown), never zero. Sums use full precision; only display
  rounds.
- **Store (personal layer).** Captured records are pushed to a private repository the owner names in
  `~/.claude/plumb/config` (`ledger.store`), one ref per session
  (`refs/plumb-ledger/<runtime>/<session>`), so parallel sessions never share a push target and a
  re-push of the same session is idempotent (a lost acknowledgement is retried with the same commit).
  The product repository is never written. Only allowlisted fields leave the machine (request id,
  time, model, token kinds, cost version, repository, branch, role, agent id); the owner opts in by
  setting the key; retention is the store's. Unset store: records stay local under the run root and
  the report says cloud sessions are not covered.
- **Export is separate from capture** (`plumb-ledger export`, run explicitly, at the end of a cloud
  session's setup-defined teardown, or by the owner). It is non-interactive (`GIT_TERMINAL_PROMPT=0`),
  authenticates with the git credential for the store's URL (in a cloud session, the token the setup
  script provisions for that repository; the product repository's token is never assumed to reach
  it), and runs a preflight (`git ls-remote`) that `plumb-doctor` and `plumb-bootstrap` also run. A
  failed or denied push keeps the records pending locally, exits non-zero, and the weekly report shows
  coverage as incomplete with the pending count.
- **Task.** A task is (repository, head ref, pull-request number). Assignment is unique: among pull
  requests of the same repository and head ref, sorted by creation time, a request belongs to the
  first whose close time (or now, if open) is at or after the request's time — so work before a pull
  request is opened belongs to it, and a reused branch name sends later work to the later pull
  request. Two open pull requests with that head ref (different bases) make the request
  `ambiguous`; no match makes it `no pull request`. Both are reported, never guessed.
- The weekly report: cost by task, model, frontier share, role and token kind; cost of reworked
  changes; unknown-cost and unknown-attribution counts.

### E. Improvement loop

- **Failure record.** `docs/failure-taxonomy.md` defines the record: a GitHub issue or pull request
  labelled `agent-failure` whose body carries one `<!-- plumb-failure v1 {...} -->` block
  (`code`, `kind`, `category`, `layer`, `evidence`, `origin` — the change that introduced it), or a
  `findings.jsonl` line written by `plumb:verify`. The record's id is the issue number or the finding
  id. Collection is REST, paginated, and includes records **created** in the period even when updated
  after it.
- **Taxonomy.** C01–C15 are defined by a repository-independent failure mechanism each; a product's
  own codes go in the contract's `[failure] extra_codes`. Both skills cite the taxonomy; neither
  restates the range.
- `plumb:retro` aggregates (ledger, rework, cost, failures) and proposes at most three changes, each
  naming the owning layer and the number that will show whether it worked. Experiments and adoption
  reuse `playbooks/hillclimb.md`, `playbooks/evaluating-an-agent.md` and `plumb-decision-log`; retro
  does not grow its own experiment machinery.
- `plumb:failure-to-rule` takes one failure record to the owning layer, a measurement, and a draft
  change. A project CI rule is proposed, never landed, by the skill.

### F. Verification

- **Observation protocol** (`docs/verify-protocol.md`): one normalized record per scenario × role ×
  side — status (`ok`, `start_failed`, `scenario_failed`, `not_run`), metric values with units,
  repeat counts, artifact references. The project's scenarios produce it; plumb never interprets a
  product screen.
- **Comparator** (plumb): base against candidate, deterministic, thresholds from the contract.
  Outcomes: `regressed` (a metric worse beyond threshold), `incomplete` (missing observation,
  unmapped feature, start or scenario failure on either side, failure on both sides), `no_diff`.
  It never emits a pass; `no_diff` reads "no regression found".
- `plumb:verify` and a canonical `agents/verifier.md` (no pinned model, rule 12) drive the project's
  lookup, start and scenarios; the Codex adapter gets the matching native agent, and the
  check-harness agent-count invariant is updated deliberately.
- The scenarios, start command, fixtures, thresholds and traps stay in the project. The browser
  measuring scripts start in the first consumer (SAKUJI) and move into plumb only when a second
  repository needs them.

### G. Cloud bootstrap

- `docs/cloud-setup.md`: the lines a cloud environment's setup script runs — the existing marketplace
  install commands, writing `~/.claude/plumb/config` from environment variables, the judge's login
  check, `plumb-doctor`. `plumb-bootstrap` wraps those lines; it reuses the existing install paths
  (`claude plugin …`, `plumb-codex-install`) and adds no second installer.

## What is merged

- The SAKUJI cost and ledger prototypes (`usage.mjs`, `week.mjs`, `prices.json`, `collect.mjs`,
  `summarize.mjs`) are rewritten in Python as `plumb-ledger` on the transcript reader of
  `scripts/session-audit.py`. Their tests become selftest fixtures.
- The claude.ai-synced `graph-engineering` skill duplicates `plumb:graph`; `plumb:graph` stays and the
  owner retires the synced copy.
- superpowers in a product repository is replaced by plumb for the owner's sessions; whether the
  repository drops superpowers stays that repository's decision.

## What is cut

Lap 0 is an inventory with evidence (session-audit and trigger-eval counts, references from
playbooks) for each candidate, done before additions so it can remove work:

- flows that cannot run in a cloud session (`pane.driver` panes, `gh-stack`) stay, but the docs lead
  with their cloud fallback;
- lineage text that no decision reads. **The two gap rows in `docs/scope.md` stay** (that document
  forbids deleting them).

Nothing is deleted on suspicion.

**Lap 0 result (2026-10-30): nothing is cut.** Evidence, from `git grep` over the corpus:

- `pane.driver` appears in `skills/lead`, `skills/interrogate`, three playbooks, `docs/role-map.md`,
  doctor and selftest. Unset, `plumb:lead` already falls back to isolated subagents with
  `skip: pane.driver unset — lanes are not visible`; the cloud path is the unset path and works.
- `stack.tool` / `gh-stack` appears in `playbooks/landing-a-stack.md`, the role map, doctor and
  selftest; unset drops to "Land it with bare gh". Same conclusion.
- `docs/path-map.md` is read by `playbooks/session-pickup.md`, `opening-a-pr.md`, `worktree-setup.md`,
  `worktree-cleanup.md`, `scripts/worktree-audit.sh`, `scripts/prompt-weight.py` and `plumb:doctor`
  as the source of truth for transcript and worktree locations. Live, not lineage.
- `docs/scope.md` is cited by `SKILL.md` and `opening-a-pr.md` (the missing pixel-diff harness). Live.

What changes instead goes into G: `docs/cloud-setup.md` states that in a cloud session `pane.driver`
and `stack.tool` are unset by design and names the fallbacks above, so the cloud path is the one the
reader meets first.

## Decisions

| # | Decision | Why | Rejected |
|---|---|---|---|
| 1 | Cost records are captured per request at turn end with their attribution, and pushed to an owner-named private repository, one ref per session | Exact identity; no shared push target; product repository untouched; contributors who do not use plumb are unaffected; attribution is a fact recorded once | An orphan branch in the product repository (shared push target, rulesets and product hooks apply, clone growth for everyone, metadata exposure in a public repository); aggregated rows in the PR body (identity lost; the SAKUJI prototype needed five rounds of reconciliation and each fix exposed the next double count); `.plumb/run/` only (gone with the cloud container) |
| 2 | Agent frontmatter pins no model (rule 12); the explorer tier is `role.explorer.model`; a personal model-pinned override of the built-in `Explore` is the owner's file, not a plumb asset | One place for model placement | Shipping a pinned `Explore` override |
| 3 | The contract is one TOML file at the worktree's top level, resolved only by `plumb-path project`, read only by `plumb-project` | One resolver, one parser, one schema version | Following `PLUMB_ROOT` (the contract would stop being the repository's); YAML (no parser shipped); several files |
| 4 | Comparator, observation protocol and run schema are plumb's; browser scripts start in the first consumer | The first consumer defines the shape; moving it earlier freezes one product's assumptions | Moving the browser harness now |

## Acceptance criteria

- **A:** for each of absent / set / invalid (bad TOML, wrong type, unsupported schema) / unavailable,
  `plumb-project` returns the documented exit status and JSON outcome; `plumb-path project` resolves
  from a subdirectory and from a linked worktree, and ignores `PLUMB_ROOT`; doctor prints `--`, `NG`,
  `ok` as specified. Selftest covers every case.
- **B:** a non-required author passes with an unreadable body file; a required author fails on each of
  missing, second line, duplicate reference, self-reference, malformed item, missing `--author` and
  missing `--pr`; an integration fixture runs the documented base-commit wiring and the required job
  fails for an invalid contract and for an unavailable parser (`plumb-project --enforce`);
  a 5 MB adversarial body (`Fixes-PR: #1, #1, …` and long lines without a newline) completes in
  under 2 seconds on the CI image. The docs show the trusted wiring and name the wrong one.
- **C:** fixtures with a merge, a squash and a rebase landing each yield the trailers of the pull
  request's commits; a shallow clone short of the period fails with the needed depth; pagination is
  exercised with more than one page; the rework rate on a fixture with a pending window, a fix
  outside the period and a fix listing two originals equals the hand-computed value.
- **D:** capture records the transcript's own per-request branch where its `cwd` matches the
  described checkout (a branch switch inside one turn attributes each request correctly), a worktree
  subagent's branch from its worktree, and `unknown` after a removed worktree or a detached HEAD;
  task assignment on fixtures for work before the pull request, a reused branch and two open pull
  requests yields the stated pull request, the later one, and `ambiguous`; a forked transcript counts shared requests once; Codex
  synthetic ids from two sessions never merge; an id conflict is reported; unknown model and missing
  tokens produce unknown cost, counted; 10,000 requests of $0.0001 sum to $1.00 before rounding; two
  sessions pushing to the store concurrently both land; a repeated push of the same session is a
  no-op; an export with absent, expired and denied credentials exits non-zero, keeps the records
  pending and the report shows incomplete coverage; with capture off the hook returns in under 50 ms
  without starting Python, and with capture on it adds under 200 ms at p95 to a turn on a 50 MB
  transcript (incremental read); the existing session-audit output on the existing fixtures is
  byte-identical.
- **E:** a replayable fixture with failures created inside and updated after the period is counted;
  one populated example runs end to end — failure evidence → owning layer → proposed change →
  measurement — and both skills stop with a visible reason when a dependency is missing.
- **F:** on fixtures the comparator returns `regressed` for an injected metric regression,
  `incomplete` for each incomplete cause, `no_diff` otherwise, and never a pass; one live run against
  SAKUJI's contract detects a deliberately introduced regression through the whole path, and one
  live run with a failed start reports `incomplete`.
- **G:** a fresh cloud session whose setup script holds only the documented lines has plumb loaded,
  `plumb-doctor` reports the routed judge, and `plumb:verify --dry-run` finds the contract.
- **Every lap:** `bash scripts/check-harness.sh`; `bash scripts/selftest.sh`; both
  `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` pass their validators; `.codex/config.toml`
  passes `codex --strict-config` when the sidecar changed; a judge pass in a different model family,
  or a visibly unmet release gate (a Sol/Luna pass does not meet it); CHANGELOG and version bumped.

## Order

Each lap is one pull request that leaves the harness working.

0. Inventory — what to cut or lead with its cloud fallback, with evidence.
1. A + B — contract and rework link.
2. C + D — ledger and cost per task (needs A for classification and authors).
3. E — the loop (needs C and D; review and CI already supply failures, so it does not wait for F).
4. F — verification (needs A; SAKUJI is the first consumer).
5. G — cloud bootstrap.

## Human gates and boundaries

- The owner merges every plumb pull request; nothing lands on `main` directly.
- A product repository's CI rule and its `.plumb/project.toml` arrive there by pull request.
- The cost store is opt-in, owner-named and private; plumb writes nothing to a product repository.
- No credential, transcript body or tool output leaves the machine.
- Prices are re-checked against the provider's published list on the day a version is added.

## Inputs carried over from SAKUJI (closed here, not there)

- Cost reconciliation double counts found by review — closed by decision 1, not by more heuristics.
- Failures created in the period but updated after it — criterion E.
- The main session writing in another worktree with `git -C` is attributed to the main checkout
  (SAKUJI U12). Capture does not fix this: such a request really runs in the main checkout's
  directory. The playbooks route writes for another task through a worktree subagent, or `cd` into
  the worktree first, so the request's own directory is the task's.
