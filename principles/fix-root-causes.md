---
name: principle-fix-root-causes
origin: plumb
description: "Apply when you touch anything that is failing or behaving wrong. Get a repro first and fix the cause, not the symptom; do not silence it with a guard. If you work around it without reaching the cause, record that you never reached it."
---

# Fix Root Causes

**This principle owns the decision to trace a symptom back to its root cause.**
The steps for tracing it live in `playbooks/fixing-a-bug.md`.

**Why this is hard to keep.** The reward arrives the instant the symptom disappears, and
**from the symptom's side, "fixed" and "hidden" cannot be told apart.** Add a nil check and
it stops crashing; add a retry and the failure stops being visible. Both only destroy the
observation, yet both have the same shape as a fix. **So resolving not to settle for the
symptom will not hold. Apply the test from outside.**

## Get a repro first

**Without a repro, there is nothing to refute the claim that it is fixed.**
Nothing is left that tells "it is gone" apart from "it happened not to show this time".

A repro is **something that returns the same result for the same input**: a failing test, a
short script, an exit code that comes back every time you follow a fixed procedure.
**Hitting it once by hand is not a repro.** If it does not reproduce, you are short of
material. Lining up the repetitions, the load and the environment is faster than fixing by
guess.

## How to tell you reached the cause

Push "why" back until **one more step would make it a design decision**. Two marks say you
got there.

1. **That cause explains every symptom you observed.** Any remainder it does not explain means you are still short of it
2. **Fixing the cause makes the symptom go away without touching the symptom side.** If you have to touch the symptom side too, you did not hit the cause

**Whether to put in a workaround comes after that test.** A workaround you cannot justify
without writing a paragraph on why it makes the symptom go away is **the mark of code that is
itself wrong.** Do not settle for adding a comment.

## One case is one case. Do not stop there

- **Go looking for the same shape.** Once you fix one site, count by machine how many other places are written the same way. Fix the one and close it out, and the rest come back as the next bug
- **If a re-run fixes it, suspect state, not code.** Code does not change between runs. What changes is configuration, caches, lockfiles, stored state. **"I deleted it and it worked" is the discovery that state can break, not a fix**
- **When you get stuck, go back to measuring.** Adding a log and looking at the actual value is cheaper than stacking guesses

**When the cause is outside what you control** (an upstream defect, an environment you cannot
change), stopping there is allowed. **But record how far you traced it and where you stopped.**
A workaround with no record cannot be told apart from hiding the symptom.

**How to read the repro and the checks after the fix is prove-it-works. The mechanism that
keeps you from plugging the same hole twice is encode-lessons-in-structure.**
