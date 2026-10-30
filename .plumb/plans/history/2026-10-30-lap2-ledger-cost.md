> **This is history. Do not execute it.**
> The current source of truth is `.plumb/specs/project-contract-and-improvement-loop.md`. **If this document disagrees with it, the source of
> truth wins.** Do not sync this back up — syncing it revives the second source of truth.

# Lap 2 — work ledger (C) and cost per task (D)

Spec: `.plumb/specs/project-contract-and-improvement-loop.md` §C, §D, acceptance C and D, decision 1.
Base: `feat/project-contract-and-loop` (lap 1, not yet merged). Release: 0.15.0.

## Facts measured before planning (2026-10-30)

- Claude transcripts write one assistant record **per content block**; the copies share
  `message.id` and `usage`. In this session's main transcript 917 assistant records hold 388
  distinct `message.id` values (up to 39 copies each).
- **`requestId` is often absent.** 248 of those 917 records carry it; every record carries
  `message.id`. The spec's `claude:<requestId>` therefore becomes: `claude:<requestId>` when
  present, else `claude:<message.id>`. Both survive a forked or copied transcript, so the spec's
  "copies count once" holds. Recorded as a spec amendment in this lap.
- `gitBranch` is `HEAD` when `cwd` is not on a branch (or not a repository). Treat `HEAD` and an
  empty value as no branch.
- Subagents live at `<project-slug>/<session>/subagents/agent-<id>.jsonl` with
  `agent-<id>.meta.json` beside it. A worktree subagent's meta has `worktreePath`,
  `worktreeBranch`, `spawnedWithWorktree: true`; its records carry `isSidechain: true`, `agentId`,
  and a `cwd` inside the worktree — but `gitBranch` may describe the parent.
- `usage` has `input_tokens`, `output_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens` and `cache_creation.{ephemeral_5m_input_tokens,
  ephemeral_1h_input_tokens}`.
- Prices (Claude API list, checked 2026-10-30, USD per million tokens):
  Fable 5.1 `claude-fable-5-1` 10 / 50, cache read 0.25; Opus 5.5 `claude-opus-5-5` 4 / 20, cache
  read 0.20; Sonnet 5.5 `claude-sonnet-5-5` 2 / 10, cache read 0.20; Haiku 5.5 `claude-haiku-5-5`
  0.10 / 0.50, cache read 0.01, and 0.50 / 2.50 (cache read 0.05) when the request's input exceeds
  100,000 tokens. Cache writes are 1.25× input (5 minutes) and 2× input (1 hour).

## Split

Two independent modules behind one dispatcher (`scripts/ledger.py`, `bin/plumb-ledger`, already
written). Each lane owns only its own files; the coordinator wires selftest, docs, CHANGELOG and the
release.

| Lane | Owns | Must not touch |
|---|---|---|
| L1 changes | `scripts/ledger_changes.py`, `scripts/test-ledger-changes.py`, fixtures under `scripts/fixtures/ledger-changes/` | everything else |
| L2 cost | `scripts/ledger_cost.py`, `scripts/ledger-capture.sh`, `assets/prices.json`, `hooks/hooks.json`, the `ledger` block in `scripts/doctor.sh`, `scripts/test-ledger-cost.py`, fixtures under `scripts/fixtures/ledger-cost/` | everything else |

Shared rules for both lanes: standard library only; Python 3.9+ syntax except where the contract
needs `tomllib` (read the contract only through `plumb-project`, never parse it yourself); GitHub
only through `gh api` (REST, `--paginate`), never GraphQL; an injectable fixture directory for every
network call so tests run offline; every number that cannot be known is `null` and counted, never
zero; full precision in sums (`decimal.Decimal`), rounding only on display; no transcript body, tool
output or credential is ever written to a record. Tests are a standalone script that prints one
`ok`/`NG` line per case and exits non-zero on any NG, like `scripts/test-skill-evals.py`.

## L1 — `plumb-ledger changes` and `plumb-ledger rework`

`changes --repo <owner/name> --since <date> --until <date> [--base <branch>] [--out <jsonl>]`
(dates are calendar days in `ledger.timezone` from the contract, default UTC; `--until` inclusive).

1. Landed pull requests: `repos/{repo}/pulls?state=closed&base=<base>&sort=updated&direction=desc`
   paginated, keep `merged_at` within the period. Base defaults to `repo.base_branch`, else the
   repository's default branch (`repos/{repo}` → `default_branch`).
