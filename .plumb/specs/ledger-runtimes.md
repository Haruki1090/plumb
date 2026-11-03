# Ledger: every runtime on the machine (Codex sweep, OpenCode)

Status: draft for 0.21.0. Owner: plumb maintainers.

## Problem

`plumb-ledger capture` records Claude Code requests from the Stop hook. Other coding CLIs used on the
same machine leave no rows:

- **Codex** has a parser (`--runtime codex`), but nothing calls it. `--transcripts <dir>` reads only
  the direct `.jsonl` files of one directory, while Codex writes
  `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl` (and moves old ones to `archived_sessions/`).
  The Stop hook exports only the sessions its own capture touched, so a cloud container that is
  reclaimed loses Codex rows that were never exported.
- **OpenCode** (2.x) keeps sessions in a SQLite database, not in transcript files, and has no adapter.

The owner wants one place that shows time, cost and model per task across all of them, on a laptop
and in cloud sessions.

## Decisions

### Runtimes

`RUNTIMES = ("claude", "codex", "opencode")`. Store refs, pending and exported files, views and the
report already key on `(runtime, session)`, so they take the new runtime without other change.

### Sweep: `plumb-ledger capture --sweep`

A capture source next to `--hook-input`, `--transcript` and `--transcripts` (mutually exclusive with
them). It captures every runtime listed in `ledger.runtimes` other than `claude` from its default
location, and skips a location that does not exist (no error, one summary line with `missing`):

| runtime  | location |
|----------|----------|
| codex    | `$CODEX_HOME/sessions` and `$CODEX_HOME/archived_sessions` (`CODEX_HOME` default `~/.codex`), every `*.jsonl` below them, recursively |
| opencode | `$OPENCODE_DATA_DIR/opencode.db`, else `${XDG_DATA_HOME:-~/.local/share}/opencode/opencode.db` |

`ledger.runtimes` is a comma- or space-separated list; default `claude,codex,opencode`. Unknown names
are ignored with one stderr line. `--runtime` is ignored with `--sweep` (an error if given explicitly
together is not needed; document that `--sweep` decides the runtimes).

Claude is not swept: its transcripts are captured by the Stop hook of the session that wrote them,
and `remote_session` depends on that binding.

### `--transcripts` for Codex recurses

With `--runtime codex`, `--transcripts <dir>` reads every `*.jsonl` below `<dir>` recursively, sorted
by path. With `--runtime claude` it stays non-recursive (subagent transcripts live in
`<session>/subagents/` and are read through their main transcript).

### Skipping unchanged Codex files

A sweep must stay cheap when it runs after every turn on a machine with hundreds of rollouts.
`state/codex/sweep.json` maps each rollout path to `{size, mtime_ns, status}`. A file whose size and
mtime are unchanged since the last sweep is not opened. `status` is `ok` or `failed`:

- `ok`: the per-file state (offset, head hash, normalizer state) is the existing
  `state/codex/<stem>.json` and is used as today.
- `failed`: the normalizer refused the file (for example `native transcript starts with an
  unobserved usage prefix`). The sweep counts it in `failed` and does not retry it until its size or
  mtime changes. Rows already captured from it stay. The error type and a short masked message go to
  `capture.log` once per change of the file, never the file's content.

The index is written atomically under the capture lock. A missing or unreadable index means every
file is checked (the per-file offsets still prevent re-reading).

### OpenCode adapter

Read-only: `sqlite3.connect("file:<path>?mode=ro", uri=True, timeout=5)`, then
`PRAGMA query_only = ON`. Only the tables `session_v2` and `session_message` are read, and only these
columns: `session_v2.id, parent_id, directory, model`; `session_message.id, session_id, type, seq,
time_updated, data`. No other table is queried (the database also holds account and credential
tables; they are never named in a query). A database that cannot be opened, is locked past the
timeout, or lacks these tables or columns is a defined failure for that runtime: one stderr line and
one `capture.log` line, status 1, and the other runtimes of the sweep still run.

**Rows.** `session_message` rows with `type = 'assistant'` whose `data` (JSON) has
`time.completed` set and a `tokens` object. One OpenCode step writes one assistant message, so a row
is one model call (its retries included). Messages still streaming are skipped and picked up by a
later sweep. Usage OpenCode records only in session totals (title generation, compaction) is not
captured; document this.

**Fields.**

