---
name: lead
description: Coordinates a queue of pull requests or issues end to end. Use when asked to review PRs without naming a single one ("review the PRs", "check the PRs waiting on me", "go through my review requests") or to work the owner's assigned issues ("implement my assigned issues one by one", "clear my queue", "work through my assignments"). Reads the queue from the tracker, drops what already landed, gives each item its own worktree and a visible pane, drives implement or review -> independent check -> ready PR, and reports what needs the owner. For one PR URL use plumb:pr-review; for one bug, playbooks/fixing-a-bug.md.
---

# Lead a queue

**The owner hands over a queue, not a task. You decide the order, hand the work out, hold the
gate, and bring back only what needs the owner.**

## Authorization and the stop line

Invoking this skill is the owner's request for parallel roles; do not ask again before starting
lanes. It authorizes nothing else: no deploy, infrastructure apply, release, branch deletion,
issue closing, or message to anyone, and a merge only by the rule below. Post review comments only
when this request asked.

**Default stop line: a ready PR** (implemented, independently reviewed, checked at the final
commit, pushed, marked ready). A request naming another line ("plan only", "draft only") wins.

**Merge a lane's PR yourself only when the base branch's contract allows it.** A merge cannot be
taken back, so each condition ties it to evidence at the head being merged. Without
`repo.production_branches` in the contract of the PR's base branch, stop at the ready PR: the owner
merges. With the key present, merge only when all four hold:

1. **The base is not production.** It is not listed in `repo.production_branches` and is not the
   default branch of the repository the PR is open against. Ask the forge for both names and
   compare bare branch names: `gh pr view <n> --json baseRefName,url` and, for the repository in
   that URL, `gh repo view <owner>/<name> --json defaultBranchRef`. A local ref such as
   `origin/HEAD` can be stale, absent or a fork's; do not use it. Read the list from the base
   branch's copy in that same repository, never the PR head's and never a fork's, because a head
   must not grant itself merge rights (`plumb:verify` trusts the base contract the same way):
   fetch `<base>` from the remote whose URL is that repository, make a throwaway worktree at the
   fetched commit and run `plumb-project --json repo.production_branches` in it. No such remote,
   a default branch you could not read, or any outcome but `set` fails this condition. A PR that
   changes `.plumb/project.toml` stays a ready PR.
2. **A passing verdict covers this head.** The independent reviewer seat's verdict is a pass with
   no finding left open, and it names the PR's current head SHA. A failing verdict, a verdict you
   wrote yourself, or one for an older head does not count; after a rebase or a fix, redo the
   re-check in `playbooks/landing-a-stack.md`, step 3.
3. **The PR is ready.** `plumb-pr-watch <n>` prints `ready`, with no `merge=blocked` and no
   `review=` detail asking for changes or a review.
4. **It is on the ledger first.** The PR's row (`ready-pr`, `next` = merge) carries the verdict's
   SHA and the `plumb-pr-watch` output before you merge.

Merge with the repository's own method, once, pinned to the verdict's SHA
(`gh pr merge <n> --match-head-commit <sha>`), so a push that lands after the checks is refused
instead of merged. Immediately before that command read `baseRefName` again: a base that differs
from the one condition 1 checked voids all four conditions. After it, the read-back below checks the
base once more; a merge that landed on any other branch goes up at once as an incident. Never force it, never bypass a required check, never
use an admin override, never delete the branch; when the forge refuses, the PR stays ready and goes
up. Then read back: `plumb-pr-watch <n>` prints `merged` and the merge commit
(`gh pr view <n> --json mergeCommit`) is an ancestor of the base branch condition 1 checked, after a fetch from that repository. Write a
`merged` row with that commit; a read-back that fails goes up as it is. Anything that targets a
production branch, or fails a condition, stays a ready PR and goes up to the owner. Pull requests
read for review (`references/pr-queue.md`) are never merged by this rule.

The repository's instruction files win on base branch, branch naming, check commands, PR template
and anything they forbid. Read them first.

## Seats

| Seat | Who | Never |
|---|---|---|
| Coordinator | The main session | Writes lane code or carries lane history (**principle-guard-the-context-window**) |
| Implementer, one per lane | `role.implementer`, else `role.bulk`, else the implementer role's `Task` (`docs/role-map.md`) | Pushes, opens PRs, reviews itself, writes spec or plan files |
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
    plumb-decision-log "$log" --header item state lane evidence next ref

Use that name exactly: another coordinator may be running, and a shared ledger mixes two queues.
Write one line per item, and one line each time an item changes state.
`ref` is the lane's branch as `branch:<name>` from the row that starts the lane, and `pr:<number>` from the
row that opens or names its pull request; `-` when there is none. It is a pointer for `plumb-run-view`, not a state.

