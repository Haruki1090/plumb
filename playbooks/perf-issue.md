# Performance

**You hold the story the measurements tell.** Tie every fix to a measurement. Do not let reading the
source stand in for measuring.

1. Capture the baseline trace from the real thing (**principle-prove-it-works**). Put the capture in a
   pane (`pane.driver`; if it is unset, run it in the foreground).
2. Put the hypothesis on the ground. **Do not talk about the performance ceiling before you have run
   anything.**

   Most fixes come out of the eight families below. **Use them as a source of hypotheses, not as a
   checklist.** A family is worth an attempt only when the trace shows the signal that family names.
   One point of focus on the dominant cost is stronger than hitting all eight.

   | Family | When it applies |
   |---|---|
   | **Elimination** | It did not need to run at all. Computation nobody consumes, a flag that is always off, a redundant sync, an old path kept just in case. **A trace shows you "slow" and never "removable"**, so this is the one family that takes reading. When it applies, it beats every other family |
   | **Splitting** | The dominant cost is proportional to the input size. Cut what each piece touches, or run independent pieces in parallel |
   | **Caching** | The same computation or fetch repeats on the same input. **Do not claim a win until you can say what invalidates it** |
   | **Indirection** | A hot path is doing expensive work a cheap intermediate can absorb. An index instead of a scan; a queue that takes it off the interactive thread. **Only when what you remove outweighs what you add.** A layer that does not reduce work is pure cost |
   | **Batching** | Small operations are each paying a fixed cost. Fold them into one |
   | **Redundancy** | The wait hangs on a single slow attempt. Duplicate it and take the faster one. **You pay in load, so only when the trace shows the wait dominates and there is headroom** |
   | **Deferral** | Cost is riding on a result that is unused, or not needed yet. Delay it to first use |
   | **Scheduling** | The work is needed, but not at that moment. Move it where nobody is waiting. Unlike deferral it can also mean running it **earlier**. What it moves is the felt experience, so measure the interactive path |
3. Build the fix out of the trace. If it crosses a function boundary, split the design first.
   Hand the implementation to the implementer role; the main session reviews the diff. Capture the
   trace after the fix. Verify each attempt before you move to the next
   (**principle-sequence-verifiable-units**).
4. Put the artifacts side by side. **"Cannot be judged" and a measurement on a different surface are
   not a pass.** Write that down as such.
5. Close out with `playbooks/closing-a-branch.md`. **Once a PR is decided on**, go to
   `playbooks/opening-a-pr.md`. Put the measured numbers in the body.

If it is not one fix but pushing one metric down continuously, `playbooks/hillclimb.md`.

**What you return:** the baseline, the value after the fix, the delta, the paths to the artifacts.
