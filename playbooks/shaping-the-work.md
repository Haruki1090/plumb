# Shaping the work

**The owner holds the shape. All this playbook holds is the line where you stop.**

"I want to build X", "add X", "make it possible to X" — work that starts from a point where
**what to build is still open**. If it is already settled, you do not need this playbook.

## Draw the stopping line first

plumb holds **principle-never-block-on-the-human**: do not make a person wait on reversible
work. This playbook holds a gate. **It looks like a head-on collision. It is not.**

The line is written inside that principle: **"what to build" belongs to the owner; "how to
build it" does not stop.**

| | What goes in it | What you do |
|---|---|---|
| **The shape** (stops) | What to build. Which option to take. Where the scope ends. What existing behavior may break | Hand it over and wait for an answer |
| **The method** (does not stop) | How to split the files. Names. How the tests are written. Ordering. Which API to use. How to slice the commits | Decide, move, and show it in the diff |

**The line between them is the price of undoing it.** Get the method wrong and one diff takes
it back. Get the shape wrong and **everything built on top of it is thrown away.** "It is
reversible, so go ahead" holds only on the method side; on the shape side, the premise has
already broken.

### The gate opens once

**Do not collect a nod per section.** The owner is reading asynchronously. One round trip is an
expensive resource, and splitting it into five stacks up five waits. **Turn the crank yourself
until the shape is solid, then hand the solid thing over once.**

### While it is stopped, the method keeps moving

Do not freeze everything after you hand it over. **Work that does not depend on the branch
keeps moving**: the scaffolding every option needs, the code you have to read, an environment
that reproduces. What waits is **only the side that depends on the choice** (the mirror image
of `plumb:decision-brief`'s "keep implementing after you hand the decision over, do not wait" —
that one says do not advance the dependent side).

### When the gate has already been passed

**Do not raise a second gate against a request the owner handed down with the shape already
written.** "Add this argument to this function" has its shape settled. It skips this playbook
and goes straight to the method. The same holds when an approved spec carries the shape.
**Asking twice is the mark of not having read what you were given.**

## 1. Say up front which weight you are treating it at

**Say it before you start.** If the owner disagrees, that is where it gets corrected.

| Tier | What it is | Document produced |
|---|---|---|
| **Probe** | Work that establishes "can this be done". **The output is an answer, not code** | none |
| **Local** | **The flow you are changing already exists in this repository and can be read.** One file, one flag, one entry point | none (the shape runs to a few lines) |
| **Structural** | A new component, a boundary moves, a surface others depend on changes | spec |

**The repository decides whether it is local, not your familiarity.**
"I know this kind of app" is not grounds for local.
**If the flow you should be changing does not exist yet, it is structural.**

When in doubt, **take the heavier one.** Tiers **only go up** — when hidden complexity surfaces
mid-way, stop, say so, and re-tier. **You never go down, at any point.**

## 2. Read the context before you ask

The existing structure, the recent changes, the source-of-truth documents. **Do not turn what
reading would already answer into a question.**

Measure the size here too. **If there are several independent subsystems, split before you
work out the details.** Force something that does not fit on one page onto one page and
everything downstream is skewed. Once split, put only the first piece through this playbook.
The rest get their own lap.

## 3. Ask

**One question per message.** Send them in a batch and what comes back is the answer to the
first one only. If you can put it as a choice, do that.

Ask about **the goal, the constraints, and what counts as success**. Do not ask about
implementation convenience — that is yours to decide.

## 4. Build options and knock them down yourself

**Build two or three and compare them** (**principle-exhaust-the-design-space**).
Lean toward cutting features that are missing. **Drop anything nobody asked for from every
option.**

**A branch you can answer by running it, you buy instead of asking.**
Which arrangement, which timing, which feel — build a disposable implementation with
`playbooks/prototype.md`, watch it, and decide. **This is where never-block applies
directly.** You ask only about what running it cannot answer: what to build, who it is for,
where it ends.

## 5. Hand it over

**When there are two or more candidates and the choice changes what gets built, use
`plumb:decision-brief`.** This playbook decides; that one presents.

**When there is really only one, do not dress it up as a choice.** Report that and move.
Handing over a "either is fine" hands over the work, not the decision.

## 6. Write a spec, in the structural tier only

It goes where `plumb-path spec --mkdir` says.
**What a spec carries (end state, acceptance criteria, why this approach, what you rejected)
and how it differs in rank from a plan is owned by SKILL.md** and is not copied here
(**principle-encode-lessons-in-structure**).

Once written, **re-read it yourself immediately.**

- Are there unfilled spots left ("later", "TBD")?
- Do any two sections contradict each other?
- **Is there a requirement that reads two ways?** If so, pick one and write that you picked it
- Does the scope fit inside one plan?

Fix and move. Do not loop on re-reading.

Then **put it in front of the owner.** The spec is the source of truth and it is what gets
approved. **This is the last gate**, and once it passes, the conversation about shape is over.

## 7. Exits

| Tier | Next |
|---|---|
| Probe | Return the recommendation and stop. **Write that what you built is thrown away** |
| Local | Go straight to implementation. **Do not write a plan** — the plan would run longer than the implementation |
| Structural | `playbooks/writing-a-plan.md` |
| Structural, where the nodes split and parallelize | `plumb:graph`. **The graph definition doubles as the plan, so do not write a separate one** |

## The line against neighboring playbooks

| Playbook | Which one to use |
|---|---|
| `playbooks/investigation.md` | **If the output ends at an explanation or a recommendation and no code changes, use that one.** If the investigation turns into building something, do not slide into implementation on momentum — re-enter through this playbook |
| `playbooks/prototype.md` | **A tool for buying a shape candidate with a disposable implementation.** Used inside step 4 here. It does not settle a shape on its own |
| `plumb:decision-brief` | **How you present a shape when you hand it over.** Called from step 5 here. Where you stop is this playbook's; how it looks is that one's |
| `plumb:graph` | **If the nodes split into five to ten and two or more graph signals are present, use that one.** The graph definition doubles as the spec. This playbook only takes you as far as settling on one shape before you go there |
| `playbooks/refactoring.md` | **If the behavior does not change, the shape is already settled.** Do not run it through this playbook. If you find yourself wanting to redesign mid-cleanup, change the name and come here |

## How this breaks

| Failure | What to do |
|---|---|
| "It is too simple to need design" | Simple only makes **the shape shorter**. It does not reduce the number of handoffs |
| Labeling it "local" to skip the spec | **Going looking for the label in order to skip** is itself the evidence you are unsure. Take the heavier one |
| Started building in the same reply that handed the shape over | The gate is the **answer**, not the length of the shape. Once you hand it over, you stop |
| Called it local because the domain is familiar | The repository decides local. **No readable flow means structural** |
| Kept what the probe built because it turned out good | Keeping it is **a different request**. Re-tier it |
| It grew, but you kept going because it was nearly done | Growth raises the tier. **Stop and say so** |
| Asked the owner about every branch | Buy what running it answers, in step 4. **Ask only about what running it cannot answer** |
| Started writing the plan before the shape was solid | The plan is downstream of the shape. **Turn something unsettled into steps and the steps get thrown away with it** |

**What you return:** the tier you chose and why, the questions you asked and the answers that
came back, the options you compared and why you dropped the rest, the shape the owner chose,
the spec path (structural tier only), and the playbook you enter next.
