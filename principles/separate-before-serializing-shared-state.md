---
name: principle-separate-before-serializing-shared-state
origin: plumb
description: "Remove the sharing itself first, and serialize with structure only when a single write target is a real invariant. Use when two or more writers can run at once (parallel agents, concurrent jobs, a fan-out), or when asked \"can these run in parallel\", \"do we need a lock here\", or \"why is this flaky under load\"."
---

# Separate before serializing shared state

**Do not create two writers to the same thing.** Only once you know they cannot be
separated do you start thinking about a lock.

**Why this is hard to keep.** When people parallelize, they split **the work**. **The write
target** never appears in the description of the work, so it falls out of the independence
call. The breakage is intermittent on top of that: **the first few runs go through.**
Going through looks like proof that they were independent, so **your own observation cannot
refute it.** Count the write targets, written out, before you run anything.

## Steps

1. **List every write target of every writer.** Files, branches, where artifacts land,
   external state, the same key. **One overlap and they are not independent**
2. **The default is to remove the sharing.** Split the write target per writer and
   **join only on read. Writing to a different field of the same file is not separation** —
   what is being written is still the same file
3. **Serialize with structure only when one write target is a real invariant.** A lock,
   splitting into phases, naming a single writer, compare-and-swap. **The moment you think
   "this needs a lock", look first at whether it can be split**

**Prose is not concurrency control.** Hand someone a note saying "take turns with this" and
two things running at the same time still do not wait.

## How to tell afterwards

- **Did you enumerate the write targets?** If you did not count them, the independence call
  has not been made
- **Was the overlap resolved by separation or by structure?** Resolved by a promise means
  not resolved
- **Where is the join?** Is there exactly one, on the reading side

## The border with the neighboring principles

**This one is about two or more writers at the same time.** One writer running twice
belongs to **principle-make-operations-idempotent**. The reason for handing work out at
all — the latency, and evicting what is bulky — belongs to
**principle-guard-the-context-window**.
