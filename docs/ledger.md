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

## Failure records

```bash
plumb-ledger failures --repo <owner/name> --since <day> --until <day> [--label agent-failure] [--findings <jsonl>]... [--json]
```

Collects the agent failures of a period: issues and pull requests labelled `agent-failure`, read
over REST page by page, plus `findings.jsonl` lines given with `--findings`. A record **created** in
the period is kept even when it was updated after it; one created before is not. The record format,
the codes and the layers are `docs/failure-taxonomy.md`.

Each record's block (`<!-- plumb:failure v1 {...} -->`) is read from the body, or, when the body has
none, from its comments; the first block wins. A missing or malformed block, a second block, or an
invalid field keeps the record with those fields `null` and names the problem (`no_block`,
`malformed_block`, `duplicate_block`, `invalid_<field>`); nothing is guessed from the title or the
text, and neither is ever printed. Codes are C01–C15 plus the contract's `[failure] extra_codes`.
The summary counts by source, code, kind and layer, the unknown fields, and the records updated
after the period.

## Cost per task

### Capture (opt-in)

Set `ledger.capture = on` in `~/.claude/plumb/config`. plumb's `Stop` hook (`hooks/hooks.json` →
`scripts/ledger-capture.sh`) then records, at the end of each turn and in the background, every
request that is new since the last capture. With capture off the hook checks the config in the
shell and returns without starting Python (about 10 ms). With it on, the hook only spawns the work
(p95 under 30 ms on a 52 MB transcript) and each capture reads only the bytes appended since the
saved offset. The hook never fails a turn. By hand: `plumb-ledger capture --transcript <path>` or,
for Codex, `--runtime codex --transcripts <dir>` (every `.jsonl` below `<dir>`, recursively, sorted by
path; for Claude it stays the direct files of `<dir>`, because subagent transcripts are read through
their main transcript). `plumb-ledger capture --sweep` captures the other runtimes on the machine
(next section). OpenCode has no transcript files: `--runtime opencode` with `--transcript` or
`--transcripts` is refused, and only the sweep reads it.

Records live in `~/.claude/plumb/ledger` (or `PLUMB_LEDGER_DIR`) for every repository; each carries
its repository. Nothing is written under a product repository.

**Identity.** Claude `claude:<message.id>`, because `requestId` is absent on many records and mixing
the two keys double-counts; Codex `codex:<session>:<n>`, never merged across sessions; OpenCode
`opencode:<message id>`. The copies of
one request (one per content block, or in a forked transcript) count once. Copies whose usage differs are kept
once and reported as conflicts. A request with no id is kept and counted as unidentified; identical unidentified rows are separate requests and all of them are exported and counted.

**Attribution**, in order of evidence: the branch the HEAD reflog of the request's own directory
(the subagent's worktree, else the record's `cwd`) names at the request's time (`reflog`), with
later renames followed so the record carries the name the pull request uses; a branch deleted since
keeps its name. Claude Code's `gitBranch` is the branch of the directory the session was launched
in and does not follow `cd`, so it is not trusted while the reflog can be read. When the reflog
cannot be read: for a subagent that ran in its own worktree, that worktree's HEAD branch at capture
time (`worktree_at_capture`); otherwise the record's `gitBranch` when that branch exists in that
checkout (`transcript`). `unknown` for a removed worktree or a detached HEAD at the request's time.
A request older than the reflog, a rebase in progress with no recorded branch before it, or a reflog
that disagrees with the current HEAD falls back to the same older rules. Known limit: renaming a
branch while another branch is checked out is not in that worktree's reflog, so such a request keeps
the old name (it then matches no pull request; it is never given another branch).
Codex rows are attributed the same way from their `cwd` and time. A main session that writes in another
worktree with `git -C` is attributed to its own directory, which is where the request really ran:
give that work to a worktree subagent, or `cd` first. A request is treated as having
happened after a branch switch made in the same second. Records captured before this rule keep
their `transcript` and `worktree_at_capture` values.

