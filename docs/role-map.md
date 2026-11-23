# Where roles run

**`~/.claude/plumb/config` decides where a role runs, not this document.**
Do not write a command name in prose. Write one and the document turns into a lie for anyone
who does not have that tool.

| Role | Key | When unset |
|---|---|---|
| Main session | — (the Claude Code you are running in) | — |
| Implementer role | `role.implementer` (a command, started in a pane through `pane.driver`); `role.implementer.model` (the `Task` fallback's `model`) | A `Task` that inherits the main session's model |
| Explorer role | `role.explorer.model` (a runtime-supported alias). Produces no diff. When an `Explore` call names no `model`, the PreToolUse hook (`scripts/agent-route.py`) gives it this value | Inherits the main session's model |
| Design role (`architect`) | `role.architect` in cockpit. The design playbook uses the owner's `architect` agent when defined | **The main session stands in** |
| Draft role | `role.draft` | The main session does the draft |
| Complex role | `role.complex` | The main session handles the implementation or diagnosis |
| Final role | `role.final` | The main session does the final review |
| Judge role | `role.judge` | **The main session stands in.** Say out loud that no other family's eyes are on it, and go on |
| Bulk role | `role.bulk` | The main session works through it in order |
| Driving a pane | `pane.driver` | Run it in the foreground |
| Stack operations | `stack.tool` | Drops to "Land it with bare gh" in `playbooks/landing-a-stack.md` |

How to ask:

    plumb-config role.judge ""

## How a subagent's model is decided

A subagent runs on the first of these that is set:

1. The `model` of the call that starts it.
2. The `model` in the agent's definition.
3. The environment variable `CLAUDE_CODE_SUBAGENT_MODEL`.
4. The main session's model.

The built-in `Explore` agent skips step 3: the variable does not change it, so a setup that sets only
the variable still runs `Explore` on the main session's model. That is why `role.explorer.model` is
enforced by a hook rather than by a sentence here. The hook (`scripts/agent-route.py`, a PreToolUse
hook on the `Agent` tool) adds `model` to the input of an `Explore` call that has none and, unless
`worker.rules.types` is set (next section), does nothing else: other agent types, a call that already
names a model, an unset key, a value that is not an alias, or any error leave the call as it was. It
writes no permission decision, so it never changes whether the call is allowed. The `Agent` tool
accepts only aliases for `model`, which is why the key does too.

**`worker.rules.types` is off unless it is set.** It lists subagent types, separated by commas
(`worker.rules.types = implementer, general-purpose`). For a call whose `subagent_type` is listed
exactly, the same hook puts one line first in the prompt: `Read <plugin root>/docs/worker-rules.md
first; it binds this task.` Running it twice adds nothing. That file holds the rules every
delegate shares (`docs/worker-rules.md`). It is a hook and not a sentence in a playbook because a rule
the delegate must follow cannot depend on the coordinator remembering to paste it. A missing rules
file, an unlisted type or any error leaves the prompt as it was.

To see which kind of agent ran on which model, read the agents table of `plumb-ledger views`.

**Do not switch the main session's model in the middle of a session.** The prompt cache is kept per
model, so a switch rewrites the whole context at the uncached rate. Choose the model when the
session starts, and route the work that should run on another model through the roles above.

**Unset is not a fault.** It returns empty and exits 0.
Even with the judge role unset, **the todo line for the judge role does not disappear**
(**visible skip**). Leave it there reading `skip: role.judge unset`.

## Where effort goes up

**Effort is a per-call setting, not a session default.** The default is medium
(**principle-spend-on-the-outcome**: output tokens are billed at a multiple of input, and
`thinking %` in `plumb-session-audit` is the term this moves). Raise it only for the roles below.

| What the role does | Effort |
|---|---|
| Extraction, classification, mechanical transformation, a bounded exploration | low |
| Implementation, investigation, a review whose target is still wide | medium (the default; do not set it) |
| Verification, arbitration, final integration, a review narrowed to a few paths | high |

Lower it and verification slips through; raise it and only the cost goes up. **Do not buy back a
target you failed to narrow with effort** — narrow first, then raise it once.

## The implementer role

The main session keeps requirements, design, ambiguous implementation, verification, arbitration and
final integration (the `high` row above). The implementer role takes a bounded brief:
implementation whose range and acceptance are already fixed. That split is what lets
`role.implementer` point at a lighter model tier than the main session; which tier fits is the
owner's call and lives in the config, not here.

Where it runs, first match wins:

1. `role.implementer` is set and `pane.driver` is usable (its managed-session check passes): start
   the command as an agent in a new pane through the driver, in the task's worktree, without
   taking the owner's focus. The command must start an interactive agent the driver recognizes.
   Name it as the caller says (`lane-<item>` in `plumb:lead`, otherwise `impl-<task>`) and wait on
   that name. Write the brief as a file from `skills/lead/references/lane-brief.md` and prompt the
   agent with its path; wait on the driver's agent state (never a sleep loop), then read the
   report file and review the diff in the main session.
2. Otherwise `role.bulk` where the caller names it as a fallback (`plumb:lead` does).
3. Otherwise a `Task`, with `model` set to `role.implementer.model` when that resolves. Say
   `skip: role.implementer unset — implementer runs as a subagent` (or `pane.driver unusable`)
   when the pane route was not taken.

In every route:

- **A report without check output is not done.** The report carries each check it ran with its exit
  status. A missing or failed-to-start check sends the task back, and that counts as a rework round
  (`playbooks/running-a-plan.md`, step 5: the main session still does not write the fix).
- **Ambiguity comes back, it is not decided in the pane.** The brief tells the implementer to stop
  and report when the range or acceptance is unclear, or when the same check fails twice for the
  same reason. The main session decides and rewrites the brief, or stands up a different role; it
  does not resend the same brief.
- **One writer per file.** Parallel implementers get one worktree each (`playbooks/fan-out.md`,
  step 1 for the shared-write inventory).
- A configured key chooses where the implementer runs. It does not authorize starting one: the
  playbook that calls for the implementer role does, as it did for a `Task`.

## The design role

The design role takes a design question the main session has already framed. It does not explore
the codebase on its own.

- **Hand it** a summary of the facts and the `path:line` each one rests on. It may read whatever it
  needs to refute that summary, and no more: widening the search is the explorer's job.
- **It returns** the option it recommends and the alternatives, then the premises it checked and the
  premises it did not. The main session decides and integrates; an unchecked premise is verified
  there before the design relies on it.
- Where it runs: an agent named `architect` in the owner's agents when there is one (its model is set
  in that definition, not in this repository), otherwise the main session does it, and says so.

