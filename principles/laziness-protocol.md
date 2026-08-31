---
name: principle-laziness-protocol
origin: plumb
description: "Apply when refactoring, when sizing a diff, and whenever you feel the urge to add an abstraction, a layer, or one more value threaded through. Lean toward deleting, and toward the smallest change that solves the problem."
---

# Laziness Protocol

**Ship the smallest change that solves the problem.** Delete before you add.
The order you delete in belongs to **principle-subtract-before-you-add**; the scale for how
hard the surviving code is to read belongs to **principle-minimize-reader-load**. This
principle owns **the size of one change**: how far down the diff in front of you can be cut.

**Why this is hard to keep.** For a model, writing costs close to nothing, and the volume
written reads back as work done. The one who pays is **whoever reads that diff later and has
to repair it**. The side that pays and the side that decides are different, so **restraint by
feel does not work.** Resolve not to overbuild, and the next layer that feels missing gets
added anyway. So do not resolve. Count before you ship.

## Count before you ship

1. **Lines deleted against lines added.** If "improve this" moved you only on the adding side, you have not gone looking for anything to delete yet
2. **Names added.** Types, functions, files, config keys. For each one, is there a reason **you could not have written this without it**
3. **Layers with one caller.** A wrapper, an adapter, an indirection. With no second consumer, that is not a layer, it is a detour
4. **How many places the same decision appears in.** If the same condition is written in two or more places, pull the decision into one place and pass the result around
5. **How many files you open to reach the answer.** Past three, suspect the depth. **A wide surface that does substantial work inside is not depth**

## Questions to pass before you add

- **Stop the moment you are asked to thread a value through.** Once you are passing a new value down through the type layer, the schema layer and the routing layer in turn, that is the mark of a design that never arrived. Before you thread it, look for a path that reaches directly
- **"For the future" is not a reason.** An indirection put in for a future that did not arrive is paid for by every reader until it does
- **Do not defer a small leak.** One pass-through, one internal representation exposed, one duplicated decision: each is cheap on its own. **They stay cheap while they multiply, and become a coordination cost you cannot remove.** Delete them before they spread

**If you cannot say why it would not cut any further, it still cuts.**
