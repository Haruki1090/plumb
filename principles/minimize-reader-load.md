---
name: principle-minimize-reader-load
origin: plumb
description: "Count the layers between a question and its answer, and the mutable state the reader has to carry: fold wrappers that have one caller, shrink mutable scope. Use when reviewing or shaping code that is hard to follow, or when asked \"why is this so hard to read\", \"is this abstraction worth it\", or \"should I add a layer here\"."
---

# Minimize Reader Load

**Maintainability is the effort a reader spends to understand.** Count it on two axes.
Keeping the diff small belongs to **principle-laziness-protocol**; the order you delete
in belongs to **principle-subtract-before-you-add**. What this principle owns is **the
measure**: what you judge "did this get better" by.

**Why this is hard to keep.** Hidden state is invisible to the person who wrote it —
**it is already in their head.** "You can just read it" is an opinion formed after
reading, and says nothing about what a first-time reader pays. **Self-assessment cannot
measure this, in principle.** So count instead of forming an opinion. The two axes below
are that count made concrete.

## Axis 1: the layers between question and answer

The number of definitions you open before you can answer "where did this value come from".

- **Fold any layer with no second consumer.** A wrapper with one caller, an adapter with
  one implementation, indirection put in for a future that never arrived
- **If two adjacent layers speak the same words, one of them is not needed.** A layer that
  passes arguments through with near-identical names in near-identical order has not
  changed the abstraction
- **A boundary is justified by how much it hides.** Show a wide surface with no real
  decisions behind it and the reader has to memorize the surface *and* the inside.
  **Only a boundary that hides many decisions earns its keep as a layer**

## Axis 2: the state the reader carries

The amount of mutable context you hold before you can answer "where can this value be
rewritten".

- **Lean narrow.** Return value > local variable > field > module state > global.
  **Derive it rather than keep it in sync**
- **Name an invariant once, at the boundary.** Written at every use site, it makes the
  reader re-check it every time

**The two axes are independent, and cutting one can raise the other.** A single flat file
with no layers can become unreadable through mutable state, and the reverse happens too.
**Look at both.** The same story about a model's context window belongs to
**principle-guard-the-context-window**. What this one counts is the load on a human reader.

## The test

Can a first-time reader answer **"where did X come from" and "what can change X" inside
30 seconds?** If not, cut a layer or narrow the state.

**Add a layer or a piece of state only when the same amount goes away somewhere else.**
Name the place it goes away before you add it. If you cannot name it, do not add it.
