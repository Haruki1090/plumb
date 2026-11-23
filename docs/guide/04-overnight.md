# Leaving a run overnight

An unattended run is the same work with nobody awake to decide. Everything you would have answered at
the keyboard has to be written down before you leave. This page is the list, and the first thing to read
when you return. The discipline itself is in `playbooks/autonomous-run.md`; the queue is `plumb:lead`.

## What to settle before you leave

Put these in the request, in your own words. plumb enforces some of them and relies on you for the rest;
each item says which.

- **A done-predicate a machine can judge.** "All 14 listed issues are ready pull requests", "the suite is
  green and the repro no longer fails", "the diff is zero". If a person must judge it, do not run it
  overnight: nobody is awake to judge. A vague goal never stops. plumb writes the predicate as the first
  line of the decision log and will not loosen it to declare victory.
- **A budget.** plumb has no meter that cuts a run off. You set the limit in the predicate: a number of
  iterations, a deadline, a count of lanes (a queue run keeps at most three or four live). Afterwards,
  `plumb-ledger report --since <day> --until <day>` shows what it cost, if `ledger.capture = on`.
- **What may be merged and what must wait.** By default `plumb:lead` stops at a ready pull request and
  merges nothing. It merges on its own only when the base branch's contract lists
  `repo.production_branches` (`docs/project-contract.md`), the pull request's base is neither on that list
  nor the default branch, an independent verdict names the current head, and `plumb-pr-watch` reads
  `ready`. A merge into a production branch is always yours.
- **Where the decision log is.** Ask for the path in the request. Queue runs write theirs under
  `plumb-path run`, as `lead-<issues|prs>-<time>-<pid>.tsv`; a plan run writes `<plan name>.tsv` there. That
  directory is untracked and survives removing a worktree.
- **When it reports.** The run returns when the predicate is met or at a real dead end. Only three things
  go up before then: an irreversible action, a product call no check can settle, and a dead end. Say how
  often you want a heartbeat if you want one, and what counts as a reason to stop and wait.

An example request:

> Work my assigned issues one by one until each is a ready pull request, landed, or waiting on a question
> I can answer in a word. Stop at ready; merge nothing and push nothing to `release`. Stop after six hours
> or twelve pull requests. Keep the decision log and give me its path.

In Japanese:

> 私にアサインされた issue を 1 件ずつ、レディ状態の PR になるか、取り込み済みになるか、一言で答えられる質問に
> なるまで進めてください。マージはせず、`release` には何も push しないでください。6 時間か PR 12 件で止まり、
> 判断ログのパスを教えてください。

## Four conditions before you trust a loop

1. **You did it once by hand.** Either you or the agent has done the task once and seen what it takes.
2. **A tool checks the result.** A test command, a script, a verifier. If the only check is the agent's
   own say-so, it is not a check.
3. **Every step can be stopped.** Nothing in the loop is irreversible without your approval, and you can
   interrupt it at any point.
4. **Earlier transcripts were read.** The failure that repeated across them has been turned into a tool,
   not a reminder. `plumb-session-audit` reads the sessions; `plumb:failure-to-rule` takes a failure to
   the layer that stops it.

If any of the four is missing, run the loop attended.

## What to read first in the morning

The commands live on your agent's path, not your shell's, so ask for them by name.

1. **`plumb:catch-up`.** Start here. It changes nothing and returns four parts: what changed, every
   decision waiting on you with a pick and a one-word answer, what is still moving, and what it could
   not read. Reply to the decisions before you read anything else.
2. **`plumb-run-view`.** Where each lane stands, from the ledger and the forge, with what landed by fact
   and what remains. `--since <hours>` widens the window past the default twelve.
3. **`plumb-stalled`.** Every open pull request by how long it has waited and on whom: ready but unmerged,
   verified but still draft, idle drafts.
4. **The decision log's audit.** `plumb-decision-log <log> --audit` resolves every commit, pull request
   and file the log names. It prints each as resolved or missing and exits 1 when any is missing. A
   commit the log claims that is not there is not evidence; carry every missing line into your reading
   of the report.

A run that cannot produce its log path is not complete, whatever its summary says. If a lane went quiet,
`plumb-lane stale` lists running lanes with no activity for a multiple of their expected time. The
[pitfalls](05-pitfalls.md) page covers what to do next.
