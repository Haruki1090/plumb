---
name: cockpit
description: Coordinate a run as the main session with routed lane attempts, shared briefs, and recorded acceptance evidence. Invoke explicitly to use cockpit mode.
disable-model-invocation: true
---

# Cockpit

Keep the main session as the writer of lane events. Resolve commands from the plugin's `bin/`
directory. The command help describes each argument.

1. Run `plumb-lane init --run R`. Classify each lane using [kinds.tsv](references/kinds.tsv) and ask
   `plumb-route resolve KIND` where the work would run.
2. Write a brief spec using the [format in the role map](../../docs/role-map.md). Run
   `plumb-brief new --run R --lane L --spec FILE`, then `plumb-brief check BRIEF`. Register it with
   `plumb-lane add --run R --lane L --work WORK --spec FILE`. To revise a registered brief, use
   `--rev REVISION` with both `new` and `add` when the lane is idle. After a plugin move, use
   `plumb-brief refresh --run R --lane L --rev REVISION` in place of `new`.
3. Run `plumb-lane start --run R --lane L --worktree DIR --base REV --json`. On an accepted start, use
   the command in the recorded event. If unset, the main session does the work. Otherwise send the
   worker the brief path and wait through `pane.driver` using its own instructions. Include the
   recorded diagnosis, hypothesis and distinguishing test when retrying after a resume.
4. Run `plumb-lane collect --run R --lane L --json` and read the worker's report. Run each acceptance
   check yourself against the collected commit. Pass the returned attempt and commit as `--attempt`
   and `--head` to `plumb-lane observe` and `plumb-lane adjudicate`. Collect already records the
   verdict for an out-of-range attempt. If an attempt cannot finish, run
   `plumb-lane abandon --run R --lane L --attempt A --reason REASON` to release its resources.
   Add `--miss` when the abandonment should count as a routing miss.
5. Ask `plumb-lane guard` what can proceed and `plumb-lane status` for the run's lanes. Use
   `plumb-lane close` when the acceptance evidence is complete. When a hold needs intervention,
   record the new diagnosis, hypothesis and distinguishing test with `plumb-lane resume`.
