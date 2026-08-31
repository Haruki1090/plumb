# Hillclimb

**You hold the metric and the soundness of the experiment.** You supervise and review; you delegate
the attempts.

Work that improves one measurable thing continuously toward a target. "Make startup 50% faster."
"Keep pushing this number down systematically." A single fix is `playbooks/perf-issue.md`.
**This is a loop.**

There is one core discipline. **One change, one measurement, adopt or revert.** Do not stack
unverified changes. Do not claim a win from having read the code. **The data decides**
(**principle-prove-it-works**).

1. Before you pick the ruler, get hold of the target and of the real load. Name the dimensions that
   can move the result (data volume, history, state, concurrency) and pick the conditions that
   reproduce what the owner is complaining about. **If no condition reproduces it, this is not a
   hillclimb: fix the repro.** Then decide one metric, the direction that counts as better, and the
   stopping predicate. **The stopping predicate pairs a target with a floor on attempts** — the form
   "at least 50% against baseline, and at least 10 attempts". That is what keeps a lucky early hit
   from ending the run.
2. Build the measuring tool, prove its sensitivity, and then freeze it
   (**principle-build-the-lever**). Run contrasting loads and confirm that the condition you aimed at
   reproduces the symptom and that the easy condition separates from it.
   **If the ruler cannot tell the two apart, rebuild the load or the metric.**
   Once frozen, one repeatable command emits the metric. Take samples until you clear the noise
   (the median of N, not one run). **Change it and every earlier number is void.**
   Before the first change, record the baseline and the green regression gate (the tests that have to
   keep passing).
3. Open the decision log. **Before the first attempt.**

   ```bash
   plumb-decision-log <log> --header id hypothesis change before after delta test verdict notes
   plumb-decision-log <log> 1 "<hypothesis>" "<change>" 1200 940 -260 green adopted ""
   ```

   Do not write it by hand: columns slip, tabs get mixed in, and a string that landed in the evidence
   runs as a formula in a spreadsheet (the tool neutralises that. **Bare numbers pass straight
   through, so before, after and delta stay sortable**).
   **This is the run's memory.** Read it before each attempt. Skip that and the search stops
   accumulating and you circle the same spot. Keep it outside the tree (under gitignore) so it
   survives a revert.
4. Ground each hypothesis in the structural understanding from step 1 and **name a concrete
   mechanism**. "Drop X from the startup path, because it blocks first paint." "Try memoizing
   something" is not a hypothesis.
5. Run one hypothesis per attempt.
   - Hand the change to the implementer role in a narrow range and **review the diff instead of
     typing it yourself** (**principle-guard-the-context-window**). If you have several independent
     hypotheses, throw them out in parallel and put them in separate worktrees so they cannot collide
     (**principle-separate-before-serializing-shared-state**).
   - Measure before and after with the frozen tool, and run the regression gate.
   - **Adopt only when the metric moved past the noise and the gate is green.** Otherwise revert every
     change. No "this might help" tweak rides along.
   - One commit per adoption. Stage only the files you touched (`git add <files>`, never `-A`).
     Record the line whether it was adopted or reverted.
6. Get past the first stall. If it fails several times running, change category, combine the near
   misses, re-read the source, try a more extreme option. **Correctness and simplicity outrank the
   number.** Revert a win that broke behavior; keep a simplification that holds the number
   (**principle-laziness-protocol**).
7. Stop when the predicate is met. **Do not loosen the predicate to declare victory.**

   **Stopping short of it passes a bar as hard as the predicate.** "I think what's left is marginal"
   does not let you stop.

   - **The floor on attempts has been reached.** If it has not, you have not earned the right to stop.
   - **Every option still standing is written out.** One line each on why you judged it will not work.
     **That line has to be one of two things.**
     (a) A pointer to an existing line in the decision log: an attempt at the same mechanism already
     failed. (b) A mechanical reason grounded in the structural understanding from step 1, such as
     "this path is only N% of the whole".
     **"Probably won't work" and "looks unpromising" are not reasons.**
     If you cannot write them out, it is not "marginal", it is "not thought about".
   - **A stop short of the target goes through the judge role** (`docs/role-map.md`).
     Hand over the list of what is left and the grounds for cutting each one, and **ask a different
     family whether anything was missed.** Do not take down a target you set yourself on your own
     judgment alone.
   - **Leave the line in the decision log that says you stopped short.** What you reached, the target,
     what is left, why you stopped.

   **A stop missing any of these four invalidates the predicate without rewriting it.**
   Do not read three of them as enough. A stop that skipped the judge role breaks this rule as well.
   Do not quit while cheap untried options remain. If you are stuck, say so instead of circling.
8. Stack the adopted commits in landing order and close out with `playbooks/closing-a-branch.md`.
   **Once a PR is decided on**, go to `playbooks/opening-a-pr.md`. The climb of the metric reads top
   to bottom.

**What you return:** the metric and the target, baseline through final and the rate of change, the
number of attempts (adopted / reverted), one line per adopted fix, the path to the decision log, and
the best option to try next if you push further.
