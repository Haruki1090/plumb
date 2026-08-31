---
name: principle-model-the-domain
origin: plumb
description: "Hold domain knowledge as structure in one place instead of scattering it across conditionals. Use when writing stateful logic, when the branches keep multiplying, when the same shape of assumption repeats across files, or when asked \"why does adding one case touch five files\" or \"should this be a state machine\"."
---

# Model the domain

**Domain knowledge lives in structure.** Knowledge spread across conditionals leaves the
machine with no way to know which branches express the same rule, so the next change pulls
them out of alignment.

**Why this is hard to keep.** Adding one more branch always looks like the smallest local
change available. Replacing the structure takes investigation and rework. **The difference
only shows from the third time onward**; the first and second time, adding is faster.
Self-restraint will not hold this. **If you do not choose at the moment you write it, the
work of winning it back gets deferred as refactoring, indefinitely.**

## Signs the structure is missing

- **A new requirement went in as one more branch on an existing if/else**
- **Two booleans have to stay in sync at all times** (a state where only one of them is
  set is constructible)
- **The same shape of assumption repeats across several files** (this kind always carries
  that field, and so on)
- **The module names are stages of processing** (load, validate, transform, save).
  **Execution order is not ownership.** Split by stage and the same domain rule gets copied
  into every stage
- **Nobody but the author can answer "does this combination actually occur"**

## What to put in

**There is no single answer.** Two questions decide it: **what you want to make impossible
to construct**, and **how it will be read**. Scattered booleans want a state machine;
sprawling branches want a table or a registry; a repeating shape of assumption wants a
type; ad-hoc rewriting wants commands and a history. **If none of those fit, answer the
two questions yourself before you pick a shape.**

**How you split modules is settled by the same questions. One module holds one piece of
domain knowledge.** Put what changes together in one place, and do not split along
technical layers.

What you make the type checker prove belongs to **principle-type-system-discipline**.
Settling the core types before the logic belongs to **principle-foundational-thinking**.
What this principle owns is only **the call that structure is missing**.

## The overshoot side

**If you add indirection and neither the branches nor the invalid states go down, what you
added is a layer, not structure.** Where the shape is already clear, local, and unlikely to
grow, leave it as boring code. Judge it from the reader's side: did the layers between
question and answer go down (**principle-minimize-reader-load**)? If nothing went down
anywhere, take it back out.