**2 Triage.** An open issue is a claim that work is missing; check it first.
When the queue is pull requests, `plumb-stalled` first shows what already waits on the owner (ready but
unmerged, and idle drafts) before you start new lanes. Verified-but-still-draft needs the repository's
evidence line as `--verified-pattern`; merged-but-unpromoted needs `--promoted-ref`.
**Keep the bodies out of your context.** Pull the queue, merged PRs and open PRs once, as JSON
files, and match them with a script (`playbooks/batching-chatty-tools.md`). With more than ten
items, hand each item's reading to the explorer role and take back one ledger row per item
(state, one-line evidence). You read only the rows.
Search **merged** PRs for each item (closing keywords act only on the default branch, so work
merged elsewhere leaves the issue open), then **read what the PR says about it**: "split out to
#N" is a mention, not a fix. Confirm on the current base's code -> `landed`. Search **open** PRs ->
`has-pr`: continue or review that PR, never a duplicate. **An item that already has a fix** (an open
or merged PR that plausibly addresses it) **is verified, not rebuilt**: reproduce the symptom twice
on the baseline, see it gone twice on the fix, through the project's own verification when the
contract has one (`plumb:verify`). The outcome is exactly one of `confirmed`, `insufficient fix`
or `inconclusive`, and no competing PR is opened. Read the code, not the issue body.
Every other item gets exactly one state:

| State | Meaning |
|---|---|
| `ready` | Buildable now from what is written and decided |
| `needs-ruling` | A decision changes what gets built (`plumb:decision-brief`) |
| `needs-shape` | What to build is still open (`playbooks/shaping-the-work.md`) |
| `owner-task` | Only a person can do it: production access, another system, a legal call |
| `blocked` | Waits on another item or a later phase; name it |

Ask only the rulings that block the first lanes, in one batch.

**3 Decompose.** Dependencies, parallel work, or several sources of truth that need coordination
(`plumb:graph`) -> draw the graph; otherwise a lane list. One lane = one item (or one bundle sharing a source of truth) = one branch = one worktree.
Inventory shared writes first (`playbooks/fan-out.md`, step 1): same file, migration numbering,
lockfile, generated contracts -> bundle or serialize. **At most 3-4 live lanes.** Checks that take
the whole machine run one at a time.

**4 Lanes up**, all in one reply: a worktree from the explicit base ref
(`playbooks/worktree-setup.md`), a tab per lane without taking the owner's focus, the implementer
started through the driver under `lane-<item>`, and the brief written as a file from
[references/lane-brief.md](references/lane-brief.md). Record each lane's starting commit.

**5 Loop.** Wait on the driver's agent state, never a sleep loop. After compaction or on resume,
`plumb-run-view` gives the lanes, what is done by fact, and what remains, from the ledger and the tracker.
Every ledger line for a lane also goes on that lane's pane label when the driver has one
(`docs/role-map.md`, labels and alerts).
On each wake of a cockpit run, run `plumb-lane stale`: a stale lane is inspected at its worktree and
replaced, not waited on.
A lane's pull request is read with `plumb-pr-watch <n>` (one word, one exit code), never by re-reading
`gh` output; `--wait` replaces a poll loop.
- *blocked*: read the prompt first. Relay an approval only inside the brief's range and
  reversible; anything else goes up
- *done*: read the report file, diff from the starting commit
  (`playbooks/running-a-plan.md`, step 4), review in the separate seat, rework to the same
  implementer with the cap from step 5 there. **The seat blocks only on a problem it can show at
  this head** (a run that fails here, a line this change made false). A problem the base already
  had is one line in the report, and blocks only if this change copied it or newly made it reachable
- *passed*: run the repository's checks once at the final commit and record SHA and exit status;
  push, open by `playbooks/opening-a-pr.md` with the template (UI changed -> screenshots), mark
  ready, ledger `ready-pr`, refill the slot; then merge only if the stop line's rule allows it

Queue outlasting the session -> layer `playbooks/autonomous-run.md`; predicate: every item is
`ready-pr`, `landed`, `needs-ruling` with the question asked, or escalated with a reason.

**6 Report.** One row per item: final state, PR or evidence, checked SHA, what the owner must do.
A lane that did work its item never named (code restored from another branch, a second
component) says so in its row and in the PR body.
Then the ledger path. **A report without the ledger path is not complete.**

## What goes up

Only: an irreversible or outward-facing action, a product call no check settles, an approval
outside a lane's range, a real dead end, a merge the stop line does not allow, and a gate a lane
wants loosened. Raise the driver's alert with it when the driver has one, never for a lane
that only finished. Decide the rest and log it
(**principle-never-block-on-the-human**). Known failure shapes:
[references/failure-modes.md](references/failure-modes.md).

**Loosening a gate is never a lane's own decision**: raising a budget or threshold, adding to an
allowlist, disabling or soft-failing a check. It needs the verifying seat's proof that the gate was
wrong and the coordinator's countersign in the ledger, and a disabled check gets a row saying when
it is restored.
