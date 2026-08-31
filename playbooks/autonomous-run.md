# Keep it running

**You hold the termination predicate. Decide what counts as done, and drive there without stopping.**

"I'm going to bed, keep going." "Run it until it's finished." "Until X."

**What this playbook holds is the property of *running long*, not the substance of the work.**
So it is not exclusive with the other playbooks. You **stack it on top of them**.

| Substance | Playbook | If it crosses a night |
|---|---|---|
| Execute a plan task by task | `playbooks/running-a-plan.md` | **The termination predicate and the checkpoints live here** |
| Keep pushing one measurable number down | `playbooks/hillclimb.md` | Same. The stopping condition from hillclimb overrides |
| A long job that is neither | **This playbook alone** | |

**"I made a plan file, so I move to `running-a-plan`" is not a way out.** What that one holds
is the discipline of handing out a single task and putting it through a gate; **it holds no
discipline for crossing a night.**
**Do not read producing one artifact as releasing you from this playbook.**

The wake-up mechanism belongs to `/loop` and `ScheduleWakeup`. **What this playbook holds is the
discipline.**

1. **Before the first iteration, write the termination predicate in a checkable form.**
   "The tests are green." "The repro is fixed." "All N of them landed." "The diff is zero."
   **A vague goal never stops. You can stop because there is a predicate.**
2. Decide how you wake. **If there is something to wait on, watch it** (CI, a merge, a ref moving
   forward). Put a long time-based heartbeat behind it as backup. If there is nothing to watch,
   use a fixed heartbeat at **the interval that makes going to look worth it**.
   That is `/loop` and `ScheduleWakeup`'s territory.
3. **Each iteration makes only the smallest change the evidence justifies.** Verify it against the
   predicate; commit if it moved forward, and **revert every change** if it did not.
   **"This might work" is a hypothesis, not a fix.** Do not let it ride along.
   Verify each unit before you go to the next (**principle-sequence-verifiable-units**).
4. **Whatever you find on the way, you clear it yourself.** A broken tool, an adjacent bug,
   a flaky verifier, review noise, a follow-up nobody picked up. **Do not stack it on the human**
   (**principle-never-block-on-the-human**). Split a fix that strays from the main thread of the work into its own change.

   **Only three things go up.** An irreversible operation. A product or taste call no experiment can
   settle. A real dead end. **Decide everything else, record it, and move.**
   Keep the predicate as the main drive and return to it after every detour.
5. **Leave a checkpoint every iteration.**

   ```bash
   # create it before the first iteration. the predicate goes in here too
   plumb-decision-log <log> --header iteration did why evidence predicate-moved
   plumb-decision-log <log> 0 "fix the predicate" "<the predicate in full>" "-" "-"
   plumb-decision-log <log> 1 "<what you did>" "<why>" "<evidence>" yes
   ```

   **Create it afterwards and the iterations up to that point never existed.**
   **Exactly one line per iteration.** Line 0 is the predicate, and stopping adds one more line.
   If you skipped an iteration, **write the reason on that iteration's line**. Do not skip without
   making the line. **A run with no trace can neither be audited nor resumed.**
   When you judge that context compaction is close, run step 4 of `playbooks/pause-safely.md`
   and then continue.
6. **Stop when the predicate is met. Stalled is not stopped.**
   If it fails several times running, change the method and push through.
   **Do not loosen the predicate to declare victory.**

   Stopping short of it goes through the same **four** as `playbooks/hillclimb.md`.

   - **A floor.** hillclimb holds it as a number of attempts; here there is no single metric, so
     the floor is **which part of the predicate moved, over how many iterations, and how far**.
     **If nothing ever moved, you have not earned the right to stop.**
   - **Write out every option still standing.** Give each one either a pointer to an existing line
     in the decision log or a mechanical reason. "Probably won't work" is not a reason.
   - **Put it through the judge role** (`docs/role-map.md`). Do not take down a predicate you set
     yourself on your own judgment alone.
   - **Leave the line in the decision log that says you stopped short.** The predicate, how far you
     got, what is left, why you stopped.

   **A stop missing any of the four invalidates the predicate without rewriting it.**
   "I feel like I'm out of ideas" is not a reason to stop.
   If it is a real dead end, say so instead of circling.

**What you return:** the termination predicate, **the path to the decision log**, how many
iterations you ran (**and the log holds a line with each of those numbers**), what landed,
what you reverted, the final state of the predicate.
**A run that cannot produce the log path is not accepted as complete.**