**The allowlist** — the only fields a record holds, and the only ones that can leave the machine:
`id`, `time`, `model`, `input`, `output`, `cache_read`, `cache_write_5m`, `cache_write_1h`,
`repository`, `branch`, `attribution_source`, `role`, `agent_type`, `agent_id`, `session`,
`runtime`, `remote_session`. No message text, tool input or output, file path or credential.

`remote_session` (0.20.0) is the cloud session id the runtime exposes in
`CLAUDE_CODE_REMOTE_SESSION_ID` (`<prefix>_<id>`), reduced to `<id>`, the part after the first
underscore. It is the id a commit's `Claude-Session: https://claude.ai/code/session_<id>` trailer
carries, and those trailers are already public wherever the commits are. It is `null` when the
variable is absent (a local session) or does not have that shape. The value belongs to the session
running the capturing process, not to every transcript it reads: it is recorded only for records
whose `session` (the transcript's session id, which its subagents share) equals
`CLAUDE_CODE_SESSION_ID`, the id of the running session's own transcript. A capture run by hand from
another shell, one that imports other sessions' transcripts (`--transcripts <dir>`), or a run where
`CLAUDE_CODE_SESSION_ID` is missing records `null` for them, not a wrong id that would move past work
to the running session's pull request. Records captured before 0.20.0 have no such field and read as `null`; nothing is
backfilled. Session-to-pull-request attribution (below) is what it is for.

Codex and OpenCode records (0.21.0) have no `CLAUDE_CODE_SESSION_ID` to compare with, so the rule is
the container's: they get the id only when `CLAUDE_CODE_REMOTE=true` (the process runs inside a
cloud session's own container, which holds that session's work and nothing else). Elsewhere, on a
laptop and also on one driven by Remote Control, they get `null`. Claude records keep the rule above.

### Other runtimes: Codex and OpenCode (`capture --sweep`)

The Stop hook sees only Claude Code's transcript. `plumb-ledger capture --sweep` captures the other
runtimes from their default locations on the machine, as a source next to `--hook-input`,
`--transcript` and `--transcripts` (it excludes them; `--runtime` is ignored). Claude is not swept:
its transcripts are captured by the Stop hook of the session that wrote them, and `remote_session`
depends on that binding.

| Runtime | Location |
|---|---|
| `codex` | `$CODEX_HOME/sessions` and `$CODEX_HOME/archived_sessions` (`CODEX_HOME` defaults to `~/.codex`), every `*.jsonl` below them, recursively |
| `opencode` | `$OPENCODE_DATA_DIR/opencode.db`, else `${XDG_DATA_HOME:-~/.local/share}/opencode/opencode.db` |

`ledger.runtimes` in `~/.claude/plumb/config` picks the runtimes, separated by commas or white space
(default `claude,codex,opencode`; `claude` is accepted and does nothing in a sweep). A name that is
not a runtime is ignored with one stderr line. A location that does not exist is not an error: the
summary has one line per runtime with `missing=<what>`.

```text
$ plumb-ledger capture --sweep
capture: codex session=... new=2 duplicates=0 unidentified=0 conflicts=0 bytes_read=1314
sweep: codex files=41 unchanged=40 failed=0 missing=archived_sessions
sweep: opencode rows=12 failed=0 missing=none
```

`--json` prints the same as JSON lines: one per session, then one per runtime with `"kind": "sweep"`.
The exit status is 1 when a runtime failed (below), 0 otherwise.

**Codex.** A sweep must stay cheap when it runs after every turn on a machine with hundreds of
rollouts. `state/codex/sweep.json` keeps, per rollout path, its size, its mtime and a status (`ok` or
`failed`). A file whose size and mtime are unchanged since the last sweep is not opened; a changed
one is read from its saved offset. `failed` is a rollout the normalizer refused (for example one that
starts with a usage total it never observed) or one that could not be read (permissions): it is counted in `failed=`, not retried until its size
or mtime changes, and leaves one line (the error type and a short masked message, never the file's
content) in `capture.log` per change. Rows already captured from it stay, and the sweep goes on
with the other files; a refused file does not change the exit status. A rollout that Codex moves to
`archived_sessions/` is read again once under its new path, and its ids, already held, absorb it. A
missing or unreadable index means every file is checked again (the per-file offsets still prevent
reading a file twice).

