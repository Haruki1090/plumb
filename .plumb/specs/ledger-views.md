# Ledger views: time, cost and model per task, readable in the store

## End state

The owner can open the ledger store on GitHub and read, without running anything, how long each task
took, what it cost and on which models, by day and by model, and what was not attributed. The weekly
retro reads the same tables and writes its decisions next to them, so the improvement loop has a
written history. Nothing here changes what leaves the machine except one identifier (below), and no
product repository is written.

Today `plumb-ledger report` prints cost by task, model, role and token kind for a period, but:

- it has no time: a task's cost cannot be set against how long it took;
- its output is terminal text, so the store's default branch shows only a README and the records sit
  in one branch per session, which GitHub does not show as data;
- requests made on the base branch (`develop`, `main`) or with unknown attribution form large buckets
  that belong to no task. A cloud session usually starts on the base branch, investigates, then
  branches; its early requests never reach the pull request it produced.

## What is added

### A. `remote_session` on captured records

- Capture adds one field, `remote_session`: the cloud session id the runtime exposes
  (`CLAUDE_CODE_REMOTE_SESSION_ID`, e.g. `cse_<id>`), reduced to `<id>` (the part after the first `_`).
  Null when the variable is absent (a local session) or malformed. It is the same id a commit's
  `Claude-Session: https://claude.ai/code/session_<id>` trailer carries, and those trailers are
  already public wherever the commits are.
- It joins the allowlist (`FIELDS`) and `docs/ledger.md`. Records captured before this have no field
  and read as null. The field is taken from the capturing process's environment, so a capture run by
  hand from another shell records null rather than a wrong id.

### B. Session-to-pull-request attribution

- `plumb-ledger changes` already lists, per landed pull request, the session links of its commits
  (`sessions`). The views (and `report`) accept `--changes <jsonl>` (repeatable) and build a map from
  `<id>` to pull requests.
- A request is assigned to a task as today (repository, head ref, pull request by time). Only when
  that gives no pull request — its branch has none, its branch is unknown, or it is the base branch —
  and its `remote_session` maps to exactly one pull request of the same repository, the request goes to
  that pull request, marked `attribution = session`. A session that maps to two or more pull requests
  stays where it was and is counted as `session_ambiguous`. Nothing else is guessed.
- Only landed pull requests carry `sessions` today; open ones are left to the branch rule.

### C. Active time

- Time is measured per session, not per request: the requests of one session (main and subagents
  together), sorted by time, form a timeline. Two consecutive requests at most `gap` apart are one
  stretch of work; the interval between them counts as active time and is credited to the task of the
  later request. A longer gap is idle and counts nowhere. The first request of a stretch adds nothing.
- `gap` defaults to 30 minutes (`--gap-minutes`), because a turn that waits on a long CI run or a
  background job issues no request for 10–25 minutes while the work is still going on. The value is
  printed with every table.
- Parallel sessions on one task each add their own time (it is effort, not calendar time). The span
  (first to last request of the task) is shown beside it.

### D. `plumb-ledger views`

```bash
plumb-ledger views --since <day> --until <day> --out <dir> [--changes <jsonl>]... [--prs <json>]...
                   [--gap-minutes 30] [--repo <owner/name>] [--timezone <tz>]
```

Reads the same sources as `report` (local records and the store), and writes, replacing the
directory's generated files:

| File | Rows |
|---|---|
| `README.md` | Period, time zone, gap, totals (requests, active hours, cost), coverage and every unknown count, links to the others |
| `tasks.md`, `tasks.csv` | One row per task: repository, head ref, pull request, attribution mix, sessions, requests, active minutes, span, cost, cost by model family, main / subagent cost |
| `days.md`, `days.csv` | One row per day in the time zone: requests, active minutes, cost, cost by model |
| `models.md`, `models.csv` | One row per model: requests, cost, share, tokens by kind |
| `sessions.csv` | One row per session: runtime, session, remote session, repository, branches, first and last request, active minutes, cost, assigned pull request(s) |

- Markdown tables are for reading on GitHub (sorted by cost, top 50, with a line saying how many rows
  the CSV has beyond that); CSV holds every row. Cost uses the same price table and rules as `report`
  (unknown cost is counted and never zero). Output is deterministic for the same records.
- `views` writes only under `--out`. It never pushes; publishing is the caller's job (E).
- Without `--changes`, B is skipped and the README says so.

### E. Publishing in the store (personal layer, outside this repository)

The store is the owner's private repository. plumb ships the command and documents two callers:

1. **Daily, in the store's own CI.** A workflow in the store checks out plumb at a pinned release
   tag, sets `ledger.store` to the checkout itself (no network beyond GitHub), runs `views` for the
   trailing 28 days into `views/latest/`, and commits it to the default branch when it changed. It has
   no access to product repositories, so B is skipped there. Documented in `docs/ledger.md` as an
   example workflow; plumb does not install it.
2. **Weekly, with the retro.** `plumb:retro` gains a step: run `views` with `--changes` for the
   week into `views/<ISO week>/`, and write the retro's result (the at most three changes, each with
   its layer and the number to watch) to `retro/<ISO week>.md` in the store. The next retro first
   reads the previous week's three numbers. When no store is set, the retro prints the same and writes
   nothing.

The store's default branch then holds only generated views and retro notes; session records stay in
their branches and are never merged (one writer per branch, as today).

## What is not done

- No dashboard, chart or hosted page.
- No backfill of `remote_session` for records already captured.
- No change to `report`'s text, beyond accepting `--changes` for B.
- plumb does not create the store's workflow or a scheduled session; the owner adds them.

## Decisions (owner, 2026-11-02)

- Both callers (daily CI without pull-request attribution, weekly retro with it).
- The command lives in plumb, so a team can adopt it by pointing `ledger.store` at an organisation
  repository.
- Gap: 30 minutes (CI runs routinely leave 10+ minutes without a request).

## Acceptance criteria

- Capture writes `remote_session` from the environment, null when absent or malformed; old records
  without it load and price as before.
- B assigns a base-branch or unknown-branch request to the one pull request its session maps to, and
  leaves it when the session maps to none or to several (counted).
- C: synthetic timelines give the expected minutes for gaps just under, at and over the limit, for
  parallel subagents inside one session, and across a branch switch.
- `views` output is byte-identical for the same input, writes only under `--out`, escapes `|` and
  newlines in Markdown cells, and quotes CSV per RFC 4180.
- `scripts/test-ledger-cost.py` (or a new `test-ledger-views.py` wired into `selftest.sh`) covers the
  above; `bash scripts/check-harness.sh` and `bash scripts/selftest.sh` pass.
- No fixture, doc or test names a real organisation, repository, branch or cost figure.

## Order

A → C → B → D (tests with each) → docs (`docs/ledger.md`, the retro skill) → version bump and
CHANGELOG → the store's workflow and the weekly schedule, set up by the owner's session after release.
