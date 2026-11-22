# cockpit mode: routing, briefs and lane state as commands

Status: approved by the owner on 2026-11-23 ("everything useful"). This spec covers PR 1 (the thin
end-to-end slice). PR 2 (hook) and PR 3 (code policy) are listed at the end so the slice does not
paint them into a corner.

## Why

A coordinating session ("cockpit") hands work to lanes on several runtimes. Today the rules that
decide which model takes which kind of work, what a lane may not do, and when to stop live in a
prose file in one run directory. Another session never sees them, model names are typed by hand
per launch, and the personal config drifted from what was actually used. Prose also failed to stop
a cheap lane from reaching a shared database the brief told it to leave alone.

Goal: a fresh session in any repository resolves a kind of work to a launch command, writes a
brief every lane reads the same rules from, and gets a deterministic `allow`/`hold` before it
starts the next attempt. Model names live only in `~/.claude/plumb/config`.

## Data first

### Config keys (personal config, `plumb-config` syntax)

```
role.<role>          = <launch command prefix>      # existing: implementer, judge, bulk
route.<kind>         = <role>                       # preferred role for a kind
route.<kind>.baseline = <role>                      # where a demoted kind goes back to
cockpit.demote_after = 2                            # consecutive misses before demotion
cockpit.hook         = off | report                 # PR 2
```

Roles added by this spec: `draft`, `complex`, `architect`, `final`. Kinds are a closed list kept in
`skills/cockpit/references/kinds.tsv` (`kind<TAB>meaning<TAB>default_role<TAB>default_baseline<TAB>read_only`):
`test-transcription`, `mechanical-edit`, `doc-format`, `review-preview`, `repro-draft`,
`small-draft`, `stateful-implementation`, `architecture`, `diagnosis`, `final-review`.
No model name appears in the repository. An unset role means "the main session does it", printed as
such, exit 0 (same contract as `plumb-config`).

### Run directory

`$(plumb-path run)/cockpit/<run-id>/`

- `events.jsonl` — the only source of truth. Append-only. Written only by the main session through
  `plumb-lane`. One JSON object per line:
  `{"seq":N,"event_id":"…","ts":"…","type":"…","lane":"…","work":"…","data":{…}}`.
  A repeated `event_id` is a no-op (idempotent re-send).
- `lanes.tsv` — derived view, rewritten from the events after every write:
  `lane work kind state role attempt head last_check stop_code next`.
- `briefs/<lane>.md` — generated briefs.
- `locks/<name>` — directory locks for declared exclusive resources (e.g. one container CI at a
  time), shared across runs of the same repository (`$(plumb-path run)/cockpit/locks/`).

Why not SQLite: lanes never write state; only the main session does, one command at a time. An
append-only log plus `mkdir` locks covers re-send and cross-run resources with no new dependency.

### Event types

`lane-added{kind,brief,allow_paths[],acceptance[]}`, `attempt-started{attempt,role,command}`,
`attempt-collected{attempt,head,changed_paths[],report}`,
`observed{attempt,ac,result:pass|fail,cause?}`, `adjudicated{attempt,verdict:hit|miss|inconclusive,reason}`,
`held{code,reason}`, `resumed{diagnosis,hypothesis,test}`, `closed{head}`.

## Rules `guard` applies (pure function of the events)

| code | condition | effect |
|---|---|---|
| `same-cause` | the same `(work, cause)` observed in two different attempts | hold; counts never reset |
| `regression` | an acceptance item that passed before fails at a later attempt | hold at once |
| `no-progress` | three attempts on the same work with no acceptance item newly passing | hold |
| `out-of-range` | `changed_paths` of a collected attempt outside `allow_paths` | hold, and record a `miss` for the route |
| `unclassified` | a failing observation with no `cause` | hold until classified |
| `stale-brief` | resume without a new diagnosis, hypothesis and distinguishing test | refuse resume |

