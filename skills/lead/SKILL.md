---
name: lead
description: Coordinates a queue of pull requests or issues end to end. Use when asked to review PRs without naming a single one ("review the PRs", "check the PRs waiting on me", "go through my review requests") or to work the owner's assigned issues ("implement my assigned issues one by one", "clear my queue", "work through my assignments"). Reads the queue from the tracker, drops what already landed, gives each item its own worktree and a visible pane, drives implement or review -> independent check -> ready PR, and reports what needs the owner. For one PR URL use plumb:pr-review; for one bug, playbooks/fixing-a-bug.md.
---

# Lead a queue

**The owner hands over a queue, not a task. You decide the order, hand the work out, hold the
gate, and bring back only what needs the owner.**

## Authorization and the stop line

Invoking this skill is the owner's request for parallel roles; do not ask again before starting
lanes. It authorizes nothing else: no merge, deploy, infrastructure apply, release, branch
deletion, issue closing, or message to anyone. Post review comments only when this request asked.

**Default stop line: a ready PR** (implemented, independently reviewed, checked at the final
commit, pushed, marked ready). A request naming another line ("plan only", "draft only") wins.

The repository's instruction files win on base branch, branch naming, check commands, PR template
and anything they forbid. Read them first.

## Seats

| Seat | Who | Never |
|---|---|---|
| Coordinator | The main session | Writes lane code or carries lane history (**principle-guard-the-context-window**) |
| Implementer, one per lane | `role.bulk`, else the implementer role (`docs/role-map.md`) | Pushes, opens PRs, reviews itself, writes spec or plan files |
| Reviewer | `role.judge`, else a fresh seat | Edits the code under review |

Lanes run through `pane.driver`, one tab per lane. Unset -> isolated subagents and
`skip: pane.driver unset — lanes are not visible`.

## Checklist

Copy it into your todo list and keep it current.

```
- [ ] 1 Intake: queue read from the tracker, ledger opened
- [ ] 2 Triage: every item has one state, rulings asked in one batch
- [ ] 3 Decompose: lanes, shared-write inventory, live cap
- [ ] 4 Lanes up: worktree + tab + brief file per lane   (stop here on "plan only")
- [ ] 5 Loop: review -> rework -> checks -> ready PR, slots refilled
- [ ] 6 Report: one row per item + ledger path
```

**1 Intake.** Read the queue from the tracker, not from the ask. Issues: open and assigned to the
owner. PRs: requesting the owner's review or authored by the owner (then read
[references/pr-queue.md](references/pr-queue.md)). Open the ledger before anything else:

    log="$(plumb-path run --mkdir)/lead-<issues|prs>-$(date +%Y%m%d-%H%M%S)-$$.tsv"
    plumb-decision-log "$log" --header item state lane evidence next

Use that name exactly: another coordinator may be running, and a shared ledger mixes two queues.
Write one line per item, and one line each time an item changes state.

**2 Triage.** An open issue is a claim that work is missing; check it first.
**Keep the bodies out of your context.** Pull the queue, merged PRs and open PRs once, as JSON
files, and match them with a script (`playbooks/batching-chatty-tools.md`). With more than ten
items, hand each item's reading to the explorer role and take back one ledger row per item
(state, one-line evidence). You read only the rows.
Search **merged** PRs for each item (closing keywords act only on the default branch, so work
merged elsewhere leaves the issue open), then **read what the PR says about it**: "split out to
#N" is a mention, not a fix. Confirm on the current base's code -> `landed`. Search **open** PRs ->
`has-pr`: continue or review that PR, never a duplicate. Read the code, not the issue body.
Every other item gets exactly one state:

| State | Meaning |
|---|---|
| `ready` | Buildable now from what is written and decided |
| `needs-ruling` | A decision changes what gets built (`plumb:decision-brief`) |
| `needs-shape` | What to build is still open (`playbooks/shaping-the-work.md`) |
| `owner-task` | Only a person can do it: production access, another system, a legal call |
| `blocked` | Waits on another item or a later phase; name it |

Ask only the rulings that block the first lanes, in one batch.

**3 Decompose.** Two or more signals from `plumb:graph` -> draw the graph; otherwise a lane
list. One lane = one item (or one bundle sharing a source of truth) = one branch = one worktree.
Inventory shared writes first (`playbooks/fan-out.md`, step 1): same file, migration numbering,
lockfile, generated contracts -> bundle or serialize. **At most 3-4 live lanes.** Checks that take
the whole machine run one at a time.

**4 Lanes up**, all in one reply: a worktree from the explicit base ref
(`playbooks/worktree-setup.md`), a tab per lane without taking the owner's focus, the implementer
started through the driver under `lane-<item>`, and the brief written as a file from
[references/lane-brief.md](references/lane-brief.md). Record each lane's starting commit.

**5 Loop.** Wait on the driver's agent state, never a sleep loop.
- *blocked*: read the prompt first. Relay an approval only inside the brief's range and
  reversible; anything else goes up
- *done*: read the report file, diff from the starting commit
  (`playbooks/running-a-plan.md`, step 4), review in the separate seat, rework to the same
  implementer with the cap from step 5 there
- *passed*: run the repository's checks once at the final commit and record SHA and exit status;
  push, open by `playbooks/opening-a-pr.md` with the template (UI changed -> screenshots), mark
  ready, ledger `ready-pr`, refill the slot

Queue outlasting the session -> layer `playbooks/autonomous-run.md`; predicate: every item is
`ready-pr`, `landed`, `needs-ruling` with the question asked, or escalated with a reason.

**6 Report.** One row per item: final state, PR or evidence, checked SHA, what the owner must do.
Then the ledger path. **A report without the ledger path is not complete.**

## What goes up

Only: an irreversible or outward-facing action, a product call no check settles, an approval
outside a lane's range, a real dead end. Decide the rest and log it
(**principle-never-block-on-the-human**). Known failure shapes:
[references/failure-modes.md](references/failure-modes.md).