2. Per pull request, `repos/{repo}/pulls/{n}/commits` paginated (at most 250 returned). Attribution
   from those commits' messages: `Co-Authored-By:` trailers, `Claude-Session:` / session links, and
   the agent named in each (claude, codex, cursor, other). Compare the count read with the pull
   request's `commits` field; when they differ, mark `attribution: "incomplete"` and add the landed
   history as a second source (`git log` of the merge commit's second parent range for a merge, the
   landed commit's own message for a squash or rebase). `sources` lists what was used.
3. Files: `repos/{repo}/pulls/{n}/files` paginated; classes from the contract's `ledger.classify`
   rules (first matching glob per file; a change's classes are the sorted set). No rules: the change
   is `unclassified` and the summary line says the contract has no classify rules.
4. `Fixes-PR` parsed from the body with the same grammar as `scripts/check-fixes.py` — import its
   parser, do not copy it. A malformed line is recorded as `fixes_pr_error`, not dropped.
5. Direct commits: first-parent commits on the base branch in the period that no pull request
   landed. Use the local clone. If the clone is shallow and cannot reach the period's start, exit 2
   with the `git fetch --deepen=<n>` (or `--shallow-since`) needed; never truncate silently.
6. Record (one JSON object per line): `kind` (`pull_request` | `direct`), `number`, `author`,
   `merged_at`, `merge_commit`, `landing` (`merge` | `squash` | `rebase`, from the merge commit's
   parent count and whether the PR's commits are in first-parent history), `head_ref`,
   `created_at`, `closed_at`, `classes`, `agents`, `attribution` (`complete` | `incomplete`),
   `sources`, `fixes_pr` (list of numbers, `[]` for `none`, `null` when absent), `fixes_pr_error`.

`rework --changes <jsonl> --since --until [--lookahead-days N] [--json]`:
cohort = `pull_request` records whose author is in `rework.required_authors` (case-insensitive)
and that landed in the period. A cohort change is reworked when any later change (any author) lists
it in `fixes_pr` and landed within the look-ahead window (default `rework.lookahead_days`, else 7)
after it. A change whose window has not closed by now and is not yet reworked is `pending`, not clean.
A fix listing several originals counts for each. Direct commits are reported separately, never in the
cohort. Output: cohort size, reworked, clean, pending, rate = reworked / (reworked + clean) (pending
excluded, stated), the reworked list with the fixing PR, and the share of cohort changes whose body
had a readable `Fixes-PR` line.

Acceptance (spec C), all offline from fixtures: merge, squash and rebase landings each yield the
trailers of the pull request's own commits; a commit count mismatch marks attribution incomplete
and lists both sources; pagination exercised with more than one page; a shallow clone short of the
period exits 2 naming the depth; the rework rate on a fixture with a pending window, a fix outside
the period and a fix listing two originals equals the hand-computed value written in the test.

## L2 — capture, price, store, export, task assignment, report

**Capture.** `hooks/hooks.json` registers a `Stop` hook running
`bash "${CLAUDE_PLUGIN_ROOT}/scripts/ledger-capture.sh"`. The shell script reads `ledger.capture`
through `scripts/plumb-config.sh` and exits 0 before starting Python unless it is `on`. When on, it
saves stdin (the hook JSON: `session_id`, `transcript_path`, `cwd`) to a temporary file and starts
`python3 scripts/ledger.py capture --hook-input <file>` in the background (`nohup … &`, output to a
log under the run root), then exits 0. The hook never fails a turn.

`capture` (also runnable by hand: `--transcript <path>` | `--hook-input <file>`, `--runtime codex
--transcripts <dir>` for Codex): reads the main transcript and its `subagents/agent-*.jsonl` from a
saved byte offset per file (state under `plumb-path run` of the session's checkout, or
`~/.claude/plumb/ledger/` when `cwd` is not a repository), only complete lines, and appends one
record per new request to `<store-dir>/pending/<runtime>/<session>.jsonl`. Identity:
`claude:<requestId>` else `claude:<message.id>`; Codex `codex:<session>:<n>`; no id → kept with
`id: null`, counted as unidentified, never merged. Copies with one id count once; copies whose usage
differs are kept once and reported as a conflict. Attribution, in order: the record's own `cwd`
resolves to a checkout and `gitBranch` is a real branch of that checkout and the record is not a
sidechain → that branch, `attribution_source: "transcript"`; a sidechain whose meta has
`worktreePath` → that worktree's current HEAD branch at capture time,
`attribution_source: "worktree_at_capture"` (a removed worktree or detached HEAD → `unknown`);
otherwise `unknown`. Never infer a past branch from today's main checkout. Repository: the
checkout's `origin` URL normalised to `owner/name`. Role: `main` or `subagent`, plus `agent_type`
from meta and `agent_id`. Fields kept (the allowlist that may leave the machine): `id`, `time`,
`model`, `input`, `output`, `cache_read`, `cache_write_5m`, `cache_write_1h`, `repository`,
`branch`, `attribution_source`, `role`, `agent_type`, `agent_id`, `session`, `runtime`.
`scripts/session-audit.py` stays unchanged: its existing fixtures must give byte-identical output.

**Price.** `assets/prices.json`: versions with `id`, `effective_from` (UTC), `source`, `checked`
(date) and per-model rates, including `long_context: {threshold_input_tokens, …}`; the tier is
decided per request on input + cache read + cache write tokens. Each request priced with the version
in effect at its time. Unknown model or missing token counts → cost `null`, counted. `Decimal` sums.

**Store and export.** `ledger.store` in the personal config is a git URL. `export [--session <id>]`:
non-interactive (`GIT_TERMINAL_PROMPT=0`), preflight `git ls-remote <store>`; for each pending
session builds a commit holding that session's records (sorted, allowlisted fields only) with a
fixed author, committer and date derived from the content, so the same records give the same commit,
and pushes it to `refs/plumb-ledger/<runtime>/<session>` with a `+` refspec (each session owns its
ref; a re-push is a no-op). Success moves the session from pending to exported locally; failure
keeps it pending and exits non-zero. Unset store: exit 0 with a line that records stay local and
cloud sessions are not covered. Credentials come from git's own helper for that URL; never print
them.

**Task assignment.** `prs --repo <owner/name> --since <date> [--out <json>]`: all pull requests
(`state=all`) with `number`, `head_ref`, `base_ref`, `created_at`, `closed_at`. A task is
(repository, head ref, PR number). Among pull requests of the same repository and head ref sorted by
creation time, a request belongs to the first whose close time (or now, if open) is at or after the
request's time. Two open pull requests with that head ref → `ambiguous`; none → `no pull request`.

**Report.** `report --since --until [--prs <json>] [--changes <jsonl>] [--rework <json>]
[--store-cache <dir>]`: reads local records plus the store's refs (`git fetch <store>
'+refs/plumb-ledger/*:refs/plumb-ledger/*'` into a cache repository) and prints: total cost, cost by
task (top 10), by model, frontier share (fable, mythos and opus models), by role and agent type, by
token kind; cost of reworked changes when `--rework` is given; counts of unknown cost, unknown
attribution, ambiguous and no-pull-request requests, unidentified requests and id conflicts;
coverage (pending exports, store unset).

**Doctor.** A `ledger` block: capture on or off; store unset (`--`) or the preflight result
(`ok` / `NG <reason>` without the URL's credentials).

Acceptance (spec D), offline from fixtures: a branch switch inside one turn attributes each request
to its own branch; a worktree subagent gets its worktree's branch; a removed worktree and a detached
HEAD give `unknown`; task assignment for work before the PR, a reused branch and two open PRs gives
the PR, the later PR and `ambiguous`; a forked transcript counts shared requests once; Codex ids from
two sessions never merge; an id conflict is reported; unknown model and missing tokens give unknown
cost, counted; 10,000 requests of $0.0001 sum to $1.00 before rounding; two sessions exporting
concurrently to a local bare repository both land; a repeated export is a no-op (same commit); an
export with an unreachable store exits non-zero and keeps the records pending, and the report shows
incomplete coverage; capture off returns in under 50 ms without starting Python; capture on adds
under 200 ms at p95 to the hook (the background spawn) on a 50 MB transcript, and a second capture
reads only the new bytes; session-audit output on its existing fixtures is byte-identical.

## Coordinator (after both lanes)

Wire both test scripts into `scripts/selftest.sh`; `docs/ledger.md` (commands, record fields, the
allowlist, the store, coverage); `SKILL.md` router and `docs/artifact-lifecycle.md` entries;
`plumb-config.sh` header lines for `ledger.capture` and `ledger.store`; the spec amendment (identity
falls back to `message.id`); CHANGELOG 0.15.0, `docs/releases/v0.15.0.md`, both `plugin.json`;
check-harness, selftest, `claude plugin validate .`; the cross-family judge on the diff.