**OpenCode** (2.x) keeps its sessions in a SQLite database. The adapter opens it read-only
(`mode=ro`, then `PRAGMA query_only = ON`) and queries two tables, selecting only these columns:
`session_v2.id, parent_id, directory, model` and `session_message.id, session_id, type,
time_updated, data`. The database also holds account and credential tables; no query names them.
From `data` it reads the time, tokens, model and agent, and nothing else (no message text). A
database that cannot be opened, stays locked past 5 seconds or lacks these tables or columns is a
defined failure for OpenCode only: one stderr line, one line in `capture.log`, exit status 1, and the
other runtimes of the sweep still run.

A row is an assistant message with `time.completed` set and a `tokens` object; one OpenCode step
writes one assistant message, so a row is one model call, retries included. A message that is still
streaming is skipped and picked up by a later sweep.

| Record | From |
|---|---|
| `id` | `opencode:<session_message.id>` |
| `time` | `data.time.created` (epoch milliseconds, UTC) |
| `model` | `<data.model.providerID>/<data.model.id>`; when `data.model` is missing, the same keys of `session_v2.model` |
| `input` | `data.tokens.input` (OpenCode stores non-cached input) |
| `output` | `data.tokens.output + data.tokens.reasoning` (OpenCode stores visible output and reasoning apart and bills both at the output rate; Claude and Codex rows count reasoning inside output). When `reasoning` is absent altogether, `output`; when either is not a non-negative integer, `null` |
| `cache_read` | `data.tokens.cache.read` |
| `cache_write_5m`, `cache_write_1h` | `data.tokens.cache.write` and `0` (no TTL split, the Codex convention); both `null` when the write figure is unknown |
| `session` | the root of the `parent_id` chain. A missing parent stops the walk at the last session found; a cycle ends at its smallest id |
| `role`, `agent_id`, `agent_type` | `main` when the message's own session is the root; else `subagent` with that session's id and `data.agent` (for example `general`) |
| `repository`, `branch`, `attribution_source` | the HEAD reflog of `session_v2.directory` at `time`, as for Codex rows |
| `runtime`, `remote_session` | `opencode`; the rule above |

A token value that is not a non-negative integer is `null`, never zero; a row whose tokens are all
`null` is skipped and counted in `skipped_lines`. Repeats of an id are dropped, and a repeat with
different tokens is a conflict, as for Claude. The sweep keeps a watermark per database in
`state/opencode/<hash of the path>.json`, the largest `time_updated` it has seen, advanced only after the
sessions' pending rows are written. It reads the rows after the watermark minus ten minutes (rows
committed late are caught; ids absorb the repeats), and a database whose `time_updated` goes behind the
watermark (a restore) is read again from the start. A row committed more than ten minutes behind the
watermark is not seen.

**Not captured.** OpenCode records usage for title generation and compaction only in its session
totals, not in a message, so it is not in the ledger. The ledger prices from `assets/prices.json`
for every runtime and does not read OpenCode's own `cost` column.

**The Stop hook.** With `ledger.capture = on`, the hook's background capture runs the Claude capture
as before and then the sweep, in the same process under the same lock. A failure in the sweep never
fails the Claude capture or the hook; it leaves a line in `capture.log`. With `ledger.export =
on-stop`, every runtime the hook swept is exported at the end of the turn as `plumb-ledger export
--runtime <runtime>`: every session of it that is still pending, not only the ones this turn added
to, so a session whose push failed is sent on a later turn even when its rollout or database rows did
not change. With nothing pending, that export does not reach the store. The first sweep on a machine with many old rollouts exports one branch per
session; it runs in the background and is resumable (pending rows stay until pushed).