Demotion: two consecutive `miss` verdicts for `(kind, role)` make `plumb-route` return the
baseline for that kind in this repository until the owner clears it with
`plumb-lane route-reset <kind>`. `inconclusive` does not advance the count.
Demotion state is derived from the events of every run of the repository, so it reaches the next
session.

## Commands

All take `--json` for `{"schema":1,"outcome":"…","reason_codes":[],"data":{}}` on stdout.
Exit codes: 0 done, 1 refused by a rule (hold), 2 bad input or state, 3 runtime unavailable.

- `plumb-route resolve <kind> [--repo DIR] [--json]` → role, command, why (preferred / baseline /
  demoted / unset). Read-only.
- `plumb-brief new --run R --lane L --spec spec.json` → writes `briefs/<L>.md`. The first line is
  `Read <absolute plugin root>/skills/cockpit/references/worker.md before anything else.` The body
  keeps the lead headings (`Range`, `Material`, `Do not touch`, `Acceptance`, `Return`) and adds
  `Kind`, `Report path`, `Forbidden means`. Same spec, same output.
- `plumb-brief check BRIEF` → lists missing or empty sections, an acceptance item with no check
  command, a missing report path. Exit 1 when anything is missing.
- `plumb-lane init|add|start|collect|observe|adjudicate|guard|resume|close|status|route-reset`.
  `start` refuses (exit 1) when `guard` holds. `collect` reads `git diff --name-only <base>..HEAD`
  plus untracked files in the lane worktree itself; the worker's report is not trusted for paths.
  `status` prints `lanes.tsv` (or JSON) and exits 0 even when lanes are held.

## worker.md

The rules every lane reads, short. Works for any runtime. Holds: the brief is the whole bar; no
shared services (container sockets, databases, other worktrees) unless the brief lists them;
commit locally, no push; write the report to the given path with the commands actually run and
their exit codes; stop and report instead of widening the range. Note in the doc that these
sentences are a courtesy: `collect` and `guard` are what enforce them.

## Skill

`skills/cockpit/SKILL.md` (`disable-model-invocation: true`): a thin loop that calls the commands
above — classify into a kind, `plumb-route resolve`, `plumb-brief new` + `check`, `plumb-lane
start`, wait through `pane.driver`, `collect`, run the checks yourself, `observe`, `adjudicate`,
`guard`. It owns no rule the commands already enforce.

## Acceptance for PR 1

1. Replay fixtures (anonymised, under `scripts/fixtures/cockpit/`) stop for their own reason:
   same cause in two attempts → `same-cause`; checks green but a manual acceptance item never
   observed → `close` refuses; a later review finds a failing item that passed before →
   `regression`; a lane that changed a path outside its range → `out-of-range` and one `miss`.
2. In a temporary repository with no run history and a fixture config, `plumb-route resolve
   test-transcription` returns the bulk role's command; after two `miss` verdicts it returns the
   baseline; `route-reset` restores it.
3. Re-sending an event with the same `event_id` changes nothing; `lanes.tsv` is identical.
4. `bash scripts/check-harness.sh` and `bash scripts/selftest.sh` pass; new cases are in selftest.
5. `docs/role-map.md` documents the new roles and `route.*` keys; CHANGELOG and version bumped
   (minor). `docs/scope.md` records what was taken from upstream and what was not.

## Later PRs

- PR 2: an opt-in PreToolUse hook (`cockpit.hook = report`) that reports, never blocks, a Bash
  launch of `codex exec` / `opencode run` without the ledger wrapper or without stdin from
  `/dev/null`, and a lane start while `guard` holds. Fixtures must include a heredoc that only
  writes such a command into a file (must not fire) and the real `hc run … zsh -c "…"` form.
- PR 3: a `[code_policy]` table in the project contract and a checker that reports comments and
  effect hooks newly introduced between base and head (multiset of rule + symbol, not counts),
  with an exceptions file. Report-only first. A project decides whether to enforce.
