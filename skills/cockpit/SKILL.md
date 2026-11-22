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
   Omit `--worktree` on retry to reuse the recorded checkout, even after a move. To switch
   checkouts, pass `--worktree DIR --rebase-baseline` to capture a new first-start snapshot and
   protection set for the lane. The original base commit still applies. Sparse checkouts and
   sparse indexes hold at start with `sparse-checkout`.
4. Run `plumb-lane collect --run R --lane L --json` and read the worker's report. Run each acceptance
   check yourself against the collected commit. Pass the returned attempt and commit as `--attempt`
   and `--head` to `plumb-lane observe` and `plumb-lane adjudicate`. Both commands hold with
   `dirty-checkout` if the Git tree or the protected fingerprints changed after collection.
   Collect already records the verdict for an out-of-range attempt. If an attempt cannot finish, run
   `plumb-lane abandon --run R --lane L --attempt A --reason REASON` to release its resources.
   Add `--miss` when the abandonment should count as a routing miss.
5. Ask `plumb-lane guard` what can proceed and `plumb-lane status` for the run's lanes. Use
   `plumb-lane close` when the acceptance evidence is complete. When a hold needs intervention,
   record the new diagnosis, hypothesis and distinguishing test with `plumb-lane resume`.

Use relative paths under **Do not touch**. `start` removes `.` components and rejects absolute
paths and `..` components. Collection checks existing ignored files, missing paths that later
appear, and protected directories against the lane's baseline. Directories are checked entry by
entry. A protected directory with over 10,000 entries in scope holds at start with `protected-too-large`.

### Known limits

- Ordinary ignored test caches are outside collection. Tests that write a tracked fixture or
  leave a non-ignored file outside the allowed range can trigger `out-of-range`.
- Collection measures net worktree state. Restoring an edit, committing and resetting to the
  same tree, or committing byte-identical pre-existing untracked content can leave an empty
  changed-path list. The collected HEAD is recorded separately.
- Git clean filters and line-ending normalization can map different worktree bytes to the same
  blob. The tree normally tracks the executable bit. Protected fingerprints retain full mode bits.
- Ignored files outside the baseline protection set and cockpit artifacts are outside collection.
  Nested repositories are visible through HEAD only. Shared services, other checkouts, network
  activity and other changes outside the worktree are outside collection. Snapshot checks assume
  a quiescent worktree and cannot establish what a test read between checks.
- The temporary index can miss ignored files force-added to the real index before their first commit.
- On a case-insensitive checkout, the temporary index can miss a case-only rename until it is committed.
- With `core.fileMode=false`, the tree can miss an executable-bit change on an otherwise unchanged file.

Collect catches careless lane work. A hostile lane can evade it. Enforce the
[worker rules](references/worker.md) for these boundaries during review.
