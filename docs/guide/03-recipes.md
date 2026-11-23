# Recipes

Twelve situations, each with a prompt to paste, the router entry it lands on, and what comes back. The
entry names are the ones in the index of the root `SKILL.md`. Replace the nouns with yours.

### 1. A test fails one run in five
> `test_sync_retries` fails about one run in five on CI and never locally. Find the cause and fix it. Done means 50 consecutive runs pass, and no sleep was added to get there. Show me the failing output first.

Lands on `playbooks/fixing-a-bug.md`. You get the pinned repro with its output before the fix, the root cause, the change, the same command after it, and the repro kept as a test.

### 2. Why is it this way
> Why does the billing service round per line item instead of per invoice? Answer from the commit history and review threads, not from guesses. Change no code.

Lands on `playbooks/investigation.md`. You get the answer with `path:line` citations, the author's own words from the commit or review where they exist, inference marked as inference, and a plain "the record does not say" when it does not.

### 3. Shape and plan a feature
> Users should be able to pause a subscription. Shape it: read how cancellation works today, show me the options that change what we build, and recommend one. After I pick, write the plan.

Lands on `playbooks/shaping-the-work.md`, then `playbooks/writing-a-plan.md`; a real choice reaches you through `plumb:decision-brief`. You get the options on the same axes with a recommendation, then a plan path, its task count and a table mapping each requirement to a task.

### 4. Run a plan
> Run the plan at `.plumb/plans/pause-subscription.md`, one task at a time, and review each task before the next. Stop at a ready pull request; I merge.

Lands on `playbooks/running-a-plan.md`. You get a ledger path, each task's start and landing commits, which tasks needed rework, every ruling the agent made and why, deferred findings, and the whole-branch review result.

### 5. Review a pull request
> Review https://github.com/acme/shop/pull/412 as the approver. Do not edit the code.

Lands on `plumb:pr-review`. You get the SHA reviewed, an approval decision, findings split into blocking, fix before merge and recorded only, each marked `CONFIRMED` or `PLAUSIBLE`, the residual risk accepted, and a list of what was not looked at.

### 6. Check a change against its base
> Verify this branch against main: does the checkout flow still work? Tell me what you compared and what you did not.

Lands on `plumb:verify`. You get a result file reading `no_diff`, `regressed` or `incomplete`, the scope compared on both sides, what was not compared and why, and the thresholds' status. It never says "pass".

### 7. Give a repository its first verify contract
> We have no verify contract. Set up verification for this repo, starting with the login flow. Do not touch product code.

Lands on `plumb:verify-init`. You get the files written, one feature proven on a base and a head, which of the five facts (surface, run, drive, observe, isolate) were found by running and which were asked of you, the paths still unowned, and provisional thresholds.

### 8. Work a queue overnight
> Implement the issues assigned to me one by one. Stop each at a ready pull request. Do not merge anything. Stop when every item is a ready pull request, landed, or waiting on a question I can answer in a word.

Lands on `plumb:lead`, layered with `playbooks/autonomous-run.md`. You get one row per item with its state, pull request, checked SHA and what you must do, and the ledger path. [Overnight](04-overnight.md) covers what to settle first.

### 9. Come back and catch up
> Catch me up. What happened while I was away, and what is waiting on me?

Lands on `plumb:catch-up`. You get four parts: what changed, every decision waiting on you with a pick, evidence, the cost if wrong and a one-word answer, what is moving without you, and what could not be read. It changes nothing.

### 10. Make one failure never happen again
> The agent merged a migration without running it (issue 87, labelled agent-failure). Turn this into the change that stops it next time, with a number that shows whether it worked.

Lands on `plumb:failure-to-rule`. You get what happened, why the agent did not notice, the same pattern found elsewhere, the layer that should stop it, the measurement and a drafted change. A rule for your CI is proposed and never landed.

### 11. The weekly look back
> Run the weekly retro for last week.

Lands on `plumb:retro`. You get a review with rework, cost per task and failures by code, last week's proposals and whether their numbers moved, and at most three changes, each with an owner and a number to watch.

### 12. Cut a slow path
> The report export takes 40 seconds for large accounts. Get it under 10. Measure first and show me the baseline with run count and spread; do not claim a win from reading code.

Lands on `playbooks/perf-issue.md`; for pushing one metric down continuously, ask for `playbooks/hillclimb.md`. You get the baseline, the value after, the delta with run count and error count, the limiter and a verdict.

## In Japanese

> 週に 1 度失敗するテストを直してください。完了条件は、連続 50 回の実行で通ることです。sleep の追加は不可です。まず失敗する出力を見せてください。

## Also useful

`plumb:recall` rebuilds a topic that spans several sessions, with each thread's state checked against git. `plumb:reflect` proposes what to change after a session and applies nothing until you approve. `plumb:help` answers how to use plumb and never starts the work.