| record | from |
|--------|------|
| `id` | `opencode:<session_message.id>` |
| `time` | `data.time.created` (epoch milliseconds, UTC) |
| `model` | `<data.model.providerID>/<data.model.id>`; when `data.model` is missing, `session_v2.model` (JSON with the same keys); `clean()` decides as for other runtimes |
| `input` | `data.tokens.input` (OpenCode stores non-cached input) |
| `output` | `data.tokens.output + data.tokens.reasoning` (OpenCode stores visible output and reasoning separately and bills both at the output rate; Claude and Codex rows count reasoning inside output) |
| `cache_read` | `data.tokens.cache.read` |
| `cache_write_5m` | `data.tokens.cache.write` (no TTL split; same convention as Codex) |
| `cache_write_1h` | `0` when `cache.write` is known, else `null` |
| `session` | the root of the `parent_id` chain (`safe_session` of its id). A cycle or a missing parent stops the walk at the last session found |
| `role` | `main` when the message's own session is the root, else `subagent` |
| `agent_id` | the message's own session id when `subagent`, else `null` |
| `agent_type` | `data.agent` when `subagent` (for example `general`), else `null` |
| `repository`, `branch`, `attribution_source` | the existing reflog attribution of `session_v2.directory` at `time`, exactly as Codex rows (`Checkouts.top/repository/from_reflog`) |
| `runtime` | `opencode` |
| `remote_session` | see below |

A token value that is not a non-negative integer is `null` (`integer()`), never zero; a row with
every token `null` is skipped and counted as `skipped_lines`.

**Incremental read.** `state/opencode/<sha1(db path)[:16]>.json` holds `watermark`, the largest
`session_message.time_updated` seen. A sweep reads rows with `time_updated > watermark - 600000`
(ten minutes back, for rows committed late), ordered by `time_updated, id`. The known-id set of each
session (`known_ids`) drops repeats; a repeat with different tokens is a conflict, as for Claude.
The watermark is advanced only after the session's pending rows are written. If the database's
`time_updated` goes backwards (a restore), rows are still deduplicated by id.

### `remote_session` for swept runtimes

Codex and OpenCode records get the id from `CLAUDE_CODE_REMOTE_SESSION_ID` only when
`CLAUDE_CODE_REMOTE=true` (the process runs in a cloud session's own container, which holds that
session's work and nothing else). Elsewhere (a laptop, including one driven by Remote Control) they
get `null`. Claude records keep the existing rule (record session == `CLAUDE_CODE_SESSION_ID`).

### The Stop hook and export

When `ledger.capture = on`, the hook's background capture runs the Claude capture as today and then
the sweep (in the same process, after the Claude capture, under the same lock). With
`ledger.export = on-stop`, `export_on_stop` exports each swept runtime as `export --runtime <runtime>`
(every pending session of it, not only those this turn added to: a session whose push failed gets no
new row on the next turn, because its rollout or database rows are unchanged, and would otherwise stay
pending until the container is gone). With nothing pending that export does not reach the store. A failure in the sweep never fails the Claude capture or the hook.

The first sweep on a machine with many old rollouts exports one branch per session; it runs in the
background and is resumable (pending rows stay until pushed).

### A machine with no Claude session running

`docs/ledger.md` documents a scheduled job for laptops, for example a macOS LaunchAgent every 15
minutes running

    plumb-ledger capture --sweep; plumb-ledger export

and the equivalent `crontab` line, joined with `;` so a failed runtime does not stop the export of
the others. plumb does not install it.

### Prices

`assets/prices.json` may carry, per model, optional `checked` and `source` keys that override the
version's for that model. Adding a model that was missing from a version is allowed when its price
held for the whole version (it turns unknown cost into known cost and changes no priced row);
changing a listed price still needs a new version.

- `opencode/deepseek-v4.1-flash-free`: input, output and cache read 0 (OpenCode's free tier; OpenCode
  itself records cost 0 for these rows). Added to the first version with its own `checked`/`source`.
- Codex models stay unpriced until the provider's list price has been checked against the provider's
  own page (third-party listings are not enough). Their cost reads as unknown, as today.

## Not in scope

- Reading OpenCode's own `cost` column. The ledger prices from `prices.json` so all runtimes are
  priced the same way.
- Claude transcripts in the sweep.
- Installing the scheduled job.

## Tests (synthetic fixtures only)

- Codex: `--transcripts` on a `YYYY/MM/DD` tree captures files at every depth; a Claude
  `--transcripts` stays non-recursive.
- Sweep index: an unchanged file is not opened again (patch `capture_codex_file` to count calls); a
  changed file is read from its offset; a refused file is `failed`, counted once, not retried until it
  changes, and the sweep continues with the other files.
- OpenCode: a SQLite fixture built in the test with `session_v2` and `session_message` (and a
  decoy `credential` table holding a sentinel string that must never appear in any output, log or
  record). Covers: field mapping (output = output + reasoning, cache write to 5m, model with provider),
  incomplete message skipped then captured after completion, subagent session (role, agent_id,
  agent_type, root session), parent cycle, re-sweep adds nothing, changed tokens → conflict,
  watermark window catches a late row, missing table → defined failure and other runtimes still run,
  database opened read-only (the file's bytes and mtime unchanged after a sweep).
- `remote_session`: set for swept rows only with `CLAUDE_CODE_REMOTE=true`.
- `ledger.runtimes`: `codex` only skips OpenCode; default sweeps both; a missing location is reported
  as missing, not as an error.
- Hook path: `capture --hook-input` with capture on runs the sweep after the Claude capture; a sweep
  failure leaves one log line and the Claude rows are written.
- Prices: the free OpenCode model prices to 0; per-model `checked` is read.
