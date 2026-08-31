---
name: principle-encode-lessons-in-structure
origin: plumb
description: "Apply when you are about to write the same instruction twice, when you have made the same fix twice, or when you are about to copy the same fact into a second place. Do not add prose - make it a mechanism: a lint, a check, a script, a single entry point. Copying the text is not a mechanism."
---

# Encode Lessons in Structure

**Prose only works when someone reads it.** A mechanism works whether or not anyone does.
**The moment you write the same thing twice, you have the observation that prose is not
enough.**

**Why this is hard to keep.** Adding a rule as prose is the cheapest move available at the
time. The cost does not appear when you write it: **it comes back later, spread thin, as the
number of times the rule went unkept**, so it never lands on the thing that caused it. And
every line you add raises how much there is to read, which makes the next rule less likely
to be read still. **Left alone, this always tips toward more prose.**

## The second time you notice, drop it to something stronger

Go down the list and take the strongest rung available in your situation.

1. **Make it unrepresentable** — what cannot be written stays kept
2. **Make a check go red** — a lint, a CI gate, a check under `scripts/`. What fails does not get through
3. **Make one entry point** — when the right way is the only thing there is to call, the wrong way is hard to write
4. **Fail at runtime** — late, but it does surface once, reliably
5. **Write it as prose** — only when none of the rungs above is available

**Settle for a weaker rung and that rung becomes the example for the next person.**
To anyone writing code that matches its surroundings, a loose form that already exists means
permission.

## Copying the text is not a mechanism

**Write the same fact in two places and one of them goes stale.** Steps, paths, the bar for
judging: all of them. So **do not copy it. Point at it.**
For the same reason, **do not assemble a fact by hand.** A list of worktrees, the path where
artifacts go: the moment you spell one out, it is a copy that can drift from the real one.
**Ask the machine, and use what it returns.**

Pointing does not stop staleness by itself, so **put a check beside it that goes red once
the two drift.** When fixing one side and forgetting the other makes something fail, you
finally have a mechanism.

## When all of them make the same mistake, the individual is not what you fix

If every delegate missed the same way, what missed was the handoff. **Do not fix them one by
one: fix the text you hand out and hand it out again.** If one delegate missed once, treat
that as one failure.

## Close it out

- **"I'll be careful" leaves nothing behind.** Either record it or make it a mechanism
- **Recording it is not finishing it.** A note saying "this should be a lint" keeps nothing until it is a lint
- **Do it now, or leave it as a task with a destination.** A realization with nowhere to go disappears

**The decision not to patch the symptom is fix-root-causes itself.**
What this principle owns is only **the shape in which the same failure cannot happen twice.**
