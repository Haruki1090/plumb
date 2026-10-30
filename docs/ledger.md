# Work ledger and cost per task

`plumb-ledger` answers two questions with numbers: **which landed changes were fixed later** (the
rework rate), and **what each task cost, on which models** (cost per task). The spec is §C and §D of
`.plumb/specs/project-contract-and-improvement-loop.md`. Repository facts (who is in the cohort,
the classification rules, the time zone) come from the project contract through `plumb-project`
(`docs/project-contract.md`); personal settings come from `~/.claude/plumb/config`.

GitHub is read only through `gh api` REST. Lists are requested page by page (`page=N`), never with
`--paginate`: that follows `Link` headers naming `repositories/{id}/...` paths, which a cloud
session's proxy refuses (HTTP 403).

## Landed changes and the rework rate

```bash
plumb-ledger changes --repo <owner/name> --since <day> --until <day> [--base <branch>] [--clone <dir>] [--out <jsonl>]
plumb-ledger rework  --changes <jsonl> --since <day> --until <day> [--lookahead-days <n>] [--json]
```

Days are calendar days in `ledger.timezone` (default UTC); `--until` is inclusive. `changes` writes
one JSON record per landed change and a summary on stderr.

| Field | Meaning |
|---|---|
| `kind` | `pull_request`, or `direct` for a first-parent commit on the base that no pull request landed |
| `repository`, `number`, `author` | The pull request (a direct commit has the git author name and no number) |
| `merged_at`, `merge_commit`, `landing` | When and how it landed: `merge`, `squash`, `rebase`, or `null` when it cannot be told |
| `head_ref`, `created_at`, `closed_at` | For task assignment |
| `classes` | Sorted set of `ledger.classify` classes of its files; `unclassified` when no rule matched or none are set |
| `agents`, `co_authors`, `sessions` | Attribution from the pull request's own commits (`Co-Authored-By:`, session links) |
| `attribution`, `sources` | `complete`, or `incomplete` when the REST commit list was cut short (250); `sources` names `pulls_commits` and, if used, `landed_history` |
| `fixes_pr`, `fixes_pr_error` | The `Fixes-PR:` line, parsed by `plumb-check-fixes`'s grammar: a list, `[]` for `none`, `null` when absent; a malformed line is kept as the error |

Classification globs match the whole repository-relative path: `*` and `?` stop at `/`, `**`
crosses directories, `**/` may match no directory, and the first matching rule wins per file.

A shallow clone that cannot reach the period's start exits 2 with the `git fetch --shallow-since`
it needs. An invalid contract exits 2 and a missing parser exits 3; neither is read as "no policy".

**The rate.** The cohort is pull requests by `rework.required_authors` that landed in the period.
One counts as reworked when a later pull request (any author) lists it in `Fixes-PR` and landed
within the look-ahead window (`rework.lookahead_days`, default 7). `Fixes-PR: #n` names a pull
request of the fixer's own repository, so a fix counts only for originals of the same `repository`
(a record with no repository matches only records with none). A change whose window is still
open and has no fix yet is **pending**, not clean, and the rate (reworked ÷ (reworked + clean)) leaves
it out. A fix listing several originals counts for each. Direct commits are counted separately and
never enter the cohort. `--json` prints `reworked` (the count) and `reworked_changes` (the rows).

## Cost per task

### Capture (opt-in)

Set `ledger.capture = on` in `~/.claude/plumb/config`. plumb's `Stop` hook (`hooks/hooks.json` →
`scripts/ledger-capture.sh`) then records, at the end of each turn and in the background, every
request that is new since the last capture. With capture off the hook checks the config in the
shell and returns without starting Python (about 10 ms). With it on, the hook only spawns the work
(p95 under 30 ms on a 52 MB transcript) and each capture reads only the bytes appended since the
saved offset. The hook never fails a turn. By hand: `plumb-ledger capture --transcript <path>` or,
for Codex, `--runtime codex --transcripts <dir>`.

Records live in `~/.claude/plumb/ledger` (or `PLUMB_LEDGER_DIR`) for every repository; each carries
its repository. Nothing is written under a product repository.