**Runs that outlive a turn: `run` and `watch`.** The Stop hook sweeps when a Claude turn ends. Codex or
OpenCode started from a Claude session can still be running then: rows written after the last turn
are captured only by a later turn, and are lost when the container is reclaimed first. Two commands
close that gap; both run `capture --sweep` and then, with `ledger.export = on-stop`, `export`, each as
a child process (a failure leaves a line in `capture.log` and never stops the caller).

```bash
plumb-ledger run -- COMMAND [ARGS...]          # e.g. plumb-ledger run -- codex exec "..."
plumb-ledger watch [--interval <seconds>]      # default 300
```

- `run` starts the command with the terminal left to it, passes SIGINT, SIGTERM and SIGHUP on to it,
  and sweeps when it ends, whatever its exit status; that status (128 + the signal for a signal) is
  `run`'s own. A command that cannot be started is 127. Only a SIGKILL of `run` itself skips the
  sweep.
- `watch` sweeps every interval for as long as it lives. One `watch` holds `watch.lock` in the
  ledger directory; a second one exits 0 at once, so a hook that fires again (resume, clear,
  compaction) starts nothing new. The holder writes its pid and plumb version into the lock, and a
  newer plumb that finds an older version there stops it with SIGTERM and takes the lock, so an
  upgrade does not leave the old `watch` recording with its old price table. A `watch` of 0.23.1 or
  earlier writes nothing, so it is never replaced: stop it once by hand. Start it in the background
  from a session-start hook, never from the environment's setup script: the setup script runs before
  the session, so the cloud session id that `remote_session` needs is not yet in its environment
  (`docs/cloud-setup.md` has the lines).

