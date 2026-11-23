---
name: reflect
description: After a session, decide what should change so the next one goes better, and propose each change in the file that will carry it. Use when asked to "reflect on this session", "what did we learn", "what should we change after this", "what would you do differently next time", or in Japanese "kono session wo furikaette", "tsugi ni ikasu koto wa nani", "nani wo aratameru beki". Proposes only; applies nothing until the owner approves. Not for one agent failure with a label (plumb:failure-to-rule) or the weekly numbers (plumb:retro).
---

# Reflect on a session

**Keep only what changes what the next agent does, and put it where that agent will read it.** A
lesson that stays in this conversation is lost with it. A lesson that lands in the wrong file is read
by no one.

## Evidence

Read the transcript and the diff. **Do not work from memory of the session**: it keeps what felt
important and drops what cost time. Look for:

- a correction the owner made, and what the agent had done before it;
- work done twice, or undone;
- a check that failed late, when an earlier step could have caught it;
- a skill that should have fired and did not, or fired and did not help;
- an instruction the owner repeated.

Resolve the transcript through `docs/path-map.md`; never glob across projects. For a long
session, hand the reading to the explorer role (`role.explorer.model`, `docs/role-map.md`) and take
back a timeline of the events above, each with its place in the transcript
(**principle-guard-the-context-window**).

## The sieve

A candidate stays only if **all three** hold. Record the first that fails.

1. **Not tied to something that will be gone in six months.** It names no branch, no ticket, no
   tool version and no one-off circumstance. That is checkable now; whether it stays true is not.
2. **Changes what the next agent does.** A different action, not a different tone. "Be careful" fails.
3. **Lands in a file that agent will read at the moment it matters.** A skill that loads on the
   task, a check that runs, a playbook the router sends it to. A note in a file no step opens fails.

## Route by layer

Take the highest layer that can hold the lesson, and only then a lower one
(`principles/encode-lessons-in-structure.md`; layers in `docs/failure-taxonomy.md`):

1. A check, lint or script that fails when the lesson is broken.
2. A line in a playbook, at the step where the mistake was made.
3. A principle, only when no step owns it and the lesson applies across playbooks.

**What a machine can enforce is never written as prose.** It goes to the Backlog as a tool to build,
with what it must check and where it would run (**principle-build-the-lever**).

A skill that should have fired is a routing failure, and the change is two things: its `description`,
and a new row in that skill's `evals/<skill>/triggers.csv` holding the prompt that missed. Measure it
with `plumb-trigger-eval --cases evals/<skill>/triggers.csv --skill plumb:<skill> --plugin-dir <source checkout> --out <dir>`
(without `--plugin-dir` it measures the installed plugin, not the edit)
before and after. A description change with no new row is not accepted.

A lesson that belongs to one failure with a label is handed to `plumb:failure-to-rule`; a lesson about
numbers over a week is `plumb:retro`. Say which, and drop it from this list.

## The three lists

Write them in this order.

**Accepted**, at most five. Each carries the **exact proposed edit** (the line before and after, or the
rows to add) and the **file** it goes in, as a path in the source repository.

**Rejected.** Each with the sieve test it failed, by number. A rejected item with no reason is an item
you did not sieve.

**Backlog.** The tools to build, each with what it checks, where it would run, and the evidence in
the session that it is needed.

**More than five Accepted means the sieve was not applied.** Go back and fail more of them; the five
that remain are the ones with the strongest evidence.

## Apply

**Nothing is applied until the owner approves.** Then:

- Edit the plumb source repository, never a file under an installed plugin cache: the next release
  replaces the cache and the change is gone. If only the cache is at hand, say so and stop.
- One change, one commit, each with the evidence it came from.
- A routing change is reported with the `plumb-trigger-eval` result before and after.
- Run `plumb-check` on the checkout before reporting the changes as done.