**Identity.** Claude `claude:<message.id>`, because `requestId` is absent on many records and mixing
the two keys double-counts; Codex `codex:<session>:<n>`, never merged across sessions. The copies of
one request (one per content block, or in a forked transcript) count once. Copies whose usage differs are kept
once and reported as conflicts. A request with no id is kept and counted as unidentified; identical unidentified rows are separate requests and all of them are exported and counted.

**Attribution**, in order of evidence: the record's own `cwd` and `gitBranch` when that branch
exists in that checkout (`transcript`); for a subagent that ran in its own worktree, that
worktree's HEAD branch at capture time (`worktree_at_capture`); otherwise `unknown` (a removed
worktree, a detached HEAD, `HEAD`, a deleted branch). A past branch is never inferred from today's
checkout. A main session that writes in another worktree with `git -C` is attributed to its own
directory, which is where the request really ran: give that work to a worktree subagent, or `cd`
first.

**The allowlist** — the only fields a record holds, and the only ones that can leave the machine:
`id`, `time`, `model`, `input`, `output`, `cache_read`, `cache_write_5m`, `cache_write_1h`,
`repository`, `branch`, `attribution_source`, `role`, `agent_type`, `agent_id`, `session`,
`runtime`. No message text, tool input or output, file path or credential.

### Price

`assets/prices.json` holds versions, each with `effective_from` (UTC), the day it was `checked`
against the provider's published list, and per-model rates in USD per million tokens, including a
long-context tier decided per request on input + cache read + cache write. Each request is priced
with the version in effect at its time. Add a version for a price change; never edit an old one.
An unknown model (Codex models today) or missing token counts make that request's cost unknown —
counted and shown, never zero. Sums keep full precision; only the display rounds.

### Store and export

Set `ledger.store = <git URL>` to the owner's private repository. `plumb-ledger export` pushes each
captured session as one commit to `refs/plumb-ledger/<runtime>/<session>`. The commit holds
`records.jsonl` (that session's records) and, when the session had conflicting copies of a request,
`conflicts.jsonl` (the conflicting ids, one `{"id": ...}` per line, nothing else), so a report built
from the store alone still counts the conflicts after the container that saw them is gone. A conflict
found by a later capture that adds no record is exported on its own. Each session owns its ref, so
parallel sessions never share a push target, and the commit is built from the content alone, so a
re-export is a no-op. One session is exported by one process at a time (a per-session lock is held
from reading its records through the push to moving them from pending to exported), and what a
capture appends meanwhile stays pending for the next export. Export runs non-interactively
(`GIT_TERMINAL_PROMPT=0`) with git's own credential for that URL, after a `git ls-remote` preflight
(`export --check`, which `plumb-doctor` also runs). A failed push keeps the records pending and exits
non-zero. Without a store, records stay local and every report says that cloud sessions are not
covered. Run `export` at the end of a cloud session: its container is reclaimed afterwards.

### Tasks and the report

```bash
plumb-ledger prs    --repo <owner/name> --since <day> [--out <json>]
plumb-ledger report --since <day> --until <day> [--prs <json>]... [--changes <jsonl>] [--rework <json>]
```

A task is (repository, head ref, pull request number). Among pull requests of one repository and
head ref, in order of creation, a request belongs to the first whose close time (or now, if open)
is at or after the request's time: work before the pull request opened belongs to it, and a reused
branch name sends later work to the later pull request. Two open pull requests for one head ref make
it `ambiguous`; none make it `no pull request`. Neither is guessed.

The report reads local records and the store's refs (fetched with prune into a cache repository
named by a hash of the store URL without credentials, so a ref deleted from the store, or a store you
switched away from, is not counted) and prints: the total; cost by task (top 10),
model, frontier share (Fable, Mythos and Opus models), role and agent type, and token kind; with
`--rework`, the cost of reworked changes and of their fixes; the counts of unknown cost, unknown
attribution, ambiguous, no pull request, unidentified and conflicting requests; and coverage
(pending exports, store unset).

Costs are list prices applied to recorded tokens. On a flat-rate plan they are not the bill; they
compare tasks and models with each other.
