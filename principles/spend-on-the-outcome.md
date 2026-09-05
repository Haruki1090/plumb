---
name: principle-spend-on-the-outcome
origin: plumb
description: "Apply when judging the cost of a session or a lever meant to reduce it. Name the term the lever moved, measure it from the transcript, and state cost per unit of finished work. A saving without a measured term is only a feeling."
---

# Spend on the Outcome

**Before you claim a lever saved anything, name whether it moved turns per session, requests
per turn, or tokens per request, and show that number from `plumb-session-audit`.** A saving
with no measured term attached is a feeling.

Session cost can be decomposed into six multiplying terms:

    Total = Users x Sessions/User x Turns/Session x Requests/Turn x Tokens/Request x Price/Token

The first two terms are the reach you want to grow. The last term is set by the vendor.
The three in the middle are the terms to shrink. They are the work the agent does on its own
behalf on top of what was asked: how long it keeps turning, how many requests each turn fans
into, and how much context every request carries.

Those three are where a session can spend heavily without producing another unit of work.
They are also where a tool, a shorter loop, or a smaller context can create a real lever.

## Why this is hard to keep

From inside a session, the context never looks large. It may be cached. Cache reads can cost less
than uncached input; the actual rate depends on the provider and model. The harness does not put the token count beside the turn that loaded
it. **The cheap-looking read price is what makes a 700K context feel free.**

It is not free. The same payload is read on every later request. A tool result returned once
can keep charging for the rest of the session, while the answer that caused it has already
scrolled away.

The waste appears in a monthly bill weeks later. By then it is disconnected from the turn
that caused it. A large charge has no visible edge back to the read, retry, side request, or
idle resume that made it large.

That delay invites stories. "The cache made it cheap." "The extra pass improved quality."
"The session was long because the task was hard." None of those claims identifies a term,
and none can be compared with the next run.

## Attach the spend to work

**Every dollar should map to a unit of work.** The audit gives you tokens, not dollars. You
supply the price. You also supply the unit: a review, a merged PR, a plan task, or another
outcome that can be counted. Pick the unit before comparing sessions.

A session whose cost cannot be stated per unit of work cannot be compared with the next one.
Total cost alone confuses useful growth with overhead. Cost per unit shows whether another
request, another turn, or another copy of the context bought another outcome.

Keep the numerator and denominator together. "This run cost less" is incomplete when it also
finished less. "This run used fewer tokens" is incomplete when it created more sessions to
finish the same work.

## Name the lever

Say which of the three controllable terms moved.

If a session stops before a follow-up or resume needs another human prompt, it moved turns per
session. If a plan stops a retry loop or a tool replaces a fan-out, it moved requests per turn.
If a command returns a pointer instead of a payload, it moved tokens per request. Show the
before and after number for that term.

Do not use token price to hide volume. A cached token is cheaper, but it is still multiplied
by every request that follows. Price per token and tokens per request are different terms and
need different explanations.

Use **principle-guard-the-context-window** for the decision at the point of loading. Use
**principle-build-the-lever** for why the measurement belongs in a repeatable script rather
than advice. This principle does not restate either one. It owns the accounting between the
lever and the outcome.

## How to tell

For the session you just finished, can you say its turns per session, requests per turn, and
tokens per request? Can you also say how many tool results were over the line and whether a
resume rebuilt the cache?

If not, run `plumb-session-audit`. Use its session rows to find the run that carried the
weight. Use the flags to choose the next lever. Then measure the same term again after the
change.

The audit does not know what the session finished, and it does not prove that the work was
worthwhile. Price and the unit of work are yours. That unit and the measured term together
let you say what the session bought and what it spent on itself.

The measurement scope is recorded in `docs/scope.md`. The thresholds are diagnostic defaults,
not provider-independent limits.
