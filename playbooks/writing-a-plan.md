# Writing a plan

**The plan is executed by someone who has not read one line of this conversation.**

Turn an approved shape into steps someone else can execute in order.
**This is not where you re-decide the shape** — if it is still moving, go back to
`playbooks/shaping-the-work.md`.

It goes where `plumb-path plan --mkdir` says. **The difference in rank between spec and plan,
and the discipline of freezing and retiring a finished plan, are owned by SKILL.md** and are
not copied here (**principle-encode-lessons-in-structure**).

## Decide who reads it, first

**The implementer role reads exactly one task: its own.** It does not open the main session's
history, the neighboring task, or the full spec
(**principle-guard-the-context-window**).
**"That part is in the spec" never reaches this reader.**

Write for someone competent who knows neither this codebase nor this domain.
The only passing condition is **whether they can read one task alone and carry it to the end.**

## 1. Draw the file map first

Before you cut tasks, lay out **the files you will create, the files you will touch, and what
each one is responsible for.**
**The split is settled here.** Re-split later and every task you cut goes out of alignment.

- One responsibility per file (**principle-model-the-domain**)
- **What changes together lives together.** Split by responsibility, not by technical layer
- **Follow the existing conventions.** In a repository running on large files, do not re-split
  on your turn alone. **But if a file you are touching now is already bloated**, that split may
  go in the plan

## 2. Size a task by the unit of review

A task is **the smallest unit that carries one lap of its own checks and can fail independently
of its neighbors** (**principle-sequence-verifiable-units**).

- **Fold scaffolding, configuration and documentation into the task for the artifact that needs
  them.** Do not stand them up separately
- **Split only when one side can fail while the neighbor still passes.** If it cannot, it is
  one job
- Every task ends with **an artifact that can be checked on its own**

## 3. Break the steps down to single actions

Write the failing test / **watch it fail** / the smallest implementation that passes it /
**watch it pass** / commit.

**Stand "watch it" up as its own step.** Folded in, it gets skipped
(**principle-gate-claims-on-evidence**).
**Write the command you run and the output you expect, verbatim.** "Test it" is not a step.

**What the tests in the plan actually contain is owned by `playbooks/writing-tests.md`.**
What you break down here is the ordering; **what those tests protect belongs there.**

## 4. Put everything the implementer needs in the header

At the top of the plan:

- **What is being built**, one sentence. **How it is being built**, a few lines. **The spec
  path** (the plan argues from the spec, so **the spec travels with the plan**)
- **The global constraints** — minimum versions, dependency locks, naming and wording
  conventions, the runtime environment. **Copy the values over from the spec verbatim.** This
  is **the one exception** to the discipline of not writing a path down twice in prose, and the
  reason is that **the implementer never opens the spec.** Summarize here and the values arrive
  rounded off

Per task:

- **The files you touch**, as paths that exist (create / edit / test; for an edit, down to the
  line range)
- **The surface you receive and the surface you hand on. Write the function names, arguments
  and return types verbatim.** An implementer who cannot read the neighboring task has no other
  route to the names the neighbor uses

## 5. Do not write holes

**What follows is a defect in the plan, not a place to fill in later.**

- "TBD", "later", "handle errors appropriately", "add validation if needed", "write tests for
  the above"
- **"Same as task N" — write the same thing again.** Nothing guarantees the tasks are read in
  order
- **A reference to a type, function or method that is defined nowhere**
- A step that writes code, with no code in it

## 6. Re-read it yourself

**Open the spec and cross-check it against the plan.**

- **Can you point at a task for every requirement in the spec?** Where you cannot, add a task
- Are any of the holes above still there?
- **Are the names steady?** `clearLayers` in step 3 and `clearFullLayers` in step 7 is a defect.
  **Names that move stop the implementers from connecting to each other** — they cannot read
  each other, so nobody notices

Fix what you find on the spot. **Do not re-read a second time.**

## 7. Have the handoff chosen

| Handoff | What happens |
|---|---|
| **The main session executes in order** | The main session sees every slice itself. Slow, but drift shows up immediately |
| **Hand it out to implementer roles** | A new role per task, and **the main session reviews the diff** |

Either way, from the point where it runs, `playbooks/running-a-plan.md`.
**The gate, the ledger and the cap on rounds apply the same whether you hand it out or not.**

**If it runs overnight, `playbooks/autonomous-run.md`** — the termination predicate and the
checkpoints belong there.
**Having produced a plan file is not a reason to drop the discipline.**

## When not to write one

| Situation | Instead |
|---|---|
| The shape is still moving | `playbooks/shaping-the-work.md`. **You cannot repair upstream from downstream** |
| The local tier (the flow you are changing exists, and the shape ran to a few lines) | Implement without a plan. **The plan would run longer than the implementation** |
| The nodes split and go parallel | `plumb:graph`. **The graph definition doubles as the plan. Do not write it twice** |
| A structural change that does not change behavior | `playbooks/refactoring.md` already carries the ordering |
| Fixing something that is failing | **Get a repro first** (**principle-fix-root-causes**). Do not start from design. Go to `playbooks/fixing-a-bug.md` |

**What you return:** the plan path, how many tasks and each one's artifact, the table mapping
spec requirements to tasks, and the handoff that was chosen. Add the note that **the plan is
disposable and goes stale the moment execution starts.**
