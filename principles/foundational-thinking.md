---
name: principle-foundational-thinking
origin: plumb
description: "Apply before writing the logic: when choosing the core types and data structures, when ordering scaffolding against feature work, when asking what gets shared between things that run in parallel. Get the data structures right and the downstream code becomes obvious."
---

# Foundational Thinking

**Settle the core types and data structures before you write the logic.** Get the shape right
and everything downstream becomes obvious. Rebuilding when a new requirement lands in an
existing design belongs to **principle-redesign-from-first-principles**. This principle owns
**the ordering**: what you settle first, and what you leave for later.

**Why this is hard to keep.** The cost of changing a data structure climbs steeply with time:
a one-line diff right after you start, a rewrite once the callers have multiplied. And yet
**the logic is where progress shows**, while time spent looking at types looks like nothing
moving. That asymmetry pushes the same way every time. You only get to pay before the cost
climbs if pushing back is written into the procedure.

## What you settle first

- **The core types.** What this work is about, and which states it can be in
- **The dominant path.** Lay out every access that **actually** hits that type and fit the shape to the heavy path. Do not distort the shape for a rare one
- **The scaffolding.** Whatever makes every later step easier by existing. If "does the next step, and the one after that, get easier with this in place" is yes, put it down first
- **Whether to share at all.** Before you put state between things that run separately, answer "what happens if one reads while the other is midway through writing". **Any answer other than "nothing" means you split instead of sharing** (**principle-separate-before-serializing-shared-state**)

## What you do not settle first

- **Abstractions.** Three places written alike is still not enough. What you unify is the shape of the types and the data, not the lines
- **Generalization.** Do not pick a shape for a requirement that has not arrived. Rebuilding when it does is **principle-redesign-from-first-principles**' job; **leaving room for that is this principle's job**
- **Cleverness.** A shape you can read beats a short one. What tests pin down is behavior and edges, not line count

**Subtraction comes before you lay any scaffolding**
(**principle-subtract-before-you-add**). Lay a foundation over dead weight and the dead weight
sets along with it.

**How to tell afterwards.** At each step, ask whether that diff put down **one coherent shape**
or deepened a shape already there. If the new capability got scattered across the callers as
special cases, the shape is not there yet.
