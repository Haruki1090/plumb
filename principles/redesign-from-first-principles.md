---
name: principle-redesign-from-first-principles
origin: plumb
description: "Design a new requirement as though it had been a premise since day one, instead of bolting it onto the existing shape. Use when a new requirement lands on a design that already exists, or when asked \"can we just add a flag for this\", \"where do I hook this in\", or \"is this worth restructuring\"."
---

# Redesign From First Principles

**When a new requirement arrives, rebuild the design as though it had been there from day
one.** Do not paste it onto the existing shape. What you settle before you start belongs to
**principle-foundational-thinking**; migrating the callers and deleting the old API in one
wave belongs to **principle-migrate-callers-then-delete-legacy-apis**. What this principle
owns is **the moment the requirement lands**: do you add, or do you rebuild.

**Why this is hard to keep.** Bolting it on always looks smaller. The diff is small, it
touches no existing behavior, and it passes review more easily. **The breakdown shows up at
the next requirement**, so whoever bolted it on never sees the cost. **The choice that looks
safe and the choice that is safe point in opposite directions.** So run the test out loud,
every time.

## The test

**"Writing this from zero today, knowing this requirement, would it come out in this
shape?"** If it would not, **list only the differences.** That list is the scope of the
rebuild.

There is a second reading, one that works after the fact. **Can you see a trace in the code
of this one requirement being treated specially?** An argument appended at the end, a flag
named after the requirement, an exceptional path. If you can see it, you pasted it on.
**A requirement that was there from day one leaves no trace of special treatment.**

## The scope of the rebuild

- **Read every affected file before you decide the shape.** Fix them one file at a time and
  the shape of the whole ends up set by whatever the first file you opened happened to need
- **Follow every reference.** Types, documentation, examples, the section that wrote down
  the rationale. **A passage explaining where the requirement came from, left stale, makes
  the next reader design on the old premise**
- **Decide the shape as a whole; ship it small and in order**
  (**principle-sequence-verifiable-units**). Deciding as a whole and shipping all at once
  are not the same thing

## When you choose to paste it on

- The requirement sits inside the existing shape without strain. **If you can say outright
  that it fits, it fits**
- The scope of the rebuild exceeds the value of the requirement. **Then record that you
  pasted it on** — when the next requirement arrives at the same place, that record is the
  starting point of the rebuild. Without it, the second bolt-on builds on the first, and
  there is no way back
