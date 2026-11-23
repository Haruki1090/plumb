---
name: principle-attack-the-premise
origin: plumb
description: "Apply when a second fix built on the same assumption has failed at the same gate. Stop fixing. Write the assumption down as one sentence, make the observation that would come out differently if it were false, and look at the whole spread of failures before trying anything else."
---

# Attack the Premise

**Two fixes that rest on the same assumption and fail at the same gate are the point where
the assumption gets tested, before a third fix.** It may well hold. Until now nobody has
checked. Tracing a symptom to its cause belongs to
**fix-root-causes**. This principle owns **the moment you stop trusting what every attempt so
far took for granted.**

**Why this is hard to keep.** Each failed fix looks like it was nearly right. The next
variation is always cheaper to try than stepping back, and **the assumption underneath never
shows up in the diff, so nothing prompts you to question it.** You wrote it down nowhere; it
arrived with the first reading of the problem and has been load-bearing ever since. **Three
attempts later you have tested the fix three times and the premise not once.**

## What fires it

**The second failure, not the third.** Count a failure when both hold:

- The attempts share a premise: "the race is in the cache", "the test is flaky, not the
  code", "the regression came in with that commit"
- They were refused by the same gate: the same test, the same check, the same reviewer finding

A new symptom appearing somewhere else after each fix counts as the same gate. The problem
moved; it did not go away.

## What you do

1. **Write the premise as one sentence that could be false.** If you cannot, you have found
   the trouble: the attempts were aimed at a feeling
2. **Name the observation that comes out differently if the premise is false, and make it.**
   Not another fix. A log line, a bisect, a run with the suspected part removed. **A test of
   the premise changes nothing in the product**
3. **Look at the spread of the failures, not at the latest one.** When does it fail and when
   does it not: which inputs, which machines, which order, which hour. A premise that explains
   one failure and not the distribution is wrong
4. **Only then choose.** The premise held: go back to fixing, now with a reason. It fell:
   restate the problem and start from the new statement, not from the old attempts

**Carry over only what was verified on its own.** A change that made a named check go from
red to green stays. Everything else from the failed attempts is reverted: a half-fix left in
place is the old premise still running.

## Where it meets the rest

- In a loop (`playbooks/hillclimb.md`, `playbooks/autonomous-run.md`), this is what "change
  category" has to mean: the category is the premise
- In a plan (`playbooks/running-a-plan.md`), a task that comes back a second time from the
  same check gets its premise written into the brief for the next round
- When the premise is yours and you cannot see past it, hand the one sentence and the
  failures to the judge role (`docs/role-map.md`). **A different family does not share your
  first reading**

## When not to apply it

When the two failures have different causes you can each name. That is two bugs.
**"They are probably unrelated" without the two names is the premise defending itself.**
