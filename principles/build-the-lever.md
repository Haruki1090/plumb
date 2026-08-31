---
name: principle-build-the-lever
origin: plumb
description: "Apply to non-trivial work of any kind - edits, migrations, analysis, checks - not just bulk jobs. Instead of doing it by hand, build the tool that does it and the tool that proves it: a codemod, a script, a generator, a skill a subagent follows. The tool is the artifact the reviewer can re-run."
---

# Build the Lever

**Before you run non-trivial work, build the tool that does it and the tool that proves it.**
Turning a lesson you keep re-learning into a permanent guard belongs to
**principle-encode-lessons-in-structure**; designing the verification itself belongs to
**principle-prove-it-works**. This principle owns **the one job in front of you**: how fast it
runs, and whether the reviewer can re-run it.

**Why this is hard to keep.** By hand starts fast. A tool starts slow, and **by the third
item done by hand the work already looks half finished**. Compared on time-to-start alone,
by hand wins every time. And what you did by hand, **the reviewer cannot re-run.** The only
way to check it is to do the same work over again, so in practice nobody checks it.
**By hand ends in "trust me". A tool ends in "run this."**

## How to build one

1. **Do the first item by hand.** Generalize before you know the steps and the tool is what ends up wrong
2. **Build the tool, then run it back over that same item.** Diff it against what you did by hand. When the two disagree, sometimes it is the hand-done one that is wrong
3. **Make it safe to run any number of times.** The reviewer will run it again
4. **Commit it if the work outlives the session.** The next round becomes a re-run instead of a redo

## A deterministic tool beats fanning the work out

If one run can process every item, **run it yourself.**
Do not make a delegate apply by hand what a script can do.

When you have no choice but to fan it out, **write the tool as a playbook the delegates
read.** Put the steps, the verification contract, and the range they must not touch into one
artifact. Rewrite it per prompt and **you hand out slightly different versions of what you
believe is one instruction, and each delegate drifts its own way.** Keep that artifact
outside the range they are allowed to write to: the side bound by the contract must not be
able to edit the contract.

## Cite this and the diff gains a file

If you cited this principle and the diff holds no script, no generator and no playbook for
the delegates, **the citation is a lie.**
`plumb-worktree-audit` and `plumb:doctor` are here because this principle was applied.

## When not to apply it

- **When it really is trivial.** Two or three obvious edits you can take in at a glance
- When building the tool costs more than the work. **But the test is not how many times it repeats**: build one even for a job you do once, if the tool is the only way to check the result

Build the tool **as small as it goes** (**principle-laziness-protocol**). Do not build a
framework.
