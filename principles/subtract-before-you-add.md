---
name: principle-subtract-before-you-add
origin: plumb
description: "Strip the dead weight, the redundant validators and the stub references first, then build on the base that got simpler. Use when deciding the order of an addition, a refactor or a rewrite, or when asked \"where do I start\", \"should I clean this up first\", or \"can we just add it on top\"."
---

# Subtract Before You Add

**Delete first. Build on the base that got simpler.**
Keeping the diff you ship small belongs to **principle-laziness-protocol**; the actual
method for folding away an old API belongs to
**principle-migrate-callers-then-delete-legacy-apis**. What this principle owns is **the
order**: subtraction goes before addition.

**Why this is hard to keep.** Deleting adds nothing that runs. **Subtraction never gets
counted as progress.** Add, and there is new behavior to see, to write into the report, to
be credited for in review. On top of that, **the window for deleting closes with time** —
dead weight you put off gets referenced by the next code you add, and the moment it is
referenced, "delete" turns into "migrate". "Delete it when I notice it" is already too
late. **Put the deleting in front of the adding.**

## The order

1. **Delete the dead weight.** What nobody calls, branches nothing reaches, orphans that
   only a reference keeps alive
2. **Drop the defenses the spec never asked for.** Speculative validators, parsers, guards.
   **A feature outside the spec drags in the verification that protects it** — persistence,
   retry on startup and schema migration each demand their own machinery for guarding
   input. Drop the feature and the defenses go with it
3. **Delete references with nothing inside them.** If the link target says nothing new,
   delete it rather than replace it. **An empty stepping stone costs the next reader one
   round trip and gives back nothing**
4. **Fit the shape to the usage you have observed.** Do not widen it for an exceptional use
   you imagined
5. **Build from there**

## How to find what to subtract

- **Prose that says the same thing twice.** Instructions, templates, explanations. If
  deleting one of them changes no meaning, that is redundancy, not emphasis
- **A switch where only one side is ever taken.** Configuration that branches, with one
  branch nobody uses
- **Invented machinery.** Are you building a new ledger or a new place to put things where
  the tools that already exist would do? In plumb, `plumb-decision-log` and `plumb-path`
  cover almost every such case

**The test for keeping something:** if your hand stops on the way to deleting it, **show
the actual place that uses it.** If you cannot show one, delete it. "It is probably used
somewhere" is not a reference.