**A machine with no Claude session running.** plumb does not install a scheduled job. On a laptop,
run the sweep and the export every 15 minutes, for example with a macOS LaunchAgent
(`~/Library/LaunchAgents/dev.plumb.ledger.plist`, loaded with `launchctl load`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.plumb.ledger</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-c</string>
    <string>plumb-ledger capture --sweep; plumb-ledger export</string>
  </array>
  <key>StartInterval</key><integer>900</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
```

Put the directory that holds `plumb-ledger` on that `PATH` (or write its full path in the command).

or a `crontab -e` line (`plumb-ledger` on cron's `PATH`, or give its full path):

```cron
*/15 * * * * plumb-ledger capture --sweep; plumb-ledger export
```

The two commands are joined with `;`, not `&&`: a runtime that fails (an unreadable OpenCode
database) makes `capture --sweep` exit 1, and the rows the other runtimes captured must still be
exported. `export` does nothing without `ledger.store`. `capture --sweep` does not need `ledger.capture = on`
(it runs when called); only the Stop hook is gated by that setting.

### Price

`assets/prices.json` holds versions, each with `effective_from` (UTC), the day it was `checked`
against the provider's published list, and per-model rates in USD per million tokens, including a
long-context tier decided per request on input + cache read + cache write. Each request is priced
with the version in effect at its time; two versions with the same `effective_from` are ordered by
their place in the file, so the later one is in effect (version 2026-11-10 corrects 2026-11-09 this
way, and adds `claude-fable-5-2`). Add a version for a price change; never edit an old one.
A model may carry its own `checked` and `source`, which override the version's for that model, and
its name is looked up as written (`opencode/deepseek-v4.1-flash-free` has a provider prefix). A model
that a version was missing may be added to it when its price held for the whole version (that turns
an unknown cost into a known one and changes no priced row); changing a listed price still needs a
new version. An unknown model or missing token counts make that request's cost unknown — counted
and shown, never zero. A model's price is added only from the provider's own pages (a third-party
listing is not enough), and its `source` says which page and how it was read. Sums keep full
precision; only the display rounds. OpenCode's free-tier model is priced 0, which is also what
OpenCode records for those rows. OpenCode Go's models (`opencode-go/deepseek-v4.1-flash`, `opencode-go/deepseek-v4-pro`, `opencode-go/glm-5.3`, 0.22.1) are priced at Go's Off-Peak list price, as models.dev (OpenCode's own model catalog) transcribes Go's documentation; Peak hours are 2x and not modelled, and a Go subscription is not billed per token. `gpt-6.1-sol` (0.21.1) is priced at the OpenAI API's standard
tier, with its long-context tier above 272K input tokens; a Codex session on a subscription is not
billed per token, so its cost, like a flat-rate Claude plan's, compares work rather than states a
bill. Codex rows put cache writes in `cache_write_5m`, which the version prices at 1.25x input, the
rate OpenAI lists for this model. `gpt-6.1-terra` ($1 input, $0.05 cache read, $5 output per MTok),
`gpt-5.6-luna` ($0.20, $0.02, $1.20) and `gpt-5.6-sol` ($4, $0.40, $20) are priced at the OpenAI
API's standard tier in the new version 2026-11-09, effective 2026-08-22 (cache write at 1.25x input,
long-context tiers above 272K input tokens), because Luna's 2026-07-30 cut and Sol 5.6's promotional
price from 2026-08-21 did not hold for the whole of 2026-10-30; every model of that version is copied
forward, and Luna's and Sol 5.6's rows before 2026-08-22 stay unknown.

### Store and export

Set `ledger.store = <git URL>` to the owner's private repository, one that holds nothing else (it
fills with one branch per session). `plumb-ledger export` pushes each captured session as one commit
to the branch `refs/heads/plumb-ledger/<runtime>/<session>`. The records are branches, not a custom
ref namespace, because a cloud session's git proxy accepts branch pushes (forced ones too) and drops
a push to any other ref; it also refuses deleting a branch, so retire sessions from a local clone.
The commit holds
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
covered. Run `export` at the end of a cloud session (its container is reclaimed afterwards), or set
`ledger.export = on-stop` (below) so that every turn does.

**Export at the end of every turn (`ledger.export = on-stop`).** A cloud session's container is
reclaimed after idle with no reliable session-end event, so there is no "end of session" to export
at. With `ledger.capture = on`, `ledger.export = on-stop` and `ledger.store` set, the Stop hook's
background job runs, after that session's capture, the same code as `plumb-ledger export --session
<id>`, for that session only. It stays in the background (the hook's latency is unchanged), a turn
that captured nothing new does not push, and a failure (store unset, unreachable, denied) leaves one
line in `capture.log` in the ledger directory, with the error type and a short message and any
credential in a URL masked; the records stay pending for the next turn or a manual `export`.
`ledger.export = manual` (the default; also unset) is the behaviour described above. `plumb-doctor`
reports the key and flags `on-stop` without a store or with capture off.

### Tasks and the report

```bash
plumb-ledger prs    --repo <owner/name> --since <day> [--out <json>]
plumb-ledger report --since <day> --until <day> [--prs <json>]... [--changes <jsonl>]... [--rework <json>]
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

### Session-to-pull-request attribution

A cloud session usually starts on the base branch, investigates, then branches. Its early requests
belong to no pull request by the rule above, so they form large buckets (`no pull request`, or
`unknown attribution` while the branch is unknown). `report` and `views` accept `--changes <jsonl>`
(repeatable; the output of `plumb-ledger changes`, whose `sessions` hold the `Claude-Session:` links
of each landed pull request's commits) and use it for one more step:

- A request is assigned as before (repository, head ref, pull request by time).
- Only when that gives no pull request (the branch has none, it is the base branch, or the branch is
  unknown) and the request's `remote_session` maps to **exactly one** landed pull request of the
  same repository, the request goes to that pull request. In `views` its attribution is `session`.
- A session that maps to two or more pull requests leaves the request where it was and is counted as
  `session_ambiguous`. A session that maps to none, and a record with no `remote_session`, stay where
  they were. Nothing else is guessed.
- A request whose repository is unknown (a cloud session often starts outside any checkout, so its
  first requests have none) goes to a pull request only when its `remote_session` maps to exactly one
  landed pull request **across all repositories**; it then takes that pull request's repository. Two
  or more, in one repository or several, leave it unknown and are counted as `session_ambiguous`.
- `--repo` filters on the repository a request was placed in, after this step: a request moved to a
  pull request of the wanted repository is counted there, one moved to another repository is left out
  as another repository, and only requests still without a repository are reported as unknown
  repository. The active time of a session is still measured on its whole timeline.
- A request that already has a pull request by its branch, or is `ambiguous` (two open pull requests
  for the head ref), is never moved.
- It needs `--prs`: without it tasks are `repository @ branch` and there is no way to tell that a
  branch has no pull request, so the step is skipped (and the output says so).

Only landed pull requests carry `sessions`, so open ones are left to the branch rule. `report` counts
the moved requests and `session_ambiguous` (JSON keys `session_attribution` and
`unknown.session_ambiguous`, and one line of text) only when `--changes` is given; its landed/not-landed
split reads the same files.

### Views

```bash
plumb-ledger views --since <day> --until <day> --out <dir> [--changes <jsonl>]... [--prs <json>]...
                   [--gap-minutes 30] [--repo <owner/name>] [--timezone <tz>]
```

The cost report is terminal text, and the store's records sit in one branch per session, which GitHub
does not show as data. `views` reads the same sources as `report` (local records and the store) and
writes tables that can be read on GitHub without running anything, replacing these files under
`--out` and nothing else (other files in the directory stay; nothing is written outside it; nothing
is pushed). The store's refs are fetched into a cache repository, which `views` keeps in a temporary
directory and removes when it ends, so neither the ledger directory nor `--out` receives it (a cache
under `--out` would be committed with the tables); `--store-cache <dir>` names one to keep:

| File | Rows |
|---|---|
| `README.md` | Period, time zone, gap, totals (requests, active hours, cost), coverage and every unknown count, links to the others |
| `tasks.md`, `tasks.csv` | One row per task: repository, head ref, pull request, attribution mix, sessions, requests, active time, span, cost, cost by model family, main / subagent cost |
| `days.md`, `days.csv` | One row per day of the period in the time zone, empty days included: requests, active time, cost, cost by model family |
| `models.md`, `models.csv` | One row per model: requests, cost, share, tokens by kind |
| `agents.md`, `agents.csv` | One row per role (main or subagent), agent type and model: threads, requests, cost, share, median context of a thread's first request and of its largest. A thread is a session (main) or one agent of a session (subagent); one that used two models counts in both rows. `agents.md` says how to read it: an agent type runs on the main model when neither the call, its definition nor `CLAUDE_CODE_SUBAGENT_MODEL` decides its model, and the table cannot show whether a model was inherited. A request with a missing context part has an unknown context, not 0, and is left out of the medians |
| `sessions.csv` | One row per session: runtime, session, remote session, repositories, branches, first and last request, active time, cost, assigned pull requests |

The Markdown tables are for reading: the 50 costliest rows (a day table lists its 50 latest days, oldest
first), then a line saying how many more rows the CSV holds. The CSV files hold every row, in RFC 4180
form (comma, CRLF, a field with a comma, quote or line break is quoted), costliest first. In Markdown,
`|` and a backslash in a cell are escaped and a line break becomes `<br>`. A task is a pull request,
a `repository @ head ref` with no pull request (`none`), an `ambiguous` head ref, or the single
`unknown attribution` row; the attribution column counts requests by how they were attributed
(`reflog`, `transcript`, `worktree_at_capture`, `unknown`, and `session` for those moved by the rule
above). Cost uses the same price table and rules as `report`: list prices, a request whose cost
cannot be known is counted (`unknown_cost_requests`, `(+n unpriced)`) and never added as zero, and
a row (task, day, model, session) whose requests all lack a price has no cost: the CSV cell (cost, share, main / subagent cost, model family) is empty and the Markdown cell says `unpriced`, never 0 (a day with no request is a real zero). A row with some priced requests shows their sum and how many were not priced. Repository names are compared without case everywhere (one key, lower case, for the record, `--prs`, `--changes`, `--rework` and `--repo`: GitHub names are case-insensitive and these sources may spell one differently), and a task is shown under the smallest of the spellings seen. CSV money has six decimals. The
same records give the same bytes. Without `--changes` the session step is skipped and the README
says so.

**Active time.** Time is measured per session, not per request. The requests of one session (the
main transcript and its subagents together), sorted by time, form a timeline. Two consecutive
requests at most `gap` apart are one stretch of work: the interval between them counts as active
time and is credited to the task of the **later** request, so time spent switching branches goes to
the branch switched to. A longer gap is idle and counts nowhere, and the first request of a stretch
adds nothing. `gap` is 30 minutes (`--gap-minutes`) because a turn that waits on a long CI run or a
background job issues no request for 10 to 25 minutes while the work goes on. Parallel sessions on
one task each add their own time (it is effort, not calendar time); the span, first to last request
of the task, is shown beside it. The timeline uses every record of the session, also those outside
`--repo` and just outside the period, so that scoping or the period's edge does not turn
neighbouring work into idle time. The gap is printed with every table.

### Records for a warehouse

```bash
plumb-ledger records --since <day> --until <day> [--timezone <tz>] [--out <file>] [--store-cache <dir>]
```

`views` writes the tables plumb defines; a warehouse (BigQuery and the like) wants the requests
themselves, to query in ways the tables do not. `records` reads the same sources as `report` (local
records and the store, merged by id) and prints the period's requests as JSON lines, oldest first:
the allowlisted fields above, in that order, then

| Field | Meaning |
|---|---|
| `cost_usd` | The request's list-price cost as an exact decimal string with nine places (BigQuery `NUMERIC` keeps nine), priced as `report` prices it; `null` when it cannot be known, never `0` |
| `price_version` | The `id` of the price version that priced it, or `null` |
| `conflict` | The id has copies with different tokens or model; the row is the first copy, as `report` counts it |

Nothing else leaves the machine: the line holds the allowlist and these three. The same records give
the same bytes. `--out` writes the file atomically; without it the lines go to standard output and the
summary (requests, unpriced, conflicting, without an id, pending export, store) to standard error.
Nothing is written in the ledger directory, and the store's cache repository lives in a temporary
directory unless `--store-cache` names one. A store that is set but cannot be read is an error (exit
2) and writes nothing, so a load never takes a partial read for the whole.

Active time and the task of a request are not in the lines: they need a session's whole timeline and
`--prs` / `--changes`, and `views` computes them. Load both when you want both: the lines for
exploring, the `views` CSV files for the numbers plumb reports.

**BigQuery.** `assets/bigquery/requests.schema.json` is the table's schema (it is tested against the
lines). After the first load below has created the staging table, create the table once, partitioned
by day and clustered for the common filters:

```sql
CREATE TABLE plumb_ledger.requests
PARTITION BY DATE(time) CLUSTER BY repository, model
AS SELECT * FROM plumb_ledger.requests_staging WHERE FALSE;
```

Then, on a schedule (in the store's CI, after the session branches are fetched as for `views`), load the
trailing window into a staging table and merge it on `id`, so a re-run or an overlapping window never
duplicates a request and a re-priced request is updated in place:

```bash
plumb/bin/plumb-ledger records --since "$(date -u -d '27 days ago' +%F)" --until "$(date -u +%F)" --out records.jsonl
bq load --replace --source_format=NEWLINE_DELIMITED_JSON plumb_ledger.requests_staging records.jsonl plumb/assets/bigquery/requests.schema.json
bq query --use_legacy_sql=false '
MERGE plumb_ledger.requests T
USING (SELECT * FROM plumb_ledger.requests_staging WHERE id IS NOT NULL) S
ON T.id = S.id
WHEN MATCHED THEN UPDATE SET
  time = S.time, model = S.model, input = S.input, output = S.output, cache_read = S.cache_read,
  cache_write_5m = S.cache_write_5m, cache_write_1h = S.cache_write_1h, repository = S.repository,
  branch = S.branch, attribution_source = S.attribution_source, role = S.role, agent_type = S.agent_type,
  agent_id = S.agent_id, session = S.session, runtime = S.runtime, remote_session = S.remote_session,
  cost_usd = S.cost_usd, price_version = S.price_version, conflict = S.conflict
WHEN NOT MATCHED THEN INSERT ROW'
```

A request without an id cannot be keyed, so the merge leaves it out; the summary counts them. Give the
job's identity only what it needs (from GitHub Actions, Workload Identity Federation to a service
account with `roles/bigquery.dataEditor` on the dataset and `roles/bigquery.jobUser` on the project).
plumb does not install this job.

### Publishing in the store

The store is the owner's private repository, and its default branch can hold generated views and
retro notes while the session records stay in their `plumb-ledger/<runtime>/<session>` branches
(one writer per branch, never merged). plumb ships the command; the store's own workflow and the
weekly run are the owner's to add. The default branch must be one outside `plumb-ledger/` (an empty repository first filled by an
export can end up with a session branch as its default; an export replaces that branch, so views and
notes on it would be lost). The weekly retro checks this and stops.

