---
name: principle-explain-the-number
origin: plumb
description: "Apply before you report, compare or act on any measured number - a timing, a rate, a score, a cost. Write down the decision the number is for before you measure, name what limits it, and report it with its run count, its spread and that limit. A number you cannot explain is not yet a result."
---

# Explain the Number

**A number is a result only once you can say why it is that number and not another.**
What you measure against belongs to **prove-it-works**; when the check is forced belongs to
**gate-claims-on-evidence**. This principle owns **the reading**: what the figure in front of
you is allowed to mean.

**Why this is hard to keep.** A number looks like an observation, and an observation looks
like it needs no defence. **But a measuring tool reports whatever happened inside its window,
including nothing.** A benchmark whose requests all failed is fast. A score computed over
trials that never attempted the task is stable. The figure arrives with two decimal places
either way, and the decimals are what get believed. **Precision is not evidence that the
thing you meant to measure took place.**

## Before you measure

**Write the decision first.** One line: what you will do if the number is high, and what you
will do if it is low. If both branches lead to the same action, do not measure; you are
collecting, not deciding. Written afterwards, the decision bends to fit the number.

## Seven questions, in this order

Ask them of every number that will change what gets built or what gets claimed. **A question
that cannot apply is answered `n/a: <reason>`, not skipped**: a single recorded fact, such as
what one session cost, has no second side to alternate against, and saying so is the answer.

1. **Why is it not twice as good?** Name the limiter: the one resource or step that sets the
   figure. If you cannot name it, you do not yet know what you measured
2. **Were both sides set up the way they run for real?** Same build mode, same warm-up, same
   data, same configuration. A tuned candidate against an untuned baseline measures the tuning
3. **Does it fit under the physical ceiling?** Do the arithmetic against what the disk, the
   network, the clock or the context window can deliver. A figure past the ceiling is a bug in
   the tool
4. **How many errors were there?** Print the count next to the figure, every time. Failed
   work is the cheapest work there is
5. **Does it come back?** Alternate the two sides (A, B, A, B), at least five rounds, and
   report the median and the range. Run all of one side first and you have measured the
   machine warming up
6. **What share of the whole is it?** A step made ten times faster matters by the fraction of
   the end-to-end path it occupied. State that fraction
7. **Did the work happen inside the window?** Count the units of work completed in the timed
   span and check the count against what you asked for

**The first question you cannot answer is where you stop and look.** Do not go on to the next
one. If looking does not answer it, the verdict is inconclusive, and you report it as that,
naming the question.

## What a reported number carries

The figure, **the number of runs, the spread, the error count, the work count and the
limiter.** Leave one out and the reader has to trust the rest.

The verdict is one of four words: **faster, slower, no measurable difference, inconclusive.**
"No measurable difference" means the gap between the medians is inside the spread you saw
between runs of the same side. "Inconclusive" means a question above
went unanswered. **Neither is a failure to report. Rounding either one up to a win is.**

## It is not only for timings

A score from an evaluation, a rework rate, a cost per task: the same seven apply. Whether
every trial attempted the task is question 7. Whether the gap survives a different sample or
a different model is question 5. The one that moves the cost term is **spend-on-the-outcome**.

## When not to apply it

A number nobody will act on, or one read only to see whether something is alive. **The
moment it enters a claim, a pull request body or a comparison, it is inside this principle.**
