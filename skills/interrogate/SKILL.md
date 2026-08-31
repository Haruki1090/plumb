---
name: interrogate
description: Adds one adversarial axis from a different model family to the refutation stage of a PR review. Use when asked to "show this to another model family", "get a second family on it", "are we judging inside one family only", and whenever the change under review is irreversible or wide. It does not stand on its own - it is called from stage 3 of `plumb:pr-review`.
---

# The other family's axis

**This layer does not stand on its own.** The source of truth for review is the `plumb:pr-review` skill.
The six stages, the two axes of the verdict, and the shape of what you return all live there.
**This holds axis E of stage 3 only** — the one listed in `plumb:pr-review`'s refutation-stage table.

**Even when called on its own with "show this to another family", do not just run it.**
Go through stage 1 (bidirectional inventory) and stage 2 (weighting, and the cut) of `plumb:pr-review` first.
**What you hand over is the set of paths stage 2 narrowed to**, not the whole diff.
Run it without those stages and the premise of "How to add it" below is gone.

## Why add it

Stage 3 of `plumb:pr-review` splits into several axes, but **every one of them except E runs inside the same model family.**
The roles are separated; the thing executing them is one.

Diversity of roles is not diversity of blind spots. The same family misses the same places.

This is measured. In plumb's batch 1, after three passes of review in the Claude family, a verdict from a
different family turned up **three defects that went to the core of the design**.

```
A way around the visible skip   It only said "do not delete the line", so never creating the line bypassed all of it
The wrong routing key           The implementation was delegated to the explorer role. The role map had no implementer role
A second source of truth        An old plan sat next to the new one, rigged so that anyone arriving later rolled every fix back
```

**All three passed straight through the same-family review, all three times.**
That review was effective on presentation and on conformance to the spec, but **the logical holes in rules it had written itself** were invisible to it.

The same shape showed up the same day on a stack of six authentication PRs in a different repository.

```
New findings from the other family   6
Found by the 4 same-family axes      0
```

The main session's report from that run puts it exactly —
**"the two places where I had drawn the line myself, 'this only hurts whoever does it' and 'grep returns nothing, so it is already broken', were visible as holes to the other family."**

**These were not oversights.** Places the same family considered and closed as fine were open to the other one.
**Separating the roles does not separate the habit of how you close a question.**

## When to add it

**The conditions are not written here.** "On E" in stage 3 of `plumb:pr-review` is the source of truth.
That is where the four trigger conditions live, along with the `skip: <reason>` rule for when none of them hold.

Copy them here and one copy gets updated alone. **That is exactly what this layer forbids below.**

## How to add it

Hand over **the paths stage 2 of `plumb:pr-review` narrowed to**. Do not aim it at everything —
you get findings in territory you decided not to look at, and end up throwing away real findings you generated yourself.

1. Open a pane (`pane.driver`; unset: run it in the foreground) and wake the judge role from `docs/role-map.md`.
2. Write the request to a file and **hand over the path alone** (**principle-guard-the-context-window**).
   What goes in the request:
   - The target paths settled in stage 2
   - How to take the diff (`git diff <base>...<head> -- <paths>`)
   - **One paragraph of intent.** What is this code trying to achieve?
     What the judge role attacks is whether it achieves that intent, not whether the intent is right
   - The shape to return: for each item, "file:line" and "concrete input or state -> wrong output / what is lost"
   - State explicitly: **"write 'none' for an item with no finding. Do not squeeze findings out"**
3. Have it write the result to a file and read that. Do not scrape it off the pane.

## What to do with what comes back

**The judge role's output is a refutation, not a verdict.**

- Reassign confidence (CONFIRMED / PLAUSIBLE) by the definitions in stage 5 of `plumb:pr-review`.
  **Even where the judge role wrote "confirmed", it is PLAUSIBLE unless the command that proves it ran this turn.**
- **Do not let the judge role assign blocking.** You assign that in stage 5.
- Put what overlaps another axis first. **A finding that matches across axes is the strongest signal there is.**
- A finding from one axis alone is still worth reading, but carry it at lower confidence.
- Where the judge role explicitly said "this is fine" and another axis disagrees,
  **carry that disagreement itself into stage 5.** Do not silently drop one side.

## What this layer does not do

- **It does not rewrite code.** Fixing is the author's job (`plumb:pr-review`, principle 6).
- **It does not reimplement `plumb:pr-review`'s steps.** The definitions of the stages, the axes and the verdict,
  and E's trigger conditions, all live there. Copied here, one copy goes stale.
  **This rule bites hardest on this very document.**
- **It does not drop the judge role back into the same family.** The environment sometimes forces that,
  and when it does, **record it** as `docs/role-map.md` requires. Never degrade it silently.
