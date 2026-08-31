---
name: principle-outcome-oriented-execution
origin: plumb
description: "Converge a rewrite or migration on the target design instead of smoothing every intermediate state with throwaway compatibility code. Use during a planned migration whose stage boundaries are written down, or when asked \"can we add a shim to keep this green\", \"what breaks in the middle\", or \"how do we roll this out in stages\"."
---

# Outcome-Oriented Execution

**A migration or a rewrite converges on the target design.** Keeping every point along the
way smooth is not the goal. Migrating the callers and deleting the old API in the same wave
is **principle-migrate-callers-then-delete-legacy-apis**; slicing the work into verifiable
units is **principle-sequence-verifiable-units**. What this principle owns is **the
handling of intermediate states**: how much breakage you take on deliberately, as plan.

**The scope is narrow.** A planned migration or rewrite whose stage boundaries are written
down — the kind of work you open a ledger for and run through
`playbooks/running-a-plan.md`. **Do not apply it to everyday changes.** Those stay green
throughout.

**Why this is hard to keep.** Breaking nothing at any point always looks right in the
moment. The compatibility layer that goes in to avoid breaking things introduces itself as
temporary. **But what removes it, and who removes it, usually lands on nobody's todo.** By
the time the migration ends, that layer has new callers on it. **Temporary becomes
permanent because the promise to delete was never written down first.**

## The gate a compatibility layer passes before it goes in

Write these three into the plan before you write the layer. If you cannot write them, the
layer does not go in.

1. **What removes it.** What has to become true for it to be unnecessary
2. **Which stage removes it, and who.** **"When the migration is over" is not a stage**
3. **What catches you forgetting.** Put a check that counts the survivors into the
   definition of green (**principle-encode-lessons-in-structure**)

## When an intermediate state is allowed to break

Only when all three hold.

- **It is declared.** Before you start, the plan says which stage stops what from working
- **It is bounded.** Only the area under migration breaks; everything else stays green
- **It reverses.** Revert that stage and you are back where you were

**Do not drop the checks on the area you are touching, not even mid-migration.** Declaring
a range that may break is one thing; stopping observation is another.

**The condition for done:** at the end of the plan, run the static checks and the runtime
verification end to end. Having been green at each stage **is not evidence of being green
end to end** (**principle-gate-claims-on-evidence**).
