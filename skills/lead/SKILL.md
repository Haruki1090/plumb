---
name: lead
description: Run a queue end to end as the coordinator - "review the open PRs", "implement the issues assigned to me one by one", "clear my queue", "work through my assignments". Reads the queue from the tracker, drops what already landed, decomposes, gives each unit its own worktree and a visible pane, drives implement -> independent review -> rework -> local checks -> ready PR, and reports what needs the owner. Use when the ask names a queue of PRs or issues rather than one change. For a single PR review use plumb:pr-review; for one bug, playbooks/fixing-a-bug.md.
---

# Lead a queue

**The owner hands over a queue, not a task. You are the coordinator: you decide the order, hand
the work out, hold the gate, and bring back only what needs the owner.**

"Review the PRs." "Implement what is assigned to me, one at a time." Those asks name no files and
no design. Filling that gap by guessing is what this skill replaces with a fixed route.

## Authorization and the stop line

**Invoking this skill is the owner's request for parallel roles.** You do not ask again before
starting lanes. It authorizes nothing else: no merge, deploy, infrastructure apply, release,
branch deletion, issue closing, or message to anyone. Review comments are posted only when the
owner asked for them in this request.

**The default stop line is a ready PR** — implemented, independently reviewed, locally checked at
the final commit, pushed, opened and marked ready. The owner merges. A request that names a
different line ("draft only", "stop after the review") overrides it.

**The repository's instruction files win over this skill** on base branch, branch naming, local
check commands, PR template and anything they forbid. Read them before step 1.

## 0. Seats

| Seat | Who | Does not |
|---|---|---|
| Coordinator | The main session | Write lane code. Carry lane history in its context (**principle-guard-the-context-window**) |
| Implementer, one per lane | `role.bulk` if set, else the implementer role (`docs/role-map.md`) | Push, open PRs, stand up its own reviewer, write spec or plan files |
| Reviewer | `role.judge` if set, else a fresh seat that did not implement | Edit the code under review |

Every seat runs where the owner can see it: through `pane.driver`, one tab per lane. With
`pane.driver` unset, run lanes as isolated subagents and say `skip: pane.driver unset — lanes are
not visible`.

## 1. Intake: the queue as data

Read the queue from the tracker, not from memory or from the ask.

- **PR queue:** open PRs that request the owner's review, or that the owner authored — number,
  base, head SHA, draft state, check state, size.
- **Issue queue:** open issues assigned to the owner — number, title, labels, linked PRs.

Open the ledger before anything else and write one line per item. **Compaction erases memory; the
ledger survives it.**

    log="$(plumb-path run --mkdir)/lead-$(date +%Y%m%d-%H%M).tsv"
    plumb-decision-log "$log" --header item state lane evidence next
    plumb-decision-log "$log" 0 intake - "<query you ran>" "<N items>"

## 2. Triage: drop what already landed

**An open issue is a claim that work is missing. Check it before you build it.**

1. **Search merged PRs for each issue**, not only linked ones. Closing keywords only act on the
   default branch, so work merged into an integration branch leaves its issue open. Landed ->
   state `landed`, evidence = the merged PR. Propose closing; do not close.
2. **Search open PRs for each issue.** One exists -> the lane continues or reviews that PR. Never
   open a duplicate.
3. **Read the code on the current base**, not the issue body. Issue bodies go stale before code.
4. Classify every remaining item into exactly one state:

| State | Next |
|---|---|
| `ready` | Becomes a lane |
| `needs-ruling` | A choice that changes what gets built -> `plumb:decision-brief` |
| `needs-shape` | What to build is still open -> `playbooks/shaping-the-work.md` before it is a lane |
| `blocked` | Waits on another item; record which |

**Ask the rulings in one batch, and only the ones that block the first lanes.** The rest ride
behind the running lanes (`plumb:graph`, step 7). Do not hold every lane for one open question.

## 3. Decompose

- **Two or more signals from the top of `plumb:graph` -> draw the graph.** Fewer -> a lane list.
- **One lane = one item (or one bundle sharing a source of truth) = one branch = one worktree.**
- **Inventory the shared writes before you fan out** (`playbooks/fan-out.md`, step 1): the same
  file, migration numbering, a lockfile, generated contracts. Overlap -> bundle the lanes or run
  them in series. Never two writers on one surface.
