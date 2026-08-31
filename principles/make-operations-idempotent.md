---
name: principle-make-operations-idempotent
origin: plumb
description: "Apply when designing operations that run across crashes, restarts and resubmissions, startup paths, and loops that run again and again. Converge on the same end state even when the previous run stopped partway."
---

# Make operations idempotent

**Run the same operation twice and the end state is the same.**
The same even when the first run died partway.

**Why this is hard to keep.** When you try it by hand you always run it **once, from a clean
state.** Manufacturing a state where a run died partway is a nuisance, so nobody tries it.
That is why **an operation that is not idempotent always looks correct at the moment it is
written.** It breaks inside a long run, after a resubmission, and during the hours when
nobody is watching.

## Converge, do not skip

**"If it already exists, do nothing" is not idempotent.**
It cannot repair the case where the thing is there and stale.
**Declare the shape it should have and close the gap against what is there now.**
Judge on content, not on presence.

- **Identify residue by content and owner.** Not by the order or the time they were created
- **A lock whose owner is dead has to be removable by the next startup.** A lock that cannot be removed stops everything, once it falls over, until a person is called
- **A retry rebuilds from the input.** Do not pick up half-built artifacts from the last run and carry on

## How to tell

1. **Run it twice in a row.** Is the end state the same (run it rather than saying so — **principle-gate-claims-on-evidence**)
2. **Kill it immediately after a write.** For every write point, does the next startup recover
3. **Does that recovery depend on what happened to be left behind**

If the answer to 3 is that it does, the operation is missing **a step that reads the current
state and closes the gap.**

## The border with the neighboring principle

**This is one writer running twice.** Two writers writing at once belong to
**principle-separate-before-serializing-shared-state**.
Making an operation idempotent does not fix two of them running at the same time.
