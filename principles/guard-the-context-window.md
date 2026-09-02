---
name: principle-guard-the-context-window
origin: plumb
description: "Apply just before you load anything into the main session: large output, long files, repeat reads, a fan-out plan. Push the bulky work to a subagent and keep only the summary and a pointer in the main session. Nothing takes context back out, so the decision can only be made before it goes in."
---

# Guard the Context Window

**The main session's context never shrinks.** No operation takes back what you already put
in. So the only place you can hold the line is **the point before it goes in**; folding
things away once it is full is always too late.

**Why this is hard to keep.** Being full does not show up as a symptom. What shows up is
degraded reasoning, and **from inside the degradation, the degradation is invisible.** The
sense that you are "getting close" is not reliable, and by the time you notice, the material
you would judge with has already thinned. **Decide what goes in by what it is for, not by how
big it is.**

## What belongs in it is what you will read again

Anything you read once and are done with does not go in the main session.
**There are two places for it.**

- **Fan it out.** Bulky reading, long output, broad exploration, edits with many steps: stand up a role and hand it over. What comes back is **a pointer to a file and the facts that change a decision**, nothing else. Do not let raw data come back
- **Put it in a file and hold the path.** What stays in the main session is the way there

The diff itself, a whole trace, a long timeline, an entire plan file:
**do not paste them. Put down what survived the cutting, or a pointer to it.**

## What you hand over goes in a file too

**Write a long request into the body of your reply and it eats the sender's context first.**
Put the request, the brief and the material in a file and **hand over the path alone.**
Cut the range you hand over as well: give someone a document that also covers the
neighboring job and they will start on the neighboring job.

## A tool result you will not read twice does not come back raw

**A result past 40KB never enters the main session as a payload.** The 40KB line is the
`TOOL-RESULT-OVER` threshold, exposed as an option and set as plumb's default; put the raw result
in a file, then return its pointer and the two or three facts that change a decision.

**The 40KB line is a gate, not advice.** A result loaded once is re-sent on every request that
follows; on 2026-09-02, 455 results crossed the line in 25 sessions whose p90 context was 704K
against a 400K compaction window.

**Submit, poll, poll, fetch is a loop you run outside the model.** Each step adds a request and its
response is re-sent afterwards, so put the loop in a script and return only its summary
under the 40KB line; `playbooks/batching-chatty-tools.md` owns that `TOOL-RESULT-OVER` lever.

## Count the price of moving it out

**Fanning out is not free.** It adds the time to write the handoff, the time to read what
comes back, and the work of integrating it. **Small things, and things tangled tightly
together, are cheaper cut into slices in the main session.** Boilerplate and references you
use every time go the other way — **keep those at hand.** Going out to read them again and
again costs more.

## How to tell

Of everything loaded into the main session right now, **can you count the parts you will
refer to again?** Count them, and if a lot is left over, you are loading it wrong. Before you
load the same kind of thing next time, **ask once whether a pointer would do instead.**

Run `plumb-session-audit --last 1` after the session; `TOOL-RESULT-OVER 0 results` is the pass
condition for the 40KB gate.

**Who you fan out to, and how, is `playbooks/fan-out.md`.** This principle owns only the
decision of whether it goes into the main session.