## Observable terminal execution

When `pane.driver` is configured, use its installed instructions to run long checks, builds, and
investigation sweeps in a visible pane. Keep the caller's working directory and preserve the user's
focus. Record the returned pane ID, log path, and command exit status; a visible process or a completed
wait is not evidence that its command passed. Preserve pipeline failures when capturing logs with
`tee`. Reuse only panes created for this task and never close another session's pane.

If the driver requires a managed-session marker, check it before controlling panes. From outside that
session, use foreground execution and record the visibility limitation. Do not attach to whichever
unrelated session happens to be focused. Routing configuration selects a driver; it does not authorize
starting extra agents, publication, or other external actions.

### Labels and alerts, when the driver has them

A driver's installed instructions may offer two more things. Use each one only where the
instructions describe it; a driver without them changes nothing in any playbook.

- **A label on a pane**: short text shown beside the pane's agent that changes neither its state nor
  any wait. When a playbook writes a ledger row for work running in a pane, put the same state on
  that pane's label each time the row changes, so the owner can read where it stands without opening
  the ledger. A label is display, never evidence: the ledger and the report file are the record.
- **An alert to the owner**: when something goes up to the owner, raise it as well as writing it in
  the reply. Only for what the owner must decide or do, never for a finished step. An alert the
  driver says was not shown is not retried; the reply is still the record.

## Cockpit routing and briefs

The user-invoked `plumb:cockpit` skill uses the launch command prefixes in the same personal
config. Its [kind table](../skills/cockpit/references/kinds.tsv) supplies the preferred and
baseline roles. `route.<kind>` overrides the preferred role and `route.<kind>.baseline` overrides
the baseline. An unset launch command means the main session does the work. `plumb-route resolve`
shows the selected role, command and reason.

`cockpit.demote_after` defaults to 2 consecutive misses for the preferred role. A hit clears an
unfinished streak. An inconclusive verdict leaves it as it was. The threshold at adjudication
applies to that verdict. A demoted route uses the baseline until the owner runs
`plumb-lane route-reset KIND`. The log retains route history across runs and linked worktrees.
Separate Git repositories have separate cockpit stores, including under a shared artifact root.

A brief spec is JSON. Paths in `allow_paths` are literal and repository-relative. A trailing
slash allows everything under that directory. Use an empty list for read-only kinds. Put the lane
report outside the worktree to keep it out of the collection inventory. Use the same spec file
for `plumb-brief new` and `plumb-lane add`. A registered brief is immutable. Generate changed
contents with `new --rev REV` and register them with `add --rev REV` when the lane has no active
attempt. After a plugin move, `plumb-brief refresh --run RUN --lane LANE --rev REV` updates the
worker instructions path in a new revision for registration. Run, lane, revision and lock names
use ASCII letters, digits, underscores and hyphens. Letters are stored in lowercase.

```json
{
  "title": "Transcribe a parser case",
  "kind": "test-transcription",
  "allow_paths": ["tests/"],
  "material": "The fixture covers an empty record.",
  "do_not_touch": ["Parser implementation"],
  "acceptance": [
    {"id": "empty-record", "description": "The empty record case passes", "check": "python3 -m unittest tests.test_parser"}
  ],
  "report_path": "/tmp/parser-lane.md",
  "forbidden_means": ["Shared database"],
  "locks": ["local-test-runner"]
}
```

The optional `locks` list declares resources a lane holds until adjudication or abandonment.
These resources are shared across runs of this repository. Use `plumb-lane abandon --attempt A
--reason REASON` to release them when an attempt cannot finish. Add `--miss` to count the
abandonment as a route miss. Pass a stable `--event-id` to retrieve the original response on retry.

Keep the same `--work` identifier across lanes or attempts on the same work in a run. Use
`--worktree` and `--base` on `start` to pin the lane checkout and comparison base. Start and
collect require the original base to be an ancestor of the checkout's HEAD. Collection compares
the start and current inventories of untracked files, including ignored paths, and excludes
cockpit artifacts. An out-of-range collection records one miss in its collection event.

Pass the attempt number and head from `collect` as `--attempt` and `--head` to `observe` and
`adjudicate`. Record passes on that attempt before closing it, including manual acceptance items.
A failing observation without a cause can be classified by recording that failed item again
with `--cause`. Use `plumb-lane status` to read and repair the replayed table even when a lane is held.