- **Cap live lanes at three or four.** The limit is your reading and the owner's approvals, not
  machine capacity. Checks that start containers or take the whole machine run **one at a time**;
  queue them.

## 4. Stand up the lanes

For each lane, in one reply:

1. **Worktree from the repository's base branch, with the base ref explicit**
   (`playbooks/worktree-setup.md`). Gitignored files are not copied; hand over absolute paths to
   the ones the lane needs.
2. **A tab per lane through `pane.driver`**, labeled `<item> <short title>`, without taking the
   owner's focus. Start the implementer in it under a unique name (`lane-<item>`), using the
   driver's agent-start command so the driver tracks its state.
3. **The brief as a file.** The four parts of `playbooks/fan-out.md` step 2, plus:
   - the acceptance criteria and the checks to run
   - commit locally; do not push, open a PR, or create spec or plan files
   - do not open extra panes or tabs
   - write the report to `<path>`; reply with the path only (long pane output is lost on the
     alternate screen)
4. Record the starting commit on the lane's ledger line.

## 5. The lane loop

Wait on the driver's agent state, not on a sleep loop. Layer `playbooks/autonomous-run.md` when
the queue will outlast the session; its termination predicate is **every item is `ready-pr`,
`landed`, `needs-ruling` with the question asked, or escalated with a reason**.

| Lane state | Coordinator action |
|---|---|
| working | Nothing. Work another lane |
| blocked | **Read the prompt before answering.** Relay an approval only when it is inside the brief's range and reversible. Anything else goes up. Never send keys you have not read the screen for |
| done | Read the report file. Diff against the starting commit (`playbooks/running-a-plan.md`, step 4) |

Then, per lane:

1. **Review in a separate seat** with the brief, the report and the diff as files. The reviewer
   refutes; it does not edit.
2. **Rework goes back to the same implementer**, capped as in `playbooks/running-a-plan.md`,
   step 5. You rule when the cap is hit.
3. **Local checks once, at the final commit**, with the repository's commands. Record the SHA and
   exit status. A quiet pane is not a pass (**principle-gate-claims-on-evidence**).
4. **Push and open the PR** by `playbooks/opening-a-pr.md` and the repository's template. UI
   changed -> screenshots in the body (`plumb:graph`, step 10). Mark it ready.
5. Ledger line: `ready-pr`, PR URL, checked SHA. **Refill the freed slot from the queue.**

### The PR-queue variant

Each PR is a lane whose seat is a reviewer, not an implementer. Run `plumb:pr-review` per PR at a
depth set by risk: a small, reversible PR gets one clean pass; an irreversible or authentication
change gets the full stages. Verdicts go to files. **Do not fix the PR under review** — findings go
back to its author, or, when the owner is the author and asked for fixes, to a separate
implementer lane.

## 6. Report

One table, one row per queue item: item, final state, PR or evidence, the SHA the checks ran on,
and what the owner must do. Then the ledger path. Put every open ruling into **one** question
batch. **A report without the ledger path is not complete.**

## What goes up to the owner

Only these: an irreversible or outward-facing action, a product or taste call no check can
settle, an approval prompt outside a lane's range, and a real dead end. Decide everything else,
write it on the ledger, and keep the lanes moving (**principle-never-block-on-the-human**).

## How this breaks

- **Built an issue that had already landed** -> step 2.1. Search merged PRs first
- **Opened a second PR for work already in review** -> step 2.2
- **Two lanes rewrote the same file** -> step 3. The inventory comes before the fan-out
- **Five lanes, and the owner's approvals became the bottleneck** -> the cap in step 3
- **Heavy checks run side by side and all stalled** -> one at a time
- **Pressed enter on an approval without reading it** -> the blocked row in step 5
- **The implementer's answer vanished from the pane** -> the report file in step 4
- **The coordinator started writing lane code** -> seat table. Hand it back to the lane
- **Reported "done" from the lane's self-report** -> steps 5.1 and 5.3
