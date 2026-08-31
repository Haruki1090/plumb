---
name: principle-never-block-on-the-human
origin: plumb
description: "Push reversible work forward, then show the result as a diff and let the owner correct it: stop only for what cannot be undone and for the decision of what to build. Use when you catch yourself asking \"is it OK if I make this change\", \"shall I keep going\", or \"how should I implement this\" in the middle of a task."
---

# Never Block on the Human

**The owner is watching asynchronously.** So the price of one round trip is not your few
minutes; it is **the owner's attention**. **"Asking just to be safe" is not the safe
side.** It spends that attention and produces nothing.

**Why this is hard to keep.** Asking always looks easier. A call you got wrong is charged
to you, while time spent waiting on an answer is charged to nobody, so **the cost flows
toward the side that never comes back to you.** Draw the line at "ask whenever unsure" and
the line keeps creeping earlier. **The line to draw is not confidence. It is the price of
undoing.**

## The line

**"What to build" belongs to the owner. "How to build it" does not stop.**

| | What it covers | What to do |
|---|---|---|
| **Stop** | What to build. Which option to take. The scope. What existing behavior may break | Hand it over and wait for the answer |
| **Stop** | Operations that cannot be undone. Force overwrites, production data, sending to the outside, publishing | Confirm before running it |
| **Do not stop** | How files are split. Names. How tests are written. Order. Which API to use. How to slice the commits | Decide, move, show it as a diff |

One test decides it: **if you got it wrong, does one diff take it back?** If it does, go.
If it does not, hand it over before you go.

## How to work on the do-not-stop side

- **Decide, record what you decided, and move.** The same goes for ambiguity, for a
  conflict, for a flaw in the plan. **A night lost to stopping on a question cannot be
  recovered**
- **Do not stop to report progress.** "Shall I carry on?" has the shape of a question but
  carries no branch
- **When you do stop, stop once, for everything at once.** Collect a nod per section and
  the round trips pile up, one per section
- **While you wait, keep doing the work that does not depend on that branch**
- A problem you notice gets **recorded and fixed on the next pass**, not reported and
  waited on where you found it

**How to hand it over** — the form for handing a branching decision to the owner is
`skills/decision-brief`. **Redrawing the stop line from this principle is
`playbooks/shaping-the-work.md`.**
