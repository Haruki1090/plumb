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

## 3. Ask in rounds

Ask about **the goal, the constraints, and what counts as success**. Do not ask about
implementation convenience — that is yours to decide.

**Do not send one question at a time, and do not send them all at once.** One at a time turns a
five-question shape into five waits. All at once comes back as the answer to the first one and
silence on the rest. **Both are the same failure: the questions went out unordered.**

### Order them by what they rest on

Write every question down, and for each one mark **which other answer it needs before it can be
asked at all**. That is the tree. "Which of the two storage backends" cannot be asked before "does this hold state
across restarts" — the second answer decides whether the first question exists.

The questions that rest on nothing are **the open edge**. Send the whole edge in one message.
Each answer settles some questions and brings others onto the edge. **Send the new edge.**

**A question that rests on an open answer is not on the edge.** Asking it anyway makes the owner
do your ordering for you, in their head, without the tree in front of them.

Ordering is what turns a dozen questions into two or three rounds. Nothing is dropped; **the
waiting is.**

### Split the edge before you send it

| What the question is | Who answers it | Do you wait |
|---|---|---|
| **The repository can answer it** | the explorer role (`docs/role-map.md`) | **no.** Send it and keep going |
| **Only the owner can answer it** | the owner | **yes.** This is the shape |

**A question the repository can answer is not a question. It is a read you have not done**
(step 2). Spend a round trip on one and you have spent the owner's attention on something a
subagent would have returned while you were writing the message
(**principle-guard-the-context-window**).

The split is the shape/method line again, applied to questions: **only what cannot be looked up
and cannot be run is worth stopping for.**

### The shape of a round

Number the questions, and **carry your own recommendation on every one.**

```
1. <what is being decided>
   <one or two lines: what is at stake, and what changes with each answer>
   -> Recommend: <your answer, and the reason>
```

**A question with no recommendation hands the work back instead of the decision.** With one, the
owner answers by exception — "2 and 4, otherwise go" — and a round costs them one reading rather
than one act of authorship. The numbering is what lets them answer that briefly.

**Word each question so that agreeing with your recommendation is "yes".** Write it the other
way and the recommendation argues against the wording, so the owner cannot answer without
re-deriving what their own "yes" meant — and a one-word reply becomes ambiguous exactly where you
needed it to be exact.

Two or more candidates where the choice changes what gets built is not a question. **It is
`plumb:decision-brief`** — go to step 5.

### You do not answer the owner's questions

**Answering your own question closes the gate from the inside.** Nothing is left to see that it
happened: the round looks complete, the shape looks agreed, and the assumption is now load-bearing
under everything built on top.

A branch you can settle by running it was never the owner's — buy it in step 4. But **"I will
assume X" on a question about what to build is not an assumption. It is a decision you took
without being handed it.** If an answer does not come back, the question stays open and the work
that rests on it stays stopped. **Everything else keeps moving** ("While it is stopped, the method
keeps moving").

### You stop asking when the edge is empty

Not when you run out of questions you thought of. **The edge is empty when every question on the
tree is answered and no answer opened a new one.** That is a condition you can check. "I think I
have enough" is not.

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

**When there is really only one, do not dress it up as a choice.** Say that it is the only one
and why the others fell away. Handing over an "either is fine" hands over the work, not the
decision.

### Every tier passes the gate

**One candidate is not a reason to skip the gate.** A single candidate is still a shape, and a
shape you arrived at alone is exactly the one nobody has looked at.

What changes with the tier is **what you put through the gate**, not whether there is one.

| Tier | What goes through |
|---|---|
| **Probe** | the question, and what you are about to try, in two or three lines |
| **Local** | the shape in a few lines, **plus what you are deliberately not touching** |
| **Structural** | the spec (step 6) |

**Local is where this gets skipped.** Its shape is the shortest, which reads as the tier where
being wrong is cheapest. It is the other way round: **a short shape is short because things were
left out, and the gate is the only place anyone sees which.** The cost of the gate does not scale
with the tier — one message, answered by exception — but the cost of a wrong shape scales with
everything built on it.

**The gate takes an answer, not a silence.** No reply is not agreement; it is the gate still open.

**It still does not stop the method.** Hand the shape over and keep moving on everything that
does not depend on the answer ("While it is stopped, the method keeps moving"). The gate holds
one thing only: **committing to a shape nobody has confirmed.**

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
| Local | **Once the gate passes**, go straight to implementation. **Do not write a plan** — the plan would run longer than the implementation |
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
| Sent every question you had in one message | Unordered. Half of them rested on answers not given yet. **Order first, send the edge** |
| Sent them one at a time to avoid that | Same failure, paid in waits instead of silence. **The fix is the ordering, not the count** |
| Asked the owner something the repository answers | That is a read you skipped (step 2). **The explorer role returns it while you write the message** |
| Filled a gap with "I will assume X" and carried on | **You took a decision you were not handed.** The question stays open; only the work that rests on it stops |
| Stopped asking because you ran out of questions | Running out of ideas is not an empty edge. **Walk the tree: is every question answered, and did the last answers open none?** |
| Got no reply, so treated the shape as agreed | **Silence is the gate still open**, not a pass |
| Skipped the gate because there was only one candidate | One candidate is still a shape, and **it is the one nobody has looked at** |
| Skipped the gate because it was local | Local shapes are short **because things were left out**. The gate is where anyone sees which |

**What you return:** the tier you chose and why, the rounds you sent and the answers that came
back, anything you sent to the explorer role instead of asking, the options you compared and why
you dropped the rest, the shape the owner confirmed at the gate, the spec path (structural tier
only), and the playbook you enter next.