**Daily, in the store's own CI.** Check out the store, bring the session branches into the checkout,
point `ledger.store` at the checkout itself, write the trailing 28 days into `views/latest/`, and
commit it to the default branch when it changed. The job has no access to product repositories, so
there is no `--changes` and no session attribution; the README of the views says so. Pin plumb to a
release tag or a commit SHA, so the views change only when you move the pin.

```yaml
name: ledger-views
on:
  schedule:
    - cron: "17 3 * * *"
  workflow_dispatch:
permissions:
  contents: write
concurrency:
  group: ledger-views
jobs:
  views:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/checkout@v4
        with:
          repository: <owner>/plumb   # the repository the plugin is installed from
          ref: <release tag or commit SHA>   # pin it; the views change with plumb's version
          path: plumb
      - name: Bring the session branches into the checkout
        run: git fetch origin '+refs/heads/plumb-ledger/*:refs/heads/plumb-ledger/*'
      - name: Write the views
        run: |
          mkdir -p "$HOME/.claude/plumb"
          printf 'ledger.store = %s\n' "$GITHUB_WORKSPACE" > "$HOME/.claude/plumb/config"
          plumb/bin/plumb-ledger views \
            --since "$(date -u -d '27 days ago' +%F)" --until "$(date -u +%F)" \
            --timezone UTC --out views/latest
      - name: Commit when it changed
        env:
          DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
        run: |
          git add views/latest
          git diff --cached --quiet && exit 0
          git -c user.name=plumb-ledger -c user.email=ledger@plumb.invalid commit -m "views: $(date -u +%F)"
          git push origin "HEAD:refs/heads/$DEFAULT_BRANCH"
```

The checkout is a clone of the default branch, so the session branches are fetched into it as local
branches first; `ledger.store` can then be the checkout's own path and the job reads nothing over the
network beyond GitHub. `--timezone` is given because the checkout holds no project contract. The
workflow is not installed by plumb. A team adopts the same thing by pointing `ledger.store` at an
organisation repository.

**Weekly, with the retro.** `plumb:retro` runs `views` with `--prs` and `--changes` for the week into
`views/<owner>/<name>/<ISO week>/` of the store, and writes its result (at most three changes, each with
its layer and the number to watch) to `retro/<owner>/<name>/<ISO week>.md`. The repository is in the
path because one store can serve several repositories (a team's store, or an owner with more than
one); the next retro reads the previous week's note from the same path, never another repository's.
With no store set the retro prints the same and writes nothing.
